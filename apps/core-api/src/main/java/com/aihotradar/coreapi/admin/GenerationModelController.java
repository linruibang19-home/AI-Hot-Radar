package com.aihotradar.coreapi.admin;

import jakarta.servlet.http.HttpServletRequest;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Protected read/switch surface for ADR-0027's generation model selection. */
@RestController
@RequestMapping("/api/v1/admin/models")
public class GenerationModelController {

    static final String CONFIRM_HEADER = "X-Confirm-Target";
    static final String IDEMPOTENCY_HEADER = "Idempotency-Key";
    static final String ACTION = "generation_model.select";

    private final GenerationModelService models;
    private final AdminIdempotency idempotency;
    private final AdminAudit audit;

    public GenerationModelController(
            GenerationModelService models, AdminIdempotency idempotency, AdminAudit audit) {
        this.models = models;
        this.idempotency = idempotency;
        this.audit = audit;
    }

    @GetMapping("/generation")
    public GenerationModelService.GenerationModelState generation() {
        return models.state();
    }

    @PostMapping("/generation/{modelId}/select")
    public ResponseEntity<?> select(
            @PathVariable String modelId,
            @RequestBody(required = false) SelectionRequest body,
            @RequestHeader(value = CONFIRM_HEADER, required = false) String confirm,
            @RequestHeader(value = IDEMPOTENCY_HEADER, required = false) String key,
            HttpServletRequest request) {
        AdminPrincipal principal =
                (AdminPrincipal) request.getAttribute(AdminPrincipal.ATTRIBUTE);

        if (!modelId.equals(confirm)) {
            audit.record(
                    principal,
                    ACTION,
                    modelId,
                    AdminAudit.Outcome.DENIED_UNCONFIRMED,
                    Map.of());
            return ResponseEntity.status(HttpStatus.PRECONDITION_REQUIRED)
                    .body(Map.of("error", "confirmation_required", "echo", CONFIRM_HEADER));
        }
        if (key == null || key.length() < 8 || key.length() > 200) {
            audit.record(
                    principal,
                    ACTION,
                    modelId,
                    AdminAudit.Outcome.FAILED,
                    Map.of("reason", "invalid idempotency key"));
            return ResponseEntity.badRequest().body(Map.of("error", "invalid_idempotency_key"));
        }

        AdminIdempotency.Claim claim = idempotency.begin(principal, key, ACTION, modelId);
        if (claim.state() == AdminIdempotency.State.REPLAY) {
            return ResponseEntity.status(claim.responseStatus()).body(claim.responseBody());
        }
        if (claim.state() == AdminIdempotency.State.CONFLICT) {
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "idempotency_key_reused"));
        }
        if (claim.state() == AdminIdempotency.State.IN_PROGRESS) {
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "request_in_progress"));
        }

        try {
            GenerationModelService.GenerationModelState state = models.select(modelId, principal);
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("current", state.current());
            response.put("thinkingEnabled", state.thinkingEnabled());
            idempotency.complete(principal, key, 200, response);
            audit.record(
                    principal,
                    ACTION,
                    modelId,
                    AdminAudit.Outcome.ALLOWED,
                    Map.of("reason", body == null ? "" : body.reason()));
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException rejected) {
            Map<String, Object> response = Map.of("error", "model_not_available");
            idempotency.complete(principal, key, 409, response);
            audit.record(
                    principal,
                    ACTION,
                    modelId,
                    AdminAudit.Outcome.FAILED,
                    Map.of("reason", "model not available"));
            return ResponseEntity.status(HttpStatus.CONFLICT).body(response);
        }
    }

    public record SelectionRequest(String reason) {
        public SelectionRequest {
            reason = reason == null ? "" : reason.strip();
            if (reason.length() > 300) {
                reason = reason.substring(0, 300);
            }
        }
    }
}
