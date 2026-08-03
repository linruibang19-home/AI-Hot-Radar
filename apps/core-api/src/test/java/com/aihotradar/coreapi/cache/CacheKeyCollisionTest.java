package com.aihotradar.coreapi.cache;

import static org.assertj.core.api.Assertions.assertThat;

import com.aihotradar.coreapi.content.ContentController;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.cache.annotation.Cacheable;

/**
 * Guards against two cached methods sharing a cache entry.
 *
 * <p>Spring's default key for a no-argument method is {@code SimpleKey.EMPTY}.
 * {@code /categories} and {@code /topics} were both annotated
 * {@code @Cacheable(TOPICS)} with no key, so whichever ran first wrote its
 * payload and the other read it back — {@code /topics} received a
 * {@code List<CategoryTab>} and died while serialising the response.
 *
 * <p>The failure is data-dependent and order-dependent, so it does not show up
 * in a single-request smoke test. Checking the annotations directly does.
 */
class CacheKeyCollisionTest {

    private record CacheEntry(String cache, String key, String method) {}

    private static List<CacheEntry> cachedMethods() {
        List<CacheEntry> entries = new ArrayList<>();
        for (Method method : ContentController.class.getDeclaredMethods()) {
            Cacheable annotation = method.getAnnotation(Cacheable.class);
            if (annotation == null) {
                continue;
            }
            String[] names = annotation.value().length > 0 ? annotation.value() : annotation.cacheNames();
            String key = annotation.key().isBlank() ? "<default:SimpleKey>" : annotation.key();
            for (String name : names) {
                entries.add(new CacheEntry(name, key, method.getName()));
            }
        }
        return entries;
    }

    @Test
    @DisplayName("no two cached methods share a cache and key")
    void keysAreUnique() {
        List<CacheEntry> entries = cachedMethods();
        assertThat(entries).isNotEmpty();

        for (int i = 0; i < entries.size(); i++) {
            for (int j = i + 1; j < entries.size(); j++) {
                CacheEntry left = entries.get(i);
                CacheEntry right = entries.get(j);
                boolean collides =
                        left.cache().equals(right.cache()) && left.key().equals(right.key());
                assertThat(collides)
                        .as(
                                "%s and %s both cache under %s / %s",
                                left.method(), right.method(), left.cache(), left.key())
                        .isFalse();
            }
        }
    }

    @Test
    @DisplayName("a method taking parameters keys on them")
    void parameterisedMethodsVaryTheirKey() {
        // Otherwise every argument combination collapses onto one entry and the
        // endpoint returns whatever the first caller asked for.
        for (Method method : ContentController.class.getDeclaredMethods()) {
            Cacheable annotation = method.getAnnotation(Cacheable.class);
            if (annotation == null || method.getParameterCount() == 0) {
                continue;
            }
            assertThat(annotation.key())
                    .as("%s takes parameters and must key on them", method.getName())
                    .isNotBlank();
        }
    }
}
