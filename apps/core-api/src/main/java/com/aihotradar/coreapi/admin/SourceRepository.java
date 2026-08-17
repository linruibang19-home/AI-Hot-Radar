package com.aihotradar.coreapi.admin;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/** PostgreSQL adapter for source operations and health projections. */
@Repository
public class SourceRepository {

    private final NamedParameterJdbcTemplate jdbc;

    public SourceRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<SourceHealth> findEnabledHealth() {
        String sql =
                """
                WITH item_counts AS (
                  SELECT source_id, count(*) AS items
                    FROM content_item
                   GROUP BY source_id
                ), fulltext_counts AS (
                  SELECT source_id,
                         count(*) FILTER (WHERE decision = 'ACCEPTED') AS fulltext_ok,
                         count(*) AS fulltext_total
                    FROM fulltext_attempt
                   GROUP BY source_id
                )
                SELECT s.id, s.name, s.organization, s.profile, s.priority,
                       s.source_tier, s.runtime_state, s.content_access,
                       s.last_success_at, s.last_error_code, s.consecutive_failures,
                       s.next_poll_at, s.operator_enabled, s.operator_note,
                       coalesce(ic.items, 0) AS items,
                       coalesce(fc.fulltext_ok, 0) AS fulltext_ok,
                       coalesce(fc.fulltext_total, 0) AS fulltext_total
                  FROM source s
                  LEFT JOIN item_counts ic ON ic.source_id = s.id
                  LEFT JOIN fulltext_counts fc ON fc.source_id = s.id
                 WHERE s.effective_enabled
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
                            (Boolean) rs.getObject("operator_enabled"),
                            rs.getString("operator_note"),
                            rs.getLong("items"),
                            total == 0 ? null : Math.round((double) ok / total * 1000) / 10.0);
                });
    }

    /** Database-backed registry summary used to label which environment a console is reading. */
    public SourceSummary findSummary() {
        return jdbc.queryForObject(
                """
                SELECT count(*) AS registered,
                       count(*) FILTER (WHERE effective_enabled) AS enabled,
                       count(*) FILTER (WHERE NOT effective_enabled) AS disabled,
                       max(greatest(updated_at, coalesce(last_success_at, updated_at))) AS data_updated_at,
                       max(config_version) AS config_version
                  FROM source
                """,
                new MapSqlParameterSource(),
                (rs, rowNum) ->
                        new SourceSummary(
                                rs.getLong("registered"),
                                rs.getLong("enabled"),
                                rs.getLong("disabled"),
                                rs.getObject("data_updated_at", OffsetDateTime.class),
                                rs.getString("config_version")));
    }

    public Optional<Map<String, Object>> findState(String id) {
        List<Map<String, Object>> rows =
                jdbc.queryForList(
                        """
                        SELECT id, configured_enabled, operator_enabled, effective_enabled,
                               operator_note, runtime_state, next_poll_at
                          FROM source WHERE id = :id
                        """,
                        new MapSqlParameterSource("id", id));
        return rows.stream().findFirst();
    }

    public int setEnabled(String id, Boolean enabled, String note) {
        return jdbc.update(
                """
                UPDATE source
                   SET operator_enabled = :enabled,
                       operator_note = :note
                 WHERE id = :id
                """,
                new MapSqlParameterSource()
                        .addValue("enabled", enabled)
                        .addValue("note", note)
                        .addValue("id", id));
    }

    public int scheduleNow(String id) {
        return jdbc.update(
                "UPDATE source SET next_poll_at = now() WHERE id = :id AND effective_enabled",
                new MapSqlParameterSource("id", id));
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
            Boolean operatorEnabled,
            String operatorNote,
            long items,
            Double fulltextSuccessRate) {}

    public record SourceSummary(
            long registered,
            long enabled,
            long disabled,
            OffsetDateTime dataUpdatedAt,
            String configVersion) {}
}
