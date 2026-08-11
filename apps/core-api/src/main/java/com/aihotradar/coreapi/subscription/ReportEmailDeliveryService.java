package com.aihotradar.coreapi.subscription;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.HexFormat;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class ReportEmailDeliveryService {
    private static final int MAX_DELIVERY_ATTEMPTS = 3;
    private static final int ENQUEUE_LIMIT = 200;
    private static final int CLAIM_LIMIT = 20;

    static final String CANDIDATES_SQL =
            """
            SELECT subscription.id AS subscription_id,
                   subscription.email_normalized,
                   latest_report.id AS report_id,
                   latest_report.period_type,
                   latest_report.period_key
              FROM report_subscription subscription
              JOIN report_subscription_period preference
                ON preference.subscription_id = subscription.id
              JOIN LATERAL (
                    SELECT report.id, report.period_type, report.period_key
                      FROM report
                     WHERE report.period_type = preference.period_type
                       AND report.status = 'PUBLISHED'
                       AND report.published_at >= subscription.confirmed_at
                     ORDER BY report.period_key DESC
                     LIMIT 1
              ) latest_report ON TRUE
             WHERE subscription.status = 'ACTIVE'
               AND (now() AT TIME ZONE subscription.timezone)::time >= preference.delivery_local_time
               AND NOT EXISTS (
                    SELECT 1
                      FROM email_delivery delivery
                     WHERE delivery.subscription_id = subscription.id
                       AND delivery.report_id = latest_report.id
               )
             ORDER BY subscription.confirmed_at, latest_report.period_key
             LIMIT :limit
            """;

    static final String CLAIM_SQL =
            """
            WITH due AS (
                SELECT id
                  FROM email_delivery
                 WHERE status IN ('PENDING', 'RETRYABLE_FAILED')
                   AND next_attempt_at <= now()
                 ORDER BY next_attempt_at, attempted_at
                 LIMIT :limit
                 FOR UPDATE SKIP LOCKED
            )
            UPDATE email_delivery delivery
               SET status = 'SENDING',
                   attempt_count = delivery.attempt_count + 1,
                   attempted_at = now()
              FROM due
             WHERE delivery.id = due.id
            RETURNING delivery.id
            """;

    static final String RECOVER_STALE_SQL =
            """
            UPDATE email_delivery
               SET status = CASE
                       WHEN attempt_count >= 3 THEN 'PERMANENT_FAILED'
                       ELSE 'RETRYABLE_FAILED'
                   END,
                   next_attempt_at = CASE
                       WHEN attempt_count >= 3 THEN NULL
                       ELSE now()
                   END,
                   error_detail = 'stale_claim_recovered'
             WHERE status = 'SENDING'
               AND attempted_at < now() - interval '15 minutes'
            """;

    private final NamedParameterJdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final SubscriptionMailer mailer;
    private final ReportSubscriptionService subscriptions;

    public ReportEmailDeliveryService(
            NamedParameterJdbcTemplate jdbc,
            PlatformTransactionManager transactionManager,
            SubscriptionMailer mailer,
            ReportSubscriptionService subscriptions) {
        this.jdbc = jdbc;
        this.transactions = new TransactionTemplate(transactionManager);
        this.mailer = mailer;
        this.subscriptions = subscriptions;
    }

    @Scheduled(fixedDelayString = "${ahr.email.dispatch-interval-ms:300000}")
    public void dispatchDue() {
        recoverStaleClaims();
        enqueueLatestPublished();
        for (UUID deliveryId : claimDue()) {
            Optional<DeliveryMessage> message = loadDeliverable(deliveryId);
            if (message.isEmpty()) {
                markSkipped(deliveryId);
                continue;
            }
            DeliveryMessage delivery = message.get();
            try {
                String unsubscribeToken = subscriptions.issueUnsubscribeToken(
                        delivery.subscriptionId(), delivery.tokenVersion());
                mailer.sendReport(delivery, unsubscribeToken);
                markSent(delivery.id());
            } catch (SubscriptionMailUnavailableException exception) {
                markFailed(delivery.id(), delivery.attemptCount(), exception.getClass().getSimpleName());
            }
        }
    }

    int recoverStaleClaims() {
        return jdbc.update(RECOVER_STALE_SQL, new MapSqlParameterSource());
    }

    int enqueueLatestPublished() {
        List<DeliveryCandidate> candidates = jdbc.query(
                CANDIDATES_SQL,
                new MapSqlParameterSource("limit", ENQUEUE_LIMIT),
                (rs, rowNum) -> new DeliveryCandidate(
                        rs.getObject("subscription_id", UUID.class),
                        rs.getString("email_normalized"),
                        rs.getObject("report_id", UUID.class),
                        rs.getString("period_type"),
                        rs.getString("period_key")));
        int inserted = 0;
        for (DeliveryCandidate candidate : candidates) {
            inserted += jdbc.update(
                    """
                    INSERT INTO email_delivery (
                        id, delivery_key, recipient, report_period_key, status,
                        subscription_id, report_id, next_attempt_at
                    ) VALUES (
                        :id, :deliveryKey, :recipient, :periodKey, 'PENDING',
                        :subscriptionId, :reportId, now()
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    new MapSqlParameterSource()
                            .addValue("id", UUID.randomUUID())
                            .addValue("deliveryKey", deliveryKey(candidate.subscriptionId(), candidate.reportId()))
                            .addValue("recipient", candidate.email())
                            .addValue("periodKey", candidate.periodKey())
                            .addValue("subscriptionId", candidate.subscriptionId())
                            .addValue("reportId", candidate.reportId()));
        }
        return inserted;
    }

    List<UUID> claimDue() {
        List<UUID> claimed = transactions.execute(status -> jdbc.query(
                CLAIM_SQL,
                new MapSqlParameterSource("limit", CLAIM_LIMIT),
                (rs, rowNum) -> rs.getObject("id", UUID.class)));
        return claimed == null ? List.of() : claimed;
    }

    Optional<DeliveryMessage> loadDeliverable(UUID deliveryId) {
        List<DeliveryMessage> rows = jdbc.query(
                """
                SELECT delivery.id, delivery.attempt_count,
                       subscription.id AS subscription_id,
                       subscription.email_normalized,
                       subscription.token_version,
                       report.id AS report_id, report.period_type, report.period_key,
                       report.title, report.summary, report.body_markdown
                  FROM email_delivery delivery
                  JOIN report_subscription subscription
                    ON subscription.id = delivery.subscription_id
                  JOIN report ON report.id = delivery.report_id
                 WHERE delivery.id = :id
                   AND delivery.status = 'SENDING'
                   AND subscription.status = 'ACTIVE'
                   AND report.status = 'PUBLISHED'
                """,
                new MapSqlParameterSource("id", deliveryId),
                (rs, rowNum) -> new DeliveryMessage(
                        rs.getObject("id", UUID.class),
                        rs.getInt("attempt_count"),
                        rs.getObject("subscription_id", UUID.class),
                        rs.getInt("token_version"),
                        rs.getString("email_normalized"),
                        rs.getObject("report_id", UUID.class),
                        rs.getString("period_type"),
                        rs.getString("period_key"),
                        rs.getString("title"),
                        rs.getString("summary"),
                        rs.getString("body_markdown")));
        return rows.stream().findFirst();
    }

    void markSent(UUID deliveryId) {
        jdbc.update(
                """
                UPDATE email_delivery
                   SET status = 'SENT', sent_at = now(), next_attempt_at = NULL, error_detail = NULL
                 WHERE id = :id AND status = 'SENDING'
                """,
                new MapSqlParameterSource("id", deliveryId));
    }

    void markSkipped(UUID deliveryId) {
        jdbc.update(
                """
                UPDATE email_delivery
                   SET status = 'SKIPPED', next_attempt_at = NULL,
                       error_detail = 'subscription_or_report_not_deliverable'
                 WHERE id = :id AND status = 'SENDING'
                """,
                new MapSqlParameterSource("id", deliveryId));
    }

    void markFailed(UUID deliveryId, int attemptCount, String errorCode) {
        boolean retryable = attemptCount < MAX_DELIVERY_ATTEMPTS;
        OffsetDateTime next = retryable
                ? OffsetDateTime.now(ZoneOffset.UTC).plus(retryDelay(attemptCount))
                : null;
        jdbc.update(
                """
                UPDATE email_delivery
                   SET status = :status,
                       next_attempt_at = :nextAttemptAt,
                       error_detail = :errorCode
                 WHERE id = :id AND status = 'SENDING'
                """,
                new MapSqlParameterSource()
                        .addValue("status", retryable ? "RETRYABLE_FAILED" : "PERMANENT_FAILED")
                        .addValue("nextAttemptAt", next)
                        .addValue("errorCode", errorCode)
                        .addValue("id", deliveryId));
    }

    static Duration retryDelay(int attemptCount) {
        return attemptCount <= 1 ? Duration.ofMinutes(10) : Duration.ofMinutes(60);
    }

    static String deliveryKey(UUID subscriptionId, UUID reportId) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] value = (subscriptionId + ":" + reportId).getBytes(StandardCharsets.UTF_8);
            return HexFormat.of().formatHex(digest.digest(value));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private record DeliveryCandidate(
            UUID subscriptionId, String email, UUID reportId, String periodType, String periodKey) {}

    public record DeliveryMessage(
            UUID id,
            int attemptCount,
            UUID subscriptionId,
            int tokenVersion,
            String recipient,
            UUID reportId,
            String periodType,
            String periodKey,
            String title,
            String summary,
            String bodyMarkdown) {}
}
