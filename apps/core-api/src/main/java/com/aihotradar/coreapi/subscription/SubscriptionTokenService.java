package com.aihotradar.coreapi.subscription;

import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

@Service
public class SubscriptionTokenService {
    private static final String HMAC_ALGORITHM = "HmacSHA256";
    private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();
    private static final Base64.Decoder DECODER = Base64.getUrlDecoder();

    private final byte[] secret;
    private final Clock clock;

    @Autowired
    public SubscriptionTokenService(
            @Value("${ahr.subscription.token-secret}") String secret) {
        this(secret, Clock.systemUTC());
    }

    SubscriptionTokenService(String secret, Clock clock) {
        if (secret == null || secret.length() < 32) {
            throw new IllegalArgumentException("subscription token secret must be at least 32 characters");
        }
        this.secret = secret.getBytes(StandardCharsets.UTF_8);
        this.clock = clock;
    }

    public String issue(String action, UUID targetId, int version, Instant expiresAt) {
        String payload = action + "|" + targetId + "|" + version + "|" + expiresAt.getEpochSecond();
        byte[] payloadBytes = payload.getBytes(StandardCharsets.UTF_8);
        return ENCODER.encodeToString(payloadBytes) + "." + ENCODER.encodeToString(sign(payloadBytes));
    }

    public TokenClaims verify(String token, String expectedAction) {
        try {
            String[] parts = token == null ? new String[0] : token.split("\\.", -1);
            if (parts.length != 2) {
                throw new InvalidSubscriptionTokenException();
            }
            byte[] payload = DECODER.decode(parts[0]);
            byte[] providedSignature = DECODER.decode(parts[1]);
            if (!ENCODER.encodeToString(payload).equals(parts[0])
                    || !ENCODER.encodeToString(providedSignature).equals(parts[1])
                    || !MessageDigest.isEqual(sign(payload), providedSignature)) {
                throw new InvalidSubscriptionTokenException();
            }

            String[] fields = new String(payload, StandardCharsets.UTF_8).split("\\|", -1);
            if (fields.length != 4 || !MessageDigest.isEqual(
                    fields[0].getBytes(StandardCharsets.UTF_8),
                    expectedAction.getBytes(StandardCharsets.UTF_8))) {
                throw new InvalidSubscriptionTokenException();
            }

            UUID targetId = UUID.fromString(fields[1]);
            int version = Integer.parseInt(fields[2]);
            Instant expiresAt = Instant.ofEpochSecond(Long.parseLong(fields[3]));
            if (version < 1 || !expiresAt.isAfter(clock.instant())) {
                throw new InvalidSubscriptionTokenException();
            }
            return new TokenClaims(targetId, version, expiresAt);
        } catch (IllegalArgumentException exception) {
            throw new InvalidSubscriptionTokenException();
        }
    }

    private byte[] sign(byte[] payload) {
        try {
            Mac mac = Mac.getInstance(HMAC_ALGORITHM);
            mac.init(new SecretKeySpec(secret, HMAC_ALGORITHM));
            return mac.doFinal(payload);
        } catch (NoSuchAlgorithmException | InvalidKeyException exception) {
            throw new IllegalStateException("HMAC-SHA256 is unavailable", exception);
        }
    }

    public record TokenClaims(UUID targetId, int version, Instant expiresAt) {}
}
