package com.ascentia.subs.auth;

import com.ascentia.subs.common.ClientIpResolver;
import com.ascentia.subs.common.RateLimitService;
import com.ascentia.subs.history.HistoryStore;
import com.ascentia.subs.jobs.JobArtifactService;
import com.ascentia.subs.jobs.JobStore;
import com.ascentia.subs.points.PointsStore;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AuthControllerUnitTest {

    @Test
    void updatePasswordRejectsExternalProvidersAndMismatchedConfirmation() {
        AuthController controller = controller(new MockEnvironment(), mock(AuthStore.class));

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
    void googleUrlPrefersExplicitRedirectUriWhenPresent() {
        MockEnvironment environment = new MockEnvironment()
                .withProperty("GOOGLE_CLIENT_ID", "google-client")
                .withProperty("GOOGLE_REDIRECT_URI", "https://frontend.example.com/oauth/callback");
        AuthStore authStore = mock(AuthStore.class);
        when(authStore.issueOauthState("google", null, "JUnit", "127.0.0.1", 600)).thenReturn("state-123");

        AuthController controller = controller(environment, authStore);
        MockHttpServletRequest request = request();

        AuthController.GoogleAuthUrlResponse response = controller.googleUrl(request);

        assertThat(response.state()).isEqualTo("state-123");
        assertThat(response.auth_url()).contains("client_id=google-client");
        assertThat(response.auth_url()).contains("redirect_uri=" + URLEncoder.encode(
                "https://frontend.example.com/oauth/callback",
                StandardCharsets.UTF_8
        ));
    }

    @Test
    void googleUrlFallsBackToFrontendLoginWhenExplicitRedirectMissing() {
        MockEnvironment environment = new MockEnvironment()
                .withProperty("GOOGLE_CLIENT_ID", "google-client")
                .withProperty("FRONTEND_URL", "https://app.example.com///");
        AuthStore authStore = mock(AuthStore.class);
        when(authStore.issueOauthState("google", null, "JUnit", "127.0.0.1", 600)).thenReturn("state-frontend");

        AuthController controller = controller(environment, authStore);
        AuthController.GoogleAuthUrlResponse response = controller.googleUrl(request());

        assertThat(response.auth_url()).contains("redirect_uri=https%3A%2F%2Fapp.example.com%2Flogin");
    }

    @Test
    void googleUrlRejectsMissingAndBlankConfiguration() {
        AuthStore authStore = mock(AuthStore.class);
        MockHttpServletRequest request = request();

        assertThatThrownBy(() -> controller(new MockEnvironment(), authStore).googleUrl(request))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Google OAuth not configured");

        assertThatThrownBy(() -> controller(new MockEnvironment().withProperty("GOOGLE_CLIENT_ID", " "), authStore).googleUrl(request))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Google OAuth not configured");

        MockEnvironment blankBaseEnvironment = new MockEnvironment()
                .withProperty("GOOGLE_CLIENT_ID", "google-client")
                .withProperty("GOOGLE_REDIRECT_URI", " ")
                .withProperty("FRONTEND_URL", " ");
        assertThatThrownBy(() -> controller(blankBaseEnvironment, authStore).googleUrl(request))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Google OAuth not configured");

        MockEnvironment missingBaseEnvironment = new MockEnvironment()
                .withProperty("GOOGLE_CLIENT_ID", "google-client");
        assertThatThrownBy(() -> controller(missingBaseEnvironment, authStore).googleUrl(request))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Google OAuth not configured");
    }

    private static AuthController controller(MockEnvironment environment, AuthStore authStore) {
        return new AuthController(
                authStore,
                mock(PointsStore.class),
                mock(JobStore.class),
                mock(JobArtifactService.class),
                mock(HistoryStore.class),
                mock(RateLimitService.class),
                new ClientIpResolver(),
                environment
        );
    }

    private static Authentication authenticationFor(String provider) {
        return new UsernamePasswordAuthenticationToken(
                new CurrentUser("user-1", "user@example.com", "User", provider, null, null, "2026-01-01T00:00:00Z", true),
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
