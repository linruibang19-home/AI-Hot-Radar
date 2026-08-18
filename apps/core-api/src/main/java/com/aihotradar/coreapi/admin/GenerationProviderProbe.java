package com.aihotradar.coreapi.admin;

import java.net.URI;
import java.time.Duration;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

/**
 * Checks a provider address and key before either is written.
 *
 * <p>Saving an unverified credential into the live generation path is the failure worth designing
 * out: enrichment, recommendation reasons, reports and RAG answers all build their client from this
 * row, so a wrong key does not surface as an error on this page — it surfaces hours later as a
 * pipeline that quietly stopped enriching.
 *
 * <p>{@code GET {base}/models} rather than a completion: it proves the address resolves and the key
 * is accepted, costs no tokens, and cannot be charged for. The path is composed exactly the way
 * {@code ahr.processing.llm} composes {@code /chat/completions}, so a base that works here works
 * there.
 */
@Component
public class GenerationProviderProbe {

    private static final Logger LOGGER = LoggerFactory.getLogger(GenerationProviderProbe.class);

    private final RestClient client;

    public GenerationProviderProbe() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(5));
        factory.setReadTimeout(Duration.ofSeconds(15));
        this.client = RestClient.builder().requestFactory(factory).build();
    }

    /**
     * @throws IllegalArgumentException with a short, non-secret reason code when the provider will
     *     not serve this pair. The upstream body is never propagated: it can echo the key.
     */
    public void verify(String baseUrl, String apiKey) {
        String target = baseUrl.replaceAll("/+$", "") + "/models";
        try {
            ProbeResult result =
                    client.get()
                            .uri(URI.create(target))
                            .header("Authorization", "Bearer " + apiKey)
                            .accept(MediaType.APPLICATION_JSON)
                            .exchange(
                                    (request, response) ->
                                            new ProbeResult(
                                                    response.getStatusCode().value(),
                                                    response.getHeaders().getFirst("Content-Type")));
            if (result == null) {
                throw new IllegalArgumentException("provider_unreachable");
            }
            if (result.status() == 401 || result.status() == 403) {
                throw new IllegalArgumentException("provider_auth_failed");
            }
            if (result.status() == 404) {
                throw new IllegalArgumentException("provider_endpoint_not_found");
            }
            if (result.status() >= 400) {
                throw new IllegalArgumentException("provider_rejected");
            }
            // A gateway console answers 200 with HTML on paths that are not its API. Accepting that
            // would store a URL that passes this check and fails every real call.
            String contentType = result.contentType() == null ? "" : result.contentType();
            if (contentType.toLowerCase().contains("html")) {
                throw new IllegalArgumentException("provider_returned_html");
            }
        } catch (IllegalArgumentException rejected) {
            throw rejected;
        } catch (RestClientException transportFailure) {
            LOGGER.warn(
                    "generation provider probe failed: exception={}",
                    transportFailure.getClass().getSimpleName());
            throw new IllegalArgumentException("provider_unreachable", transportFailure);
        }
    }

    private record ProbeResult(int status, String contentType) {}
}
