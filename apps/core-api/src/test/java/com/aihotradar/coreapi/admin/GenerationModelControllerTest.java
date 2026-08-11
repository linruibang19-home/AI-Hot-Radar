package com.aihotradar.coreapi.admin;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import java.util.List;
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
class GenerationModelControllerTest {

    @Mock private GenerationModelService models;
    @Mock private AdminIdempotency idempotency;
    @Mock private AdminAudit audit;

    private GenerationModelController controller;
    private MockHttpServletRequest request;
    private AdminPrincipal operator;

    @BeforeEach
    void setUp() {
        controller = new GenerationModelController(models, idempotency, audit);
        request = new MockHttpServletRequest();
        operator = new AdminPrincipal(UUID.randomUUID(), "operator", AdminRole.OPERATOR);
        request.setAttribute(AdminPrincipal.ATTRIBUTE, operator);
    }

    @Test
    void selection_requires_exact_confirmation_before_claiming_idempotency() {
        ResponseEntity<?> response =
                controller.select(
                        "deepseek-v4-pro",
                        new GenerationModelController.SelectionRequest("compare"),
                        null,
                        "switch-12345",
                        request);

        assertThat(response.getStatusCode().value()).isEqualTo(428);
        verifyNoInteractions(models, idempotency);
    }

    @Test
    void operator_selects_only_after_all_guards() {
        when(idempotency.begin(operator, "switch-12345", "generation_model.select", "deepseek-v4-pro"))
                .thenReturn(new AdminIdempotency.Claim(AdminIdempotency.State.NEW, null, Map.of()));
        var state =
                new GenerationModelService.GenerationModelState(
                        Map.of("model_id", "deepseek-v4-pro", "version", 2),
                        List.of(),
                        false,
                        "siliconflow-fixed");
        when(models.select("deepseek-v4-pro", operator)).thenReturn(state);

        ResponseEntity<?> response =
                controller.select(
                        "deepseek-v4-pro",
                        new GenerationModelController.SelectionRequest("compare report quality"),
                        "deepseek-v4-pro",
                        "switch-12345",
                        request);

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        verify(models).select("deepseek-v4-pro", operator);
        verify(idempotency)
                .complete(
                        org.mockito.ArgumentMatchers.eq(operator),
                        org.mockito.ArgumentMatchers.eq("switch-12345"),
                        org.mockito.ArgumentMatchers.eq(200),
                        org.mockito.ArgumentMatchers.anyMap());
    }
}
