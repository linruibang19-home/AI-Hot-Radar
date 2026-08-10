package com.aihotradar.coreapi.content;

import static org.assertj.core.api.Assertions.assertThat;

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
}
