package com.aihotradar.coreapi.content;

import java.time.OffsetDateTime;
import java.util.List;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Daily report endpoints (AHR-FEAT-105).
 *
 * <p>Web, email and RSS all read this same record, so none of them can drift
 * into showing a different set of facts.
 */
@RestController
@RequestMapping("/api/v1/reports")
public class ReportController {

    private final NamedParameterJdbcTemplate jdbc;

    public ReportController(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping
    public List<ReportSummary> list(
            @RequestParam(required = false, defaultValue = "daily") String period,
            @RequestParam(required = false, defaultValue = "30") int limit) {
        String sql =
                """
                SELECT period_key, title, summary, item_count, generated_at, model_name
                  FROM report
                 WHERE period_type = :period
                 ORDER BY period_key DESC
                 LIMIT :limit
                """;
        return jdbc.query(
                sql,
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
                                rs.getString("model_name")));
    }

    @GetMapping("/{period}/{key}")
    public ResponseEntity<ReportDetail> detail(
            @PathVariable String period, @PathVariable String key) {
        String sql =
                """
                SELECT period_key, title, summary, body_markdown, item_count,
                       generated_at, model_name, prompt_version
                  FROM report
                 WHERE period_type = :period AND period_key = :key
                """;
        List<ReportDetail> rows =
                jdbc.query(
                        sql,
                        new MapSqlParameterSource()
                                .addValue("period", normalisePeriod(period))
                                .addValue("key", key),
                        (rs, rowNum) ->
                                new ReportDetail(
                                        rs.getString("period_key"),
                                        rs.getString("title"),
                                        rs.getString("summary"),
                                        rs.getString("body_markdown"),
                                        rs.getInt("item_count"),
                                        rs.getObject("generated_at", OffsetDateTime.class),
                                        rs.getString("model_name"),
                                        rs.getString("prompt_version")));

        return rows.stream().findFirst().map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    /**
     * Reject unknown period values rather than passing them to SQL.
     *
     * <p>The parameter is bound, so this is not an injection guard; it keeps an
     * arbitrary string from silently returning an empty list, which would look
     * like "no reports" instead of "wrong URL".
     */
    private static String normalisePeriod(String period) {
        return switch (period == null ? "" : period.toLowerCase()) {
            case "weekly" -> "weekly";
            case "monthly" -> "monthly";
            default -> "daily";
        };
    }

    public record ReportSummary(
            String date,
            String title,
            String summary,
            int itemCount,
            OffsetDateTime generatedAt,
            String modelName) {}

    public record ReportDetail(
            String date,
            String title,
            String summary,
            String bodyMarkdown,
            int itemCount,
            OffsetDateTime generatedAt,
            String modelName,
            String promptVersion) {}
}
