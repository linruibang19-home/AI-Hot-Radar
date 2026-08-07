package com.aihotradar.coreapi.admin;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Map;
import java.util.Optional;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Authentication and role enforcement for {@code /api/v1/admin/**}.
 *
 * <p>AHR-API-500 §"所有 /admin/** 需要 RBAC" is a locked requirement that the service was not
 * meeting: {@code GET /api/v1/admin/sources} answered anybody. The console was read-only, so
 * nothing could be changed through it, but "there is nothing to steal" is not the same as
 * "authentication is not required" — and the moment a mutation endpoint appeared, the gap would
 * have become an unauthenticated write surface.
 *
 * <p>Registered by {@link AdminSecurityConfig} rather than component-scanned. A {@code @Component}
 * filter is pulled into every {@code @WebMvcTest} slice, where its collaborators do not exist —
 * which is a test-shaped reason, but the registration also puts the URL pattern and the filter
 * order in one readable place instead of spreading them over annotations.
 *
 * <p><b>Protected by path prefix, not by annotation.</b> A new endpoint under {@code /admin} is
 * covered because of where it lives, not because someone remembered to mark it. The inverse — a
 * filter that checks a list of known paths, or an annotation each controller opts into — fails open
 * for exactly the endpoint that was added in a hurry.
 *
 * <p><b>On CSRF.</b> The contract asks for CSRF or same-origin protection alongside RBAC. That
 * requirement exists for <em>ambient</em> credentials: a cookie is attached by the browser to a
 * cross-site request, so the site must prove the request was intentional. This surface
 * authenticates with an {@code Authorization} header, which no cross-origin form or image tag can
 * set, and there is no cookie or session for a browser to attach automatically. A CSRF token here
 * would be a second secret guarding a door that does not open on its own. Recorded rather than
 * silently skipped, because "we implemented the checklist item" and "the attack is not reachable"
 * are different claims and only the second one is true.
 */
public class AdminAuthFilter extends OncePerRequestFilter {

    static final String PROTECTED_PREFIX = "/api/v1/admin/";
    private static final String BEARER = "Bearer ";

    private final AdminTokens tokens;
    private final AdminAudit audit;

    public AdminAuthFilter(AdminTokens tokens, AdminAudit audit) {
        this.tokens = tokens;
        this.audit = audit;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith(PROTECTED_PREFIX);
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        boolean mutating = !"GET".equals(request.getMethod());
        String action = request.getMethod() + " " + request.getRequestURI();

        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith(BEARER)) {
            deny(response, HttpStatus.UNAUTHORIZED, "missing bearer token");
            // Reads are not audited when they are merely unauthenticated: a public scanner hitting
            // the path would fill the table with noise. A rejected *mutation* is worth a row.
            if (mutating) {
                audit.record(null, action, null, AdminAudit.Outcome.DENIED_NO_TOKEN, Map.of());
            }
            return;
        }

        Optional<AdminPrincipal> resolved = tokens.resolve(header.substring(BEARER.length()));
        if (resolved.isEmpty()) {
            deny(response, HttpStatus.UNAUTHORIZED, "invalid token");
            // Always audited, read or write: repeated bad tokens are the signal this table exists
            // to preserve.
            audit.record(null, action, null, AdminAudit.Outcome.DENIED_BAD_TOKEN, Map.of());
            return;
        }

        AdminPrincipal principal = resolved.get();
        if (mutating && !principal.role().canMutate()) {
            deny(response, HttpStatus.FORBIDDEN, "role may not mutate");
            audit.record(principal, action, null, AdminAudit.Outcome.DENIED_ROLE, Map.of());
            return;
        }

        tokens.touch(principal.id());
        request.setAttribute(AdminPrincipal.ATTRIBUTE, principal);
        chain.doFilter(request, response);
    }

    /**
     * 401/403 with a fixed body.
     *
     * <p>The same message whatever went wrong. "No such credential" and "credential revoked" and
     * "role too low for this path" are useful to an operator reading the audit table and useful to
     * someone probing the endpoint; only the first of those should be able to read them.
     */
    private void deny(HttpServletResponse response, HttpStatus status, String reason)
            throws IOException {
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        response.getWriter().write("{\"error\":\"forbidden\"}");
        logger.warn("admin request denied: " + reason);
    }
}
