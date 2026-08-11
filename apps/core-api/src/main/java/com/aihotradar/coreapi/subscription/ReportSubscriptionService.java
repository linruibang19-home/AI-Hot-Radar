package com.aihotradar.coreapi.subscription;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.time.DateTimeException;
import java.time.temporal.ChronoUnit;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class ReportSubscriptionService {
    private static final int CONFIRMATION_HOURS = 24;
    private static final int UNSUBSCRIBE_DAYS = 3650;

    static final String UPSERT_REQUEST_SQL =
            """
            INSERT INTO report_subscription_request (
                id, email_normalized, timezone, status, token_version, expires_at
            ) VALUES (:id, :email, :timezone, 'PENDING', 1, :expiresAt)
            ON CONFLICT (email_normalized) WHERE status = 'PENDING'
            DO UPDATE SET
                timezone = EXCLUDED.timezone,
                token_version = report_subscription_request.token_version + 1,
                expires_at = EXCLUDED.expires_at,
                confirmation_sent_at = NULL,
                updated_at = now()
            WHERE report_subscription_request.confirmation_sent_at IS NULL
               OR report_subscription_request.confirmation_sent_at < now() - interval '10 minutes'
            RETURNING id, token_version, expires_at
            """;

    private final NamedParameterJdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final SubscriptionTokenService tokens;
    private final SubscriptionMailer mailer;

    public ReportSubscriptionService(
            NamedParameterJdbcTemplate jdbc,
            PlatformTransactionManager transactionManager,
            SubscriptionTokenService tokens,
            SubscriptionMailer mailer) {
        this.jdbc = jdbc;
        this.transactions = new TransactionTemplate(transactionManager);
        this.tokens = tokens;
        this.mailer = mailer;
    }

    public void request(String email, Set<String> rawPeriods, String timezone) {
        String normalizedEmail = normalizeEmail(email);
        List<ReportPeriod> periods = normalizePeriods(rawPeriods);
        String normalizedTimezone = normalizeTimezone(timezone);
        Instant expiresAt = Instant.now().plus(CONFIRMATION_HOURS, ChronoUnit.HOURS);

        PendingConfirmation pending = transactions.execute(status -> {
            List<PendingConfirmation> rows = jdbc.query(
                    UPSERT_REQUEST_SQL,
                    new MapSqlParameterSource()
                            .addValue("id", UUID.randomUUID())
                            .addValue("email", normalizedEmail)
                            .addValue("timezone", normalizedTimezone)
                            .addValue("expiresAt", OffsetDateTime.ofInstant(expiresAt, ZoneOffset.UTC)),
                    (rs, rowNum) -> new PendingConfirmation(
                            rs.getObject("id", UUID.class),
                            rs.getInt("token_version"),
                            rs.getObject("expires_at", OffsetDateTime.class).toInstant()));
            if (rows.isEmpty()) {
                return null;
            }
            PendingConfirmation issued = rows.getFirst();
            jdbc.update(
                    "DELETE FROM report_subscription_request_period WHERE request_id = :id",
                    new MapSqlParameterSource("id", issued.id()));
            SqlParameterSource[] batch = periods.stream()
                    .map(period -> new MapSqlParameterSource()
                            .addValue("requestId", issued.id())
                            .addValue("period", period.value()))
                    .toArray(SqlParameterSource[]::new);
            jdbc.batchUpdate(
                    """
                    INSERT INTO report_subscription_request_period (request_id, period_type)
                    VALUES (:requestId, :period)
                    """,
                    batch);
            return issued;
        });

        // A recently sent request intentionally returns the same public response without
        // generating another email or invalidating the link already in the recipient's inbox.
        if (pending == null) {
            return;
        }

        String token = tokens.issue("confirm", pending.id(), pending.version(), pending.expiresAt());
        mailer.sendConfirmation(normalizedEmail, token);
        jdbc.update(
                """
                UPDATE report_subscription_request
                   SET confirmation_sent_at = now(), updated_at = now()
                 WHERE id = :id AND token_version = :version AND status = 'PENDING'
                """,
                new MapSqlParameterSource()
                        .addValue("id", pending.id())
                        .addValue("version", pending.version()));
    }

    public SubscriptionState confirm(String token) {
        SubscriptionTokenService.TokenClaims claims = tokens.verify(token, "confirm");
        return transactions.execute(status -> {
            List<PendingRequest> requests = jdbc.query(
                    """
                    SELECT id, email_normalized, timezone
                      FROM report_subscription_request
                     WHERE id = :id
                       AND token_version = :version
                       AND status = 'PENDING'
                       AND expires_at > now()
                     FOR UPDATE
                    """,
                    new MapSqlParameterSource()
                            .addValue("id", claims.targetId())
                            .addValue("version", claims.version()),
                    (rs, rowNum) -> new PendingRequest(
                            rs.getObject("id", UUID.class),
                            rs.getString("email_normalized"),
                            rs.getString("timezone")));
            if (requests.isEmpty()) {
                throw new InvalidSubscriptionTokenException();
            }
            PendingRequest request = requests.getFirst();
            List<String> periods = jdbc.queryForList(
                    """
                    SELECT period_type
                      FROM report_subscription_request_period
                     WHERE request_id = :id
                     ORDER BY period_type
                    """,
                    new MapSqlParameterSource("id", request.id()),
                    String.class);
            if (periods.isEmpty()) {
                throw new InvalidSubscriptionTokenException();
            }

            UUID proposedId = UUID.randomUUID();
            ActiveSubscription active = jdbc.queryForObject(
                    """
                    INSERT INTO report_subscription (
                        id, email_normalized, status, timezone, token_version, confirmed_at
                    ) VALUES (:id, :email, 'ACTIVE', :timezone, 1, now())
                    ON CONFLICT (email_normalized) DO UPDATE SET
                        status = 'ACTIVE',
                        timezone = EXCLUDED.timezone,
                        token_version = report_subscription.token_version + 1,
                        confirmed_at = now(),
                        unsubscribed_at = NULL,
                        updated_at = now()
                    RETURNING id, token_version
                    """,
                    new MapSqlParameterSource()
                            .addValue("id", proposedId)
                            .addValue("email", request.email())
                            .addValue("timezone", request.timezone()),
                    (rs, rowNum) -> new ActiveSubscription(
                            rs.getObject("id", UUID.class), rs.getInt("token_version")));

            jdbc.update(
                    "DELETE FROM report_subscription_period WHERE subscription_id = :id",
                    new MapSqlParameterSource("id", active.id()));
            SqlParameterSource[] periodBatch = periods.stream()
                    .map(period -> new MapSqlParameterSource()
                            .addValue("subscriptionId", active.id())
                            .addValue("period", period))
                    .toArray(SqlParameterSource[]::new);
            jdbc.batchUpdate(
                    """
                    INSERT INTO report_subscription_period (subscription_id, period_type)
                    VALUES (:subscriptionId, :period)
                    """,
                    periodBatch);
            jdbc.update(
                    """
                    UPDATE report_subscription_request
                       SET status = 'CONFIRMED', confirmed_at = now(), updated_at = now()
                     WHERE id = :id
                    """,
                    new MapSqlParameterSource("id", request.id()));
            return new SubscriptionState("ACTIVE", periods);
        });
    }

    public SubscriptionState unsubscribe(String token) {
        SubscriptionTokenService.TokenClaims claims = tokens.verify(token, "unsubscribe");
        int updated = jdbc.update(
                """
                UPDATE report_subscription
                   SET status = 'UNSUBSCRIBED',
                       unsubscribed_at = now(),
                       token_version = token_version + 1,
                       updated_at = now()
                 WHERE id = :id AND token_version = :version AND status = 'ACTIVE'
                """,
                new MapSqlParameterSource()
                        .addValue("id", claims.targetId())
                        .addValue("version", claims.version()));
        if (updated != 1) {
            throw new InvalidSubscriptionTokenException();
        }
        return new SubscriptionState("UNSUBSCRIBED", List.of());
    }

    public String issueUnsubscribeToken(UUID subscriptionId, int version) {
        return tokens.issue(
                "unsubscribe",
                subscriptionId,
                version,
                Instant.now().plus(UNSUBSCRIBE_DAYS, ChronoUnit.DAYS));
    }

    static String normalizeEmail(String email) {
        if (email == null) {
            throw new IllegalArgumentException("email is required");
        }
        String normalized = email.trim().toLowerCase(Locale.ROOT);
        if (normalized.length() > 320 || !normalized.matches("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$")) {
            throw new IllegalArgumentException("email is invalid");
        }
        return normalized;
    }

    static List<ReportPeriod> normalizePeriods(Set<String> rawPeriods) {
        if (rawPeriods == null || rawPeriods.isEmpty()) {
            throw new IllegalArgumentException("at least one report period is required");
        }
        return rawPeriods.stream()
                .map(ReportPeriod::parse)
                .distinct()
                .sorted(Comparator.comparing(ReportPeriod::value))
                .toList();
    }

    static String normalizeTimezone(String timezone) {
        if (timezone == null || timezone.isBlank()) {
            throw new IllegalArgumentException("timezone is required");
        }
        try {
            return ZoneId.of(timezone.trim()).getId();
        } catch (DateTimeException exception) {
            throw new IllegalArgumentException("timezone is invalid", exception);
        }
    }

    private record PendingConfirmation(UUID id, int version, Instant expiresAt) {}

    private record PendingRequest(UUID id, String email, String timezone) {}

    private record ActiveSubscription(UUID id, int tokenVersion) {}

    public record SubscriptionState(String status, List<String> periods) {}
}
