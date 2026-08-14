package com.aihotradar.coreapi.content;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;

/** Application service for report validation, grouping and reader projections. */
@Service
public class ReportService {

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

    private final ReportRepository repository;

    public ReportService(ReportRepository repository) {
        this.repository = repository;
    }

    public List<ReportSummary> list(String period, int limit) {
        return repository.listPublished(
                        normalisePeriod(period), Math.min(Math.max(limit, 1), 90))
                .stream()
                .map(ReportService::toSummary)
                .toList();
    }

    public Optional<ReportDetail> detail(String period, String key) {
        String resolvedPeriod = normalisePeriod(period);
        return repository.findPublished(resolvedPeriod, key)
                .map(row -> buildDetail(resolvedPeriod, key, row));
    }

    private ReportDetail buildDetail(
            String period, String key, ReportRepository.ReportRow row) {
        List<ReportEntry> entries =
                repository.findEntries(row.id()).stream()
                        .map(ReportService::toEntry)
                        .toList();
        List<ReportSection> sections = groupSections(entries);
        ReportStats stats = buildStats(row.bodyMarkdown(), sections, entries);
        return new ReportDetail(
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
                toNavigation(repository.navigation(period, key)));
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
            String bodyMarkdown,
            List<ReportSection> sections,
            List<ReportEntry> entries) {
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
        int readableCharacters =
                bodyMarkdown == null ? 0 : bodyMarkdown.replaceAll("\\s+", "").length();
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

    static String normalisePeriod(String period) {
        return switch (period == null ? "" : period.toLowerCase(Locale.ROOT)) {
            case "weekly" -> "weekly";
            case "monthly" -> "monthly";
            default -> "daily";
        };
    }

    private static ReportSummary toSummary(ReportRepository.ReportSummaryRow row) {
        return new ReportSummary(
                row.date(),
                row.title(),
                row.summary(),
                row.itemCount(),
                row.generatedAt(),
                row.modelName(),
                row.status());
    }

    private static ReportEntry toEntry(ReportRepository.ReportEntryRow row) {
        return new ReportEntry(
                normaliseSection(row.section()),
                row.position(),
                row.id(),
                row.title(),
                row.summary(),
                row.canonicalUrl(),
                row.contentType(),
                row.sourceId(),
                row.sourceName(),
                row.organization(),
                row.sourceTier(),
                row.storySlug(),
                row.independentSources());
    }

    private static ReportNavigation toNavigation(ReportRepository.ReportNavigationRow row) {
        return new ReportNavigation(row.previousKey(), row.nextKey());
    }

    private static String normaliseSection(String section) {
        return section == null || section.isBlank()
                ? "other"
                : section.toLowerCase(Locale.ROOT);
    }

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

    public record ReportSection(
            String key,
            String label,
            int count,
            List<ReportEntry> items) {}

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
