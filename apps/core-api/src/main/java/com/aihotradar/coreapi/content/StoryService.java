package com.aihotradar.coreapi.content;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.stereotype.Service;

/** Application service that applies the public Story publication policy. */
@Service
public class StoryService {

    static final double PUBLIC_CONFIDENCE_THRESHOLD = 0.67;

    private final StoryRepository repository;

    public StoryService(StoryRepository repository) {
        this.repository = repository;
    }

    public List<StorySummary> list(int limit) {
        return repository.findPublished(
                        Math.min(Math.max(limit, 1), 100), PUBLIC_CONFIDENCE_THRESHOLD)
                .stream()
                .map(StoryService::toSummary)
                .toList();
    }

    public Optional<StoryDetail> detail(String slug) {
        return repository.findPublishedBySlug(slug, PUBLIC_CONFIDENCE_THRESHOLD)
                .map(
                        row ->
                                new StoryDetail(
                                        toSummary(row),
                                        repository.findTimeline(slug).stream()
                                                .map(StoryService::toEntry)
                                                .toList()));
    }

    private static StorySummary toSummary(StoryRepository.StoryRow row) {
        return new StorySummary(
                row.id(),
                row.slug(),
                row.title(),
                row.occurredAt(),
                row.heat(),
                row.independentSources(),
                row.itemCount(),
                row.locked(),
                row.contentType(),
                row.primarySourceName(),
                row.primarySourceTier(),
                row.sourceNames());
    }

    private static StoryEntry toEntry(StoryRepository.StoryEntryRow row) {
        return new StoryEntry(
                row.id(),
                row.title(),
                row.summary(),
                row.canonicalUrl(),
                row.publishedAt(),
                row.observedAt(),
                row.contentType(),
                row.relationType(),
                row.similarity(),
                row.sourceName(),
                row.sourceTier(),
                row.organization());
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
            String primarySourceTier,
            List<String> sourceNames) {}

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
