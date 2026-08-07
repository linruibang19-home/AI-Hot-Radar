package com.aihotradar.coreapi.admin;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * Writes one row per admin mutation attempt.
 *
 * <p>Denied attempts are recorded too. An audit log holding only what succeeded cannot show
 * somebody trying tokens against the console, which is a large part of what it is for — and the
 * distinction between "unknown token" and "valid token, insufficient role" is the difference
 * between an outsider and a misconfigured client.
 *
 * <p>Never writes credentials, headers or request bodies (AHR-QSO-700 §3 requires Authorization to
 * be redacted from logs, and an audit table is a log that is easier to query).
 */
@Component
public class AdminAudit {

    private static final Logger log = LoggerFactory.getLogger(AdminAudit.class);

    public enum Outcome {
        ALLOWED,
        DENIED_NO_TOKEN,
        DENIED_BAD_TOKEN,
        DENIED_ROLE,
        DENIED_UNCONFIRMED,
        FAILED
    }

    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper json;

    public AdminAudit(NamedParameterJdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc = jdbc;
        this.json = json;
    }

    public void record(
            AdminPrincipal principal,
            String action,
            String target,
            Outcome outcome,
            Map<String, Object> detail) {

        String payload;
        try {
            payload = json.writeValueAsString(detail == null ? Map.of() : detail);
        } catch (JsonProcessingException e) {
            payload = "{}";
        }

        try {
            jdbc.update(
                    """
                    INSERT INTO admin_audit
                        (principal_id, principal_label, role, action, target, outcome, detail)
                    VALUES
                        (:principalId, :label, :role, :action, :target, :outcome, :detail::jsonb)
                    """,
                    new MapSqlParameterSource()
                            .addValue("principalId", principal == null ? null : principal.id())
                            .addValue("label", principal == null ? null : principal.label())
                            .addValue(
                                    "role",
                                    principal == null ? null : principal.role().name())
                            .addValue("action", action)
                            .addValue("target", target)
                            .addValue("outcome", outcome.name())
                            .addValue("detail", payload));
        } catch (RuntimeException e) {
            // The audit write must not turn a successful operation into a 500, and must not turn a
            // rejection into an acceptance. Losing the row is bad; it is less bad than either.
            log.error("failed to write admin audit row for {} on {}", action, target, e);
        }
    }

    /** Recent activity, newest first — the read side of the table. */
    public java.util.List<Map<String, Object>> recent(int limit) {
        return jdbc.queryForList(
                """
                SELECT at, principal_label, role, action, target, outcome, detail
                  FROM admin_audit
                 ORDER BY at DESC
                 LIMIT :limit
                """,
                new MapSqlParameterSource("limit", Math.min(Math.max(limit, 1), 200)));
    }
}
