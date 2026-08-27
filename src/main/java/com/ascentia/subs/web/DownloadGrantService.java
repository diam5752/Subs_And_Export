package com.ascentia.subs.web;

import com.ascentia.subs.config.AppProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

@Service
public class DownloadGrantService {

    private static final String DEV_SECRET = "gsubs-dev-only-download-grant-secret-not-for-production";
    private static final Set<String> CLAIM_KEYS = Set.of("exp", "iat", "name", "path", "uid", "v");
    private static final int VERSION = 1;
    private static final int MAX_TOKEN_LENGTH = 4_096;

    private final ObjectMapper objectMapper;
    private final byte[] secret;
    private final int ttlSeconds;
    private final Clock clock;

    @Autowired
    public DownloadGrantService(AppProperties properties, ObjectMapper objectMapper) {
        this(properties, objectMapper, Clock.systemUTC());
    }

    DownloadGrantService(AppProperties properties, ObjectMapper objectMapper, Clock clock) {
        this.objectMapper = objectMapper;
        this.clock = clock;
        this.ttlSeconds = properties.getDownloadGrantTtlSeconds();
        if (ttlSeconds < 60 || ttlSeconds > 600) {
            throw new IllegalStateException("Download grant TTL must be between 60 and 600 seconds");
        }
        String configured = properties.getDownloadGrantSecret();
        if (configured == null || configured.getBytes(StandardCharsets.UTF_8).length < 32) {
            if (!properties.isDev()) {
                throw new IllegalStateException("GSP_DOWNLOAD_GRANT_SECRET must contain at least 32 bytes");
            }
            configured = DEV_SECRET;
        }
        this.secret = configured.getBytes(StandardCharsets.UTF_8);
    }

    public IssuedGrant issue(String userId, String filePath, String filename) {
        validateClaim(userId, "user", 128);
        validateFilePath(filePath);
        validateClaim(filename, "filename", 255);
        long issuedAt = Instant.now(clock).getEpochSecond();
        Map<String, Object> payload = new TreeMap<>();
        payload.put("exp", issuedAt + ttlSeconds);
        payload.put("iat", issuedAt);
        payload.put("name", filename);
        payload.put("path", filePath);
        payload.put("uid", userId);
        payload.put("v", VERSION);
        try {
            String encodedPayload = encode(objectMapper.writeValueAsBytes(payload));
            String signature = encode(sign(encodedPayload));
            return new IssuedGrant(encodedPayload + "." + signature, ttlSeconds);
        } catch (java.io.IOException exception) {
            throw new IllegalStateException("Could not encode download grant", exception);
        }
    }

    public Claims validate(String token, String expectedFilePath) {
        validateFilePath(expectedFilePath);
        if (token == null || token.isBlank() || token.length() > MAX_TOKEN_LENGTH || token.chars().filter(character -> character == '.').count() != 1) {
            throw new IllegalArgumentException("Download grant is malformed");
        }
        String[] parts = token.split("\\.", -1);
        if (!parts[0].matches("[A-Za-z0-9_-]+")) {
            throw new IllegalArgumentException("Download grant encoding is invalid");
        }
        byte[] suppliedSignature = decode(parts[1]);
        byte[] expectedSignature = sign(parts[0]);
        if (!MessageDigest.isEqual(suppliedSignature, expectedSignature)) {
            throw new IllegalArgumentException("Download grant signature is invalid");
        }

        try {
            JsonNode payload = objectMapper.readTree(decode(parts[0]));
            Set<String> payloadKeys = new HashSet<>();
            payload.fieldNames().forEachRemaining(payloadKeys::add);
            if (!payload.isObject()
                    || !CLAIM_KEYS.equals(payloadKeys)
                    || !payload.path("v").isIntegralNumber()
                    || payload.path("v").intValue() != VERSION
                    || !payload.path("iat").isIntegralNumber()
                    || !payload.path("exp").isIntegralNumber()
                    || !payload.path("uid").isTextual()
                    || !payload.path("path").isTextual()
                    || !payload.path("name").isTextual()) {
                throw new IllegalArgumentException("Download grant claims are invalid");
            }
            long issuedAt = payload.path("iat").longValue();
            long expiresAt = payload.path("exp").longValue();
            String userId = payload.path("uid").textValue();
            String filePath = payload.path("path").textValue();
            String filename = payload.path("name").textValue();
            validateClaim(userId, "user", 128);
            validateFilePath(filePath);
            validateClaim(filename, "filename", 255);
            if (!MessageDigest.isEqual(filePath.getBytes(StandardCharsets.UTF_8), expectedFilePath.getBytes(StandardCharsets.UTF_8))) {
                throw new IllegalArgumentException("Download grant is for a different artifact");
            }
            if (expiresAt - issuedAt != ttlSeconds) {
                throw new IllegalArgumentException("Download grant timing is invalid");
            }
            long now = Instant.now(clock).getEpochSecond();
            if (issuedAt > now + 30 || now >= expiresAt) {
                throw new IllegalArgumentException("Download grant has expired");
            }
            return new Claims(userId, filePath, filename, issuedAt, expiresAt);
        } catch (java.io.IOException exception) {
            throw new IllegalArgumentException("Download grant payload is invalid", exception);
        }
    }

    private byte[] sign(String encodedPayload) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret, "HmacSHA256"));
            return mac.doFinal(encodedPayload.getBytes(StandardCharsets.US_ASCII));
        } catch (GeneralSecurityException exception) {
            throw new IllegalStateException("HMAC-SHA256 is unavailable", exception);
        }
    }

    private static String encode(byte[] value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value);
    }

    private static byte[] decode(String value) {
        if (value == null || value.isBlank() || !value.matches("[A-Za-z0-9_-]+")) {
            throw new IllegalArgumentException("Download grant encoding is invalid");
        }
        try {
            return Base64.getUrlDecoder().decode(value);
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Download grant encoding is invalid", exception);
        }
    }

    private static void validateFilePath(String filePath) {
        if (filePath == null || filePath.isBlank() || filePath.length() > 1_024 || filePath.contains("\\")) {
            throw new IllegalArgumentException("Download grant path is invalid");
        }
        String[] parts = filePath.split("/", -1);
        if (parts.length < 3 || !"artifacts".equals(parts[0])) {
            throw new IllegalArgumentException("Download grant path is invalid");
        }
        for (String part : parts) {
            if (part.isBlank() || ".".equals(part) || "..".equals(part) || hasControlCharacter(part)) {
                throw new IllegalArgumentException("Download grant path is invalid");
            }
        }
    }

    private static void validateClaim(String value, String label, int maximumLength) {
        if (value == null || value.isBlank() || value.length() > maximumLength || hasControlCharacter(value)) {
            throw new IllegalArgumentException("Download grant " + label + " is invalid");
        }
    }

    private static boolean hasControlCharacter(String value) {
        return value.chars().anyMatch(character -> character < 32 || character == 127);
    }

    public record IssuedGrant(String token, int expiresIn) {
    }

    public record Claims(String userId, String filePath, String filename, long issuedAt, long expiresAt) {
    }
}
