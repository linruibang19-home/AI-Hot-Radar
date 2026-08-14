package com.aihotradar.coreapi.content;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/** PostgreSQL read adapter for reader-facing Story projections. */
@Repository
public class StoryRepository {

    static final String SUMMARY_SELECT =
            """
            SELECT st.id, st.slug, st.title, st.occurred_at, st.heat_score,
                   st.independent_source_count, st.item_count,
                   st.locked_by_editor,
                   pi.content_type,
                   ps.name AS primary_source_name,
                   ps.source_tier AS primary_source_tier,
                   ARRAY(
                       SELECT source_name
                         FROM (
                               SELECT DISTINCT s2.name AS source_name
                                 FROM story_item si2
                                 JOIN content_item ci2 ON ci2.id = si2.content_item_id
                                 JOIN source s2 ON s2.id = ci2.source_id
                                WHERE si2.story_id = st.id
                              ) story_sources
                        ORDER BY source_name
                   ) AS source_names
              FROM story st
              LEFT JOIN content_item pi ON pi.id = st.primary_item_id
              LEFT JOIN source ps ON ps.id = pi.source_id
            """;

    static final String LIST_FILTER =
            """
             WHERE st.status = 'PUBLISHED'
               AND st.independent_source_count >= 2
               AND (SELECT COUNT(*)
                      FROM story_item confidence_items
                     WHERE confidence_items.story_id = st.id
                       AND confidence_items.similarity_score IS NOT NULL) >= st.item_count - 1
               AND (SELECT MIN(confidence_items.similarity_score)
                      FROM story_item confidence_items
                     WHERE confidence_items.story_id = st.id
                       AND confidence_items.similarity_score IS NOT NULL) >= :minConfidence
             ORDER BY st.heat_score DESC NULLS LAST, st.occurred_at DESC
             LIMIT :limit
            """;

    static final String DETAIL_FILTER =
            """
             WHERE st.slug = :slug
               AND st.status = 'PUBLISHED'
               AND st.independent_source_count >= 2
               AND (SELECT COUNT(*)
                      FROM story_item confidence_items
                     WHERE confidence_items.story_id = st.id
                       AND confidence_items.similarity_score IS NOT NULL) >= st.item_count - 1
               AND (SELECT MIN(confidence_items.similarity_score)
                      FROM story_item confidence_items
                     WHERE confidence_items.story_id = st.id
                       AND confidence_items.similarity_score IS NOT NULL) >= :minConfidence
            """;

    static final String ITEMS_SQL =
            """
            SELECT ci.id, COALESCE(ci.zh_title, ci.title) AS title,
                   ci.summary_zh, ci.canonical_url, ci.published_at,
                   ci.observed_at, ci.content_type,
                   si.relation_type, si.similarity_score,
                   s.name AS source_name, s.source_tier, s.organization
              FROM story_item si
              JOIN story st ON st.id = si.story_id
              JOIN content_item ci ON ci.id = si.content_item_id
              JOIN source s ON s.id = ci.source_id
             WHERE st.slug = :slug
             ORDER BY COALESCE(ci.published_at, ci.observed_at) ASC
            """;

    private static final RowMapper<StoryRow> SUMMARY_MAPPER =
            (rs, rowNum) ->
                    new StoryRow(
                            rs.getString("id"),
                            rs.getString("slug"),
                            rs.getString("title"),
                            rs.getObject("occurred_at", OffsetDateTime.class),
                            rs.getObject("heat_score") == null ? null : rs.getDouble("heat_score"),
                            rs.getInt("independent_source_count"),
                            rs.getInt("item_count"),
                            rs.getBoolean("locked_by_editor"),
                            rs.getString("content_type"),
                            rs.getString("primary_source_name"),
                            rs.getString("primary_source_tier"),
                            readSourceNames(rs));

    private final NamedParameterJdbcTemplate jdbc;

    public StoryRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    List<StoryRow> findPublished(int limit, double minConfidence) {
        return jdbc.query(
                SUMMARY_SELECT + LIST_FILTER,
                new MapSqlParameterSource()
                        .addValue("limit", limit)
                        .addValue("minConfidence", minConfidence),
                SUMMARY_MAPPER);
    }

    Optional<StoryRow> findPublishedBySlug(String slug, double minConfidence) {
        List<StoryRow> rows =
                jdbc.query(
                        SUMMARY_SELECT + DETAIL_FILTER,
                        new MapSqlParameterSource("slug", slug)
                                .addValue("minConfidence", minConfidence),
                        SUMMARY_MAPPER);
        return rows.stream().findFirst();
    }

    List<StoryEntryRow> findTimeline(String slug) {
        return jdbc.query(
                ITEMS_SQL,
                new MapSqlParameterSource("slug", slug),
                (rs, rowNum) -> mapEntry(rs));
    }

    private static StoryEntryRow mapEntry(ResultSet rs) throws SQLException {
        return new StoryEntryRow(
                rs.getString("id"),
                rs.getString("title"),
                rs.getString("summary_zh"),
                rs.getString("canonical_url"),
                rs.getObject("published_at", OffsetDateTime.class),
                rs.getObject("observed_at", OffsetDateTime.class),
                rs.getString("content_type"),
                rs.getString("relation_type"),
                rs.getObject("similarity_score") == null
                        ? null
                        : rs.getDouble("similarity_score"),
                rs.getString("source_name"),
                rs.getString("source_tier"),
                rs.getString("organization"));
    }

    private static List<String> readSourceNames(ResultSet rs) throws SQLException {
        java.sql.Array values = rs.getArray("source_names");
        if (values == null) {
            return List.of();
        }
        Object raw = values.getArray();
        if (raw instanceof String[] names) {
            return Arrays.asList(names);
        }
        return Arrays.stream((Object[]) raw).map(String::valueOf).toList();
    }

    record StoryRow(
            String id,
            String slug,
            String title,
            OffsetDateTime occurredAt,
            Double heat,
            int independentSources,
            int itemCount,
            boolean locked,
            String contentType,
            String primarySourceName,
            String primarySourceTier,
            List<String> sourceNames) {}

    record StoryEntryRow(
            String id,
            String title,
            String summary,
            String canonicalUrl,
            OffsetDateTime publishedAt,
            OffsetDateTime observedAt,
            String contentType,
            String relationType,
            Double similarity,
            String sourceName,
            String sourceTier,
            String organization) {}
}
