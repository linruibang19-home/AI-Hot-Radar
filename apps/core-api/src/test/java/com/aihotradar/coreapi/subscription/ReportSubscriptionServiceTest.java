package com.aihotradar.coreapi.subscription;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.Set;
import org.junit.jupiter.api.Test;

class ReportSubscriptionServiceTest {
    @Test
    void email_periods_and_timezone_are_normalized_before_storage() {
        assertThat(ReportSubscriptionService.normalizeEmail(" Reader@Example.COM "))
                .isEqualTo("reader@example.com");
        assertThat(ReportSubscriptionService.normalizePeriods(Set.of("monthly", "daily")))
                .extracting(ReportPeriod::value)
                .containsExactly("daily", "monthly");
        assertThat(ReportSubscriptionService.normalizeTimezone("Asia/Shanghai"))
                .isEqualTo("Asia/Shanghai");
    }

    @Test
    void invalid_public_preferences_are_rejected() {
        assertThatThrownBy(() -> ReportSubscriptionService.normalizeEmail("not-an-email"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ReportSubscriptionService.normalizePeriods(Set.of()))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ReportSubscriptionService.normalizePeriods(Set.of("hourly")))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> ReportSubscriptionService.normalizeTimezone("Mars/Olympus"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void repeated_requests_are_cooled_down_without_revealing_subscription_state() {
        assertThat(ReportSubscriptionService.UPSERT_REQUEST_SQL)
                .contains("ON CONFLICT (email_normalized) WHERE status = 'PENDING'")
                .contains("interval '10 minutes'")
                .contains("confirmation_sent_at = NULL");
    }
}
