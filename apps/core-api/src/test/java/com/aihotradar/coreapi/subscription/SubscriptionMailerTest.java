package com.aihotradar.coreapi.subscription;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class SubscriptionMailerTest {
    @Test
    void renders_the_report_subset_as_readable_safe_html() {
        String html = SubscriptionMailer.renderReportMarkdown("""
                # AI Hot Radar 日报

                今日总述

                ## 模型发布

                - **[安全标题](https://example.com/release)** · 官方
                  一段摘要

                ---
                <script>alert(1)</script>
                """);

        assertThat(html)
                .contains("<h2")
                .contains("href=\"https://example.com/release\"")
                .contains("安全标题")
                .contains("一段摘要")
                .contains("&lt;script&gt;alert(1)&lt;/script&gt;")
                .doesNotContain("# AI Hot Radar")
                .doesNotContain("<script>");
    }
}
