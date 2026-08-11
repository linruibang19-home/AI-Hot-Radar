package com.aihotradar.coreapi.admin;

import jakarta.servlet.http.HttpServletRequest;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * The operator mutations that {@code SourceHealthController} has been deferring since M1
 * (AHR-API-500: {@code PATCH /admin/sources/{id}}, {@code POST /admin/sources/{id}/run}).
 *
 * <p>Authentication and role are handled by {@link AdminAuthFilter} before anything here runs, so
 * this class is only responsible for the two things a filter cannot know: whether the caller
 * confirmed the specific target, and what actually changed.
 */
@RestController
@RequestMapping("/api/v1/admin/sources")
public class SourceAdminController {

    /**
     * AHR-QSO-700 §3 requires second confirmation on key operations. Enforced here rather than in
     * the browser: a confirmation dialog is a property of one client, and the endpoint is reachable
     * without it. The caller must echo the exact id it intends to change — the same reason GitHub
     * asks you to type a repository name, and it fails the case that actually happens, which is a
     * correct-looking request aimed at the wrong row.
     */
    static final String CONFIRM_HEADER = "X-Confirm-Target";

    private final NamedParameterJdbcTemplate jdbc;
    private final AdminAudit audit;

    public SourceAdminController(NamedParameterJdbcTemplate jdbc, AdminAudit audit) {
        this.jdbc = jdbc;
        this.audit = audit;
    }

    /** Override, or stop overriding, whether a source is polled. */
    @PatchMapping("/{id}")
    public ResponseEntity<?> setEnabled(
            @PathVariable String id,
            @RequestBody EnabledPatch patch,
            @RequestHeader(value = CONFIRM_HEADER, required = false) String confirm,
            HttpServletRequest request) {

        AdminPrincipal principal = principalOf(request);
        if (!id.equals(confirm)) {
            audit.record(
                    principal,
                    "source.set_enabled",
                    id,
                    AdminAudit.Outcome.DENIED_UNCONFIRMED,
                    Map.of("requested", String.valueOf(patch.enabled())));
            return ResponseEntity.status(HttpStatus.PRECONDITION_REQUIRED)
                    .body(Map.of("error", "confirmation_required", "echo", CONFIRM_HEADER));
        }

        Map<String, Object> before = currentState(id);
        if (before == null) {
            return ResponseEntity.notFound().build();
        }

        int updated =
                jdbc.update(
                        """
                        UPDATE source
                           SET operator_enabled = :enabled,
                               operator_note = :note
                         WHERE id = :id
                        """,
                        new MapSqlParameterSource()
                                .addValue("enabled", patch.enabled())
                                .addValue("note", patch.note())
                                .addValue("id", id));

        Map<String, Object> after = currentState(id);
        Map<String, Object> detail = new HashMap<>();
        detail.put("from", before.get("effective_enabled"));
        detail.put("to", after == null ? null : after.get("effective_enabled"));
        detail.put("override", patch.enabled());
        detail.put("note", patch.note());
        audit.record(
                principal,
                "source.set_enabled",
                id,
                updated == 1 ? AdminAudit.Outcome.ALLOWED : AdminAudit.Outcome.FAILED,
                detail);

        return ResponseEntity.ok(after);
    }

    /**
     * Bring a source's next poll forward to now.
     *
     * <p>Does not fetch anything itself: the scheduler owns polling, and a controller that reached
     * out to the network would be a second ingestion path with its own timeouts, its own SSRF
     * surface and its own idea of the failure ladder. This moves the clock and lets the scheduler
     * do what it already does — which is also why it is safe to press twice.
     */
    @PostMapping("/{id}/run")
    public ResponseEntity<?> runNow(
            @PathVariable String id,
            @RequestHeader(value = CONFIRM_HEADER, required = false) String confirm,
            HttpServletRequest request) {

        AdminPrincipal principal = principalOf(request);
        if (!id.equals(confirm)) {
            audit.record(
                    principal, "source.run", id, AdminAudit.Outcome.DENIED_UNCONFIRMED, Map.of());
            return ResponseEntity.status(HttpStatus.PRECONDITION_REQUIRED)
                    .body(Map.of("error", "confirmation_required", "echo", CONFIRM_HEADER));
        }

        int updated =
                jdbc.update(
                        "UPDATE source SET next_poll_at = now() WHERE id = :id AND effective_enabled",
                        new MapSqlParameterSource("id", id));

        if (updated == 0) {
            // Either no such source, or it is disabled. Scheduling a poll for a source the
            // scheduler will skip would report success for something that never happens.
            audit.record(
                    principal,
                    "source.run",
                    id,
                    AdminAudit.Outcome.FAILED,
                    Map.of("reason", "unknown or disabled"));
            return ResponseEntity.status(HttpStatus.CONFLICT)
                    .body(Map.of("error", "source_unknown_or_disabled"));
        }

        audit.record(principal, "source.run", id, AdminAudit.Outcome.ALLOWED, Map.of());
        return ResponseEntity.accepted().body(Map.of("scheduled", true, "id", id));
    }

    private Map<String, Object> currentState(String id) {
        List<Map<String, Object>> rows =
                jdbc.queryForList(
                        """
                        SELECT id, configured_enabled, operator_enabled, effective_enabled,
                               operator_note, runtime_state, next_poll_at
                          FROM source WHERE id = :id
                        """,
                        new MapSqlParameterSource("id", id));
        return rows.isEmpty() ? null : rows.get(0);
    }

    private AdminPrincipal principalOf(HttpServletRequest request) {
        return (AdminPrincipal) request.getAttribute(AdminPrincipal.ATTRIBUTE);
    }

    /**
     * {@code enabled} is nullable on purpose: null clears the override and returns the source to
     * whatever {@code config/sources.yaml} says. Without it an operator could only ever pin a value,
     * and "put it back the way it was" would mean editing the registry.
     */
    public record EnabledPatch(Boolean enabled, String note) {}
}
