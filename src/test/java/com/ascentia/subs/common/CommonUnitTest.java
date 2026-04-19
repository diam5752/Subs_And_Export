package com.ascentia.subs.common;

import com.ascentia.subs.auth.CurrentUser;
import com.ascentia.subs.auth.CurrentUserAccess;
import com.ascentia.subs.auth.AuthStore;
import com.ascentia.subs.auth.BearerTokenAuthenticationFilter;
import com.ascentia.subs.config.AppProperties;
import com.ascentia.subs.web.AppController;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.validation.BeanPropertyBindingResult;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class CommonUnitTest {

    private static final class ValidationTarget {
        @SuppressWarnings("unused")
        void submit(String value) {
        }
    }

    @Test
    void jsonCodecRoundTripsAndProducesJsonbObjects() {
        JsonCodec codec = new JsonCodec(new ObjectMapper());
        String json = codec.write(Map.of("answer", 42, "name", "test"));
        assertThat(codec.readMap(json)).containsEntry("answer", 42).containsEntry("name", "test");
        assertThat(codec.readMap(null)).isEmpty();
        assertThat(codec.readMap("")).isEmpty();
        assertThat(codec.toJsonb(Map.of("k", "v")).getType()).isEqualTo("jsonb");
        assertThat(codec.toJsonb(null).getValue()).isNull();
    }

    @Test
    void apiExceptionHelpersSanitizeResolveAndHandleFrameworkExceptions() throws Exception {
        ApiExceptionHandler handler = new ApiExceptionHandler();
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/api/test");

        assertThat(ApiExceptionHandler.sanitizeMessage("use sk-secret and gsk_secret"))
                .doesNotContain("sk-secret")
                .contains("[API_KEY_REDACTED]");
        assertThat(ApiExceptionHandler.sanitizeMessage("")).isEqualTo("Request failed");
        assertThat(ApiExceptionHandler.sanitizeMessage(null)).isEqualTo("Request failed");

        ResponseStatusException direct = new ResponseStatusException(HttpStatus.BAD_REQUEST, "Bad input");
        assertThat(ApiExceptionHandler.messageOf(direct)).isEqualTo("Bad input");
        assertThat(handler.handleStatus(direct, request).getBody()).containsEntry("detail", "Bad input");

        ResponseStatusException reasonFallback = mock(ResponseStatusException.class);
        ProblemDetail blankBody = ProblemDetail.forStatus(HttpStatus.NOT_FOUND);
        blankBody.setDetail(" ");
        when(reasonFallback.getBody()).thenReturn(blankBody);
        when(reasonFallback.getReason()).thenReturn("Missing resource");
        when(reasonFallback.getStatusCode()).thenReturn(HttpStatus.NOT_FOUND);
        assertThat(ApiExceptionHandler.messageOf(reasonFallback)).isEqualTo("Missing resource");

        ResponseStatusException phraseFallback = mock(ResponseStatusException.class);
        when(phraseFallback.getBody()).thenReturn(blankBody);
        when(phraseFallback.getReason()).thenReturn(" ");
        when(phraseFallback.getStatusCode()).thenReturn(HttpStatus.NOT_FOUND);
        assertThat(ApiExceptionHandler.messageOf(phraseFallback)).isEqualTo("Not Found");

        ResponseStatusException bodyPreferred = mock(ResponseStatusException.class);
        ProblemDetail detailedBody = ProblemDetail.forStatus(HttpStatus.CONFLICT);
        detailedBody.setDetail("Body detail");
        when(bodyPreferred.getBody()).thenReturn(detailedBody);
        when(bodyPreferred.getReason()).thenReturn("Ignored");
        when(bodyPreferred.getStatusCode()).thenReturn(HttpStatus.CONFLICT);
        assertThat(ApiExceptionHandler.messageOf(bodyPreferred)).isEqualTo("Body detail");

        ResponseStatusException nullBody = mock(ResponseStatusException.class);
        when(nullBody.getBody()).thenReturn(null);
        when(nullBody.getReason()).thenReturn(" ");
        when(nullBody.getStatusCode()).thenReturn(HttpStatus.UNAUTHORIZED);
        assertThat(ApiExceptionHandler.messageOf(nullBody)).isEqualTo("Unauthorized");

        Method method = ValidationTarget.class.getDeclaredMethod("submit", String.class);
        MethodParameter parameter = new MethodParameter(method, 0);
        BeanPropertyBindingResult bindingResult = new BeanPropertyBindingResult(new Object(), "payload");
        bindingResult.addError(new FieldError("payload", "name", "Name is required"));
        MethodArgumentNotValidException validationException = new MethodArgumentNotValidException(parameter, bindingResult);
        assertThat(handler.handleValidation(validationException, request).getBody())
                .containsEntry("detail", "Name is required")
                .containsEntry("path", "/api/test");

        BeanPropertyBindingResult emptyBindingResult = new BeanPropertyBindingResult(new Object(), "payload");
        MethodArgumentNotValidException defaultValidationException = new MethodArgumentNotValidException(parameter, emptyBindingResult);
        assertThat(handler.handleValidation(defaultValidationException, request).getBody())
                .containsEntry("detail", "Validation failed");

        assertThat(handler.handleSecurity(new BadCredentialsException("bad"), request).getBody())
                .containsEntry("detail", "Could not validate credentials")
                .containsEntry("status", 401);
        assertThat(handler.handleSecurity(new AccessDeniedException("no"), request).getBody())
                .containsEntry("detail", "Forbidden")
                .containsEntry("status", 403);

        assertThat(handler.handleGeneric(new IllegalStateException("boom sk-secret"), request).getBody())
                .extracting(body -> body.get("detail"))
                .asString()
                .contains("[API_KEY_REDACTED]");
        assertThat(handler.handleGeneric(new IllegalStateException((String) null), request).getBody())
                .containsEntry("detail", "Request failed");
    }

    @Test
    void clientIpResolverPrefersRemoteAddrThenHeadersAndFallsBackToUnknown() {
        ClientIpResolver resolver = new ClientIpResolver();

        MockHttpServletRequest directRequest = new MockHttpServletRequest();
        directRequest.setRemoteAddr("127.0.0.1");
        directRequest.addHeader("x-forwarded-for", "10.0.0.1");
        assertThat(resolver.resolve(directRequest)).isEqualTo("127.0.0.1");

        HttpServletRequest headerOnly = mock(HttpServletRequest.class);
        when(headerOnly.getRemoteAddr()).thenReturn(null);
        when(headerOnly.getHeader("x-forwarded-for")).thenReturn("10.0.0.1, 10.0.0.2");
        assertThat(resolver.resolve(headerOnly)).isEqualTo("10.0.0.2");

        HttpServletRequest realIp = mock(HttpServletRequest.class);
        when(realIp.getRemoteAddr()).thenReturn(null);
        when(realIp.getHeader("x-forwarded-for")).thenReturn(" ");
        when(realIp.getHeader("x-real-ip")).thenReturn("not-an-ip");
        assertThat(resolver.resolve(realIp)).isEqualTo("not-an-ip");

        HttpServletRequest unknown = mock(HttpServletRequest.class);
        when(unknown.getRemoteAddr()).thenReturn(null);
        when(unknown.getHeader("x-forwarded-for")).thenReturn(null);
        when(unknown.getHeader("x-real-ip")).thenReturn(" ");
        assertThat(resolver.resolve(unknown)).isEqualTo("unknown");

        HttpServletRequest blankForwarded = mock(HttpServletRequest.class);
        when(blankForwarded.getRemoteAddr()).thenReturn(" ");
        when(blankForwarded.getHeader("x-forwarded-for")).thenReturn(" , ");
        when(blankForwarded.getHeader("x-real-ip")).thenReturn(null);
        assertThat(resolver.resolve(blankForwarded)).isEqualTo("unknown");
    }

    @Test
    void currentUserAccessRequiresAuthenticatedPrincipal() {
        CurrentUser currentUser = new CurrentUser("u1", "user@example.com", "User", "local", null, null, "2026-01-01T00:00:00Z", false);
        UsernamePasswordAuthenticationToken authentication = new UsernamePasswordAuthenticationToken(currentUser, "token");
        assertThat(CurrentUserAccess.require(authentication)).isEqualTo(currentUser);
        assertThatThrownBy(() -> CurrentUserAccess.require(null)).isInstanceOf(ResponseStatusException.class);
        assertThatThrownBy(() -> CurrentUserAccess.require(new UsernamePasswordAuthenticationToken("not-a-user", "token")))
                .isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void bearerTokenAuthenticationFilterHandlesPresentMissingAndInvalidTokens() throws Exception {
        AuthStore authStore = mock(AuthStore.class);
        BearerTokenAuthenticationFilter filter = new BearerTokenAuthenticationFilter(authStore);
        CurrentUser currentUser = new CurrentUser("u1", "user@example.com", "User", "local", null, null, "2026-01-01T00:00:00Z", false);
        when(authStore.authenticateToken("valid-token")).thenReturn(java.util.Optional.of(currentUser));
        when(authStore.authenticateToken("invalid-token")).thenReturn(java.util.Optional.empty());

        MockHttpServletRequest validRequest = new MockHttpServletRequest();
        validRequest.addHeader(HttpHeaders.AUTHORIZATION, "Bearer valid-token");
        filter.doFilter(validRequest, new MockHttpServletResponse(), new MockFilterChain());
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNotNull();
        assertThat(SecurityContextHolder.getContext().getAuthentication().getPrincipal()).isEqualTo(currentUser);
        SecurityContextHolder.clearContext();

        MockHttpServletRequest invalidRequest = new MockHttpServletRequest();
        invalidRequest.addHeader(HttpHeaders.AUTHORIZATION, "Bearer invalid-token");
        filter.doFilter(invalidRequest, new MockHttpServletResponse(), new MockFilterChain());
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
        SecurityContextHolder.clearContext();

        MockHttpServletRequest nonBearerRequest = new MockHttpServletRequest();
        nonBearerRequest.addHeader(HttpHeaders.AUTHORIZATION, "Basic invalid-token");
        filter.doFilter(nonBearerRequest, new MockHttpServletResponse(), new MockFilterChain());
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
        SecurityContextHolder.clearContext();

        filter.doFilter(new MockHttpServletRequest(), new MockHttpServletResponse(), new MockFilterChain());
        assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
    }

    @Test
    void appControllerServesFilesBlocksTraversalAndRejectsDirectories() throws Exception {
        RateLimitService rateLimitService = mock(RateLimitService.class);
        doNothing().when(rateLimitService).check(org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyString(), org.mockito.ArgumentMatchers.anyInt(), org.mockito.ArgumentMatchers.anyInt());

        AppProperties properties = new AppProperties();
        ClientIpResolver clientIpResolver = new ClientIpResolver();
        AppController controller = new AppController(properties, rateLimitService, clientIpResolver);
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRemoteAddr("127.0.0.1");

        assertThatThrownBy(() -> controller.serveStatic("../pom.xml", false, request))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("403 FORBIDDEN");

        Path file = Path.of("data", "unit-static.txt");
        Files.createDirectories(file.getParent());
        Files.write(file, "hello".getBytes(StandardCharsets.UTF_8));

        assertThat(controller.serveStatic("unit-static.txt", false, request).getBody()).isNotNull();
        assertThat(controller.serveStatic("unit-static.txt", true, request).getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION))
                .contains("attachment");

        Path directory = Path.of("data", "unit-static-dir");
        Files.createDirectories(directory);
        assertThatThrownBy(() -> controller.serveStatic("unit-static-dir", false, request))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("404 NOT_FOUND");

        Path video = Path.of("data", "unit-video.mp4");
        Files.write(video, "video".getBytes(StandardCharsets.UTF_8));
        assertThat(controller.serveStatic("unit-video.mp4", false, request).getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION))
                .contains("unit-video.mp4");
        for (String extension : java.util.List.of(".mov", ".avi", ".webm", ".mkv")) {
            String filename = "unit-video" + extension;
            Files.write(Path.of("data", filename), "video".getBytes(StandardCharsets.UTF_8));
            assertThat(controller.serveStatic(filename, false, request).getHeaders().getFirst(HttpHeaders.CONTENT_DISPOSITION))
                    .contains(filename);
        }
        assertThatThrownBy(() -> controller.serveStatic(null, false, request))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("404 NOT_FOUND");
        assertThatThrownBy(() -> controller.serveStatic("missing.txt", false, request))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("404 NOT_FOUND");
    }
}
