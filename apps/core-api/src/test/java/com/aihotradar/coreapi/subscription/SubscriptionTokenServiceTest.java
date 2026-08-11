package com.aihotradar.coreapi.subscription;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class SubscriptionTokenServiceTest {
    private static final Instant NOW = Instant.parse("2026-08-11T12:00:00Z");
    private final SubscriptionTokenService tokens = new SubscriptionTokenService(
            "test-subscription-secret-000000000000000000", Clock.fixed(NOW, ZoneOffset.UTC));

    @Test
    void signed_token_round_trips_without_storing_plaintext() {
        UUID id = UUID.randomUUID();
        Instant expiry = NOW.plus(24, ChronoUnit.HOURS);

        String token = tokens.issue("confirm", id, 3, expiry);
        SubscriptionTokenService.TokenClaims claims = tokens.verify(token, "confirm");

        assertThat(claims.targetId()).isEqualTo(id);
        assertThat(claims.version()).isEqualTo(3);
        assertThat(claims.expiresAt()).isEqualTo(expiry);
        assertThat(token).doesNotContain(id.toString());
    }

    @Test
    void token_is_bound_to_its_action() {
        String token = tokens.issue("confirm", UUID.randomUUID(), 1, NOW.plusSeconds(60));

        assertThatThrownBy(() -> tokens.verify(token, "unsubscribe"))
                .isInstanceOf(InvalidSubscriptionTokenException.class);
    }

    @Test
    void expired_or_tampered_token_is_rejected() {
        String expired = tokens.issue("confirm", UUID.randomUUID(), 1, NOW.minusSeconds(1));
        String valid = tokens.issue("confirm", UUID.randomUUID(), 1, NOW.plusSeconds(60));
        String tampered = valid.substring(0, valid.length() - 1) + (valid.endsWith("A") ? "B" : "A");

        assertThatThrownBy(() -> tokens.verify(expired, "confirm"))
                .isInstanceOf(InvalidSubscriptionTokenException.class);
        assertThatThrownBy(() -> tokens.verify(tampered, "confirm"))
                .isInstanceOf(InvalidSubscriptionTokenException.class);
    }

    @Test
    void weak_secret_is_refused_at_startup() {
        assertThatThrownBy(() -> new SubscriptionTokenService("too-short", Clock.systemUTC()))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
