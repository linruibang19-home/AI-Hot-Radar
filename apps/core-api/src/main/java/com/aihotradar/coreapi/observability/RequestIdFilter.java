package com.aihotradar.coreapi.observability;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Propagates a stable request ID across the Java/Python boundary.
 *
 * <p>AHR-QSO-700 §5 requires {@code request_id} on every log line so one
 * ingestion or RAG operation can be traced end to end. An inbound
 * {@code X-Request-ID} is preserved; otherwise a new one is minted. The value is
 * placed in SLF4J's MDC and echoed on the response.
 */
@Component
@Order(1)
public class RequestIdFilter extends OncePerRequestFilter {

    public static final String REQUEST_ID_HEADER = "X-Request-ID";
    public static final String MDC_KEY = "request_id";

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {

        String incoming = request.getHeader(REQUEST_ID_HEADER);
        String requestId =
                (incoming == null || incoming.isBlank()) ? UUID.randomUUID().toString() : incoming;

        MDC.put(MDC_KEY, requestId);
        response.setHeader(REQUEST_ID_HEADER, requestId);
        try {
            chain.doFilter(request, response);
        } finally {
            // The worker thread is pooled; a leaked MDC entry would mislabel later requests.
            MDC.remove(MDC_KEY);
        }
    }
}
