package com.aihotradar.coreapi.admin;

import java.net.URI;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** The generation provider's address and key, editable from the console (V027). */
@Service
public class GenerationProviderService {

    /** What the seeded row holds, and what "fall back to the environment" writes back. */
    static final String ENVIRONMENT_MARKER = "env://LLM_BASE_URL";

    private final NamedParameterJdbcTemplate jdbc;
    private final GenerationCredentialCipher cipher;
    private final GenerationProviderProbe probe;

    public GenerationProviderService(
            NamedParameterJdbcTemplate jdbc,
            GenerationCredentialCipher cipher,
            GenerationProviderProbe probe) {
        this.jdbc = jdbc;
        this.cipher = cipher;
        this.probe = probe;
    }

    /** Never includes the key. `keyFingerprint` is what identifies it. */
    public Map<String, Object> state() {
        Map<String, Object> row =
                jdbc.queryForMap(
                        """
                        SELECT base_url, key_fingerprint, version, updated_at
                          FROM generation_provider_config
                         WHERE singleton_key = 1
                        """,
                        Map.of());
        String baseUrl = String.valueOf(row.get("base_url"));
        boolean fromEnvironment = ENVIRONMENT_MARKER.equals(baseUrl);

        Map<String, Object> state = new LinkedHashMap<>();
        // The marker is an implementation detail of the seed row; the console shows an empty
        // address and a badge instead, because "env://LLM_BASE_URL" is not somewhere anyone typed.
        state.put("baseUrl", fromEnvironment ? "" : baseUrl);
        state.put("usesEnvironment", fromEnvironment);
        state.put("keyFingerprint", row.get("key_fingerprint"));
        state.put("keyFromEnvironment", row.get("key_fingerprint") == null);
        state.put("version", row.get("version"));
        state.put("updatedAt", row.get("updated_at"));
        // Surfaced so the console can say "this deployment cannot store a key" up front, rather
        // than letting the operator type one and fail at save.
        state.put("credentialStorageReady", cipher.configured());
        return state;
    }

    /**
     * Verify, then store.
     *
     * <p>Order matters: nothing is written unless the provider accepted the pair, so a mistyped key
     * leaves the running configuration untouched instead of taking generation down until someone
     * notices.
     *
     * <p>An absent key means "keep the stored one" — so the address can be corrected without
     * re-pasting a credential — but only when there is a stored one to keep. While the row still
     * points at the environment, Core API holds no copy of the key and cannot verify anything, so
     * the first save has to supply it.
     */
    @Transactional
    public Map<String, Object> update(String baseUrl, String apiKey, AdminPrincipal principal) {
        String address = baseUrl == null ? "" : baseUrl.strip();
        // Password managers and chat clients paste trailing whitespace into key fields, and a
        // provider rejects the result as an invalid credential rather than as a formatting problem.
        String suppliedKey = apiKey == null ? "" : apiKey.strip();
        validateAddress(address);

        String storedCiphertext =
                jdbc.queryForObject(
                        """
                        SELECT api_key_ciphertext FROM generation_provider_config
                         WHERE singleton_key = 1
                        """,
                        Map.of(),
                        String.class);

        String effectiveKey;
        if (!suppliedKey.isEmpty()) {
            effectiveKey = suppliedKey;
        } else if (storedCiphertext != null) {
            effectiveKey = cipher.decrypt(storedCiphertext);
        } else {
            throw new IllegalArgumentException("api_key_required");
        }

        probe.verify(address, effectiveKey);

        GenerationCredentialCipher.EncryptedCredential sealed = cipher.encrypt(effectiveKey);
        jdbc.update(
                """
                UPDATE generation_provider_config
                   SET base_url = :baseUrl,
                       api_key_ciphertext = :ciphertext,
                       key_fingerprint = :fingerprint,
                       version = version + 1,
                       updated_by = :principalId,
                       updated_at = now()
                 WHERE singleton_key = 1
                """,
                new MapSqlParameterSource()
                        .addValue("baseUrl", address)
                        .addValue("ciphertext", sealed.payload())
                        .addValue("fingerprint", sealed.fingerprint())
                        .addValue("principalId", principal.id()));
        return state();
    }

    /**
     * Hand the provider back to {@code LLM_BASE_URL} / {@code LLM_API_KEY}.
     *
     * <p>The console's undo. Without it an operator who saves a wrong address has no way back
     * except editing the database by hand, which is exactly the situation this page exists to end.
     */
    @Transactional
    public Map<String, Object> resetToEnvironment(AdminPrincipal principal) {
        jdbc.update(
                """
                UPDATE generation_provider_config
                   SET base_url = :marker,
                       api_key_ciphertext = NULL,
                       key_fingerprint = NULL,
                       version = version + 1,
                       updated_by = :principalId,
                       updated_at = now()
                 WHERE singleton_key = 1
                """,
                new MapSqlParameterSource()
                        .addValue("marker", ENVIRONMENT_MARKER)
                        .addValue("principalId", principal.id()));
        return state();
    }

    private static void validateAddress(String address) {
        if (address.isEmpty() || address.length() > 500) {
            throw new IllegalArgumentException("invalid_provider_url");
        }
        try {
            URI uri = URI.create(address);
            boolean http =
                    "https".equalsIgnoreCase(uri.getScheme())
                            || "http".equalsIgnoreCase(uri.getScheme());
            // Credentials in the URL would be logged by every proxy on the way and stored in a
            // column that is deliberately not the encrypted one.
            if (!http || uri.getHost() == null || uri.getUserInfo() != null) {
                throw new IllegalArgumentException("invalid_provider_url");
            }
        } catch (RuntimeException malformed) {
            throw new IllegalArgumentException("invalid_provider_url", malformed);
        }
    }
}
