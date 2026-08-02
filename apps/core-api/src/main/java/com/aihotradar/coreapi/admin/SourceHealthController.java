package com.aihotradar.coreapi.admin;

import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Read-only source health view (AHR-ROADMAP-800 M1: "后台信源/任务只读页").
 *
 * <p>Read-only by design at this stage: AHR-QSO-700 §3 requires least-privilege
 * RBAC and second confirmation before any admin mutation, and no authentication
 * exists yet. Exposing start/stop or re-run controls now would create an
 * unauthenticated write surface, so those wait for M5.
 *
 * <p>The report fields follow AHR-SOURCE-900 §8 so operators can tell a source
 * that only ever yields metadata from one that is genuinely failing.
 */
@RestController
@RequestMapping("/api/v1/admin")
public class SourceHealthController {

    private final NamedParameterJdbcTemplate jdbc;

    public SourceHealthController(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping("/sources")
    public List<SourceHealth> sources() {
        String sql =
                """
                SELECT s.id, s.name, s.organization, s.profile, s.priority,
                       s.source_tier, s.runtime_state, s.content_access,
                       s.last_success_at, s.last_error_code, s.consecutive_failures,
                       s.next_poll_at,
                       (SELECT count(*) FROM content_item ci WHERE ci.source_id = s.id) AS items,
                       (SELECT count(*) FROM fulltext_attempt fa
                         WHERE fa.source_id = s.id AND fa.decision = 'ACCEPTED') AS fulltext_ok,
                       (SELECT count(*) FROM fulltext_attempt fa
                         WHERE fa.source_id = s.id) AS fulltext_total
                  FROM source s
                 WHERE s.configured_enabled
                 ORDER BY
                   CASE s.runtime_state
                     WHEN 'QUARANTINED' THEN 0
                     WHEN 'DEGRADED' THEN 1
                     WHEN 'RATE_LIMITED' THEN 2
                     WHEN 'PROBING' THEN 3
                     WHEN 'METADATA_ONLY' THEN 4
                     ELSE 5
                   END,
                   s.priority, s.id
                """;

        return jdbc.query(
                sql,
                new MapSqlParameterSource(),
                (rs, rowNum) -> {
                    long total = rs.getLong("fulltext_total");
                    long ok = rs.getLong("fulltext_ok");
                    return new SourceHealth(
                            rs.getString("id"),
                            rs.getString("name"),
                            rs.getString("organization"),
                            rs.getString("profile"),
                            rs.getString("priority"),
                            rs.getString("source_tier"),
                            rs.getString("runtime_state"),
                            rs.getString("content_access"),
                            rs.getObject("last_success_at", OffsetDateTime.class),
                            rs.getString("last_error_code"),
                            rs.getInt("consecutive_failures"),
                            rs.getObject("next_poll_at", OffsetDateTime.class),
                            rs.getLong("items"),
                            // Reported as a rate rather than raw counts so a source
                            // with one lucky success is not mistaken for a healthy one.
                            total == 0 ? null : Math.round((double) ok / total * 1000) / 10.0);
                });
    }

    public record SourceHealth(
            String id,
            String name,
            String organization,
            String profile,
            String priority,
            String tier,
            String runtimeState,
            String contentAccess,
            OffsetDateTime lastSuccessAt,
            String lastErrorCode,
            int consecutiveFailures,
            OffsetDateTime nextPollAt,
            long items,
            Double fulltextSuccessRate) {}
}
