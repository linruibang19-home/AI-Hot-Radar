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
                   ci.hot_score, ci.independent_source_count,
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
                rs.getObject("hot_score") == null ? null : rs.getDouble("hot_score"),
                rs.getObject("independent_source_count") == null
                        ? null
                        : rs.getInt("independent_source_count"),
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
        return findFeed(cursor, limit, sourceId, contentType, query, null);
    }

    public List<ContentItem> findFeed(
            Cursor cursor,
            int limit,
            String sourceId,
            String contentType,
            String query,
            String day) {

        StringBuilder sql = new StringBuilder(BASE_SELECT);
        MapSqlParameterSource params = new MapSqlParameterSource();

        if (day != null && !day.isBlank()) {
            // Same expression as dayCounts, so a day's header and its contents
            // can never disagree about which items belong to it.
            sql.append(
                    " AND (COALESCE(ci.published_at, ci.observed_at)"
                            + " AT TIME ZONE 'Asia/Shanghai')::date = CAST(:day AS date)");
            params.addValue("day", day.trim());
        }

        if (cursor != null) {
            sql.append(
                    " AND (COALESCE(ci.published_at, ci.observed_at), ci.id)"
                            + " < (:cursorTime, CAST(:cursorId AS uuid))");
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

        // Order by the same expression the UI groups by. Ordering on
        // published_at alone sent items without a publication date to the end of
        // the feed while the page still grouped them under the day they were
        // observed, so a recent-looking day section appeared below much older
        // ones and the timeline read as jumbled.
        sql.append(
                " ORDER BY COALESCE(ci.published_at, ci.observed_at) DESC, ci.id DESC LIMIT :limit");
        params.addValue("limit", limit);

        return jdbc.query(sql.toString(), params, MAPPER);
    }

    public Optional<ContentItem> findById(String id) {
        String sql = BASE_SELECT + " AND ci.id = CAST(:id AS uuid)";
        List<ContentItem> rows =
                jdbc.query(sql, new MapSqlParameterSource("id", id), MAPPER);
        return rows.stream().findFirst();
    }

    /**
     * The curated shortlist for the homepage.
     *
     * <p>Reads {@code selection_record} rather than re-ranking here, so the site
     * shows exactly the decision that was recorded and can explain it
     * (AHR-PRD-100 §4 requires the contributing factors to be visible).
     */
    public List<SelectedItem> findSelected(int days, int limit, String contentType, String sort) {
        StringBuilder sql =
                new StringBuilder(
                        """
                        SELECT ci.id, ci.title, ci.zh_title, ci.summary_zh, cr.excerpt,
                               ci.canonical_url, ci.published_at, ci.observed_at,
                               ci.content_type, ci.quality_score,
                               ci.hot_score, ci.independent_source_count,
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
                        """);
        MapSqlParameterSource params =
                new MapSqlParameterSource().addValue("days", days).addValue("limit", limit);

        if (contentType != null && !contentType.isBlank()) {
            List<String> types = ContentCategory.resolve(contentType);
            if (!types.isEmpty()) {
                sql.append(" AND ci.content_type IN (:contentTypes)");
                params.addValue("contentTypes", types);
            }
        }

        // "latest" orders by publication rather than by the day the editor picked
        // it: a piece selected today may have been published yesterday, and the
        // time-ordered view has to reflect the article's own timeline.
        sql.append(
                "heat".equals(sort)
                        ? " ORDER BY ci.hot_score DESC NULLS LAST, sr.score DESC"
                        : "latest".equals(sort)
                                ? " ORDER BY COALESCE(ci.published_at, ci.observed_at) DESC"
                                : " ORDER BY sr.selected_for_date DESC, sr.score DESC");
        sql.append(" LIMIT :limit");

        return jdbc.query(
                sql.toString(),
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
                  FROM public_item_topic it
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
                SELECT t.slug, t.name, count(ci.id) AS total
                  FROM topic t
                  LEFT JOIN public_item_topic it ON it.topic_id = t.id
                  LEFT JOIN content_item ci
                         ON ci.id = it.content_item_id AND ci.duplicate_of_id IS NULL
                 GROUP BY t.slug, t.name
                HAVING count(ci.id) > 0
                 ORDER BY total DESC
                """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource(),
                (rs, rowNum) ->
                        new TopicSummary(
                                rs.getString("slug"), rs.getString("name"), rs.getLong("total")));
    }

    /**
     * The topic map: every vocabulary entry with its group, description and count.
     *
     * <p>Unlike {@link #listTopics()} this keeps zero-count topics. The map is
     * meant to show the shape of the controlled vocabulary — a topic with no
     * coverage yet is itself information, and hiding it would make the taxonomy
     * look like it changes size as content arrives.
     */
    public List<TopicNode> topicMap() {
        String sql =
                """
                SELECT t.slug, t.name, t.description, t.display_order,
                       t.parent_id IS NULL AS is_group,
                       COALESCE(g.slug, t.slug) AS group_slug,
                       COALESCE(g.name, t.name) AS group_name,
                       -- A group row has no parent to read the blurb from, so it
                       -- supplies its own; otherwise the heading loses its text
                       -- because the group is always the first row of its block.
                       CASE WHEN t.parent_id IS NULL THEN t.description
                            ELSE g.description END AS group_description,
                       COALESCE(g.display_order, t.display_order) AS group_order,
                       count(ci.id) AS total
                  FROM topic t
                  LEFT JOIN topic g ON g.id = t.parent_id
                  LEFT JOIN public_item_topic it ON it.topic_id = t.id
                  LEFT JOIN content_item ci
                         ON ci.id = it.content_item_id AND ci.duplicate_of_id IS NULL
                 GROUP BY t.slug, t.name, t.description, t.display_order,
                          t.parent_id, g.slug, g.name, g.description, g.display_order
                 ORDER BY group_order, is_group DESC, t.display_order, t.slug
                """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource(),
                (rs, rowNum) ->
                        new TopicNode(
                                rs.getString("slug"),
                                rs.getString("name"),
                                rs.getString("description"),
                                rs.getBoolean("is_group"),
                                rs.getString("group_slug"),
                                rs.getString("group_name"),
                                rs.getString("group_description"),
                                rs.getLong("total")));
    }

    /**
     * The company / model-family cards.
     *
     * <p>Counted over `item_entity`, distinct by item, because a vendor owns several entity rows
     * and an article mentioning both "OpenAI" and "GPT-5.6" is one article. A plain count would
     * report it twice and make the busiest vendors look busier than they are.
     *
     * <p>Vendors with no matching entity still appear, with zero. The curated list is a statement
     * about what the site tracks; hiding an empty one would quietly turn "we have nothing on
     * Mistral this week" into "Mistral does not exist".
     */
    public List<VendorNode> vendorMap() {
        String sql =
                """
                SELECT v.slug, v.name, v.description,
                       count(DISTINCT ci.id) FILTER (
                           WHERE ivr.relation_level = 'primary'
                       ) AS total,
                       count(DISTINCT ci.id) FILTER (
                           WHERE ivr.relation_level = 'related'
                       ) AS related_total,
                       count(DISTINCT ci.id) FILTER (
                           WHERE ivr.relation_level = 'mention'
                       ) AS mention_total,
                       count(DISTINCT ci.id) FILTER (
                           WHERE ivr.relation_level = 'primary'
                             AND COALESCE(ci.published_at, ci.observed_at) >= now() - interval '7 days'
                       ) AS recent_primary_total,
                       max(ivr.evaluated_at) AS updated_at
                  FROM vendor v
                  LEFT JOIN item_vendor_relation ivr ON ivr.vendor_slug = v.slug
                  LEFT JOIN content_item ci
                         ON ci.id = ivr.content_item_id AND ci.duplicate_of_id IS NULL
                 GROUP BY v.slug, v.name, v.description, v.display_order
                 ORDER BY v.display_order, v.slug
                """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource(),
                (rs, rowNum) ->
                        new VendorNode(
                                rs.getString("slug"),
                                rs.getString("name"),
                                rs.getString("description"),
                                rs.getLong("total"),
                                rs.getLong("related_total"),
                                rs.getLong("mention_total"),
                                rs.getLong("recent_primary_total"),
                                rs.getObject("updated_at", OffsetDateTime.class)));
    }

    /**
     * The content-form cards, from `content_item.content_type`.
     *
     * <p>Inner join on the metadata table so a type with no display entry does not render as a
     * card labelled with its raw enum name. Measured: 137 of 1578 items have no content_type at
     * all, and those are simply absent rather than bucketed into an "other" card that would mean
     * "the classifier had nothing to say".
     */
    public List<MapNode> contentTypeMap() {
        String sql =
                """
                SELECT m.content_type AS slug, m.name, m.description,
                       count(ci.id) AS total
                  FROM content_type_meta m
                  LEFT JOIN content_item ci
                         ON ci.content_type = m.content_type AND ci.duplicate_of_id IS NULL
                 GROUP BY m.content_type, m.name, m.description, m.display_order
                 ORDER BY m.display_order, m.content_type
                """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource(),
                (rs, rowNum) ->
                        new MapNode(
                                rs.getString("slug"),
                                rs.getString("name"),
                                rs.getString("description"),
                                rs.getLong("total")));
    }

    /** Items belonging to a vendor, through any of its entities. */
    public List<ContentItem> findByVendor(String slug, int limit) {
        String sql =
                BASE_SELECT
                        + """
                           AND EXISTS (
                               SELECT 1
                                 FROM item_entity ie
                                 JOIN entity e ON e.id = ie.entity_id
                                 JOIN vendor_entity ve ON ve.entity_slug = e.slug
                                WHERE ie.content_item_id = ci.id AND ve.vendor_slug = :slug
                           )
                         ORDER BY COALESCE(ci.published_at, ci.observed_at) DESC, ci.id DESC
                         LIMIT :limit
                        """;
        return jdbc.query(
                sql,
                new MapSqlParameterSource().addValue("slug", slug).addValue("limit", limit),
                MAPPER);
    }

    /** One explainable, cursor-pageable relation tier for the public vendor page. */
    public List<VendorItem> findVendorFeed(
            String slug, String relation, VendorCursor cursor, int limit) {
        StringBuilder sql =
                new StringBuilder(
                        """
                        SELECT ci.id, ci.title, ci.zh_title, ci.summary_zh, cr.excerpt,
                               ci.canonical_url, ci.published_at, ci.observed_at,
                               ci.content_type, ci.quality_score,
                               ci.hot_score, ci.independent_source_count,
                               s.id AS source_id, s.name AS source_name,
                               s.source_tier, s.organization,
                               ivr.relation_level, ivr.score, ivr.matched_entity_slug,
                               ivr.reason_code, ivr.evaluated_at
                          FROM item_vendor_relation ivr
                          JOIN content_item ci ON ci.id = ivr.content_item_id
                          JOIN source s ON s.id = ci.source_id
                          LEFT JOIN content_revision cr ON cr.id = ci.current_revision_id
                         WHERE ci.duplicate_of_id IS NULL
                           AND ivr.vendor_slug = :slug
                           AND ivr.relation_level = :relation
                        """);
        MapSqlParameterSource params =
                new MapSqlParameterSource()
                        .addValue("slug", slug)
                        .addValue("relation", relation)
                        .addValue("limit", limit);
        if (cursor != null) {
            sql.append(
                    """
                      AND (COALESCE(ci.published_at, ci.observed_at), ivr.score, ci.id)
                          < (:publishedAt, :score, CAST(:id AS uuid))
                    """);
            params.addValue("score", cursor.score());
            params.addValue("publishedAt", cursor.publishedAt());
            params.addValue("id", cursor.id());
        }
        sql.append(
                """
                 ORDER BY COALESCE(ci.published_at, ci.observed_at) DESC,
                          ivr.score DESC,
                          ci.id DESC
                 LIMIT :limit
                """);
        return jdbc.query(
                sql.toString(),
                params,
                (rs, rowNum) ->
                        new VendorItem(
                                mapRow(rs),
                                rs.getString("relation_level"),
                                rs.getDouble("score"),
                                rs.getString("matched_entity_slug"),
                                rs.getString("reason_code"),
                                rs.getObject("evaluated_at", OffsetDateTime.class)));
    }

    public long countVendorFeed(String slug, String relation) {
        Long value =
                jdbc.queryForObject(
                        """
                        SELECT count(*)
                          FROM item_vendor_relation ivr
                          JOIN content_item ci ON ci.id = ivr.content_item_id
                         WHERE ivr.vendor_slug = :slug
                           AND ivr.relation_level = :relation
                           AND ci.duplicate_of_id IS NULL
                        """,
                        new MapSqlParameterSource()
                                .addValue("slug", slug)
                                .addValue("relation", relation),
                        Long.class);
        return value == null ? 0 : value;
    }

    public OffsetDateTime vendorFeedUpdatedAt(String slug) {
        List<OffsetDateTime> rows =
                jdbc.query(
                        "SELECT max(evaluated_at) AS updated_at FROM item_vendor_relation"
                                + " WHERE vendor_slug = :slug",
                        new MapSqlParameterSource("slug", slug),
                        (rs, rowNum) -> rs.getObject("updated_at", OffsetDateTime.class));
        return rows.isEmpty() ? null : rows.get(0);
    }

    public List<ContentItem> findByTopic(String slug, int limit) {
        String sql =
                BASE_SELECT
                        + """
                           AND ci.id IN (
                               SELECT it.content_item_id FROM public_item_topic it
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

    /** One confidence-filtered, cursor-pageable topic feed. */
    public List<TopicItem> findTopicFeed(String slug, Cursor cursor, int limit) {
        StringBuilder sql =
                new StringBuilder(
                        """
                        SELECT ci.id, ci.title, ci.zh_title, ci.summary_zh, cr.excerpt,
                               ci.canonical_url, ci.published_at, ci.observed_at,
                               ci.content_type, ci.quality_score,
                               ci.hot_score, ci.independent_source_count,
                               s.id AS source_id, s.name AS source_name,
                               s.source_tier, s.organization,
                               pit.confidence
                          FROM public_item_topic pit
                          JOIN topic t ON t.id = pit.topic_id
                          JOIN content_item ci ON ci.id = pit.content_item_id
                          JOIN source s ON s.id = ci.source_id
                          LEFT JOIN content_revision cr ON cr.id = ci.current_revision_id
                         WHERE t.slug = :slug
                           AND ci.duplicate_of_id IS NULL
                        """);
        MapSqlParameterSource params =
                new MapSqlParameterSource().addValue("slug", slug).addValue("limit", limit);
        if (cursor != null) {
            sql.append(
                    """
                      AND (COALESCE(ci.published_at, ci.observed_at), ci.id)
                          < (:publishedAt, CAST(:id AS uuid))
                    """);
            params.addValue("publishedAt", cursor.publishedAt());
            params.addValue("id", cursor.id());
        }
        sql.append(
                """
                 ORDER BY COALESCE(ci.published_at, ci.observed_at) DESC, ci.id DESC
                 LIMIT :limit
                """);
        return jdbc.query(
                sql.toString(),
                params,
                (rs, rowNum) -> new TopicItem(mapRow(rs), rs.getDouble("confidence")));
    }

    public long countTopicFeed(String slug) {
        Long value =
                jdbc.queryForObject(
                        """
                        SELECT count(*)
                          FROM public_item_topic pit
                          JOIN topic t ON t.id = pit.topic_id
                          JOIN content_item ci ON ci.id = pit.content_item_id
                         WHERE t.slug = :slug AND ci.duplicate_of_id IS NULL
                        """,
                        new MapSqlParameterSource("slug", slug),
                        Long.class);
        return value == null ? 0 : value;
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

    /**
     * Item counts per publication day, newest first.
     *
     * The feed is read by date but the item endpoint paginates by count, and on
     * this corpus a single day holds close to 200 items — reaching the previous
     * date took eight "load more" clicks that each looked like nothing had
     * happened. One cheap GROUP BY lets every date render at once, with its
     * items fetched only when a day is opened.
     *
     * The day is derived in the display timezone, not UTC. Grouping by UTC
     * would file everything published after 08:00 Beijing time under the
     * previous day, which is the same defect that once made the whole site
     * render times a day off.
     */
    public List<DayBucket> dayCounts(String contentType, String q) {
        StringBuilder sql =
                new StringBuilder(
                        """
                        SELECT (COALESCE(published_at, observed_at)
                                    AT TIME ZONE 'Asia/Shanghai')::date AS day,
                               count(*) AS total
                          FROM content_item
                         WHERE duplicate_of_id IS NULL
                           AND current_revision_id IS NOT NULL
                        """);
        MapSqlParameterSource params = new MapSqlParameterSource();

        if (contentType != null && !contentType.isBlank()) {
            // A UI tab covers several content types, exactly as in findFeed. A
            // direct equality on the tab key matches nothing: the tab is
            // "model" while the stored values are "model_release" and friends.
            List<String> types = ContentCategory.resolve(contentType);
            if (!types.isEmpty()) {
                sql.append(" AND content_type IN (:contentTypes)");
                params.addValue("contentTypes", types);
            }
        }
        if (q != null && !q.isBlank()) {
            sql.append(
                    " AND (search_vector @@ plainto_tsquery('simple', :rawQuery)"
                            + " OR title ILIKE :likeQuery"
                            + " OR zh_title ILIKE :likeQuery)");
            params.addValue("rawQuery", q.trim());
            params.addValue("likeQuery", "%" + q.trim() + "%");
        }

        sql.append(" GROUP BY day ORDER BY day DESC");
        return jdbc.query(
                sql.toString(),
                params,
                (rs, rowNum) ->
                        new DayBucket(rs.getString("day"), rs.getLong("total")));
    }

    public Stats stats() {
        String sql =
                """
                SELECT (SELECT count(*) FROM content_item WHERE duplicate_of_id IS NULL) AS items,
                       (SELECT count(*) FROM content_item WHERE enrichment_state = 'ENRICHED') AS enriched,
                       (SELECT count(*) FROM source WHERE runtime_state = 'ACTIVE') AS active_sources,
                       (SELECT count(*) FROM content_chunk WHERE is_active) AS chunks
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

    public record Stats(long items, long enriched, long activeSources, long chunks) {}

    /** A curated item plus the recorded reason it was chosen. */
    public record SelectedItem(
            ContentItem item, java.time.LocalDate selectedFor, double score, String reason) {}

    public record TopicRef(String slug, String name, Double confidence) {}

    public record TopicSummary(String slug, String name, long total) {}

    /** One entry of the topic map, carrying the group it belongs to. */
    public record TopicNode(
            String slug,
            String name,
            String description,
            boolean group,
            String groupSlug,
            String groupName,
            String groupDescription,
            long total) {}

    /** One auditable company/model-family entry on the public map. */
    public record VendorNode(
            String slug,
            String name,
            String description,
            long total,
            long relatedTotal,
            long mentionTotal,
            long recentPrimaryTotal,
            OffsetDateTime updatedAt) {}

    /** A simple map card used by the content-form dimension. */
    public record MapNode(String slug, String name, String description, long total) {}

    public record VendorItem(
            ContentItem item,
            String relation,
            double score,
            String matchedEntity,
            String reasonCode,
            OffsetDateTime evaluatedAt) {}

    public record VendorCursor(double score, OffsetDateTime publishedAt, String id) {}

    public record TopicItem(ContentItem item, double confidence) {}

    public record HotItem(
            String id,
            String title,
            long heat,
            int independentSources,
            String contentType,
            String sourceName) {}

    public record CategoryCount(String contentType, long total) {}

    /** A calendar day in the display timezone, as `YYYY-MM-DD`. */
    public record DayBucket(String day, long total) {}
}
