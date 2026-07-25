package com.ascentia.subs.auth;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;

class GoogleAvatarUrlTest {

    @Test
    void acceptsOnlyTheGoogleProfileImageHostOverHttps() {
        assertThat(GoogleAvatarUrl.normalize(
                "https://lh3.googleusercontent.com/a/avatar=s96-c"
        )).isEqualTo("https://lh3.googleusercontent.com/a/avatar=s96-c");
        assertThat(GoogleAvatarUrl.normalize(
                "https://lh3.googleusercontent.com:443/a/avatar=s96-c"
        )).isEqualTo("https://lh3.googleusercontent.com:443/a/avatar=s96-c");
        assertThat(GoogleAvatarUrl.normalize(
                " HTTPS://LH3.GOOGLEUSERCONTENT.COM/a/avatar "
        )).isEqualTo("HTTPS://LH3.GOOGLEUSERCONTENT.COM/a/avatar");
    }

    @Test
    void dropsMissingAndOversizedValues() {
        assertThat(GoogleAvatarUrl.normalize(null)).isNull();
        assertThat(GoogleAvatarUrl.normalize(" ")).isNull();
        assertThat(GoogleAvatarUrl.normalize("x".repeat(2_049))).isNull();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "http://lh3.googleusercontent.com/a/avatar",
            "https://evil.example/a/avatar",
            "https://user@lh3.googleusercontent.com/a/avatar",
            "https://lh3.googleusercontent.com:444/a/avatar",
            "https://lh3.googleusercontent.com",
            "https://lh3.googleusercontent.com/a/avatar#tracking",
            "https://lh3.googleusercontent.com/%zz",
            "not-a-url"
    })
    void dropsUnsafeOrMalformedValues(String value) {
        assertThat(GoogleAvatarUrl.normalize(value)).isNull();
    }
}
