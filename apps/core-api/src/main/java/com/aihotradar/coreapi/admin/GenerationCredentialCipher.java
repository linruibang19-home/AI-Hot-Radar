package com.aihotradar.coreapi.admin;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;
import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * AES-256-GCM envelope for the generation provider's API key.
 *
 * <p>The key has to reach PostgreSQL for the console to be able to change it, and it has to reach
 * AI Service to be usable — so it cannot be hashed, only encrypted. The master key stays in the
 * environment, which means a database dump on its own decrypts to nothing.
 *
 * <p>GCM rather than CBC: the key is read back and sent to a provider, so a silently corrupted or
 * tampered ciphertext must fail loudly rather than produce plausible bytes that then leak into an
 * outbound request.
 *
 * <p>The fingerprint is the first 12 hex characters of SHA-256. It exists so the console can show
 * <em>which</em> key is stored without being able to show the key, and so two operators can agree
 * they are looking at the same credential.
 */
@Component
public class GenerationCredentialCipher {

    private static final int NONCE_BYTES = 12;
    private static final int TAG_BITS = 128;
    private static final SecureRandom RANDOM = new SecureRandom();

    private final byte[] key;

    public GenerationCredentialCipher(
            @Value("${ahr.llm-credential-master-key:}") String masterKey) {
        this.key = decodeMasterKey(masterKey);
    }

    private static byte[] decodeMasterKey(String masterKey) {
        if (masterKey == null || masterKey.isBlank()) {
            return new byte[0];
        }
        try {
            return Base64.getDecoder().decode(masterKey.trim());
        } catch (IllegalArgumentException notBase64) {
            return new byte[0];
        }
    }

    /** Whether this deployment can store a credential at all. */
    public boolean configured() {
        return key.length == 32;
    }

    public EncryptedCredential encrypt(String plaintext) {
        requireConfigured();
        try {
            byte[] nonce = new byte[NONCE_BYTES];
            RANDOM.nextBytes(nonce);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(
                    Cipher.ENCRYPT_MODE,
                    new SecretKeySpec(key, "AES"),
                    new GCMParameterSpec(TAG_BITS, nonce));
            byte[] sealed = cipher.doFinal(plaintext.getBytes(StandardCharsets.UTF_8));
            Base64.Encoder encoder = Base64.getUrlEncoder().withoutPadding();
            return new EncryptedCredential(
                    "v1." + encoder.encodeToString(nonce) + "." + encoder.encodeToString(sealed),
                    fingerprint(plaintext));
        } catch (GeneralSecurityException failure) {
            throw new IllegalStateException("could not encrypt the generation credential", failure);
        }
    }

    public String decrypt(String payload) {
        requireConfigured();
        try {
            String[] parts = payload == null ? new String[0] : payload.split("\\.", 3);
            if (parts.length != 3 || !"v1".equals(parts[0])) {
                throw new IllegalStateException("unsupported credential envelope");
            }
            Base64.Decoder decoder = Base64.getUrlDecoder();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(
                    Cipher.DECRYPT_MODE,
                    new SecretKeySpec(key, "AES"),
                    new GCMParameterSpec(TAG_BITS, decoder.decode(parts[1])));
            return new String(cipher.doFinal(decoder.decode(parts[2])), StandardCharsets.UTF_8);
        } catch (GeneralSecurityException | IllegalArgumentException failure) {
            // A rotated master key and a corrupted envelope are the same thing from the operator's
            // side — this deployment cannot read its own credential store — and distinguishing them
            // in the response would mostly tell an attacker which one they are looking at.
            throw new IllegalStateException("could not decrypt the generation credential", failure);
        }
    }

    private void requireConfigured() {
        if (!configured()) {
            throw new IllegalStateException(
                    "LLM_CREDENTIAL_MASTER_KEY is not a 32-byte base64 value");
        }
    }

    /** Non-reversible, and short enough to read aloud. Never derived from the ciphertext. */
    public static String fingerprint(String plaintext) {
        try {
            byte[] digest =
                    MessageDigest.getInstance("SHA-256")
                            .digest(plaintext.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest).substring(0, 12);
        } catch (GeneralSecurityException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }

    public record EncryptedCredential(String payload, String fingerprint) {}
}
