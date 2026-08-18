package com.aihotradar.coreapi.admin;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

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
class GenerationProviderControllerTest {

    @Mock private GenerationProviderService provider;
    @Mock private AdminIdempotency idempotency;
    @Mock private AdminAudit audit;

    private GenerationProviderController controller;
    private MockHttpServletRequest request;
    private AdminPrincipal operator;

    private static final String ADDRESS = "https://api.deepseek.com";

    @BeforeEach
    void setUp() {
        controller = new GenerationProviderController(provider, idempotency, audit);
        request = new MockHttpServletRequest();
        operator = new AdminPrincipal(UUID.randomUUID(), "operator", AdminRole.OPERATOR);
        request.setAttribute(AdminPrincipal.ATTRIBUTE, operator);
    }

    private static GenerationProviderController.ProviderRequest body(String url, String key) {
        return new GenerationProviderController.ProviderRequest(url, key);
    }

    @Test
    void the_address_must_be_echoed_before_anything_is_probed_or_stored() {
        ResponseEntity<?> response =
                controller.save(body(ADDRESS, "sk-key"), null, "provider-key-1", request);

        assertThat(response.getStatusCode().value()).isEqualTo(428);
        verifyNoInteractions(provider, idempotency);
    }

    @Test
    void a_body_without_an_address_is_rejected_rather_than_matching_an_absent_header() {
        // Comparing two empty strings would call a missing address "confirmed"
        // and carry it into the service.
        ResponseEntity<?> response = controller.save(body(null, "sk-key"), null, "provider-key-1", request);

        assertThat(response.getStatusCode().value()).isEqualTo(428);
        verifyNoInteractions(provider, idempotency);
    }

    @Test
    void a_verified_pair_is_stored_once_and_audited_by_fingerprint_not_by_key() {
        when(idempotency.begin(operator, "provider-key-1", "generation_provider.update", ADDRESS))
                .thenReturn(new AdminIdempotency.Claim(AdminIdempotency.State.NEW, null, Map.of()));
        when(provider.update(ADDRESS, "sk-key", operator))
                .thenReturn(Map.of("baseUrl", ADDRESS, "keyFingerprint", "abc123def456"));

        ResponseEntity<?> response =
                controller.save(body(ADDRESS, "sk-key"), ADDRESS, "provider-key-1", request);

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        verify(provider).update(ADDRESS, "sk-key", operator);
        verify(audit).record(
                operator,
                "generation_provider.update",
                ADDRESS,
                AdminAudit.Outcome.ALLOWED,
                Map.of("keyFingerprint", "abc123def456"));
    }

    @Test
    void a_replayed_save_does_not_probe_the_provider_again() {
        when(idempotency.begin(operator, "provider-key-1", "generation_provider.update", ADDRESS))
                .thenReturn(new AdminIdempotency.Claim(
                        AdminIdempotency.State.REPLAY, 200, Map.of("baseUrl", ADDRESS)));

        ResponseEntity<?> response =
                controller.save(body(ADDRESS, "sk-key"), ADDRESS, "provider-key-1", request);

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        verifyNoInteractions(provider);
    }

    @Test
    void a_rejected_provider_is_a_422_and_leaves_the_running_configuration_alone() {
        when(idempotency.begin(operator, "provider-key-1", "generation_provider.update", ADDRESS))
                .thenReturn(new AdminIdempotency.Claim(AdminIdempotency.State.NEW, null, Map.of()));
        when(provider.update(ADDRESS, "sk-bad", operator))
                .thenThrow(new IllegalArgumentException("provider_auth_failed"));

        ResponseEntity<?> response =
                controller.save(body(ADDRESS, "sk-bad"), ADDRESS, "provider-key-1", request);

        assertThat(response.getStatusCode().value()).isEqualTo(422);
        assertThat(response.getBody()).isEqualTo(Map.of("error", "provider_auth_failed"));
    }

    @Test
    void an_unconfigured_credential_store_is_a_503_not_a_500() {
        when(idempotency.begin(operator, "provider-key-1", "generation_provider.update", ADDRESS))
                .thenReturn(new AdminIdempotency.Claim(AdminIdempotency.State.NEW, null, Map.of()));
        when(provider.update(ADDRESS, "sk-key", operator))
                .thenThrow(new IllegalStateException("no master key"));

        ResponseEntity<?> response =
                controller.save(body(ADDRESS, "sk-key"), ADDRESS, "provider-key-1", request);

        assertThat(response.getStatusCode().value()).isEqualTo(503);
        assertThat(response.getBody()).isEqualTo(Map.of("error", "credential_storage_unavailable"));
    }

    @Test
    void resetting_to_the_environment_needs_its_own_confirmation() {
        ResponseEntity<?> denied = controller.reset(ADDRESS, "provider-key-2", request);
        assertThat(denied.getStatusCode().value()).isEqualTo(428);

        when(idempotency.begin(operator, "provider-key-2", "generation_provider.reset", "environment"))
                .thenReturn(new AdminIdempotency.Claim(AdminIdempotency.State.NEW, null, Map.of()));
        when(provider.resetToEnvironment(operator))
                .thenReturn(Map.of("usesEnvironment", true, "keyFingerprint", "null"));

        ResponseEntity<?> allowed = controller.reset("environment", "provider-key-2", request);

        assertThat(allowed.getStatusCode().value()).isEqualTo(200);
        verify(provider).resetToEnvironment(operator);
    }

    @Test
    void a_missing_idempotency_key_is_refused_before_the_provider_is_contacted() {
        ResponseEntity<?> response = controller.save(body(ADDRESS, "sk-key"), ADDRESS, "short", request);

        assertThat(response.getStatusCode().value()).isEqualTo(400);
        verifyNoInteractions(provider);
    }
}
