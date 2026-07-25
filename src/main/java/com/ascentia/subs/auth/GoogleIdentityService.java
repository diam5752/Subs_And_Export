package com.ascentia.subs.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class GoogleIdentityService {

    private static final String GOOGLE_JWK_SET_URI =
            "https://www.googleapis.com/oauth2/v3/certs";
    private static final Set<String> GOOGLE_ISSUERS = Set.of(
            "accounts.google.com",
            "https://accounts.google.com"
    );
    private static final Pattern EMAIL_PATTERN =
            Pattern.compile("^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$");
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();
    private static final int MAX_ID_TOKEN_LENGTH = 16_384;

    private final Environment environment;
    private final JwtDecoder decoder;

    @Autowired
    public GoogleIdentityService(Environment environment) {
        this(
                environment,
                NimbusJwtDecoder.withJwkSetUri(GOOGLE_JWK_SET_URI).build()
        );
    }

    GoogleIdentityService(Environment environment, JwtDecoder decoder) {
        this.environment = environment;
        this.decoder = decoder;
    }

    public String clientId() {
        String value = environment.getProperty("GOOGLE_CLIENT_ID");
        if (value == null || value.isBlank()) {
            throw new ResponseStatusException(
                    HttpStatus.SERVICE_UNAVAILABLE,
                    "Google login is not configured."
            );
        }
        return value.strip();
    }

    public String createNonce() {
        byte[] bytes = new byte[32];
        SECURE_RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public String nonceHash(String nonce) {
        try {
            return java.util.HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(
                            nonce.getBytes(StandardCharsets.UTF_8)
                    )
            );
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    public GoogleProfile verify(
            String idToken,
            String expectedNonceHash,
            boolean requireNonce
    ) {
        if (idToken == null || idToken.isBlank()) {
            throw unauthorized("Google ID token is required.");
        }
        if (idToken.length() > MAX_ID_TOKEN_LENGTH) {
            throw unauthorized("Google ID token is too large.");
        }
        String expectedAudience = clientId();
        Jwt jwt;
        try {
            jwt = decoder.decode(idToken);
        } catch (JwtException exception) {
            throw unauthorized("Google token could not be verified.");
        }

        List<String> audience = jwt.getAudience();
        if (audience.size() != 1 || !expectedAudience.equals(audience.getFirst())) {
            throw unauthorized("Google token audience is not allowed.");
        }
        String issuer = jwt.getClaimAsString("iss");
        if (!GOOGLE_ISSUERS.contains(issuer)) {
            throw unauthorized("Google token issuer is not allowed.");
        }
        Object verified = jwt.getClaims().get("email_verified");
        if (!isVerified(verified)) {
            throw unauthorized("Google email must be verified.");
        }
        String subject = clean(jwt.getSubject());
        if (subject.isEmpty()) {
            throw unauthorized("Google token subject is missing.");
        }
        if (subject.length() > 255) {
            throw unauthorized("Google token subject is too long.");
        }
        Instant expiresAt = jwt.getExpiresAt();
        if (expiresAt == null || !expiresAt.isAfter(Instant.now())) {
            throw unauthorized("Google token has expired.");
        }
        verifyNonce(
                jwt.getClaimAsString("nonce"),
                expectedNonceHash,
                requireNonce
        );

        String email = clean(jwt.getClaimAsString("email")).toLowerCase(Locale.ROOT);
        if (email.length() > 255 || !EMAIL_PATTERN.matcher(email).matches()) {
            throw unauthorized("Google profile email is invalid.");
        }
        String name = clean(jwt.getClaimAsString("name"));
        if (name.isEmpty()) {
            name = email;
        }
        String avatarUrl = GoogleAvatarUrl.normalize(
                jwt.getClaimAsString("picture")
        );
        return new GoogleProfile(
                email,
                name.substring(0, Math.min(100, name.length())),
                subject,
                avatarUrl
        );
    }

    private void verifyNonce(
            String nonce,
            String expectedNonceHash,
            boolean requireNonce
    ) {
        if (expectedNonceHash == null || expectedNonceHash.isBlank()) {
            if (requireNonce) {
                throw unauthorized("Google login nonce is required.");
            }
            return;
        }
        if (nonce == null || nonce.isBlank() || !MessageDigest.isEqual(
                nonceHash(nonce).getBytes(StandardCharsets.UTF_8),
                expectedNonceHash.getBytes(StandardCharsets.UTF_8)
        )) {
            throw unauthorized("Google login nonce could not be verified.");
        }
    }

    private static boolean isVerified(Object value) {
        return Boolean.TRUE.equals(value)
                || "true".equalsIgnoreCase(String.valueOf(value))
                || "1".equals(String.valueOf(value));
    }

    private static String clean(String value) {
        return value == null ? "" : value.strip();
    }

    private static ResponseStatusException unauthorized(String message) {
        return new ResponseStatusException(HttpStatus.UNAUTHORIZED, message);
    }

    public record GoogleProfile(
            String email,
            String name,
            String subject,
            String avatarUrl
    ) {
        public GoogleProfile(String email, String name, String subject) {
            this(email, name, subject, null);
        }
    }
}
