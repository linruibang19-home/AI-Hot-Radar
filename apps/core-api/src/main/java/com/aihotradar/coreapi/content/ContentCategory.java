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

    /** Forces an exact `content_type` match instead of a tab lookup. See {@link #resolve}. */
    public static final String EXACT_PREFIX = "type:";

    /**
     * Resolve a filter key to content types.
     *
     * <p>Three forms, in precedence order:
     *
     * <ol>
     *   <li>{@code type:<content_type>} — exactly that one type, no tab expansion;
     *   <li>a tab key — the several types that tab covers;
     *   <li>anything else — taken as a raw content type, so the API stays usable directly.
     * </ol>
     *
     * <p><b>Why the prefix exists.</b> Tab keys and content types share a namespace and two of
     * them collide: {@code tutorial} is a tab covering {@code tutorial} *and* {@code open_source},
     * and {@code opinion} is both. The topic map's content-form cards show a count for one exact
     * type, so a card reading "查看 28 条" that opened a 52-item tab would be showing a number it
     * then contradicts. This keeps the card's promise and leaves the tabs untouched.
     *
     * <p>The previous documentation here claimed an unknown key returned empty — "a bad tab in a
     * bookmarked URL should show the full feed". The code returned {@code List.of(tab)} and had
     * done for some time, so a typo already produced an empty page. The behaviour is the useful
     * one; the comment was the stale half.
     */
    public static List<String> resolve(String tab) {
        if (tab == null || tab.isBlank() || "all".equalsIgnoreCase(tab)) {
            return List.of();
        }
        String key = tab.toLowerCase();
        if (key.startsWith(EXACT_PREFIX)) {
            String exact = key.substring(EXACT_PREFIX.length()).trim();
            return exact.isEmpty() ? List.of() : List.of(exact);
        }
        List<String> mapped = TABS.get(key);
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
