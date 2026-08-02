package com.aihotradar.coreapi.content;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Story endpoints (M3, AHR-DATA-300 §8).
 *
 * <p>A Story is one real-world event with every item that reported it. The
 * ranking here differs from {@code /hot} in a way that matters: an item's heat
 * is a proxy, while a Story's independent-source count is measured, so this is
 * the endpoint that can honestly claim to rank by attention.
 */
@RestController
@RequestMapping("/api/v1/stories")
public class StoryController {

    private final NamedParameterJdbcTemplate jdbc;

    public StoryController(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final String SUMMARY_SELECT =
            """
            SELECT st.id, st.slug, st.title, st.occurred_at, st.heat_score,
                   st.independent_source_count, st.item_count,
                   st.locked_by_editor,
                   pi.content_type,
                   ps.name AS primary_source_name,
                   ps.source_tier AS primary_source_tier
              FROM story st
              LEFT JOIN content_item pi ON pi.id = st.primary_item_id
              LEFT JOIN source ps ON ps.id = pi.source_id
            """;

    private static final RowMapper<StorySummary> SUMMARY_MAPPER =
            (ResultSet rs, int rowNum) ->
                    new StorySummary(
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
                            rs.getString("primary_source_tier"));

    /** Stories ranked by heat. */
    @GetMapping
    public List<StorySummary> list(
            @RequestParam(required = false, defaultValue = "30") int limit,
            @RequestParam(required = false, defaultValue = "1") int minSources) {

        String sql =
                SUMMARY_SELECT
                        + """
                         WHERE st.status = 'PUBLISHED'
                           AND st.independent_source_count >= :minSources
                         ORDER BY st.heat_score DESC NULLS LAST, st.occurred_at DESC
                         LIMIT :limit
                        """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource()
                        .addValue("limit", Math.min(Math.max(limit, 1), 100))
                        .addValue("minSources", Math.max(minSources, 1)),
                SUMMARY_MAPPER);
    }

    @GetMapping("/{slug}")
    public ResponseEntity<StoryDetail> detail(@PathVariable String slug) {
        List<StorySummary> found =
                jdbc.query(
                        SUMMARY_SELECT + " WHERE st.slug = :slug",
                        new MapSqlParameterSource("slug", slug),
                        SUMMARY_MAPPER);
        if (found.isEmpty()) {
            return ResponseEntity.notFound().build();
        }

        // The timeline is ordered oldest first: a reader following an event
        // wants to see how it developed, not how it was ranked.
        String itemsSql =
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

        List<StoryEntry> entries =
                jdbc.query(
                        itemsSql,
                        new MapSqlParameterSource("slug", slug),
                        (ResultSet rs, int rowNum) -> mapEntry(rs));

        return ResponseEntity.ok(new StoryDetail(found.get(0), entries));
    }

    private static StoryEntry mapEntry(ResultSet rs) throws SQLException {
        return new StoryEntry(
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

    public record StorySummary(
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
            String primarySourceTier) {}

    public record StoryEntry(
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

    public record StoryDetail(StorySummary story, List<StoryEntry> timeline) {}
}
