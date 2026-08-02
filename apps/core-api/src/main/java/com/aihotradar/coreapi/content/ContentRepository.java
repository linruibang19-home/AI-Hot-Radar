package com.aihotradar.coreapi.content;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * Read access to published content.
 *
 * <p>Two rules from the spec are enforced here rather than in the controller, so
 * no future caller can bypass them:
 *
 * <ul>
 *   <li>near-duplicate copies are hidden ({@code duplicate_of_id IS NULL}), because
 *       AHR-DATA-300 §5 treats them as the same article;
 *   <li>items are returned even when enrichment has not run, so the site stays
 *       usable while the model is unavailable (M2 acceptance).
 * </ul>
 */
@Repository
public class ContentRepository {

    private static final String BASE_SELECT =
            """
            SELECT ci.id, ci.title, ci.zh_title, ci.summary_zh, cr.excerpt,
                   ci.canonical_url, ci.published_at, ci.observed_at,
                   ci.content_type, ci.quality_score,
                   s.id AS source_id, s.name AS source_name,
                   s.source_tier, s.organization
              FROM content_item ci
              JOIN source s ON s.id = ci.source_id
              LEFT JOIN content_revision cr ON cr.id = ci.current_revision_id
             WHERE ci.duplicate_of_id IS NULL
            """;

    private final NamedParameterJdbcTemplate jdbc;

    public ContentRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<ContentItem> MAPPER =
            (ResultSet rs, int rowNum) -> mapRow(rs);

    private static ContentItem mapRow(ResultSet rs) throws SQLException {
        return new ContentItem(
                rs.getString("id"),
                rs.getString("title"),
                rs.getString("zh_title"),
                rs.getString("summary_zh"),
                rs.getString("excerpt"),
                rs.getString("canonical_url"),
                rs.getObject("published_at", OffsetDateTime.class),
                rs.getObject("observed_at", OffsetDateTime.class),
                rs.getString("content_type"),
                rs.getObject("quality_score") == null ? null : rs.getDouble("quality_score"),
                new ContentItem.SourceRef(
                        rs.getString("source_id"),
                        rs.getString("source_name"),
                        rs.getString("source_tier"),
                        rs.getString("organization")));
    }

    /**
     * One page of the feed, newest first.
     *
     * <p>The cursor is the {@code (published_at, id)} pair of the last row seen.
     * Comparing the pair as a tuple keeps paging stable when many items share a
     * timestamp, which is common for batch-published releases.
     */
    public List<ContentItem> findFeed(
            Cursor cursor, int limit, String sourceId, String contentType, String query) {

        StringBuilder sql = new StringBuilder(BASE_SELECT);
        MapSqlParameterSource params = new MapSqlParameterSource();

        if (cursor != null) {
            sql.append(
                    " AND (ci.published_at, ci.id) < (:cursorTime, CAST(:cursorId AS uuid))");
            params.addValue("cursorTime", cursor.publishedAt());
            params.addValue("cursorId", cursor.id());
        }
        if (sourceId != null && !sourceId.isBlank()) {
            sql.append(" AND ci.source_id = :sourceId");
            params.addValue("sourceId", sourceId);
        }
        if (contentType != null && !contentType.isBlank()) {
            // A UI tab maps to several content types ("产品" covers product and
            // API releases), so the filter takes a list rather than one value.
            List<String> types = ContentCategory.resolve(contentType);
            if (!types.isEmpty()) {
                sql.append(" AND ci.content_type IN (:contentTypes)");
                params.addValue("contentTypes", types);
            }
        }
        if (query != null && !query.isBlank()) {
            // Full-text match on the weighted tsvector, with a trigram fallback so
            // partial version strings ("v2.52") still hit — tsvector tokenisation
            // splits those apart (AHR-PRD-100 §102 forbids relying on semantic
            // matching alone for exact names and versions).
            sql.append(
                    " AND (ci.search_vector @@ plainto_tsquery('simple', :rawQuery)"
                            + " OR ci.title ILIKE :likeQuery"
                            + " OR ci.zh_title ILIKE :likeQuery)");
            params.addValue("rawQuery", query.trim());
            params.addValue("likeQuery", "%" + query.trim() + "%");
        }

        sql.append(" ORDER BY ci.published_at DESC NULLS LAST, ci.id DESC LIMIT :limit");
        params.addValue("limit", limit);

        return jdbc.query(sql.toString(), params, MAPPER);
    }

