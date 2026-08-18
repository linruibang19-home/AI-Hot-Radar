package com.aihotradar.coreapi.admin;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import java.util.Optional;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** Protected read/write surface for the generation provider's address and key (V027). */
@RestController
@RequestMapping("/api/v1/admin/models/provider")
public class GenerationProviderController {

    static final String SAVE_ACTION = "generation_provider.update";
    static final String RESET_ACTION = "generation_provider.reset";
    /** What the reset request has to echo; there is no address to name when clearing one. */
    static final String RESET_CONFIRM = "environment";

    private final GenerationProviderService provider;
    private final AdminIdempotency idempotency;
    private final AdminAudit audit;

    public GenerationProviderController(
            GenerationProviderService provider, AdminIdempotency idempotency, AdminAudit audit) {
        this.provider = provider;
        this.idempotency = idempotency;
        this.audit = audit;
    }

    @GetMapping
    public Map<String, Object> state() {
        return provider.state();
    }

    @PostMapping
    public ResponseEntity<?> save(
            @RequestBody(required = false) ProviderRequest body,
            @RequestHeader(value = GenerationModelController.CONFIRM_HEADER, required = false)
                    String confirm,
            @RequestHeader(value = GenerationModelController.IDEMPOTENCY_HEADER, required = false)
                    String key,
            HttpServletRequest request) {
        AdminPrincipal principal = (AdminPrincipal) request.getAttribute(AdminPrincipal.ATTRIBUTE);
        String address = body == null || body.baseUrl() == null ? "" : body.baseUrl().strip();

        // Null-safe both ways, and an absent address can never satisfy the echo: comparing two
        // empty strings would let a body with no address through to a NullPointerException.
        if (address.isEmpty() || !address.equals(confirm)) {
            audit.record(
                    principal, SAVE_ACTION, address, AdminAudit.Outcome.DENIED_UNCONFIRMED, Map.of());
            return ResponseEntity.status(HttpStatus.PRECONDITION_REQUIRED)
                    .body(Map.of("error", "confirmation_required", "echo",
                            GenerationModelController.CONFIRM_HEADER));
        }
        return mutate(principal, key, SAVE_ACTION, address,
                () -> provider.update(address, body.apiKey(), principal));
    }

    @PostMapping("/reset")
    public ResponseEntity<?> reset(
            @RequestHeader(value = GenerationModelController.CONFIRM_HEADER, required = false)
                    String confirm,
            @RequestHeader(value = GenerationModelController.IDEMPOTENCY_HEADER, required = false)
                    String key,
            HttpServletRequest request) {
        AdminPrincipal principal = (AdminPrincipal) request.getAttribute(AdminPrincipal.ATTRIBUTE);
        if (!RESET_CONFIRM.equals(confirm)) {
            audit.record(
                    principal, RESET_ACTION, RESET_CONFIRM,
                    AdminAudit.Outcome.DENIED_UNCONFIRMED, Map.of());
            return ResponseEntity.status(HttpStatus.PRECONDITION_REQUIRED)
                    .body(Map.of("error", "confirmation_required", "echo",
                            GenerationModelController.CONFIRM_HEADER));
        }
        return mutate(principal, key, RESET_ACTION, RESET_CONFIRM,
                () -> provider.resetToEnvironment(principal));
    }

    /** The idempotency and audit shell both writes share. */
    private ResponseEntity<?> mutate(
            AdminPrincipal principal,
            String key,
            String action,
            String target,
            java.util.function.Supplier<Map<String, Object>> operation) {
        if (key == null || key.length() < 8 || key.length() > 200) {
            return ResponseEntity.badRequest().body(Map.of("error", "invalid_idempotency_key"));
        }
        AdminIdempotency.Claim claim = idempotency.begin(principal, key, action, target);
        Optional<ResponseEntity<?>> replayed = replay(claim);
        if (replayed.isPresent()) {
            return replayed.get();
        }
        try {
            Map<String, Object> state = operation.get();
            idempotency.complete(principal, key, 200, state);
            // The fingerprint identifies the credential without being one, so it is the right thing
            // to keep in an audit row: "who changed the key to which key", with no key in the table.
            audit.record(principal, action, target, AdminAudit.Outcome.ALLOWED,
                    Map.of("keyFingerprint", String.valueOf(state.get("keyFingerprint"))));
            return ResponseEntity.ok(state);
        } catch (IllegalArgumentException rejected) {
            Map<String, Object> response = Map.of("error", rejected.getMessage());
            idempotency.complete(principal, key, 422, response);
            audit.record(principal, action, target, AdminAudit.Outcome.FAILED,
                    Map.of("reason", String.valueOf(rejected.getMessage())));
            return ResponseEntity.unprocessableEntity().body(response);
        } catch (IllegalStateException unavailable) {
            Map<String, Object> response = Map.of("error", "credential_storage_unavailable");
            idempotency.complete(principal, key, 503, response);
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(response);
        }
    }

    private Optional<ResponseEntity<?>> replay(AdminIdempotency.Claim claim) {
        return switch (claim.state()) {
            case REPLAY -> Optional.of(
                    ResponseEntity.status(claim.responseStatus()).body(claim.responseBody()));
            case CONFLICT -> Optional.of(ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "idempotency_key_reused")));
            case IN_PROGRESS -> Optional.of(ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "request_in_progress")));
            case NEW -> Optional.empty();
        };
    }

    public record ProviderRequest(String baseUrl, String apiKey) {}
}
