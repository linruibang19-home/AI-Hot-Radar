package com.aihotradar.coreapi.content;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ReportControllerTest {

    @Test
    void reader_list_keeps_generated_reports_visible_before_editorial_ui_exists() {
        // The report generator intentionally stores every automatic run as DRAFT.
        // Filtering here made all daily/weekly/monthly reports disappear because
        // the planned editorial publish endpoint/UI has not been implemented yet.
        assertThat(ReportController.LIST_SQL)
                .contains("period_type = :period")
                .doesNotContain("status = 'PUBLISHED'");
    }

    @Test
    void reader_detail_keeps_generated_reports_visible_before_editorial_ui_exists() {
        assertThat(ReportController.DETAIL_SQL)
                .contains("period_key = :key")
                .doesNotContain("status = 'PUBLISHED'");
    }

    @Test
    void detail_read_model_uses_report_item_provenance_instead_of_parsing_markdown() {
        assertThat(ReportController.ITEMS_SQL)
                .contains("FROM report_item")
                .contains("JOIN content_item")
                .contains("JOIN source")
                .contains("LEFT JOIN story")
                .contains("ORDER BY ri.position");
    }

    @Test
    void sections_keep_the_persisted_order_and_use_reader_labels() {
        List<ReportController.ReportSection> sections =
                ReportController.groupSections(
                        List.of(
                                entry("model_release", "a", "source-a", "primary", "story-a"),
                                entry("model_release", "b", "source-b", "community", "story-a"),
                                entry("research", "c", "source-a", "primary", null)));

        assertThat(sections).extracting(ReportController.ReportSection::key)
                .containsExactly("model_release", "research");
        assertThat(sections).extracting(ReportController.ReportSection::label)
                .containsExactly("模型发布", "研究进展");
        assertThat(sections.getFirst().count()).isEqualTo(2);
    }

    @Test
    void stats_count_unique_sources_and_events_and_never_report_zero_reading_time() {
        List<ReportController.ReportEntry> entries =
                List.of(
                        entry("model_release", "a", "source-a", "primary", "story-a"),
                        entry("model_release", "b", "source-b", "community", "story-a"),
                        entry("research", "c", "source-a", "primary", null));
        List<ReportController.ReportSection> sections = ReportController.groupSections(entries);

        ReportController.ReportStats stats =
                ReportController.buildStats("很短的报告", sections, entries);

        assertThat(stats.items()).isEqualTo(3);
        assertThat(stats.sections()).isEqualTo(2);
        assertThat(stats.sources()).isEqualTo(2);
        assertThat(stats.primarySources()).isEqualTo(2);
        assertThat(stats.stories()).isEqualTo(2);
        assertThat(stats.readingMinutes()).isEqualTo(1);
    }

    private static ReportController.ReportEntry entry(
            String section, String suffix, String source, String tier, String story) {
        return new ReportController.ReportEntry(
                section,
                0,
                UUID.nameUUIDFromBytes(suffix.getBytes(StandardCharsets.UTF_8)),
                "标题 " + suffix,
                "摘要",
                "https://example.com/" + suffix,
                section,
                source,
                source,
                source,
                tier,
                story,
                story == null ? 1 : 2);
    }
}
