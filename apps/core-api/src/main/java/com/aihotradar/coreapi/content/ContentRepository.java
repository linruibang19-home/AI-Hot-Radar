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
            sql.append(" AND ci.content_type = :contentType");
            params.addValue("contentType", contentType);
        }
        if (query != null && !query.isBlank()) {
            // ILIKE over titles is adequate at current volume; FTS ranking is an
            // M2 search-page concern and needs the tsvector index to be populated.
            sql.append(" AND (ci.title ILIKE :query OR ci.zh_title ILIKE :query)");
            params.addValue("query", "%" + query.trim() + "%");
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
}
