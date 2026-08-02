package com.aihotradar.coreapi.content;

import java.util.List;
import java.util.Map;

/**
 * Maps a UI category tab to the content types it covers.
 *
 * <p>The tabs are reader-facing groupings, not the taxonomy itself: a reader
 * looking for "产品" expects both product launches and API changes, and "论文"
 * covers research whether or not it arrived via arXiv. Keeping the mapping here
 * means the tabs can be re-cut without touching stored data.
 */
public final class ContentCategory {

    private static final Map<String, List<String>> TABS =
            Map.of(
                    "model", List.of("model_release"),
                    "product", List.of("product_release", "api_update"),
                    "industry", List.of("business", "policy", "security"),
                    "paper", List.of("research"),
                    "tutorial", List.of("tutorial", "open_source"),
                    "opinion", List.of("opinion"));

    private ContentCategory() {}

    /**
     * Resolve a tab key to content types.
     *
     * <p>An unknown key returns empty, which the caller treats as "no filter"
     * rather than "no results" — a bad tab in a bookmarked URL should show the
     * full feed, not an empty page.
     */
    public static List<String> resolve(String tab) {
        if (tab == null || tab.isBlank() || "all".equalsIgnoreCase(tab)) {
            return List.of();
        }
        // A raw content_type is also accepted so the API stays usable directly.
        List<String> mapped = TABS.get(tab.toLowerCase());
        return mapped != null ? mapped : List.of(tab);
    }

    public static List<String> tabKeys() {
        return List.of("model", "product", "industry", "paper", "tutorial", "opinion");
    }

    private static final Map<String, String> LABELS =
            Map.of(
                    "model", "模型",
                    "product", "产品",
                    "industry", "行业",
                    "paper", "论文",
                    "tutorial", "教程",
                    "opinion", "观点");

    public static String label(String tab) {
        return LABELS.getOrDefault(tab, tab);
    }

    /**
     * The tab a stored content type belongs to, or null if none claims it.
     *
     * <p>Derived from {@link #TABS} rather than written out a second time: a type
     * added to a tab must not need a matching edit here to be counted.
     */
    public static String tabFor(String contentType) {
        if (contentType == null) {
            return null;
        }
        for (Map.Entry<String, List<String>> entry : TABS.entrySet()) {
            if (entry.getValue().contains(contentType)) {
                return entry.getKey();
            }
        }
        return null;
    }
}
