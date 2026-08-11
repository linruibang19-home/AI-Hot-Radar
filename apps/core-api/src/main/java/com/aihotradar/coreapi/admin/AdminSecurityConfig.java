package com.aihotradar.coreapi.admin;

import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Wires {@link AdminAuthFilter} in front of the admin API.
 *
 * <p><b>Why not Spring Security.</b> It is the reflexive answer and it would be the wrong one here.
 * The surface is a single bearer token checked against a table: no sessions, no cookies, no form
 * login, no OAuth, no CSRF token to manage. Adding the starter would bring a large default
 * configuration whose first job would be to switch most of itself off, and the resulting chain
 * would be harder to read than the sixty lines it replaced. The judgement flips the moment there
 * are user accounts or a second authentication method, and that is the point at which it should be
 * revisited rather than now — see docs/adr/0019.
 */
@Configuration
public class AdminSecurityConfig {

    @Bean
    public FilterRegistrationBean<AdminAuthFilter> adminAuthFilter(
            AdminTokens tokens, AdminAudit audit) {

        FilterRegistrationBean<AdminAuthFilter> registration =
                new FilterRegistrationBean<>(new AdminAuthFilter(tokens, audit));

        // Stated here as well as in the filter's own shouldNotFilter. Two independent
        // expressions of the same boundary: the container never routes anything else to it, and
        // the filter refuses anything else if it is ever mounted more broadly.
        registration.addUrlPatterns("/api/v1/admin/*");

        // After RequestIdFilter (order 1), so a denied admin request still carries the request id
        // that ties its log line to the audit row.
        registration.setOrder(2);
        return registration;
    }
}
