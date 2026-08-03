package com.aihotradar.coreapi.cache;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import com.aihotradar.coreapi.content.ContentController;
import com.aihotradar.coreapi.content.ContentItem;
import com.aihotradar.coreapi.content.ContentRepository;
import java.time.OffsetDateTime;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.serializer.RedisSerializer;

/**
 * Round-trips the cached payloads through the configured Redis serializer.
 *
 * <p>Every DTO the API caches is a Java record, and records are implicitly
 * final. Under {@code DefaultTyping.NON_FINAL} the writer omitted their type
 * header, so a value serialised fine and then failed to deserialise. Nothing
 * caught it: the write path works, the read path only runs on the second
 * request within the TTL, and the web tier turns a 500 into an empty payload —
 * so the homepage quietly rendered zeros instead of erroring.
 *
 * <p>These tests exercise the serializer the application actually builds, not a
 * hand-rolled ObjectMapper, because the defect was in that configuration.
 */
class CacheSerializationTest {

    private final RedisSerializer<Object> serializer = valueSerializer();

    @SuppressWarnings("unchecked")
    private static RedisSerializer<Object> valueSerializer() {
        return (RedisSerializer<Object>) (RedisSerializer<?>) CacheConfig.valueSerializer();
    }

    private Object roundTrip(Object value) {
        byte[] bytes = serializer.serialize(value);
        assertThat(bytes).isNotNull();
        return serializer.deserialize(bytes);
    }

    @Test
    @DisplayName("a bare record survives the round trip")
    void statsRecordRoundTrips() {
        var stats = new ContentRepository.Stats(876, 834, 102, 3818);
        assertThat(roundTrip(stats)).isEqualTo(stats);
    }

    @Test
    @DisplayName("the serialised form carries a type header")
    void serialisedFormIsTyped() {
        // The exact failure: without the header the payload was a bare
        // `{"items":876,...}` and the reader had nothing to reconstruct from.
        byte[] bytes = serializer.serialize(new ContentRepository.Stats(1, 2, 3, 4));
        assertThat(new String(bytes)).contains("com.aihotradar.coreapi");
    }

    @Test
    @DisplayName("a list of records survives the round trip")
    void categoryListRoundTrips() {
        List<ContentController.CategoryTab> tabs =
                List.of(
                        new ContentController.CategoryTab("all", "全部", 876),
                        new ContentController.CategoryTab("model", "模型", 68));

        Object restored = roundTrip(tabs);

        assertThat(restored).isInstanceOf(List.class);
        // The list came back as LinkedHashMaps before, which only blew up later
        // as "object is not an instance of declaring class" while writing the
        // HTTP response.
        assertThat((List<?>) restored).allSatisfy(
                element -> assertThat(element).isInstanceOf(ContentController.CategoryTab.class));
        assertThat(restored).isEqualTo(tabs);
    }

    @Test
    @DisplayName("nested records and timestamps survive the round trip")
    void selectedItemRoundTrips() {
        var item =
                new ContentItem(
                        "8a1e0c2b-0000-0000-0000-000000000001",
                        "Title",
                        "标题",
                        "摘要",
                        "excerpt",
                        "https://example.com/a",
                        OffsetDateTime.parse("2026-08-03T09:12:53Z"),
                        OffsetDateTime.parse("2026-08-03T09:13:00Z"),
                        "model_release",
                        88.0,
                        41.5,
                        3,
                        new ContentItem.SourceRef("src", "Source", "primary", "Org"));

        var selected =
                new ContentRepository.SelectedItem(
                        item, java.time.LocalDate.parse("2026-08-03"), 91.5, "理由");

        assertThat(roundTrip(List.of(selected))).isEqualTo(List.of(selected));
    }

    @Test
    @DisplayName("a record with null fields survives the round trip")
    void nullableFieldsRoundTrip() {
        var item =
                new ContentItem(
                        "id",
                        "Title",
                        null,
                        null,
                        null,
                        "https://example.com/b",
                        null,
                        OffsetDateTime.parse("2026-08-03T09:13:00Z"),
                        null,
                        null,
                        null,
                        null,
                        new ContentItem.SourceRef("src", "Source", "primary", null));

        assertThat(roundTrip(item)).isEqualTo(item);
    }

    @Test
    @DisplayName("the cache manager builds without a live Redis")
    void cacheManagerBuilds() {
        assertThat(new CacheConfig().cacheManager(mock(RedisConnectionFactory.class))).isNotNull();
    }
}
