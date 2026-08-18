package com.aihotradar.coreapi.admin;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.Base64;
import org.junit.jupiter.api.Test;

class GenerationCredentialCipherTest {

    private static final String MASTER_KEY = Base64.getEncoder().encodeToString(new byte[32]);

    @Test
    void encrypts_with_a_fresh_nonce_and_a_stable_non_secret_fingerprint() {
        GenerationCredentialCipher cipher = new GenerationCredentialCipher(MASTER_KEY);

        var first = cipher.encrypt("sk-provider-key");
        var second = cipher.encrypt("sk-provider-key");

        assertThat(first.payload()).startsWith("v1.").doesNotContain("sk-provider-key");
        // A repeated nonce under GCM leaks plaintext relationships, so identical
        // input must still produce different ciphertext.
        assertThat(second.payload()).isNotEqualTo(first.payload());
        assertThat(first.fingerprint()).hasSize(12).isEqualTo(second.fingerprint());
    }

    @Test
    void round_trips_so_the_stored_key_can_be_reused_and_re_verified() {
        GenerationCredentialCipher cipher = new GenerationCredentialCipher(MASTER_KEY);

        assertThat(cipher.decrypt(cipher.encrypt("sk-provider-key").payload()))
                .isEqualTo("sk-provider-key");
    }

    @Test
    void reports_an_unconfigured_deployment_rather_than_storing_plaintext() {
        GenerationCredentialCipher cipher = new GenerationCredentialCipher("");

        assertThat(cipher.configured()).isFalse();
        assertThatThrownBy(() -> cipher.encrypt("sk-provider-key"))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void a_wrong_length_master_key_is_not_silently_accepted() {
        // Base64 of 16 bytes decodes fine and would give AES-128 without anyone
        // noticing; the length check is what makes "AES-256" true.
        String short16 = Base64.getEncoder().encodeToString(new byte[16]);

        assertThat(new GenerationCredentialCipher(short16).configured()).isFalse();
        assertThat(new GenerationCredentialCipher("not-base64!!").configured()).isFalse();
    }

    @Test
    void a_rotated_key_or_a_tampered_envelope_fails_closed() {
        String other = Base64.getEncoder().encodeToString("0123456789abcdef0123456789abcdef".getBytes());
        String stored = new GenerationCredentialCipher(MASTER_KEY).encrypt("sk-provider-key").payload();

        assertThatThrownBy(() -> new GenerationCredentialCipher(other).decrypt(stored))
                .isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> new GenerationCredentialCipher(MASTER_KEY).decrypt("v2.a.b"))
                .isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> new GenerationCredentialCipher(MASTER_KEY).decrypt(null))
                .isInstanceOf(IllegalStateException.class);
    }
}
