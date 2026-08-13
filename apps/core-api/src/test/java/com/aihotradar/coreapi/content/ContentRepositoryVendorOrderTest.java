package com.aihotradar.coreapi.content;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.time.OffsetDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

class ContentRepositoryVendorOrderTest {

    @SuppressWarnings({"unchecked", "rawtypes"})
    @Test
    void vendor_timeline_orders_by_effective_publication_time_before_relation_score() {
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.query(any(String.class), any(MapSqlParameterSource.class), any(RowMapper.class)))
                .thenReturn(List.of());
        ContentRepository repository = new ContentRepository(jdbc);

        repository.findVendorFeed(
                "deepseek",
                "related",
                new ContentRepository.VendorCursor(
                        0.91, OffsetDateTime.parse("2026-08-13T11:54:00Z"),
                        "00000000-0000-0000-0000-000000000001"),
                21);

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc)
                .query(sql.capture(), any(MapSqlParameterSource.class), any(RowMapper.class));

        String normalized = sql.getValue().replaceAll("\\s+", " ");
        assertThat(normalized)
                .contains(
                        "(COALESCE(ci.published_at, ci.observed_at), ivr.score, ci.id) < (:publishedAt, :score, CAST(:id AS uuid))")
                .contains(
                        "ORDER BY COALESCE(ci.published_at, ci.observed_at) DESC, ivr.score DESC, ci.id DESC");
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    @Test
    void public_chunk_count_only_reports_the_active_index_generation() {
        NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);
        when(jdbc.query(any(String.class), any(MapSqlParameterSource.class), any(RowMapper.class)))
                .thenReturn(List.of());
        ContentRepository repository = new ContentRepository(jdbc);

        repository.stats();

        ArgumentCaptor<String> sql = ArgumentCaptor.forClass(String.class);
        verify(jdbc).query(sql.capture(), any(MapSqlParameterSource.class), any(RowMapper.class));
        assertThat(sql.getValue().replaceAll("\\s+", " "))
                .contains("count(*) FROM content_chunk WHERE is_active");
    }
}
