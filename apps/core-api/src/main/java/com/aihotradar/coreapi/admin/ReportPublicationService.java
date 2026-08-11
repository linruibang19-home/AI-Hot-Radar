package com.aihotradar.coreapi.admin;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;

/** Applies the small report publication state machine locked by ADR-0025. */
@Component
public class ReportPublicationService {

    private final NamedParameterJdbcTemplate jdbc;

    public ReportPublicationService(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public ReportState transition(UUID id, String targetStatus) {
        if (!"PUBLISHED".equals(targetStatus) && !"WITHDRAWN".equals(targetStatus)) {
            throw new IllegalArgumentException("unsupported report status: " + targetStatus);
        }

        List<ReportState> before = find(id);
        if (before.isEmpty()) {
            return null;
        }
        ReportState current = before.getFirst();
        if (targetStatus.equals(current.status())) {
            return current;
        }

        jdbc.update(
                """
                UPDATE report
                   SET status = :status,
                       published_at = CASE
                           WHEN :status = 'PUBLISHED' THEN COALESCE(published_at, now())
                           ELSE published_at
                       END
                 WHERE id = :id
                """,
                new MapSqlParameterSource()
                        .addValue("status", targetStatus)
                        .addValue("id", id));
        return find(id).getFirst();
    }

    public List<ReportState> find(UUID id) {
        return jdbc.query(
                """
                SELECT id, period_type, period_key, title, summary, body_markdown,
                       status, item_count,
                       generated_at, published_at, generation_meta::text AS generation_meta
                  FROM report
                 WHERE id = :id
                """,
                new MapSqlParameterSource("id", id),
                (rs, rowNum) ->
                        new ReportState(
                                rs.getObject("id", UUID.class),
                                rs.getString("period_type"),
                                rs.getString("period_key"),
                                rs.getString("title"),
                                rs.getString("summary"),
                                rs.getString("body_markdown"),
                                rs.getString("status"),
                                rs.getInt("item_count"),
                                rs.getObject("generated_at", OffsetDateTime.class),
                                rs.getObject("published_at", OffsetDateTime.class),
                                rs.getString("generation_meta")));
    }

    public List<Map<String, Object>> list(String status, int limit) {
        String where = status == null || status.isBlank() ? "" : " WHERE status = :status";
        MapSqlParameterSource params =
                new MapSqlParameterSource()
                        .addValue("status", status == null ? null : status.toUpperCase())
                        .addValue("limit", Math.min(Math.max(limit, 1), 100));
        return jdbc.queryForList(
                """
                SELECT id, period_type, period_key, title, summary, status, item_count,
                       generated_at, published_at, generation_meta::text AS generation_meta
                  FROM report
                """
                        + where
                        + " ORDER BY generated_at DESC LIMIT :limit",
                params);
    }

    public record ReportState(
            UUID id,
            String period,
            String key,
            String title,
            String summary,
            String bodyMarkdown,
            String status,
            int itemCount,
            OffsetDateTime generatedAt,
            OffsetDateTime publishedAt,
            String generationMeta) {}
}
