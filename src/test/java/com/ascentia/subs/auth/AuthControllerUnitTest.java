package com.ascentia.subs.auth;

import com.ascentia.subs.common.ClientIpResolver;
import com.ascentia.subs.common.RateLimitService;
import com.ascentia.subs.history.HistoryStore;
import com.ascentia.subs.jobs.JobArtifactService;
import com.ascentia.subs.jobs.JobStore;
import com.ascentia.subs.points.PointsStore;
import jakarta.servlet.http.Cookie;
import java.util.Objects;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AuthControllerUnitTest {

    @Test
    void updatePasswordRejectsExternalProvidersAndMismatchedConfirmation() {
        AuthController controller = controller(
                new MockEnvironment(),
                mock(AuthStore.class),
                mock(GoogleIdentityService.class)
        );

        assertThatThrownBy(() -> controller.updatePassword(
                new AuthController.UpdatePasswordRequest("letters123456", "letters123456"),
                authenticationFor("google")
        )).isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Cannot update password for external provider");

        assertThatThrownBy(() -> controller.updatePassword(
                new AuthController.UpdatePasswordRequest("letters123456", "different123456"),
                authenticationFor("local")
        )).isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Passwords do not match");
    }

    @Test
    void googleNonceSetsHashedHttpOnlyCookieAndReturnsPublicClientId() {
        GoogleIdentityService googleIdentityService = mock(GoogleIdentityService.class);
        when(googleIdentityService.clientId()).thenReturn("google-client");
        when(googleIdentityService.createNonce()).thenReturn("browser-nonce");
        when(googleIdentityService.nonceHash("browser-nonce")).thenReturn("nonce-hash");
        AuthController controller = controller(
                new MockEnvironment().withProperty("APP_ENV", "production"),
                mock(AuthStore.class),
                googleIdentityService
        );
        MockHttpServletResponse response = new MockHttpServletResponse();

        AuthController.GoogleAuthNonceResponse result = controller.googleNonce(
                request(),
                response
        );

        assertThat(result.nonce()).isEqualTo("browser-nonce");
        assertThat(result.client_id()).isEqualTo("google-client");
        assertThat(result.expires_in()).isEqualTo(600);
        assertThat(Objects.requireNonNull(response.getHeader("Set-Cookie")))
                .contains("gsubs_google_nonce=nonce-hash")
                .contains("Max-Age=600")
                .contains("Path=/")
                .contains("Secure")
                .contains("HttpOnly")
                .contains("SameSite=Lax");
    }

    @Test
    void googleLoginVerifiesNonceAndIssuesSession() {
        GoogleIdentityService googleIdentityService = mock(GoogleIdentityService.class);
        AuthStore authStore = mock(AuthStore.class);
        MockEnvironment environment = new MockEnvironment().withProperty("APP_ENV", "production");
        AuthController controller = controller(environment, authStore, googleIdentityService);
        MockHttpServletRequest request = request();
        request.setCookies(new Cookie("gsubs_google_nonce", "nonce-hash"));
        MockHttpServletResponse response = new MockHttpServletResponse();
        GoogleIdentityService.GoogleProfile profile =
                new GoogleIdentityService.GoogleProfile(
                        "google@example.com",
                        "Google User",
                        "google-subject"
                );
        CurrentUser user = new CurrentUser(
                "google-user",
                profile.email(),
                profile.name(),
                "google",
                null,
                profile.subject(),
                "2026-07-25T00:00:00Z",
                true
        );
        when(googleIdentityService.verify(
                "signed-id-token",
                "nonce-hash",
                true
        )).thenReturn(profile);
        when(authStore.upsertGoogleUser(
                profile.email(),
                profile.name(),
                profile.subject()
        )).thenReturn(user);
        when(authStore.issueSession(user, "JUnit")).thenReturn("session-token");

        AuthController.TokenResponse token = controller.googleLogin(
                new AuthController.GoogleLoginRequest("signed-id-token"),
                request,
                response
        );

        assertThat(token.access_token()).isEqualTo("session-token");
        assertThat(token.user_id()).isEqualTo("google-user");
        verify(googleIdentityService).verify("signed-id-token", "nonce-hash", true);
        assertThat(Objects.requireNonNull(response.getHeader("Set-Cookie")))
                .contains("gsubs_google_nonce=")
                .contains("Max-Age=0");
    }

    @Test
    void googleLoginUsesCookiePresenceToRequireNonceInDevelopment() {
        GoogleIdentityService googleIdentityService = mock(GoogleIdentityService.class);
        AuthStore authStore = mock(AuthStore.class);
        AuthController controller = controller(
                new MockEnvironment().withProperty("APP_ENV", "dev"),
                authStore,
                googleIdentityService
        );
        GoogleIdentityService.GoogleProfile profile =
                new GoogleIdentityService.GoogleProfile(
                        "google@example.com",
                        "Google User",
                        "google-subject"
                );
        CurrentUser user = new CurrentUser(
                "google-user",
                profile.email(),
                profile.name(),
                "google",
                null,
                profile.subject(),
                "2026-07-25T00:00:00Z",
                true
        );
        when(authStore.upsertGoogleUser(
                profile.email(),
                profile.name(),
                profile.subject()
        )).thenReturn(user);
        when(authStore.issueSession(user, "JUnit")).thenReturn("session-token");

        MockHttpServletRequest withoutCookie = request();
        when(googleIdentityService.verify("token-without-cookie", null, false))
                .thenReturn(profile);
        controller.googleLogin(
                new AuthController.GoogleLoginRequest("token-without-cookie"),
                withoutCookie,
                new MockHttpServletResponse()
        );
        verify(googleIdentityService).verify("token-without-cookie", null, false);

        MockHttpServletRequest withCookie = request();
        withCookie.setCookies(
                new Cookie("other", "ignored"),
                new Cookie("gsubs_google_nonce", "nonce-hash")
        );
        when(googleIdentityService.verify(
                "token-with-cookie",
                "nonce-hash",
                true
        )).thenReturn(profile);
        controller.googleLogin(
                new AuthController.GoogleLoginRequest("token-with-cookie"),
                withCookie,
                new MockHttpServletResponse()
        );
        verify(googleIdentityService).verify(
                "token-with-cookie",
                "nonce-hash",
                true
        );
    }

    @Test
    void googleNonceRejectsOutOfRangeTtlAndUsesNonSecureCookieInDev() {
        GoogleIdentityService googleIdentityService = mock(GoogleIdentityService.class);
        when(googleIdentityService.createNonce()).thenReturn("browser-nonce");
        when(googleIdentityService.nonceHash("browser-nonce")).thenReturn("nonce-hash");
        when(googleIdentityService.clientId()).thenReturn("google-client");

        for (int invalidTtl : new int[]{59, 901}) {
            AuthController invalidController = controller(
                    new MockEnvironment()
                            .withProperty("APP_ENV", "dev")
                            .withProperty(
                                    "GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS",
                                    String.valueOf(invalidTtl)
                            ),
                    mock(AuthStore.class),
                    googleIdentityService
            );
            assertThatThrownBy(() -> invalidController.googleNonce(
                    request(),
                    new MockHttpServletResponse()
            )).isInstanceOf(IllegalStateException.class)
                    .hasMessageContaining("between 60 and 900");
        }

        AuthController devController = controller(
                new MockEnvironment()
                        .withProperty("APP_ENV", "dev")
                        .withProperty("GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS", "60"),
                mock(AuthStore.class),
                googleIdentityService
        );
        MockHttpServletResponse response = new MockHttpServletResponse();
        devController.googleNonce(request(), response);
        assertThat(Objects.requireNonNull(response.getHeader("Set-Cookie")))
                .doesNotContain("Secure");
    }

    private static AuthController controller(
            MockEnvironment environment,
            AuthStore authStore,
            GoogleIdentityService googleIdentityService
    ) {
        return new AuthController(
                authStore,
                mock(PointsStore.class),
                mock(JobStore.class),
                mock(JobArtifactService.class),
                mock(HistoryStore.class),
                mock(RateLimitService.class),
                new ClientIpResolver(),
                environment,
                googleIdentityService
        );
    }

    private static Authentication authenticationFor(String provider) {
        return new UsernamePasswordAuthenticationToken(
                new CurrentUser(
                        "user-1",
                        "user@example.com",
                        "User",
                        provider,
                        null,
                        null,
                        "2026-01-01T00:00:00Z",
                        true
                ),
                "token"
        );
    }

    private static MockHttpServletRequest request() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("127.0.0.1");
        request.addHeader("User-Agent", "JUnit");
        return request;
    }
}
