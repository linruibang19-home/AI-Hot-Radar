package com.aihotradar.coreapi.content;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.time.OffsetDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;

class ContentControllerVendorTest {

    @Test
    void unknown_relation_fails_closed_to_primary() {
        ContentRepository repository = mock(ContentRepository.class);
        when(repository.findVendorFeed(eq("openai"), eq("primary"), any(), eq(3)))
                .thenReturn(List.of());
        when(repository.countVendorFeed("openai", "primary")).thenReturn(0L);
        ContentController controller = new ContentController(repository);

        ContentController.VendorPage page =
                controller.vendorFeed("openai", null, 2, "anything-else");

        assertThat(page.total()).isZero();
        assertThat(page.page().hasMore()).isFalse();
    }

    @Test
    void feed_returns_real_total_instead_of_array_length() {
        ContentRepository repository = mock(ContentRepository.class);
        ContentRepository.VendorItem first = vendorItem("a", 0.95);
        ContentRepository.VendorItem second = vendorItem("b", 0.90);
        ContentRepository.VendorItem extra = vendorItem("c", 0.85);
        when(repository.findVendorFeed(eq("openai"), eq("primary"), any(), eq(3)))
                .thenReturn(List.of(first, second, extra));
        when(repository.countVendorFeed("openai", "primary")).thenReturn(42L);
        ContentController controller = new ContentController(repository);

        ContentController.VendorPage page =
                controller.vendorFeed("openai", null, 2, "primary");

        assertThat(page.data()).containsExactly(first, second);
        assertThat(page.total()).isEqualTo(42);
        assertThat(page.page().hasMore()).isTrue();
        assertThat(page.page().nextCursor()).isNotBlank();
    }

    @Test
    void topic_feed_returns_real_total_and_cursor() {
        ContentRepository repository = mock(ContentRepository.class);
        ContentRepository.TopicItem first = new ContentRepository.TopicItem(item("a"), 0.9);
        ContentRepository.TopicItem second = new ContentRepository.TopicItem(item("b"), 0.8);
        when(repository.findTopicFeed(eq("reasoning"), any(), eq(2)))
                .thenReturn(List.of(first, second));
        when(repository.countTopicFeed("reasoning")).thenReturn(17L);

        ContentController.TopicPage page =
                new ContentController(repository).topicFeed("reasoning", null, 1);

        assertThat(page.data()).containsExactly(first);
        assertThat(page.total()).isEqualTo(17);
        assertThat(page.page().hasMore()).isTrue();
        assertThat(page.page().nextCursor()).isNotBlank();
    }

    private static ContentRepository.VendorItem vendorItem(String id, double score) {
        ContentItem item = item(id);
        OffsetDateTime now = item.observedAt();
        return new ContentRepository.VendorItem(
                item, "primary", score, "openai", "subject_in_title", now);
    }

    private static ContentItem item(String id) {
        OffsetDateTime now = OffsetDateTime.parse("2026-08-13T00:00:00Z");
        return new ContentItem(
                        id,
                        id,
                        id,
                        "summary",
                        null,
                        "https://example.com/" + id,
                        now,
                        now,
                        "research",
                        80.0,
                        null,
                        1,
                        new ContentItem.SourceRef("s", "source", "primary", "org"));
    }
}
