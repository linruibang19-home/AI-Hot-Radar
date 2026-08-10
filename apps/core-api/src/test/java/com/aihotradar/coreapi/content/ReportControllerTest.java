package com.aihotradar.coreapi.content;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class ReportControllerTest {

    @Test
    void public_list_exposes_only_published_reports() {
        assertThat(ReportController.LIST_SQL).contains("status = 'PUBLISHED'");
    }

    @Test
    void public_detail_exposes_only_published_reports() {
        assertThat(ReportController.DETAIL_SQL).contains("status = 'PUBLISHED'");
    }
}
