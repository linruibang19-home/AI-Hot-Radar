package com.aihotradar.coreapi.admin;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verifyNoInteractions;

import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.core.namedparam.SqlParameterSource;

class AdminTokensTest {

    private final NamedParameterJdbcTemplate jdbc = mock(NamedParameterJdbcTemplate.class);

    @Test
    void the_token_is_hashed_with_sha256_hex() {
        // Pinned against a known vector rather than against itself: if the encoding ever changes,
        // every stored credential stops resolving, and that must fail here rather than in
        // production at 3am.
        assertThat(AdminTokens.hash("abc"))
                .isEqualTo("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
        assertThat(AdminTokens.hash("abc")).hasSize(64).matches("[0-9a-f]{64}");
    }

    @Test
    void different_tokens_hash_differently() {
        assertThat(AdminTokens.hash("a".repeat(32))).isNotEqualTo(AdminTokens.hash("b".repeat(32)));
    }

    @Test
    void an_empty_token_never_reaches_the_database() {
        AdminTokens tokens = new AdminTokens(jdbc, "", "");

        assertThat(tokens.resolve(null)).isEmpty();
        assertThat(tokens.resolve("")).isEmpty();
        assertThat(tokens.resolve("   ")).isEmpty();

        verifyNoInteractions(jdbc);
    }

    // --- bootstrap ----------------------------------------------------------

    @Test
    void no_configured_token_registers_nothing() {
        // The admin API is then closed to everything. A missing secret must fail closed: the
        // failure mode of an unset variable should be a locked door, not an open one.
        new AdminTokens(jdbc, "", "").bootstrap();
        new AdminTokens(jdbc, "   ", "   ").bootstrap();

        verifyNoInteractions(jdbc);
    }

    @Test
    void a_short_bootstrap_token_is_refused_rather_than_warned_about() {
        // SHA-256 without stretching is only adequate because the token is high-entropy. This is
        // the check that keeps that assumption true, so it has to stop startup rather than log.
        AdminTokens tokens = new AdminTokens(jdbc, "hunter2", "");

        assertThatThrownBy(tokens::bootstrap)
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("at least");
    }

    @Test
    void the_minimum_length_is_not_quietly_lowered() {
        assertThat(AdminTokens.BOOTSTRAP_MIN_LENGTH).isGreaterThanOrEqualTo(32);
    }

    @Test
    void the_web_tier_gets_a_credential_that_cannot_mutate() {
        // The property worth having: the container rendering the console holds a role that cannot
        // disable a source, so compromising it does not hand over the ingestion pipeline.
        ArgumentCaptor<SqlParameterSource> params = ArgumentCaptor.forClass(SqlParameterSource.class);
        new AdminTokens(jdbc, "o".repeat(64), "v".repeat(64)).bootstrap();

        verify(jdbc, times(2)).update(anyString(), params.capture());
        List<Object> roles =
                params.getAllValues().stream().map(p -> p.getValue("role")).toList();
        assertThat(roles).containsExactly("OPERATOR", "VIEWER");
    }

    @Test
    void a_long_enough_token_is_registered_once() {
        AdminTokens tokens = new AdminTokens(jdbc, "x".repeat(64), "");

        tokens.bootstrap();

        // ON CONFLICT DO NOTHING keyed on the hash, so restarting cannot accumulate rows.
        verify(jdbc)
                .update(
                        anyString(),
                        any(org.springframework.jdbc.core.namedparam.SqlParameterSource.class));
    }

    // --- roles --------------------------------------------------------------

    @Test
    void an_unrecognised_stored_role_grants_nothing() {
        // Defaulting to VIEWER would look safe and still be wrong: it grants read access on a
        // value nobody intended to write.
        assertThat(AdminRole.parse("SUPERUSER")).isEmpty();
        assertThat(AdminRole.parse(null)).isEmpty();
        assertThat(AdminRole.parse("operator")).isEmpty();

        assertThat(AdminRole.parse("OPERATOR")).contains(AdminRole.OPERATOR);
        assertThat(AdminRole.parse("VIEWER")).contains(AdminRole.VIEWER);
    }

    @Test
    void only_operator_may_mutate() {
        assertThat(AdminRole.OPERATOR.canMutate()).isTrue();
        assertThat(AdminRole.VIEWER.canMutate()).isFalse();
    }

    @Test
    void a_principal_carries_no_token() {
        // Not a style point: an object holding the credential is an object that can leak it into a
        // log line or a stack trace.
        for (var component : AdminPrincipal.class.getRecordComponents()) {
            assertThat(component.getName().toLowerCase())
                    .doesNotContain("token")
                    .doesNotContain("secret")
                    .doesNotContain("hash");
        }
        assertThat(Optional.of(new AdminPrincipal(java.util.UUID.randomUUID(), "l", AdminRole.VIEWER)))
                .isPresent();
    }
}
