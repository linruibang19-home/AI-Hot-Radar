package com.aihotradar.coreapi.health;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.aihotradar.coreapi.observability.RequestIdFilter;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

/**
 * Liveness must not depend on PostgreSQL or Redis, so this test runs without
 * either. Readiness is exercised by the Compose smoke check instead.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class HealthControllerTest {

    @Autowired private MockMvc mockMvc;

    @Test
    void liveReturnsOkWithoutDependencies() throws Exception {
        mockMvc.perform(get("/health/live"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ok"))
                .andExpect(jsonPath("$.service").value("core-api"));
    }

    @Test
    void requestIdIsEchoedWhenSupplied() throws Exception {
        mockMvc.perform(get("/health/live").header(RequestIdFilter.REQUEST_ID_HEADER, "abc-123"))
                .andExpect(header().string(RequestIdFilter.REQUEST_ID_HEADER, "abc-123"));
    }

    @Test
    void requestIdIsGeneratedWhenAbsent() throws Exception {
        mockMvc.perform(get("/health/live"))
                .andExpect(header().exists(RequestIdFilter.REQUEST_ID_HEADER));
    }
}
