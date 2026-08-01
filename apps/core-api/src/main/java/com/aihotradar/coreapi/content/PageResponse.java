package com.aihotradar.coreapi.content;

import java.util.List;

/**
 * Cursor-paged envelope matching {@code ItemPage} in api/openapi.yaml.
 *
 * <p>Cursor paging rather than offset paging: the feed is append-heavy, and an
 * offset would skip or repeat rows whenever new content lands between requests.
 */
public record PageResponse<T>(List<T> data, PageMeta page) {

    public record PageMeta(String nextCursor, boolean hasMore) {}

    public static <T> PageResponse<T> of(List<T> data, String nextCursor, boolean hasMore) {
        return new PageResponse<>(data, new PageMeta(nextCursor, hasMore));
    }
}
