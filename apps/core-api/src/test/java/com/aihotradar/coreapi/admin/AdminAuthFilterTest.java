package com.aihotradar.coreapi.admin;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import jakarta.servlet.FilterChain;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

/**
 * The gate on {@code /api/v1/admin/**}.
 *
 * <p>What is pinned here is mostly what must <em>not</em> happen: no request reaches a controller
 * without a credential, a read credential cannot write, and a rejection is recorded rather than
 * silently dropped.
 */
class AdminAuthFilterTest {

    private static final String TOKEN = "a".repeat(64);

    private AdminTokens tokens;
    private AdminAudit audit;
    private AdminAuthFilter filter;
    private FilterChain chain;

    private static final AdminPrincipal OPERATOR =
            new AdminPrincipal(UUID.randomUUID(), "laptop", AdminRole.OPERATOR);
    private static final AdminPrincipal VIEWER =
            new AdminPrincipal(UUID.randomUUID(), "dashboard", AdminRole.VIEWER);

    @BeforeEach
    void setUp() {
        tokens = mock(AdminTokens.class);
        audit = mock(AdminAudit.class);
        chain = mock(FilterChain.class);
        filter = new AdminAuthFilter(tokens, audit);
    }

    private MockHttpServletRequest request(String method, String uri) {
        MockHttpServletRequest request = new MockHttpServletRequest(method, uri);
        request.setRequestURI(uri);
        return request;
    }

    // --- the prefix is the boundary -----------------------------------------

    @Test
    void anything_outside_the_admin_prefix_is_not_touched() {
        // The public content API must not start demanding tokens.
        assertThat(filter.shouldNotFilter(request("GET", "/api/v1/content/items"))).isTrue();
        assertThat(filter.shouldNotFilter(request("GET", "/health/live"))).isTrue();
    }

    @Test
    void every_admin_path_is_covered_including_ones_that_do_not_exist_yet() {
        // Protection follows from the path, not from remembering to annotate a new controller.
        assertThat(filter.shouldNotFilter(request("GET", "/api/v1/admin/sources"))).isFalse();
        assertThat(filter.shouldNotFilter(request("POST", "/api/v1/admin/jobs/7/retry"))).isFalse();
        assertThat(filter.shouldNotFilter(request("POST", "/api/v1/admin/stories/merge"))).isFalse();
    }

    // --- deny by default ----------------------------------------------------

    @Test
    void a_request_without_a_token_never_reaches_the_controller() throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request("GET", "/api/v1/admin/sources"), response, chain);

        assertThat(response.getStatus()).isEqualTo(401);
        verify(chain, never()).doFilter(any(), any());
    }

    @Test
    void an_unknown_token_is_rejected_and_recorded() throws Exception {
        when(tokens.resolve(anyString())).thenReturn(Optional.empty());
        MockHttpServletRequest request = request("GET", "/api/v1/admin/sources");
        request.addHeader("Authorization", "Bearer " + TOKEN);
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(401);
        verify(chain, never()).doFilter(any(), any());
        // Repeated bad tokens are the thing the audit table exists to preserve.
        verify(audit)
                .record(
                        eq(null),
                        anyString(),
                        eq(null),
                        eq(AdminAudit.Outcome.DENIED_BAD_TOKEN),
                        any());
    }

    @Test
    void a_scheme_other_than_bearer_is_not_accepted() throws Exception {
        MockHttpServletRequest request = request("GET", "/api/v1/admin/sources");
        request.addHeader("Authorization", "Basic " + TOKEN);
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(401);
    }

    // --- roles --------------------------------------------------------------

    @Test
    void a_viewer_may_read() throws Exception {
        when(tokens.resolve(TOKEN)).thenReturn(Optional.of(VIEWER));
        MockHttpServletRequest request = request("GET", "/api/v1/admin/audit");
        request.addHeader("Authorization", "Bearer " + TOKEN);
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(any(), any());
        assertThat(request.getAttribute(AdminPrincipal.ATTRIBUTE)).isEqualTo(VIEWER);
    }

    @Test
    void a_viewer_may_not_write() throws Exception {
        // The whole reason there are two roles. If this passes with one role, "least privilege" is
        // a word in a document rather than a property of the system.
        when(tokens.resolve(TOKEN)).thenReturn(Optional.of(VIEWER));
        MockHttpServletRequest request = request("PATCH", "/api/v1/admin/sources/openai-blog");
        request.addHeader("Authorization", "Bearer " + TOKEN);
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, chain);

        assertThat(response.getStatus()).isEqualTo(403);
        verify(chain, never()).doFilter(any(), any());
        verify(audit)
                .record(eq(VIEWER), anyString(), eq(null), eq(AdminAudit.Outcome.DENIED_ROLE), any());
    }

    @Test
    void an_operator_may_write_and_is_passed_to_the_controller() throws Exception {
        when(tokens.resolve(TOKEN)).thenReturn(Optional.of(OPERATOR));
        MockHttpServletRequest request = request("PATCH", "/api/v1/admin/sources/openai-blog");
        request.addHeader("Authorization", "Bearer " + TOKEN);
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, chain);

        verify(chain).doFilter(any(), any());
        assertThat(request.getAttribute(AdminPrincipal.ATTRIBUTE)).isEqualTo(OPERATOR);
        verify(tokens).touch(OPERATOR.id());
    }

    // --- what the response says ---------------------------------------------

    @Test
    void the_rejection_body_does_not_say_which_check_failed() throws Exception {
        // "no such token" and "role too low" are useful to an operator reading the audit table and
        // useful to someone probing the endpoint. Only the first should be able to read them.
        when(tokens.resolve(TOKEN)).thenReturn(Optional.of(VIEWER));
        MockHttpServletRequest forbidden = request("POST", "/api/v1/admin/sources/x/run");
        forbidden.addHeader("Authorization", "Bearer " + TOKEN);
        MockHttpServletResponse roleDenied = new MockHttpServletResponse();
        filter.doFilter(forbidden, roleDenied, chain);

        MockHttpServletResponse noToken = new MockHttpServletResponse();
        filter.doFilter(request("POST", "/api/v1/admin/sources/x/run"), noToken, chain);

        assertThat(roleDenied.getContentAsString()).isEqualTo(noToken.getContentAsString());
        assertThat(roleDenied.getContentAsString()).doesNotContain("role");
    }
}
