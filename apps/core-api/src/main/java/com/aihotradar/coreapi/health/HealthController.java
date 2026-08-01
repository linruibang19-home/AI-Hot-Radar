package com.aihotradar.coreapi.health;

import java.util.LinkedHashMap;
import java.util.Map;
import javax.sql.DataSource;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Liveness and readiness endpoints.
 *
 * <p>{@code /health/live} stays dependency-free so a database outage never makes
 * the process look dead. {@code /health/ready} reports PostgreSQL and Redis
 * reachability and returns 503 when either is down.
 */
@RestController
@RequestMapping("/health")
public class HealthController {

    private final DataSource dataSource;
    private final RedisConnectionFactory redisConnectionFactory;

    public HealthController(DataSource dataSource, RedisConnectionFactory redisConnectionFactory) {
        this.dataSource = dataSource;
        this.redisConnectionFactory = redisConnectionFactory;
    }

    @GetMapping("/live")
    public Map<String, Object> live() {
        return Map.of("status", "ok", "service", "core-api");
    }

    @GetMapping("/ready")
    public ResponseEntity<Map<String, Object>> ready() {
        Map<String, String> checks = new LinkedHashMap<>();

        try (var connection = dataSource.getConnection();
                var statement = connection.prepareStatement("SELECT 1")) {
            statement.executeQuery().close();
            checks.put("postgres", "ok");
        } catch (Exception exception) {
            checks.put("postgres", "error: " + exception.getClass().getSimpleName());
        }

        try (var connection = redisConnectionFactory.getConnection()) {
            connection.ping();
            checks.put("redis", "ok");
        } catch (Exception exception) {
            checks.put("redis", "error: " + exception.getClass().getSimpleName());
        }

        boolean healthy = checks.values().stream().allMatch("ok"::equals);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", healthy ? "ok" : "degraded");
        body.put("service", "core-api");
        body.put("checks", checks);

        return ResponseEntity.status(healthy ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE)
                .body(body);
    }
}
