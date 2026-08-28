package com.aihotradar.coreapi.content;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Executable boundary: every browsing surface applies the reader-ready gate.
 *
 * <p>{@code PUBLIC_FEED_READY} existed and was documented in the class javadoc, but
 * only three of eleven read queries appended it. Measured on 2026-08-29, the four
 * that reached a reader without it were returning unenriched rows: the hot list 14
 * of 30, the curated feed 13 of 49, and a homepage card rendered the raw extracted
 * title {@code Previewing the Model Hardware StandardAnnouncementsAug 27, 2026We're
 * opening…}.
 *
 * <p>Fixing those four does not stop the fifth. This test reads the repository
 * source and fails when a list query that projects a reader-visible title omits the
 * gate, so the next query has to make the same decision deliberately.
 */
class ContentRepositoryPublicGateTest {

    private static final Path SOURCE =
            Path.of("src/main/java/com/aihotradar/coreapi/content/ContentRepository.java");

    /**
     * Resolving one row by id is not a browsing surface.
     *
     * <p>A feed curates; a permalink resolves. An item that exists should still
     * answer at its own URL, and RAG citations depend on that — evidence is bound to
     * a {@code content_chunk}, which exists whether or not the item has been
     * enriched yet. Gating this would turn a live citation into a 404 in exchange
     * for a nicer title, which is the wrong trade.
     */
    private static final Set<String> EXEMPT = Set.of("findById");

    private static final Pattern METHOD =
            Pattern.compile("^ {4}public\\s+(\\S+)\\s+(\\w+)\\(", Pattern.MULTILINE);

    @Test
    @DisplayName("every list query that shows a title to a reader applies PUBLIC_FEED_READY")
    void reader_facing_list_queries_are_gated() throws IOException {
        String source = Files.readString(SOURCE, StandardCharsets.UTF_8);

        List<String> ungated = new ArrayList<>();
        Matcher matcher = METHOD.matcher(source);
        List<int[]> spans = new ArrayList<>();
        List<String> names = new ArrayList<>();
        List<String> returns = new ArrayList<>();
        while (matcher.find()) {
            spans.add(new int[] {matcher.start(), 0});
            names.add(matcher.group(2));
            returns.add(matcher.group(1));
        }
        for (int i = 0; i < spans.size(); i++) {
            spans.get(i)[1] = i + 1 < spans.size() ? spans.get(i + 1)[0] : source.length();
        }

        for (int i = 0; i < names.size(); i++) {
            String name = names.get(i);
            String body = source.substring(spans.get(i)[0], spans.get(i)[1]);
            boolean returnsList = returns.get(i).startsWith("List<");
            // A query that projects zh_title puts a title in front of a reader; one
            // that does not (counts, topic refs, timestamps) cannot leak markup.
            boolean showsTitle = body.contains("zh_title");
            if (!returnsList || !showsTitle || EXEMPT.contains(name)) {
                continue;
            }
            if (!body.contains("PUBLIC_FEED_READY")) {
                ungated.add(name);
            }
        }

        assertThat(ungated)
                .as(
                        "these queries return titles to readers without the reader-ready gate; "
                                + "append PUBLIC_FEED_READY, or add the method to EXEMPT with the "
                                + "reason it is not a browsing surface")
                .isEmpty();
    }

    @Test
    @DisplayName("the gate still checks all three conditions")
    void gate_checks_state_title_and_summary() {
        // Enrichment state alone is not enough: a row can be marked ENRICHED with an
        // empty Chinese title, and COALESCE would then fall back to the raw one.
        assertThat(ContentRepository.PUBLIC_FEED_READY)
                .contains("ci.enrichment_state = 'ENRICHED'")
                .contains("BTRIM(ci.zh_title)")
                .contains("BTRIM(ci.summary_zh)");
    }
}
