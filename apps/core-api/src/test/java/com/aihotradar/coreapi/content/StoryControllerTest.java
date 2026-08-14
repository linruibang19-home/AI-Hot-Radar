package com.aihotradar.coreapi.content;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class StoryControllerTest {

    @Test
    void public_listing_only_exposes_events_with_multiple_independent_sources() {
        assertThat(StoryRepository.LIST_FILTER)
                .contains("st.status = 'PUBLISHED'")
                .contains("st.independent_source_count >= 2")
                .contains("MIN(confidence_items.similarity_score)")
                .contains(":minConfidence");
    }

    @Test
    void public_detail_rejects_internal_single_item_groups() {
        assertThat(StoryRepository.DETAIL_FILTER)
                .contains("st.status = 'PUBLISHED'")
                .contains("st.independent_source_count >= 2")
                .contains(":minConfidence");
    }

    @Test
    void summary_read_model_returns_the_named_sources_behind_the_count() {
        assertThat(StoryRepository.SUMMARY_SELECT)
                .contains("FROM story_item si2")
                .contains("SELECT DISTINCT s2.name AS source_name")
                .contains("AS source_names");
    }
}
