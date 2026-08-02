package com.aihotradar.coreapi.content;

import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import com.aihotradar.coreapi.cache.CacheConfig;
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
            @RequestParam(required = false) String source,
            @RequestParam(required = false) String contentType,
            @RequestParam(required = false) String q) {

        int pageSize = Math.min(limit == null ? DEFAULT_LIMIT : Math.max(limit, 1), MAX_LIMIT);

        // Fetch one extra row to decide hasMore without a second count query.
        List<ContentItem> rows =
                repository.findFeed(decodeCursor(cursor), pageSize + 1, source, contentType, q);

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
    @Cacheable(CacheConfig.TOPICS)
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
    @Cacheable(CacheConfig.TOPICS)
    public List<ContentRepository.TopicSummary> topics() {
        return repository.listTopics();
    }

    @GetMapping("/topics/map")
    @Cacheable(value = CacheConfig.TOPICS, key = "'map'")
    public List<ContentRepository.TopicNode> topicMap() {
        return repository.topicMap();
    }

    @GetMapping("/topics/{slug}")
    public List<ContentItem> topicItems(
            @PathVariable String slug,
            @RequestParam(required = false, defaultValue = "30") int limit) {
        return repository.findByTopic(slug, Math.min(Math.max(limit, 1), MAX_LIMIT));
    }

    @GetMapping("/items/days")
    public List<ContentRepository.DayCount> days(
            @RequestParam(required = false, defaultValue = "14") int days) {
        return repository.countByDay(Math.min(Math.max(days, 1), 90));
    }

    /**
     * Cursors are opaque to clients: base64 of "timestamp|id".
     *
     * <p>Encoding keeps the pagination key from looking like a stable public
     * identifier that callers might start depending on.
     */
    private static String encodeCursor(ContentItem item) {
        String raw = (item.publishedAt() == null ? "" : item.publishedAt().toString()) + "|" + item.id();
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
}
