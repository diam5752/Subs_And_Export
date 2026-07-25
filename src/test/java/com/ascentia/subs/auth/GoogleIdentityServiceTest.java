package com.ascentia.subs.auth;

import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class GoogleIdentityServiceTest {

    @Test
    void verifiesAudienceIssuerExpiryEmailSubjectAndNonce() {
        JwtDecoder decoder = mock(JwtDecoder.class);
        GoogleIdentityService service = service(decoder);
        String nonce = service.createNonce();
        Jwt jwt = validJwt(nonce);
        when(decoder.decode("signed-token")).thenReturn(jwt);

        GoogleIdentityService.GoogleProfile profile = service.verify(
                "signed-token",
                service.nonceHash(nonce),
                true
        );

        assertThat(profile.email()).isEqualTo("user@example.com");
        assertThat(profile.name()).isEqualTo("Google User");
        assertThat(profile.subject()).isEqualTo("google-subject");
    }

    @Test
    void rejectsInvalidClaimsAndProviderFailuresWithSafeMessages() {
        JwtDecoder decoder = mock(JwtDecoder.class);
        GoogleIdentityService service = service(decoder);
        when(decoder.decode("bad-signature")).thenThrow(new JwtException("provider detail"));
        when(decoder.decode("wrong-issuer")).thenReturn(
                jwtBuilder("nonce").claim("iss", "https://evil.example").build()
        );
        when(decoder.decode("unverified")).thenReturn(
                jwtBuilder("nonce").claim("email_verified", false).build()
        );

        assertThatThrownBy(() -> service.verify("bad-signature", null, false))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Google token could not be verified")
                .hasMessageNotContaining("provider detail");
        assertThatThrownBy(() -> service.verify("wrong-issuer", null, false))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("issuer");
        assertThatThrownBy(() -> service.verify("unverified", null, false))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("verified");
    }

    @Test
    void rejectsMissingOrMismatchedNonceAndMissingConfiguration() {
        JwtDecoder decoder = mock(JwtDecoder.class);
        GoogleIdentityService service = service(decoder);
        when(decoder.decode("signed-token")).thenReturn(validJwt("actual-nonce"));

        assertThatThrownBy(() -> service.verify("signed-token", null, true))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("nonce is required");
        assertThatThrownBy(() -> service.verify(
                "signed-token",
                service.nonceHash("expected-nonce"),
                true
        )).isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("nonce could not be verified");

        GoogleIdentityService unconfigured = new GoogleIdentityService(
                new MockEnvironment(),
                decoder
        );
        assertThatThrownBy(unconfigured::clientId)
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("not configured");
        GoogleIdentityService blankConfiguration = new GoogleIdentityService(
                new MockEnvironment().withProperty("GOOGLE_CLIENT_ID", " "),
                decoder
        );
        assertThatThrownBy(blankConfiguration::clientId)
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("not configured");
    }

    @Test
    void rejectsMalformedTokenAndIdentityClaims() {
        JwtDecoder decoder = mock(JwtDecoder.class);
        GoogleIdentityService service = service(decoder);
        when(decoder.decode("wrong-audience")).thenReturn(
                jwtBuilder("nonce").claim("aud", List.of("other-client")).build()
        );
        when(decoder.decode("multiple-audiences")).thenReturn(
                jwtBuilder("nonce").claim(
                        "aud",
                        List.of("google-client", "other-client")
                ).build()
        );
        when(decoder.decode("missing-subject")).thenReturn(
                jwtBuilder("nonce").subject("").build()
        );
        when(decoder.decode("long-subject")).thenReturn(
                jwtBuilder("nonce").subject("s".repeat(256)).build()
        );
        when(decoder.decode("missing-expiry")).thenReturn(
                jwtBuilderWithoutExpiry("nonce").build()
        );
        when(decoder.decode("expired")).thenReturn(
                jwtBuilder("nonce").expiresAt(Instant.now().minusSeconds(1)).build()
        );
        when(decoder.decode("invalid-email")).thenReturn(
                jwtBuilder("nonce").claim("email", "not-an-email").build()
        );
        when(decoder.decode("long-email")).thenReturn(
                jwtBuilder("nonce").claim(
                        "email",
                        "a".repeat(250) + "@example.com"
                ).build()
        );

        assertThatThrownBy(() -> service.verify(null, null, false))
                .hasMessageContaining("required");
        assertThatThrownBy(() -> service.verify(" ", null, false))
                .hasMessageContaining("required");
        assertThatThrownBy(() -> service.verify("x".repeat(16_385), null, false))
                .hasMessageContaining("too large");
        assertThatThrownBy(() -> service.verify("wrong-audience", null, false))
                .hasMessageContaining("audience");
        assertThatThrownBy(() -> service.verify("multiple-audiences", null, false))
                .hasMessageContaining("audience");
        assertThatThrownBy(() -> service.verify("missing-subject", null, false))
                .hasMessageContaining("subject is missing");
        assertThatThrownBy(() -> service.verify("long-subject", null, false))
                .hasMessageContaining("subject is too long");
        assertThatThrownBy(() -> service.verify("missing-expiry", null, false))
                .hasMessageContaining("expired");
        assertThatThrownBy(() -> service.verify("expired", null, false))
                .hasMessageContaining("expired");
        assertThatThrownBy(() -> service.verify("invalid-email", null, false))
                .hasMessageContaining("email is invalid");
        assertThatThrownBy(() -> service.verify("long-email", null, false))
                .hasMessageContaining("email is invalid");
    }

    @Test
    void acceptsProviderBooleanVariantsAndNormalizesFallbackName() {
        JwtDecoder decoder = mock(JwtDecoder.class);
        GoogleIdentityService service = service(decoder);
        when(decoder.decode("string-true")).thenReturn(
                jwtBuilder("nonce")
                        .claim("email_verified", "true")
                        .claim("name", " ")
                        .build()
        );
        when(decoder.decode("numeric-string")).thenReturn(
                jwtBuilder("nonce")
                        .claim("email_verified", "1")
                        .claim("name", "N".repeat(120))
                        .build()
        );

        assertThat(service.verify("string-true", "", false).name())
                .isEqualTo("user@example.com");
        assertThat(service.verify("numeric-string", null, false).name())
                .hasSize(100);
    }

    @Test
    void rejectsMissingAndBlankTokenNonce() {
        JwtDecoder decoder = mock(JwtDecoder.class);
        GoogleIdentityService service = service(decoder);
        when(decoder.decode("missing-nonce")).thenReturn(
                jwtBuilder(null).build()
        );
        when(decoder.decode("blank-nonce")).thenReturn(
                jwtBuilder(" ").build()
        );

        assertThatThrownBy(() -> service.verify(
                "missing-nonce",
                service.nonceHash("expected"),
                true
        )).hasMessageContaining("nonce could not be verified");
        assertThatThrownBy(() -> service.verify(
                "blank-nonce",
                service.nonceHash("expected"),
                true
        )).hasMessageContaining("nonce could not be verified");
    }

    private static GoogleIdentityService service(JwtDecoder decoder) {
        return new GoogleIdentityService(
                new MockEnvironment().withProperty("GOOGLE_CLIENT_ID", "google-client"),
                decoder
        );
    }

    private static Jwt validJwt(String nonce) {
        return jwtBuilder(nonce).build();
    }

    private static Jwt.Builder jwtBuilder(String nonce) {
        return jwtBuilderWithoutExpiry(nonce)
                .expiresAt(Instant.now().plusSeconds(300));
    }

    private static Jwt.Builder jwtBuilderWithoutExpiry(String nonce) {
        Instant now = Instant.now();
        Jwt.Builder builder = Jwt.withTokenValue("signed-token")
                .header("alg", "RS256")
                .issuedAt(now.minusSeconds(30))
                .subject("google-subject")
                .claim("aud", List.of("google-client"))
                .claim("iss", "https://accounts.google.com")
                .claim("email", " User@Example.com ")
                .claim("email_verified", true)
                .claim("name", "Google User");
        if (nonce != null) {
            builder.claim("nonce", nonce);
        }
        return builder;
    }
}
