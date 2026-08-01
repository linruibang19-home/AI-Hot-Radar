package com.aihotradar.coreapi.content;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.time.OffsetDateTime;

/**
 * One piece of content as exposed by the public API.
 *
 * <p>AHR-SOURCE-900 §2 sets the public rendering policy: the site shows title,
 * source, a short excerpt and the canonical link. Full body text is held for
 * internal search and RAG and is deliberately absent from this record.
 *
 * <p>Every field the spec requires for traceability is present: source, canonical
 * URL, published and observed timestamps, and source tier
 * (AHR-SPEC-000 §7).
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ContentItem(
        String id,
        String title,
        String zhTitle,
        String summary,
        String excerpt,
        String canonicalUrl,
        OffsetDateTime publishedAt,
        OffsetDateTime observedAt,
        String contentType,
        Double qualityScore,
        SourceRef source) {

    /** Minimal source descriptor; the full source record is admin-only. */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record SourceRef(String id, String name, String tier, String organization) {}
}
