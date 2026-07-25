package com.ascentia.subs.auth;

import com.ascentia.subs.common.ClientIpResolver;
import com.ascentia.subs.common.RateLimitService;
import com.ascentia.subs.history.HistoryStore;
import com.ascentia.subs.jobs.JobArtifactService;
import com.ascentia.subs.jobs.JobStore;
import com.ascentia.subs.points.PointsStore;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.Duration;
import java.util.Arrays;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@Validated
@RestController
@RequestMapping("/auth")
public class AuthController {

    private final AuthStore authStore;
    private final PointsStore pointsStore;
    private final JobStore jobStore;
    private final JobArtifactService jobArtifactService;
    private final HistoryStore historyStore;
    private final RateLimitService rateLimitService;
    private final ClientIpResolver clientIpResolver;
    private final Environment environment;
    private final GoogleIdentityService googleIdentityService;

    public AuthController(
            AuthStore authStore,
            PointsStore pointsStore,
            JobStore jobStore,
            JobArtifactService jobArtifactService,
            HistoryStore historyStore,
            RateLimitService rateLimitService,
            ClientIpResolver clientIpResolver,
            Environment environment,
            GoogleIdentityService googleIdentityService
    ) {
        this.authStore = authStore;
        this.pointsStore = pointsStore;
        this.jobStore = jobStore;
        this.jobArtifactService = jobArtifactService;
        this.historyStore = historyStore;
        this.rateLimitService = rateLimitService;
        this.clientIpResolver = clientIpResolver;
        this.environment = environment;
        this.googleIdentityService = googleIdentityService;
    }

    @PostMapping("/register")
    UserResponse register(@Valid @RequestBody RegisterRequest request, HttpServletRequest servletRequest) {
        String ip = clientIpResolver.resolve(servletRequest);
        rateLimitService.check("register", ip, 3, 60);
        rateLimitService.check("signup_daily", ip, 5, 86_400);
        CurrentUser user = authStore.registerLocalUser(request.email(), request.password(), request.name());
        return UserResponse.from(user);
    }

