package com.ascentia.subs.web;

import com.ascentia.subs.config.AppProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class DownloadGrantServiceTest {

    private static final String FILE_PATH = "artifacts/job-1/processed_720x1280.mp4";
    private static final String SECRET = "g".repeat(64);
    private static final Instant ISSUED_AT = Instant.ofEpochSecond(1_800_000_000L);

    @Test
    void grantIsExactTamperEvidentAndShortLived() {
        AppProperties properties = configuredProperties();
        DownloadGrantService issuer = new DownloadGrantService(
                properties,
                new ObjectMapper(),
                Clock.fixed(ISSUED_AT, ZoneOffset.UTC)
        );

        DownloadGrantService.IssuedGrant issued = issuer.issue(
                "user-1",
                FILE_PATH,
                "Δοκιμή_subs.mp4"
        );
        DownloadGrantService.Claims claims = issuer.validate(issued.token(), FILE_PATH);

        assertThat(issued.expiresIn()).isEqualTo(300);
        assertThat(claims.userId()).isEqualTo("user-1");
        assertThat(claims.filename()).isEqualTo("Δοκιμή_subs.mp4");
        assertThat(claims.expiresAt()).isEqualTo(1_800_000_300L);
        assertThatThrownBy(() -> issuer.validate(issued.token(), "artifacts/job-1/other.mp4"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("different artifact");

        String[] parts = issued.token().split("\\.", -1);
        String tampered = parts[0] + "." + (parts[1].startsWith("a") ? "b" : "a") + parts[1].substring(1);
        assertThatThrownBy(() -> issuer.validate(tampered, FILE_PATH))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("signature");

        DownloadGrantService expiredValidator = new DownloadGrantService(
                properties,
                new ObjectMapper(),
                Clock.fixed(ISSUED_AT.plusSeconds(300), ZoneOffset.UTC)
        );
        assertThatThrownBy(() -> expiredValidator.validate(issued.token(), FILE_PATH))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("expired");
    }

    @Test
    void productionRejectsAMissingOrShortSigningSecret() {
        AppProperties properties = new AppProperties();
        properties.setEnv("production");
        properties.setDownloadGrantSecret("short");

        assertThatThrownBy(() -> new DownloadGrantService(properties, new ObjectMapper()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("GSP_DOWNLOAD_GRANT_SECRET");
    }

    @Test
    void rejectsUnsafeConfigurationAndEveryNonCanonicalClaimShape() {
        AppProperties lowTtl = configuredProperties();
        lowTtl.setDownloadGrantTtlSeconds(59);
        assertThatThrownBy(() -> new DownloadGrantService(lowTtl, new ObjectMapper()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("TTL");

        AppProperties highTtl = configuredProperties();
        highTtl.setDownloadGrantTtlSeconds(601);
        assertThatThrownBy(() -> new DownloadGrantService(highTtl, new ObjectMapper()))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("TTL");

        AppProperties fallbackProperties = configuredProperties();
        fallbackProperties.setDownloadGrantSecret(null);
        DownloadGrantService fallback = new DownloadGrantService(
                fallbackProperties,
                new ObjectMapper(),
                Clock.fixed(ISSUED_AT, ZoneOffset.UTC)
        );
        assertThat(fallback.issue("user-1", FILE_PATH, "video.mp4").token()).isNotBlank();

        DownloadGrantService service = fixedService();
        String[] invalidUsers = {null, "", " ", "u".repeat(129), "bad\nuser"};
        for (String user : invalidUsers) {
            assertThatThrownBy(() -> service.issue(user, FILE_PATH, "video.mp4"))
                    .isInstanceOf(IllegalArgumentException.class);
        }
        String[] invalidNames = {null, "", " ", "n".repeat(256), "bad\rname.mp4"};
        for (String name : invalidNames) {
            assertThatThrownBy(() -> service.issue("user-1", FILE_PATH, name))
                    .isInstanceOf(IllegalArgumentException.class);
        }
        String[] invalidPaths = {
                null,
                "",
                " ",
                "a".repeat(1_025),
                "artifacts\\job-1\\video.mp4",
                "artifacts/job-1",
                "uploads/job-1/video.mp4",
                "artifacts//video.mp4",
                "artifacts/./video.mp4",
                "artifacts/../video.mp4",
                "artifacts/job-1/bad\nvideo.mp4"
        };
        for (String path : invalidPaths) {
            assertThatThrownBy(() -> service.issue("user-1", path, "video.mp4"))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test
    void rejectsEveryMalformedTokenEnvelope() {
        DownloadGrantService service = fixedService();
        String valid = service.issue("user-1", FILE_PATH, "video.mp4").token();
        String payload = valid.substring(0, valid.indexOf('.'));
        String[] malformed = {
                null,
                "",
                " ",
                "x".repeat(4_097),
                "one.two.three",
                "💥.signature",
                payload + ".",
                payload + ".*",
                payload + ".A"
        };
        for (String token : malformed) {
            assertThatThrownBy(() -> service.validate(token, FILE_PATH))
                    .isInstanceOf(IllegalArgumentException.class);
        }
    }

    @Test
    void rejectsSignedPayloadsWithWrongSchemaClaimsOrTiming() throws Exception {
        DownloadGrantService service = fixedService();

        assertRejected(service, signedJson("[]"));
        assertRejected(service, signedPayload(Map.of(
                "exp", 1_800_000_300L,
                "iat", 1_800_000_000L,
                "name", "video.mp4",
                "path", FILE_PATH,
                "uid", "user-1",
                "v", 1,
                "extra", true
        )));

        for (Map.Entry<String, ?> mutation : List.of(
                Map.entry("v", "1"),
                Map.entry("v", 2),
                Map.entry("iat", "now"),
                Map.entry("exp", "later"),
                Map.entry("uid", 123),
                Map.entry("path", 123),
                Map.entry("name", 123),
                Map.entry("uid", ""),
                Map.entry("uid", "u".repeat(129)),
                Map.entry("uid", "bad\nuser"),
                Map.entry("path", "uploads/job-1/video.mp4"),
                Map.entry("name", ""),
                Map.entry("name", "n".repeat(256)),
                Map.entry("name", "bad\rname.mp4"),
                Map.entry("exp", 1_800_000_301L)
        )) {
            Map<String, Object> payload = validPayload();
            payload.put(mutation.getKey(), mutation.getValue());
            assertRejected(service, signedPayload(payload));
        }

        Map<String, Object> future = validPayload();
        future.put("iat", 1_800_000_031L);
        future.put("exp", 1_800_000_331L);
        assertRejected(service, signedPayload(future));

        assertRejected(service, signedBytes(new byte[]{(byte) 0xC3, (byte) 0x28}));
    }

    private static void assertRejected(DownloadGrantService service, String token) {
        assertThatThrownBy(() -> service.validate(token, FILE_PATH))
                .isInstanceOf(IllegalArgumentException.class);
    }

    private static Map<String, Object> validPayload() {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("exp", 1_800_000_300L);
        payload.put("iat", 1_800_000_000L);
        payload.put("name", "video.mp4");
        payload.put("path", FILE_PATH);
        payload.put("uid", "user-1");
        payload.put("v", 1);
        return payload;
    }

    private static String signedPayload(Map<String, Object> payload) throws Exception {
        return signedBytes(new ObjectMapper().writeValueAsBytes(payload));
    }

    private static String signedJson(String json) throws Exception {
        return signedBytes(json.getBytes(StandardCharsets.UTF_8));
    }

    private static String signedBytes(byte[] payload) throws Exception {
        String encodedPayload = Base64.getUrlEncoder().withoutPadding().encodeToString(payload);
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(SECRET.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        String signature = Base64.getUrlEncoder().withoutPadding().encodeToString(
                mac.doFinal(encodedPayload.getBytes(StandardCharsets.US_ASCII))
        );
        return encodedPayload + "." + signature;
    }

    private static DownloadGrantService fixedService() {
        return new DownloadGrantService(
                configuredProperties(),
                new ObjectMapper(),
                Clock.fixed(ISSUED_AT, ZoneOffset.UTC)
        );
    }

    private static AppProperties configuredProperties() {
        AppProperties properties = new AppProperties();
        properties.setEnv("dev");
        properties.setDownloadGrantSecret(SECRET);
        properties.setDownloadGrantTtlSeconds(300);
        return properties;
    }
}
