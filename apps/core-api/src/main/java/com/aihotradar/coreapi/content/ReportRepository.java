package com.aihotradar.coreapi.content;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/** PostgreSQL read adapter for immutable published report snapshots. */
@Repository
public class ReportRepository {

    static final String LIST_SQL =
            """
            SELECT period_key, title, summary, item_count, generated_at, model_name, status
             FROM report
             WHERE period_type = :period AND status = 'PUBLISHED'
             ORDER BY period_key DESC
             LIMIT :limit
            """;

    static final String DETAIL_SQL =
            """
            SELECT id, period_key, title, summary, body_markdown, item_count,
                   generated_at, model_name, prompt_version, status, published_at
              FROM report
             WHERE period_type = :period AND period_key = :key AND status = 'PUBLISHED'
            """;

    static final String ITEMS_SQL =
            """
            SELECT ri.section, ri.position, ci.id,
                   COALESCE(ci.zh_title, ci.title) AS title,
                   ci.summary_zh, ci.canonical_url, ci.content_type,
                   s.id AS source_id, s.name AS source_name, s.organization,
                   s.source_tier, st.slug AS story_slug,
                   COALESCE(st.independent_source_count, 1) AS independent_sources
              FROM report_item ri
              JOIN content_item ci ON ci.id = ri.content_item_id
              JOIN source s ON s.id = ci.source_id
              LEFT JOIN story st ON st.id = ci.story_id
             WHERE ri.report_id = :reportId
             ORDER BY ri.position
            """;

    static final String NAV_SQL =
            """
            SELECT max(period_key) FILTER (WHERE period_key < :key) AS previous_key,
                   min(period_key) FILTER (WHERE period_key > :key) AS next_key
              FROM report
             WHERE period_type = :period
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public ReportRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    List<ReportSummaryRow> listPublished(String period, int limit) {
        return jdbc.query(
                LIST_SQL,
                new MapSqlParameterSource()
                        .addValue("period", period)
                        .addValue("limit", limit),
                (rs, rowNum) ->
                        new ReportSummaryRow(
                                rs.getString("period_key"),
                                rs.getString("title"),
                                rs.getString("summary"),
                                rs.getInt("item_count"),
                                rs.getObject("generated_at", OffsetDateTime.class),
                                rs.getString("model_name"),
                                rs.getString("status")));
    }

    Optional<ReportRow> findPublished(String period, String key) {
        List<ReportRow> rows =
                jdbc.query(
                        DETAIL_SQL,
                        new MapSqlParameterSource()
                                .addValue("period", period)
                                .addValue("key", key),
                        (rs, rowNum) ->
                                new ReportRow(
                                        rs.getObject("id", UUID.class),
                                        rs.getString("period_key"),
                                        rs.getString("title"),
                                        rs.getString("summary"),
                                        rs.getString("body_markdown"),
                                        rs.getInt("item_count"),
                                        rs.getObject("generated_at", OffsetDateTime.class),
                                        rs.getString("model_name"),
                                        rs.getString("prompt_version"),
                                        rs.getString("status"),
                                        rs.getObject("published_at", OffsetDateTime.class)));
        return rows.stream().findFirst();
    }

    List<ReportEntryRow> findEntries(UUID reportId) {
        return jdbc.query(
                ITEMS_SQL,
                new MapSqlParameterSource("reportId", reportId),
                (rs, rowNum) ->
                        new ReportEntryRow(
                                rs.getString("section"),
                                rs.getInt("position"),
                                rs.getObject("id", UUID.class),
                                rs.getString("title"),
                                rs.getString("summary_zh"),
                                rs.getString("canonical_url"),
                                rs.getString("content_type"),
                                rs.getString("source_id"),
                                rs.getString("source_name"),
                                rs.getString("organization"),
                                rs.getString("source_tier"),
                                rs.getString("story_slug"),
                                rs.getInt("independent_sources")));
    }

    ReportNavigationRow navigation(String period, String key) {
        return jdbc.queryForObject(
                NAV_SQL,
                new MapSqlParameterSource().addValue("period", period).addValue("key", key),
                (rs, rowNum) ->
                        new ReportNavigationRow(
                                rs.getString("previous_key"), rs.getString("next_key")));
    }

    record ReportRow(
            UUID id,
            String date,
            String title,
            String summary,
            String bodyMarkdown,
            int itemCount,
            OffsetDateTime generatedAt,
            String modelName,
            String promptVersion,
            String status,
            OffsetDateTime publishedAt) {}

    record ReportSummaryRow(
            String date,
            String title,
            String summary,
            int itemCount,
            OffsetDateTime generatedAt,
            String modelName,
            String status) {}

    record ReportEntryRow(
            String section,
            int position,
            UUID id,
            String title,
            String summary,
            String canonicalUrl,
            String contentType,
            String sourceId,
            String sourceName,
            String organization,
            String sourceTier,
            String storySlug,
            int independentSources) {}

    record ReportNavigationRow(String previousKey, String nextKey) {}
}
