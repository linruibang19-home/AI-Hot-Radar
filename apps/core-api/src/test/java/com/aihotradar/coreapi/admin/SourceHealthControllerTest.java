package com.aihotradar.coreapi.admin;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

import java.time.OffsetDateTime;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class SourceHealthControllerTest {

    @Mock private SourceRepository sources;

    @Test
    void summary_is_read_from_the_current_database_instead_of_a_web_constant() {
        var expected =
                new SourceRepository.SourceSummary(
                        140, 129, 11, OffsetDateTime.parse("2026-08-17T16:13:00+08:00"), "2026-08-17.2");
        when(sources.findSummary()).thenReturn(expected);

        var actual = new SourceHealthController(sources).summary();

        assertThat(actual).isEqualTo(expected);
    }
}
