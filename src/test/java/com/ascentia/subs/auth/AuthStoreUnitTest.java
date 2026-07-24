package com.ascentia.subs.auth;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AuthStoreUnitTest {

    @Test
    void verifyPasswordAcceptsOnlyCurrentScryptEncodings() {
        String password = "letters123456";
        String encoded = AuthStore.hashPassword(password);

        assertThat(AuthStore.verifyPassword(password, encoded)).isTrue();
        assertThat(AuthStore.verifyPassword("wrong-password123", encoded)).isFalse();
        assertThat(AuthStore.verifyPassword(password, null)).isFalse();
        assertThat(AuthStore.verifyPassword(password, " ")).isFalse();
        assertThat(AuthStore.verifyPassword(password, "scrypt$bad")).isFalse();
        assertThat(AuthStore.verifyPassword(password, "scrypt$16384$8$1$zz$11")).isFalse();
        String salt = "00".repeat(16);
        String digest = "00".repeat(64);
        assertThat(AuthStore.verifyPassword(password, "scrypt$32768$8$1$" + salt + "$" + digest)).isFalse();
        assertThat(AuthStore.verifyPassword(password, "scrypt$16384$9$1$" + salt + "$" + digest)).isFalse();
        assertThat(AuthStore.verifyPassword(password, "scrypt$16384$8$2$" + salt + "$" + digest)).isFalse();
        assertThat(AuthStore.verifyPassword(password, "scrypt$16384$8$1$00$" + digest)).isFalse();
        assertThat(AuthStore.verifyPassword(password, "scrypt$16384$8$1$" + salt + "$00")).isFalse();
        assertThat(AuthStore.verifyPassword(password, "old-password-encoding")).isFalse();
        assertThat(AuthStore.verifyPassword(password, "salty$untrusted-sha256-digest")).isFalse();
    }

    @Test
    void hashTokenIsStableAndSensitiveToInput() {
        assertThat(AuthStore.hashToken("token-a"))
                .hasSize(64)
                .isEqualTo(AuthStore.hashToken("token-a"))
                .isNotEqualTo(AuthStore.hashToken("token-b"));
    }
}