    public Optional<ContentItem> findById(String id) {
        String sql = BASE_SELECT + " AND ci.id = CAST(:id AS uuid)";
        List<ContentItem> rows =
                jdbc.query(sql, new MapSqlParameterSource("id", id), MAPPER);
        return rows.stream().findFirst();
    }

    /** Feed counts grouped by day, for the date-grouped homepage. */
    public List<DayCount> countByDay(int days) {
        String sql =
                """
                SELECT date_trunc('day', COALESCE(published_at, observed_at)) AS day,
                       count(*) AS total
                  FROM content_item
                 WHERE duplicate_of_id IS NULL
                   AND COALESCE(published_at, observed_at) > now() - (:days || ' days')::interval
                 GROUP BY 1 ORDER BY 1 DESC
                """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource("days", days),
                (rs, rowNum) ->
                        new DayCount(
                                rs.getObject("day", OffsetDateTime.class), rs.getLong("total")));
    }

    /**
     * The curated shortlist for the homepage.
     *
     * <p>Reads {@code selection_record} rather than re-ranking here, so the site
     * shows exactly the decision that was recorded and can explain it
     * (AHR-PRD-100 §4 requires the contributing factors to be visible).
     */
    public List<SelectedItem> findSelected(int days, int limit) {
        String sql =
                """
                SELECT ci.id, ci.title, ci.zh_title, ci.summary_zh, cr.excerpt,
                       ci.canonical_url, ci.published_at, ci.observed_at,
                       ci.content_type, ci.quality_score,
                       s.id AS source_id, s.name AS source_name,
                       s.source_tier, s.organization,
                       sr.selected_for_date, sr.score AS selection_score, sr.reason
                  FROM selection_record sr
                  JOIN content_item ci ON ci.id = sr.content_item_id
                  JOIN source s ON s.id = ci.source_id
                  LEFT JOIN content_revision cr ON cr.id = ci.current_revision_id
                 WHERE sr.withdrawn_at IS NULL
                   AND ci.duplicate_of_id IS NULL
                   AND sr.selected_for_date > current_date - CAST(:days AS integer)
                 ORDER BY sr.selected_for_date DESC, sr.score DESC
                 LIMIT :limit
                """;
        MapSqlParameterSource params =
                new MapSqlParameterSource().addValue("days", days).addValue("limit", limit);

        return jdbc.query(
                sql,
                params,
                (rs, rowNum) ->
                        new SelectedItem(
                                mapRow(rs),
                                rs.getObject("selected_for_date", java.time.LocalDate.class),
                                rs.getDouble("selection_score"),
                                rs.getString("reason")));
    }

    /** Topics attached to one item. */
    public List<TopicRef> findTopics(String itemId) {
        String sql =
                """
                SELECT t.slug, t.name, it.confidence
                  FROM item_topic it
                  JOIN topic t ON t.id = it.topic_id
                 WHERE it.content_item_id = CAST(:id AS uuid)
                 ORDER BY it.confidence DESC NULLS LAST
                """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource("id", itemId),
                (rs, rowNum) ->
                        new TopicRef(
                                rs.getString("slug"), rs.getString("name"), rs.getDouble("confidence")));
    }

    /** Topics ordered by how much content currently carries them. */
    public List<TopicSummary> listTopics() {
        String sql =
                """
                SELECT t.slug, t.name, count(it.content_item_id) AS total
                  FROM topic t
                  LEFT JOIN item_topic it ON it.topic_id = t.id
                  LEFT JOIN content_item ci
                         ON ci.id = it.content_item_id AND ci.duplicate_of_id IS NULL
                 GROUP BY t.slug, t.name
                HAVING count(it.content_item_id) > 0
                 ORDER BY total DESC
                """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource(),
                (rs, rowNum) ->
                        new TopicSummary(
                                rs.getString("slug"), rs.getString("name"), rs.getLong("total")));
    }

    public List<ContentItem> findByTopic(String slug, int limit) {
        String sql =
                BASE_SELECT
                        + """
                           AND ci.id IN (
                               SELECT it.content_item_id FROM item_topic it
                               JOIN topic t ON t.id = it.topic_id
                              WHERE t.slug = :slug
                           )
                         ORDER BY ci.published_at DESC NULLS LAST, ci.id DESC
                         LIMIT :limit
                        """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource().addValue("slug", slug).addValue("limit", limit),
                MAPPER);
    }

    /**
     * Current hot ranking.
     *
     * <p>Reads the stored hot_score rather than ranking on the fly: AHR-PRD-100
     * §4 requires the score and its factors to be inspectable, and recomputing
     * per request would make the list shift between page loads.
     */
    public List<HotItem> findHot(int limit) {
        String sql =
                """
                SELECT ci.id, COALESCE(ci.zh_title, ci.title) AS title,
                       ci.hot_score, ci.independent_source_count, ci.content_type,
                       s.name AS source_name
                  FROM content_item ci
                  JOIN source s ON s.id = ci.source_id
                 WHERE ci.duplicate_of_id IS NULL
                   AND ci.hot_score IS NOT NULL
                 ORDER BY ci.hot_score DESC
                 LIMIT :limit
                """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource("limit", limit),
                (rs, rowNum) ->
                        new HotItem(
                                rs.getString("id"),
                                rs.getString("title"),
                                Math.round(rs.getDouble("hot_score")),
                                rs.getInt("independent_source_count"),
                                rs.getString("content_type"),
                                rs.getString("source_name")));
    }

    /** Item counts per category tab, so empty tabs can be hidden. */
    public List<CategoryCount> categoryCounts() {
        String sql =
                """
                SELECT content_type, count(*) AS total
                  FROM content_item
                 WHERE duplicate_of_id IS NULL AND content_type IS NOT NULL
                 GROUP BY content_type
                """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource(),
                (rs, rowNum) ->
                        new CategoryCount(rs.getString("content_type"), rs.getLong("total")));
    }

    public Stats stats() {
        String sql =
                """
                SELECT (SELECT count(*) FROM content_item WHERE duplicate_of_id IS NULL) AS items,
                       (SELECT count(*) FROM content_item WHERE enrichment_state = 'ENRICHED') AS enriched,
                       (SELECT count(*) FROM source WHERE runtime_state = 'ACTIVE') AS active_sources,
                       (SELECT count(*) FROM content_chunk) AS chunks
                """;
        List<Stats> rows =
                jdbc.query(
                        sql,
                        new MapSqlParameterSource(),
                        (rs, rowNum) ->
                                new Stats(
                                        rs.getLong("items"),
                                        rs.getLong("enriched"),
                                        rs.getLong("active_sources"),
                                        rs.getLong("chunks")));
        return rows.isEmpty() ? new Stats(0, 0, 0, 0) : rows.get(0);
    }

    public record Cursor(OffsetDateTime publishedAt, String id) {}

    public record DayCount(OffsetDateTime day, long total) {}

    public record Stats(long items, long enriched, long activeSources, long chunks) {}

    /** A curated item plus the recorded reason it was chosen. */
    public record SelectedItem(
            ContentItem item, java.time.LocalDate selectedFor, double score, String reason) {}

    public record TopicRef(String slug, String name, Double confidence) {}

    public record TopicSummary(String slug, String name, long total) {}

    public record HotItem(
            String id,
            String title,
            long heat,
            int independentSources,
            String contentType,
            String sourceName) {}

    public record CategoryCount(String contentType, long total) {}
}
