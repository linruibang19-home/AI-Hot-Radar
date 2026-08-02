package com.aihotradar.coreapi.content;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

/**
 * Category tab mapping.
 *
 * <p>The tabs drive both the filter and the counts shown beside each tab, so a
 * type that belongs to no tab is invisible on the site while still inflating the
 * "全部" total. These tests pin that relationship.
 */
class ContentCategoryTest {

    @ParameterizedTest
    @CsvSource({
        "model, model_release",
        "paper, research",
        "opinion, opinion",
    })
    @DisplayName("a single-type tab resolves to exactly that type")
    void singleTypeTabs(String tab, String expected) {
        assertThat(ContentCategory.resolve(tab)).containsExactly(expected);
    }

    @Test
    @DisplayName("产品 covers API updates as well as product launches")
    void productTabSpansTwoTypes() {
        assertThat(ContentCategory.resolve("product"))
                .containsExactlyInAnyOrder("product_release", "api_update");
    }

    @ParameterizedTest
    @ValueSource(strings = {"all", "", "   "})
    @DisplayName("the all tab applies no filter")
    void allTabIsUnfiltered(String tab) {
        assertThat(ContentCategory.resolve(tab)).isEmpty();
    }

    @Test
    @DisplayName("a null tab applies no filter rather than throwing")
    void nullTabIsUnfiltered() {
        assertThat(ContentCategory.resolve(null)).isEmpty();
    }

    @Test
    @DisplayName("a raw content type stays usable directly against the API")
    void rawContentTypePassesThrough() {
        assertThat(ContentCategory.resolve("security")).containsExactly("security");
    }

    @Test
    @DisplayName("tab lookup is case-insensitive")
    void tabLookupIgnoresCase() {
        assertThat(ContentCategory.resolve("MODEL")).containsExactly("model_release");
    }

    @Test
    @DisplayName("every tab key resolves to at least one type")
    void everyTabKeyResolves() {
        // A tab key with no mapping would render as a tab that always shows the
        // unfiltered feed, which looks like the filter is broken.
        for (String tab : ContentCategory.tabKeys()) {
            assertThat(ContentCategory.resolve(tab)).as("tab %s", tab).isNotEmpty();
        }
    }

    @Test
    @DisplayName("every tab key has a label")
    void everyTabKeyHasALabel() {
        for (String tab : ContentCategory.tabKeys()) {
            assertThat(ContentCategory.label(tab)).as("tab %s", tab).isNotEqualTo(tab);
        }
    }

    @ParameterizedTest
    @CsvSource({
        "model_release, model",
        "api_update, product",
        "product_release, product",
        "policy, industry",
        "open_source, tutorial",
    })
    @DisplayName("a stored type maps back to the tab that shows it")
    void reverseLookupMatchesForwardMapping(String contentType, String expectedTab) {
        assertThat(ContentCategory.tabFor(contentType)).isEqualTo(expectedTab);
    }

    @Test
    @DisplayName("an unmapped type belongs to no tab")
    void unmappedTypeHasNoTab() {
        assertThat(ContentCategory.tabFor("sdk_release")).isNull();
        assertThat(ContentCategory.tabFor(null)).isNull();
    }

    @Test
    @DisplayName("forward and reverse mappings agree for every tab")
    void mappingsAreConsistent() {
        // Guards the category counts: a type routed to one tab by resolve() but
        // to another by tabFor() would be filtered into a tab whose count
        // excludes it.
        for (String tab : ContentCategory.tabKeys()) {
            List<String> types = ContentCategory.resolve(tab);
            for (String type : types) {
                assertThat(ContentCategory.tabFor(type)).as("type %s", type).isEqualTo(tab);
            }
        }
    }
}
