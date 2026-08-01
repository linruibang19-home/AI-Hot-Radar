package com.aihotradar.coreapi.health;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.aihotradar.coreapi.observability.RequestIdFilter;
import javax.sql.DataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

/**
 * Liveness and request-ID tests.
 *
 * <p>Uses {@code @WebMvcTest} with mocked infrastructure beans rather than
 * {@code @SpringBootTest}: the full context would eagerly initialise a real
 * DataSource and Redis connection, which would make these tests require live
 * infrastructure. Readiness against real dependencies is covered by the Compose
 * smoke check instead.
 */
@WebMvcTest(controllers = HealthController.class)
class HealthControllerTest {

    @Autowired private MockMvc mockMvc;

    @MockitoBean private DataSource dataSource;

    @MockitoBean private RedisConnectionFactory redisConnectionFactory;

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
