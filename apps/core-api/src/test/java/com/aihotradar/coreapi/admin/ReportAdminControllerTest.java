package com.aihotradar.coreapi.admin;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;

@ExtendWith(MockitoExtension.class)
class ReportAdminControllerTest {

    @Mock private ReportPublicationService reports;
    @Mock private AdminIdempotency idempotency;
    @Mock private AdminAudit audit;

    private ReportAdminController controller;
    private MockHttpServletRequest request;
    private AdminPrincipal operator;
    private UUID reportId;

    @BeforeEach
    void setUp() {
        controller = new ReportAdminController(reports, idempotency, audit);
        request = new MockHttpServletRequest();
        operator = new AdminPrincipal(UUID.randomUUID(), "operator", AdminRole.OPERATOR);
        request.setAttribute(AdminPrincipal.ATTRIBUTE, operator);
        reportId = UUID.randomUUID();
    }

    @Test
    void mutation_requires_target_confirmation_before_any_write() {
        ResponseEntity<?> response =
                controller.publish(reportId, null, "publish-12345", request);

        assertThat(response.getStatusCode().value()).isEqualTo(428);
        verifyNoInteractions(idempotency, reports);
        verify(audit)
                .record(
                        operator,
                        "report.publish",
                        reportId.toString(),
                        AdminAudit.Outcome.DENIED_UNCONFIRMED,
                        Map.of());
    }

    @Test
    void mutation_requires_a_bounded_idempotency_key() {
        ResponseEntity<?> response =
                controller.publish(reportId, reportId.toString(), "short", request);

        assertThat(response.getStatusCode().value()).isEqualTo(400);
        verifyNoInteractions(idempotency, reports);
    }

    @Test
    void a_completed_idempotency_key_replays_without_another_transition() {
        when(idempotency.begin(
                        operator, "publish-12345", "report.publish", reportId.toString()))
                .thenReturn(
                        new AdminIdempotency.Claim(
                                AdminIdempotency.State.REPLAY,
                                200,
                                Map.of("status", "PUBLISHED")));

        ResponseEntity<?> response =
                controller.publish(
                        reportId, reportId.toString(), "publish-12345", request);

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(response.getBody()).isEqualTo(Map.of("status", "PUBLISHED"));
        verifyNoInteractions(reports);
    }

    @Test
    void operator_can_publish_a_report_once_all_guards_pass() {
        var before = state("DRAFT", null);
        var after = state("PUBLISHED", OffsetDateTime.now());
        when(idempotency.begin(
                        operator, "publish-12345", "report.publish", reportId.toString()))
                .thenReturn(new AdminIdempotency.Claim(AdminIdempotency.State.NEW, null, Map.of()));
        when(reports.find(reportId)).thenReturn(List.of(before));
        when(reports.transition(reportId, "PUBLISHED")).thenReturn(after);

        ResponseEntity<?> response =
                controller.publish(
                        reportId, reportId.toString(), "publish-12345", request);

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        verify(reports).transition(reportId, "PUBLISHED");
        verify(idempotency)
                .complete(
                        org.mockito.ArgumentMatchers.eq(operator),
                        org.mockito.ArgumentMatchers.eq("publish-12345"),
                        org.mockito.ArgumentMatchers.eq(200),
                        org.mockito.ArgumentMatchers.anyMap());
        verify(audit)
                .record(
                        operator,
                        "report.publish",
                        reportId.toString(),
                        AdminAudit.Outcome.ALLOWED,
                        Map.of("from", "DRAFT", "to", "PUBLISHED"));
    }

    private ReportPublicationService.ReportState state(
            String status, OffsetDateTime publishedAt) {
        return new ReportPublicationService.ReportState(
                reportId,
                "daily",
                "2026-08-10",
                "日报",
                "总述",
                "# 日报",
                status,
                10,
                OffsetDateTime.now(),
                publishedAt,
                "{}");
    }
}
