package com.ascentia.subs.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AuthStoreUnitTest {

    @Test
    void verifyPasswordSupportsScryptLegacyAndMalformedEncodings() {
        String password = "letters123456";
        String encoded = AuthStore.hashPassword(password);

        assertThat(AuthStore.verifyPassword(password, encoded)).isTrue();
        assertThat(AuthStore.verifyPassword("wrong-password123", encoded)).isFalse();
        assertThat(AuthStore.verifyPassword(password, null)).isFalse();
        assertThat(AuthStore.verifyPassword(password, " ")).isFalse();
        assertThat(AuthStore.verifyPassword(password, "scrypt$bad")).isFalse();
        assertThat(AuthStore.verifyPassword(password, "scrypt$16384$8$1$zz$11")).isFalse();
        assertThat(AuthStore.verifyPassword(password, "legacy-without-delimiter")).isFalse();

        String salt = "salty";
        String legacy = salt + "$" + sha256Hex(salt + ":" + password);
        assertThat(AuthStore.verifyPassword(password, legacy)).isTrue();
        assertThat(AuthStore.verifyPassword("other-password123", legacy)).isFalse();
    }

    @Test
    void hashTokenIsStableAndSensitiveToInput() {
        assertThat(AuthStore.hashToken("token-a"))
                .hasSize(64)
                .isEqualTo(AuthStore.hashToken("token-a"))
                .isNotEqualTo(AuthStore.hashToken("token-b"));
    }

    private static String sha256Hex(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception exception) {
            throw new IllegalStateException(exception);
        }
    }
}