    @PostMapping(value = "/token", consumes = "application/x-www-form-urlencoded")
    TokenResponse token(
            @RequestParam("username") String username,
            @RequestParam("password") String password,
            HttpServletRequest servletRequest
    ) {
        String ip = clientIpResolver.resolve(servletRequest);
        rateLimitService.check("login", ip, 5, 60);
        CurrentUser user = authStore.authenticateLocal(username, password)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST, "Incorrect email or password"));
        String token = authStore.issueSession(user, servletRequest.getHeader("User-Agent"));
        return new TokenResponse(token, "bearer", user.id(), user.name());
    }

    @GetMapping("/me")
    UserResponse me(Authentication authentication) {
        return UserResponse.from(CurrentUserAccess.require(authentication));
    }

    @GetMapping("/points")
    PointsBalanceResponse points(Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        return new PointsBalanceResponse(pointsStore.getBalance(currentUser.id()));
    }

    @PutMapping("/me")
    UserResponse updateMe(@Valid @RequestBody UpdateNameRequest request, Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        rateLimitService.check("auth_change", currentUser.id(), 5, 60);
        authStore.updateName(currentUser.id(), request.name());
        return authStore.findUserById(currentUser.id()).map(UserResponse::from).orElseThrow();
    }

    @PutMapping("/password")
    Map<String, String> updatePassword(@Valid @RequestBody UpdatePasswordRequest request, Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        rateLimitService.check("auth_change", currentUser.id(), 5, 60);
        if (!"local".equals(currentUser.provider())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Cannot update password for external provider");
        }
        if (!request.password().equals(request.confirmPassword())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Passwords do not match");
        }
        authStore.updatePassword(currentUser.id(), request.password());
        authStore.revokeAllSessions(currentUser.id());
        return Map.of("status", "success");
    }

    @GetMapping("/export")
    ExportDataResponse exportData(Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        return new ExportDataResponse(
                ExportProfileResponse.from(currentUser),
                jobStore.listJobsForUser(currentUser.id(), 1_000).stream().map(JobResponse::from).toList(),
                historyStore.recentForUser(currentUser.id(), 1_000).stream().map(HistoryEventResponse::from).toList()
        );
    }

    @DeleteMapping("/me")
    Map<String, String> deleteMe(Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        rateLimitService.check("auth_change", currentUser.id(), 5, 60);
        jobStore.listJobsForUser(currentUser.id(), 1_000).forEach(job -> jobArtifactService.deleteArtifacts(job.id()));
        authStore.revokeAllSessions(currentUser.id());
        authStore.deleteUser(currentUser.id());
        return Map.of("status", "deleted", "message", "Account and all data have been permanently deleted");
    }

    @GetMapping("/google/nonce")
    GoogleAuthNonceResponse googleNonce(
            HttpServletRequest servletRequest,
            HttpServletResponse servletResponse
    ) {
        String ip = clientIpResolver.resolve(servletRequest);
        rateLimitService.check("login", ip, 5, 60);
        String nonce = googleIdentityService.createNonce();
        int ttlSeconds = googleNonceTtlSeconds();
        setGoogleNonceCookie(
                servletResponse,
                googleIdentityService.nonceHash(nonce),
                ttlSeconds
        );
        return new GoogleAuthNonceResponse(
                nonce,
                ttlSeconds,
                googleIdentityService.clientId()
        );
    }

    @PostMapping("/google")
    TokenResponse googleLogin(
            @Valid @RequestBody GoogleLoginRequest request,
            HttpServletRequest servletRequest,
            HttpServletResponse servletResponse
    ) {
        String ip = clientIpResolver.resolve(servletRequest);
        rateLimitService.check("login", ip, 5, 60);
        String nonceHash = cookieValue(
                servletRequest,
                "gsubs_google_nonce"
        );
        GoogleIdentityService.GoogleProfile profile = googleIdentityService.verify(
                request.idToken(),
                nonceHash,
                isProduction() || nonceHash != null
        );
        CurrentUser user = authStore.upsertGoogleUser(
                profile.email(),
                profile.name(),
                profile.subject()
        );
        String token = authStore.issueSession(
                user,
                servletRequest.getHeader("User-Agent")
        );
        clearGoogleNonceCookie(servletResponse);
        return new TokenResponse(
                token,
                "bearer",
                user.id(),
                user.name()
        );
    }

    private int googleNonceTtlSeconds() {
        int value = environment.getProperty(
                "GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS",
                Integer.class,
                600
        );
        if (value < 60 || value > 900) {
            throw new IllegalStateException(
                    "GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS must be between 60 and 900"
            );
        }
        return value;
    }

    private void setGoogleNonceCookie(
            HttpServletResponse response,
            String value,
            int maxAgeSeconds
    ) {
        ResponseCookie cookie = ResponseCookie.from("gsubs_google_nonce", value)
                .httpOnly(true)
                .secure(isProduction())
                .sameSite("Lax")
                .path("/")
                .maxAge(Duration.ofSeconds(maxAgeSeconds))
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private void clearGoogleNonceCookie(HttpServletResponse response) {
        setGoogleNonceCookie(response, "", 0);
    }

    private boolean isProduction() {
        String value = environment.getProperty(
                "APP_ENV",
                environment.getProperty("GSP_APP_ENV", "production")
        );
        return !Set.of(
                "dev",
                "development",
                "local",
                "localhost"
        ).contains(value.strip().toLowerCase(Locale.ROOT));
    }

    private static String cookieValue(
            HttpServletRequest request,
            String name
    ) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) {
            return null;
        }
        return Arrays.stream(cookies)
                .filter(cookie -> name.equals(cookie.getName()))
                .map(Cookie::getValue)
                .findFirst()
                .orElse(null);
    }

    public record RegisterRequest(@NotBlank @Email @Size(max = 255) String email,
                                  @NotBlank @Size(min = 12, max = 128) String password,
                                  @NotBlank @Size(max = 100) String name) {
    }

    public record UpdateNameRequest(@NotBlank @Size(max = 100) String name) {
    }

    public record UpdatePasswordRequest(@NotBlank @Size(min = 12, max = 128) String password,
                                        @NotBlank @Size(max = 128) String confirmPassword) {
    }

    public record GoogleLoginRequest(
            @NotBlank @Size(max = 16_384) String idToken
    ) {
    }

    public record TokenResponse(String access_token, String token_type, String user_id, String name) {
    }

    public record UserResponse(String id, String email, String name, String provider) {
        static UserResponse from(CurrentUser user) {
            return new UserResponse(user.id(), user.email(), user.name(), user.provider());
        }
    }

    public record PointsBalanceResponse(int balance) {
    }

    public record GoogleAuthNonceResponse(
            String nonce,
            int expires_in,
            String client_id
    ) {
    }

    public record ExportProfileResponse(String id, String email, String name, String created_at, String provider) {
        static ExportProfileResponse from(CurrentUser user) {
            return new ExportProfileResponse(user.id(), user.email(), user.name(), user.createdAt(), user.provider());
        }
    }

    public record ExportDataResponse(ExportProfileResponse profile, java.util.List<JobResponse> jobs, java.util.List<HistoryEventResponse> history) {
    }

    public record JobResponse(String id, String status, int progress, String message, int created_at, int updated_at, Map<String, Object> result_data, Integer balance) {
        static JobResponse from(JobStore.Job job) {
            return new JobResponse(job.id(), job.status(), job.progress(), job.message(), job.createdAt(), job.updatedAt(), job.resultData(), null);
        }
    }

    public record HistoryEventResponse(String ts, String user_id, String email, String kind, String summary, Map<String, Object> data) {
        static HistoryEventResponse from(HistoryStore.HistoryEvent event) {
            return new HistoryEventResponse(event.ts(), event.userId(), event.email(), event.kind(), event.summary(), event.data());
        }
    }
}
