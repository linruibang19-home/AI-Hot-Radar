package com.aihotradar.coreapi.admin;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;

/** Persistent idempotency results for admin mutations (AHR-API-500 §5). */
@Component
public class AdminIdempotency {

    public enum State {
        NEW,
        REPLAY,
        CONFLICT,
        IN_PROGRESS
    }

    public record Claim(State state, Integer responseStatus, Map<String, Object> responseBody) {}

    private final NamedParameterJdbcTemplate jdbc;
    private final ObjectMapper json;

    public AdminIdempotency(NamedParameterJdbcTemplate jdbc, ObjectMapper json) {
        this.jdbc = jdbc;
        this.json = json;
    }

    public Claim begin(AdminPrincipal principal, String key, String action, String target) {
        String requestHash = sha256(action + "\n" + target);
        int inserted =
                jdbc.update(
                        """
                        INSERT INTO admin_idempotency
                            (principal_id, idempotency_key, action, target, request_hash)
                        VALUES (:principalId, :key, :action, :target, :requestHash)
                        ON CONFLICT (principal_id, idempotency_key) DO NOTHING
                        """,
                        new MapSqlParameterSource()
                                .addValue("principalId", principal.id())
                                .addValue("key", key)
                                .addValue("action", action)
                                .addValue("target", target)
                                .addValue("requestHash", requestHash));
        if (inserted == 1) {
            return new Claim(State.NEW, null, Map.of());
        }

        List<Map<String, Object>> rows =
                jdbc.queryForList(
                        """
                        SELECT request_hash, response_status, response_body::text AS response_body
                          FROM admin_idempotency
                         WHERE principal_id = :principalId AND idempotency_key = :key
                        """,
                        new MapSqlParameterSource()
                                .addValue("principalId", principal.id())
                                .addValue("key", key));
        if (rows.isEmpty()) {
            return new Claim(State.IN_PROGRESS, null, Map.of());
        }

        Map<String, Object> row = rows.getFirst();
        if (!requestHash.equals(row.get("request_hash"))) {
            return new Claim(State.CONFLICT, null, Map.of());
        }
        if (row.get("response_status") == null) {
            int reclaimed =
                    jdbc.update(
                            """
                            UPDATE admin_idempotency
                               SET created_at = now()
                             WHERE principal_id = :principalId
                               AND idempotency_key = :key
                               AND response_status IS NULL
                               AND created_at < now() - interval '5 minutes'
                            """,
                            new MapSqlParameterSource()
                                    .addValue("principalId", principal.id())
                                    .addValue("key", key));
            if (reclaimed == 1) {
                return new Claim(State.NEW, null, Map.of());
            }
            return new Claim(State.IN_PROGRESS, null, Map.of());
        }
        return new Claim(
                State.REPLAY,
                ((Number) row.get("response_status")).intValue(),
                parseBody((String) row.get("response_body")));
    }

    public void complete(
            AdminPrincipal principal, String key, int responseStatus, Map<String, Object> body) {
        jdbc.update(
                """
                UPDATE admin_idempotency
                   SET response_status = :status,
                       response_body = :body::jsonb,
                       completed_at = now()
                 WHERE principal_id = :principalId AND idempotency_key = :key
                """,
                new MapSqlParameterSource()
                        .addValue("status", responseStatus)
                        .addValue("body", writeBody(body))
                        .addValue("principalId", principal.id())
                        .addValue("key", key));
    }

    private Map<String, Object> parseBody(String body) {
        if (body == null || body.isBlank()) {
            return Map.of();
        }
        try {
            return json.readValue(body, new TypeReference<>() {});
        } catch (JsonProcessingException ignored) {
            return Map.of("error", "stored_response_unreadable");
        }
    }

    private String writeBody(Map<String, Object> body) {
        try {
            return json.writeValueAsString(body);
        } catch (JsonProcessingException ignored) {
            return "{}";
        }
    }

    private static String sha256(String value) {
        try {
            byte[] digest =
                    MessageDigest.getInstance("SHA-256")
                            .digest(value.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
    }
}
