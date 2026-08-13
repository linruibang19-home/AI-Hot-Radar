package com.aihotradar.coreapi.content;

import com.aihotradar.coreapi.cache.CacheConfig;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Public content endpoints, matching api/openapi.yaml. */
@RestController
@RequestMapping("/api/v1")
public class ContentController {

    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 50;

    private final ContentRepository repository;

    public ContentController(ContentRepository repository) {
        this.repository = repository;
    }

    @GetMapping("/items")
    public PageResponse<ContentItem> listItems(
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false) Integer limit,
            @RequestParam(required = false) String day,
            @RequestParam(required = false) String source,
            @RequestParam(required = false) String contentType,
            @RequestParam(required = false) String q) {

        int pageSize = Math.min(limit == null ? DEFAULT_LIMIT : Math.max(limit, 1), MAX_LIMIT);

        // Fetch one extra row to decide hasMore without a second count query.
        List<ContentItem> rows =
                repository.findFeed(decodeCursor(cursor), pageSize + 1, source, contentType, q, day);

        boolean hasMore = rows.size() > pageSize;
        List<ContentItem> page = hasMore ? rows.subList(0, pageSize) : rows;
        String nextCursor = hasMore ? encodeCursor(page.get(page.size() - 1)) : null;

        return PageResponse.of(page, nextCursor, hasMore);
    }

    @GetMapping("/items/{id}")
    public ResponseEntity<ContentItem> getItem(@PathVariable String id) {
        return repository.findById(id).map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping("/stats")
    @Cacheable(CacheConfig.STATS)
    public ContentRepository.Stats stats() {
        return repository.stats();
    }

    @GetMapping("/selected")
    @Cacheable(
            value = CacheConfig.SELECTED,
            key = "#days + ':' + #limit + ':' + #contentType + ':' + #sort")
    public List<ContentRepository.SelectedItem> selected(
            @RequestParam(required = false, defaultValue = "7") int days,
            @RequestParam(required = false, defaultValue = "40") int limit,
            @RequestParam(required = false) String contentType,
            @RequestParam(required = false, defaultValue = "curated") String sort) {
        return repository.findSelected(
                Math.min(Math.max(days, 1), 30),
                Math.min(Math.max(limit, 1), 100),
                contentType,
                sort);
    }

    @GetMapping("/items/{id}/topics")
    public List<ContentRepository.TopicRef> itemTopics(@PathVariable String id) {
        return repository.findTopics(id);
    }

    @GetMapping("/hot")
    @Cacheable(value = CacheConfig.SELECTED, key = "'hot:' + #limit")
    public List<ContentRepository.HotItem> hot(
            @RequestParam(required = false, defaultValue = "10") int limit) {
        return repository.findHot(Math.min(Math.max(limit, 1), 30));
    }

    /**
     * Category tabs with their item counts.
     *
     * <p>Aggregation happens here rather than in the client so the tab-to-type
     * mapping lives in exactly one place; the web tier only renders what it is
     * given. Tabs are always returned, including empty ones, so the navigation
     * does not change shape as content arrives.
     */
    @GetMapping("/categories")
    // Explicit key. Two no-arg methods sharing a cache both default to
    // SimpleKey.EMPTY, so /categories and /topics were reading each other's
    // payload: /topics got a List<CategoryTab> and failed while serialising the
    // response as "object is not an instance of declaring class".
    @Cacheable(value = CacheConfig.TOPICS, key = "'categories'")
    public List<CategoryTab> categories() {
        Map<String, Long> byTab = new LinkedHashMap<>();
        long total = 0;
        for (ContentRepository.CategoryCount row : repository.categoryCounts()) {
            String tab = ContentCategory.tabFor(row.contentType());
            total += row.total();
            if (tab != null) {
                byTab.merge(tab, row.total(), Long::sum);
            }
        }

        List<CategoryTab> tabs = new ArrayList<>();
        tabs.add(new CategoryTab("all", "全部", total));
        for (String key : ContentCategory.tabKeys()) {
            tabs.add(new CategoryTab(key, ContentCategory.label(key), byTab.getOrDefault(key, 0L)));
        }
        return tabs;
    }

    public record CategoryTab(String key, String label, long total) {}

    @GetMapping("/topics")
    @Cacheable(value = CacheConfig.TOPICS, key = "'list'")
    public List<ContentRepository.TopicSummary> topics() {
        return repository.listTopics();
    }

    @GetMapping("/topics/map")
    @Cacheable(value = CacheConfig.TOPICS, key = "'map'")
    public List<ContentRepository.TopicNode> topicMap() {
        return repository.topicMap();
    }

    /**
     * The company / model-family dimension of the topic map.
     *
     * <p>Separate endpoints per dimension rather than one combined payload: they have different
     * shapes and different cache lifetimes, and a single blob would make the page wait for the
     * slowest of the three.
     *
     * <p>An explicit cache key, like every other method here. Spring's default key for a no-arg
     * method is {@code SimpleKey.EMPTY}, which is how {@code /categories} and {@code /topics} once
     * ended up reading each other's payload.
     */
    @GetMapping("/vendors/map")
    @Cacheable(value = CacheConfig.TOPICS, key = "'vendors'")
    public List<ContentRepository.VendorNode> vendorMap() {
        return repository.vendorMap();
    }

    /** The content-form dimension, from `content_item.content_type`. */
    @GetMapping("/content-types/map")
    @Cacheable(value = CacheConfig.TOPICS, key = "'contentTypes'")
    public List<ContentRepository.MapNode> contentTypeMap() {
        return repository.contentTypeMap();
    }

    @GetMapping("/vendors/{slug}")
    public List<ContentItem> vendorItems(
            @PathVariable String slug,
            @RequestParam(required = false, defaultValue = "30") int limit) {
        return repository.findByVendor(slug, Math.min(Math.max(limit, 1), MAX_LIMIT));
    }

    @GetMapping("/vendors/{slug}/feed")
    public VendorPage vendorFeed(
            @PathVariable String slug,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false, defaultValue = "20") int limit,
            @RequestParam(required = false, defaultValue = "primary") String relation) {
        String tier = normaliseVendorRelation(relation);
        int pageSize = Math.min(Math.max(limit, 1), MAX_LIMIT);
        List<ContentRepository.VendorItem> rows =
                repository.findVendorFeed(slug, tier, decodeVendorCursor(cursor), pageSize + 1);
        boolean hasMore = rows.size() > pageSize;
        List<ContentRepository.VendorItem> page = hasMore ? rows.subList(0, pageSize) : rows;
        String nextCursor =
                hasMore && !page.isEmpty() ? encodeVendorCursor(page.get(page.size() - 1)) : null;
        return new VendorPage(
                page,
                new PageResponse.PageMeta(nextCursor, hasMore),
                repository.countVendorFeed(slug, tier),
                repository.vendorFeedUpdatedAt(slug));
    }

    public record VendorPage(
            List<ContentRepository.VendorItem> data,
            PageResponse.PageMeta page,
            long total,
            OffsetDateTime updatedAt) {}

    @GetMapping("/topics/{slug}")
    public List<ContentItem> topicItems(
            @PathVariable String slug,
            @RequestParam(required = false, defaultValue = "30") int limit) {
        return repository.findByTopic(slug, Math.min(Math.max(limit, 1), MAX_LIMIT));
    }

    @GetMapping("/topics/{slug}/feed")
    public TopicPage topicFeed(
            @PathVariable String slug,
            @RequestParam(required = false) String cursor,
            @RequestParam(required = false, defaultValue = "20") int limit) {
        int pageSize = Math.min(Math.max(limit, 1), MAX_LIMIT);
        List<ContentRepository.TopicItem> rows =
                repository.findTopicFeed(slug, decodeCursor(cursor), pageSize + 1);
        boolean hasMore = rows.size() > pageSize;
        List<ContentRepository.TopicItem> page = hasMore ? rows.subList(0, pageSize) : rows;
        String nextCursor =
                hasMore && !page.isEmpty()
                        ? encodeCursor(page.get(page.size() - 1).item())
                        : null;
        return new TopicPage(
                page,
                new PageResponse.PageMeta(nextCursor, hasMore),
                repository.countTopicFeed(slug));
    }

    public record TopicPage(
            List<ContentRepository.TopicItem> data, PageResponse.PageMeta page, long total) {}

    /**
     * Every publication date with its item count, newest first.
     *
     * <p>Replaces a rolling {@code days}-window count that grouped in UTC.
     * Neither suited the feed: it is read by date, so it needs *all* the dates,
     * and a UTC bucket files everything published after 08:00 Beijing time
     * under the previous day.
     */
    @GetMapping("/items/days")
    @Cacheable(value = CacheConfig.STATS, key = "'days:' + #contentType + ':' + #q")
    public List<ContentRepository.DayBucket> days(
            @RequestParam(required = false) String contentType,
            @RequestParam(required = false) String q) {
        return repository.dayCounts(
                contentType == null || contentType.isBlank() ? null : contentType,
                q == null || q.isBlank() ? null : q);
    }

    /**
     * Cursors are opaque to clients: base64 of "timestamp|id".
     *
     * <p>Encoding keeps the pagination key from looking like a stable public
     * identifier that callers might start depending on.
     */
    private static String encodeCursor(ContentItem item) {
        // Must be the same expression the feed orders by. Using publishedAt
        // alone produced an empty timestamp for items without one, which
        // decodeCursor then rejected — so "load more" silently restarted from
        // the top instead of paging.
        OffsetDateTime effective =
                item.publishedAt() == null ? item.observedAt() : item.publishedAt();
        String raw = (effective == null ? "" : effective.toString()) + "|" + item.id();
        return Base64.getUrlEncoder().withoutPadding()
                .encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }

    private static ContentRepository.Cursor decodeCursor(String cursor) {
        if (cursor == null || cursor.isBlank()) {
            return null;
        }
        try {
            String raw = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
            String[] parts = raw.split("\\|", 2);
            if (parts.length != 2 || parts[0].isBlank()) {
                return null;
            }
            return new ContentRepository.Cursor(OffsetDateTime.parse(parts[0]), parts[1]);
        } catch (RuntimeException exception) {
            // A malformed cursor restarts from the top rather than 500ing: the
            // client cannot recover from an error here, but a fresh page is useful.
            return null;
        }
    }

    private static String normaliseVendorRelation(String relation) {
        return switch (relation == null ? "" : relation.toLowerCase()) {
            case "related" -> "related";
            case "mention" -> "mention";
            default -> "primary";
        };
    }

    private static String encodeVendorCursor(ContentRepository.VendorItem row) {
        ContentItem item = row.item();
        OffsetDateTime effective =
                item.publishedAt() == null ? item.observedAt() : item.publishedAt();
        String raw = row.score() + "|" + effective + "|" + item.id();
        return Base64.getUrlEncoder().withoutPadding()
                .encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }

    private static ContentRepository.VendorCursor decodeVendorCursor(String cursor) {
        if (cursor == null || cursor.isBlank()) return null;
        try {
            String raw = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
            String[] parts = raw.split("\\|", 3);
            if (parts.length != 3) return null;
            return new ContentRepository.VendorCursor(
                    Double.parseDouble(parts[0]), OffsetDateTime.parse(parts[1]), parts[2]);
        } catch (RuntimeException exception) {
            return null;
        }
    }
}
