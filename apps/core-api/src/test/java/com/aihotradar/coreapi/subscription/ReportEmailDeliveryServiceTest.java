package com.aihotradar.coreapi.subscription;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Duration;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ReportEmailDeliveryServiceTest {
    @Test
    void candidate_query_only_reads_active_subscriptions_and_published_reports() {
        assertThat(ReportEmailDeliveryService.CANDIDATES_SQL)
                .contains("subscription.status = 'ACTIVE'")
                .contains("report.status = 'PUBLISHED'")
                .contains("report.published_at >= subscription.confirmed_at")
                .contains("delivery_local_time")
                .contains("NOT EXISTS");
    }

    @Test
    void concurrent_workers_claim_without_waiting_on_each_other() {
        assertThat(ReportEmailDeliveryService.CLAIM_SQL)
                .contains("FOR UPDATE SKIP LOCKED")
                .contains("status IN ('PENDING', 'RETRYABLE_FAILED')")
                .contains("status = 'SENDING'");
        assertThat(ReportEmailDeliveryService.RECOVER_STALE_SQL)
                .contains("status = 'SENDING'")
                .contains("interval '15 minutes'")
                .contains("stale_claim_recovered")
                .contains("PERMANENT_FAILED");
    }

    @Test
    void retry_schedule_is_bounded_and_delivery_key_is_stable() {
        assertThat(ReportEmailDeliveryService.retryDelay(1)).isEqualTo(Duration.ofMinutes(10));
        assertThat(ReportEmailDeliveryService.retryDelay(2)).isEqualTo(Duration.ofMinutes(60));

        UUID subscription = UUID.randomUUID();
        UUID report = UUID.randomUUID();
        String first = ReportEmailDeliveryService.deliveryKey(subscription, report);
        assertThat(first).hasSize(64).isEqualTo(ReportEmailDeliveryService.deliveryKey(subscription, report));
        assertThat(first).isNotEqualTo(ReportEmailDeliveryService.deliveryKey(subscription, UUID.randomUUID()));
    }
}
