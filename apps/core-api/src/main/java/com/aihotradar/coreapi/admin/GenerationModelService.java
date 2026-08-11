package com.aihotradar.coreapi.admin;

import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** PostgreSQL-backed DeepSeek generation model catalog and current selection. */
@Service
public class GenerationModelService {

    private final NamedParameterJdbcTemplate jdbc;

    public GenerationModelService(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public GenerationModelState state() {
        Map<String, Object> current =
                jdbc.queryForMap(
                        """
                        SELECT c.model_id, c.version, c.updated_at,
                               m.display_name, m.description, m.context_window_tokens,
                               m.input_cny_per_million, m.cached_input_cny_per_million,
                               m.output_cny_per_million, m.pricing_effective_on, m.pricing_source
                          FROM generation_model_config c
                          JOIN generation_model_catalog m ON m.model_id = c.model_id
                         WHERE c.singleton_key = 1
                        """,
                        Map.of());
        List<Map<String, Object>> available =
                jdbc.queryForList(
                        """
                        SELECT model_id, display_name, description, context_window_tokens,
                               input_cny_per_million, cached_input_cny_per_million,
                               output_cny_per_million, pricing_effective_on, pricing_source
                          FROM generation_model_catalog
                         WHERE enabled
                         ORDER BY input_cny_per_million, model_id
                        """,
                        Map.of());
        return new GenerationModelState(current, available, false, "siliconflow-fixed");
    }

    @Transactional
    public GenerationModelState select(String modelId, AdminPrincipal principal) {
        int enabled =
                jdbc.queryForObject(
                        """
                        SELECT count(*)
                          FROM generation_model_catalog
                         WHERE model_id = :modelId AND enabled
                        """,
                        new MapSqlParameterSource("modelId", modelId),
                        Integer.class);
        if (enabled != 1) {
            throw new IllegalArgumentException("model is not in the enabled catalog");
        }

        jdbc.update(
                """
                UPDATE generation_model_config
                   SET model_id = :modelId,
                       version = CASE WHEN model_id = :modelId THEN version ELSE version + 1 END,
                       updated_by = :principalId,
                       updated_at = CASE WHEN model_id = :modelId THEN updated_at ELSE now() END
                 WHERE singleton_key = 1
                """,
                new MapSqlParameterSource()
                        .addValue("modelId", modelId)
                        .addValue("principalId", principal.id()));
        return state();
    }

    /** The current model, allowlist and the deliberately fixed retrieval-model boundary. */
    public record GenerationModelState(
            Map<String, Object> current,
            List<Map<String, Object>> available,
            boolean thinkingEnabled,
            String retrievalModels) {}
}
