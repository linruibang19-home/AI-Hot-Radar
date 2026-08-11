package com.aihotradar.coreapi.content;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Daily, weekly and monthly report endpoints (AHR-FEAT-105).
 *
 * <p>Web, email and future RSS output read the same stored report facts. The detail response exposes
 * the report-item provenance as a structured read model; the browser never has to reverse-engineer
 * generated Markdown to find titles, publishers or Story relationships.
 */
@RestController
@RequestMapping("/api/v1/reports")
public class ReportController {

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

    private static final Map<String, String> SECTION_LABELS =
            Map.ofEntries(
                    Map.entry("model_release", "模型发布"),
                    Map.entry("product_release", "产品发布"),
                    Map.entry("api_update", "API 与平台更新"),
                    Map.entry("open_source", "开源项目"),
                    Map.entry("research", "研究进展"),
                    Map.entry("security", "安全"),
                    Map.entry("business", "行业与商业"),
                    Map.entry("policy", "政策与监管"),
                    Map.entry("tutorial", "教程与实践"),
                    Map.entry("opinion", "观点"),
                    Map.entry("other", "其他"));

    private final NamedParameterJdbcTemplate jdbc;

    public ReportController(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping
    public List<ReportSummary> list(
            @RequestParam(required = false, defaultValue = "daily") String period,
            @RequestParam(required = false, defaultValue = "30") int limit) {
        return jdbc.query(
                LIST_SQL,
                new MapSqlParameterSource()
                        .addValue("period", normalisePeriod(period))
                        .addValue("limit", Math.min(Math.max(limit, 1), 90)),
                (rs, rowNum) ->
                        new ReportSummary(
                                rs.getString("period_key"),
                                rs.getString("title"),
                                rs.getString("summary"),
                                rs.getInt("item_count"),
                                rs.getObject("generated_at", OffsetDateTime.class),
                                rs.getString("model_name"),
                                rs.getString("status")));
    }

    @GetMapping("/{period}/{key}")
    public ResponseEntity<ReportDetail> detail(
            @PathVariable String period, @PathVariable String key) {
        String resolvedPeriod = normalisePeriod(period);
        List<ReportRow> rows =
                jdbc.query(
                        DETAIL_SQL,
                        new MapSqlParameterSource()
                                .addValue("period", resolvedPeriod)
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

        if (rows.isEmpty()) {
            return ResponseEntity.notFound().build();
        }

        ReportRow row = rows.getFirst();
        List<ReportEntry> entries = loadEntries(row.id());
        List<ReportSection> sections = groupSections(entries);
        ReportStats stats = buildStats(row.bodyMarkdown(), sections, entries);
        ReportNavigation navigation = loadNavigation(resolvedPeriod, key);

        return ResponseEntity.ok(
                new ReportDetail(
                        row.date(),
                        row.title(),
                        row.summary(),
                        row.bodyMarkdown(),
                        row.itemCount(),
                        row.generatedAt(),
                        row.modelName(),
                        row.promptVersion(),
                        row.status(),
                        row.publishedAt(),
                        sections,
                        stats,
                        navigation));
    }

    private List<ReportEntry> loadEntries(UUID reportId) {
        return jdbc.query(
                ITEMS_SQL,
                new MapSqlParameterSource("reportId", reportId),
                (rs, rowNum) ->
                        new ReportEntry(
                                normaliseSection(rs.getString("section")),
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

    private ReportNavigation loadNavigation(String period, String key) {
        return jdbc.queryForObject(
                NAV_SQL,
                new MapSqlParameterSource().addValue("period", period).addValue("key", key),
                (rs, rowNum) ->
                        new ReportNavigation(
                                rs.getString("previous_key"), rs.getString("next_key")));
    }

    static List<ReportSection> groupSections(List<ReportEntry> entries) {
        Map<String, List<ReportEntry>> grouped = new LinkedHashMap<>();
        for (ReportEntry entry : entries) {
            grouped.computeIfAbsent(entry.section(), ignored -> new ArrayList<>()).add(entry);
        }
        return grouped.entrySet().stream()
                .map(
                        section ->
                                new ReportSection(
                                        section.getKey(),
                                        sectionLabel(section.getKey()),
                                        section.getValue().size(),
                                        List.copyOf(section.getValue())))
                .toList();
    }

    static ReportStats buildStats(
            String bodyMarkdown, List<ReportSection> sections, List<ReportEntry> entries) {
        Set<String> sources = new LinkedHashSet<>();
        Set<String> stories = new LinkedHashSet<>();
        int primarySources = 0;

        for (ReportEntry entry : entries) {
            sources.add(entry.sourceId());
            if ("primary".equalsIgnoreCase(entry.sourceTier())) {
                primarySources++;
            }
            stories.add(
                    entry.storySlug() == null || entry.storySlug().isBlank()
                            ? "item:" + entry.id()
                            : "story:" + entry.storySlug());
        }

        int readableCharacters = bodyMarkdown == null ? 0 : bodyMarkdown.replaceAll("\\s+", "").length();
        int readingMinutes = Math.max(1, (int) Math.ceil(readableCharacters / 500.0));
        return new ReportStats(
                entries.size(),
                sections.size(),
                sources.size(),
                primarySources,
                stories.size(),
                readingMinutes);
    }

    static String sectionLabel(String key) {
        return SECTION_LABELS.getOrDefault(normaliseSection(key), "其他");
    }

    private static String normaliseSection(String section) {
        return section == null || section.isBlank()
                ? "other"
                : section.toLowerCase(Locale.ROOT);
    }

    /**
     * Reject unknown period values rather than passing them to SQL.
     *
     * <p>The parameter is bound, so this is not an injection guard; it keeps an arbitrary string
     * from silently returning an empty list, which would look like "no reports" instead of "wrong
     * URL".
     */
    private static String normalisePeriod(String period) {
        return switch (period == null ? "" : period.toLowerCase(Locale.ROOT)) {
            case "weekly" -> "weekly";
            case "monthly" -> "monthly";
            default -> "daily";
        };
    }

    private record ReportRow(
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

    public record ReportSummary(
            String date,
            String title,
            String summary,
            int itemCount,
            OffsetDateTime generatedAt,
            String modelName,
            String status) {}

    public record ReportEntry(
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

    public record ReportSection(String key, String label, int count, List<ReportEntry> items) {}

    public record ReportStats(
            int items,
            int sections,
            int sources,
            int primarySources,
            int stories,
            int readingMinutes) {}

    public record ReportNavigation(String previousKey, String nextKey) {}

    public record ReportDetail(
            String date,
            String title,
            String summary,
            String bodyMarkdown,
            int itemCount,
            OffsetDateTime generatedAt,
            String modelName,
            String promptVersion,
            String status,
            OffsetDateTime publishedAt,
            List<ReportSection> sections,
            ReportStats stats,
            ReportNavigation navigation) {}
}
