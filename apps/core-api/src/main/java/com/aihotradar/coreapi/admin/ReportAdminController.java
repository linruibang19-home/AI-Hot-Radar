package com.aihotradar.coreapi.admin;

import jakarta.servlet.http.HttpServletRequest;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Protected report review and publication endpoints (AHR-API-500 §5). */
@RestController
@RequestMapping("/api/v1/admin/reports")
public class ReportAdminController {

    static final String CONFIRM_HEADER = "X-Confirm-Target";
    static final String IDEMPOTENCY_HEADER = "Idempotency-Key";

    private final ReportPublicationService reports;
    private final AdminIdempotency idempotency;
    private final AdminAudit audit;

    public ReportAdminController(
            ReportPublicationService reports, AdminIdempotency idempotency, AdminAudit audit) {
        this.reports = reports;
        this.idempotency = idempotency;
        this.audit = audit;
    }

    @GetMapping
    public List<Map<String, Object>> list(
            @RequestParam(required = false) String status,
            @RequestParam(required = false, defaultValue = "50") int limit) {
        return reports.list(status, limit);
    }

    @GetMapping("/{id}")
    public ResponseEntity<?> detail(@PathVariable UUID id) {
        List<ReportPublicationService.ReportState> rows = reports.find(id);
        return rows.isEmpty() ? ResponseEntity.notFound().build() : ResponseEntity.ok(rows.getFirst());
    }

    @PostMapping("/{id}/publish")
    public ResponseEntity<?> publish(
            @PathVariable UUID id,
            @RequestHeader(value = CONFIRM_HEADER, required = false) String confirm,
            @RequestHeader(value = IDEMPOTENCY_HEADER, required = false) String key,
            HttpServletRequest request) {
        return mutate(id, "PUBLISHED", "report.publish", confirm, key, request);
    }

    @PostMapping("/{id}/withdraw")
    public ResponseEntity<?> withdraw(
            @PathVariable UUID id,
            @RequestHeader(value = CONFIRM_HEADER, required = false) String confirm,
            @RequestHeader(value = IDEMPOTENCY_HEADER, required = false) String key,
            HttpServletRequest request) {
        return mutate(id, "WITHDRAWN", "report.withdraw", confirm, key, request);
    }

    private ResponseEntity<?> mutate(
            UUID id,
            String targetStatus,
            String action,
            String confirm,
            String key,
            HttpServletRequest request) {
        AdminPrincipal principal =
                (AdminPrincipal) request.getAttribute(AdminPrincipal.ATTRIBUTE);
        String target = id.toString();

        if (!target.equals(confirm)) {
            audit.record(
                    principal,
                    action,
                    target,
                    AdminAudit.Outcome.DENIED_UNCONFIRMED,
                    Map.of());
            return ResponseEntity.status(HttpStatus.PRECONDITION_REQUIRED)
                    .body(Map.of("error", "confirmation_required", "echo", CONFIRM_HEADER));
        }
        if (key == null || key.length() < 8 || key.length() > 200) {
            audit.record(
                    principal,
                    action,
                    target,
                    AdminAudit.Outcome.FAILED,
                    Map.of("reason", "invalid idempotency key"));
            return ResponseEntity.badRequest()
                    .body(Map.of("error", "invalid_idempotency_key"));
        }

        AdminIdempotency.Claim claim = idempotency.begin(principal, key, action, target);
        if (claim.state() == AdminIdempotency.State.REPLAY) {
            return ResponseEntity.status(claim.responseStatus()).body(claim.responseBody());
        }
        if (claim.state() == AdminIdempotency.State.CONFLICT) {
            audit.record(
                    principal,
                    action,
                    target,
                    AdminAudit.Outcome.FAILED,
                    Map.of("reason", "idempotency key reused"));
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "idempotency_key_reused"));
        }
        if (claim.state() == AdminIdempotency.State.IN_PROGRESS) {
            audit.record(
                    principal,
                    action,
                    target,
                    AdminAudit.Outcome.FAILED,
                    Map.of("reason", "request in progress"));
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "request_in_progress"));
        }

        ReportPublicationService.ReportState before = reports.find(id).stream().findFirst().orElse(null);
        if (before == null) {
            Map<String, Object> body = Map.of("error", "report_not_found");
            idempotency.complete(principal, key, 404, body);
            audit.record(
                    principal,
                    action,
                    target,
                    AdminAudit.Outcome.FAILED,
                    Map.of("reason", "report not found"));
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(body);
        }

        try {
            ReportPublicationService.ReportState after = reports.transition(id, targetStatus);
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("id", target);
            body.put("period", after.period());
            body.put("key", after.key());
            body.put("status", after.status());
            body.put("publishedAt", after.publishedAt());
            idempotency.complete(principal, key, 200, body);
            audit.record(
                    principal,
                    action,
                    target,
                    AdminAudit.Outcome.ALLOWED,
                    Map.of("from", before.status(), "to", after.status()));
            return ResponseEntity.ok(body);
        } catch (RuntimeException failure) {
            Map<String, Object> body = Map.of("error", "report_transition_failed");
            idempotency.complete(principal, key, 500, body);
            audit.record(
                    principal,
                    action,
                    target,
                    AdminAudit.Outcome.FAILED,
                    Map.of("reason", failure.getClass().getSimpleName()));
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(body);
        }
    }
}
