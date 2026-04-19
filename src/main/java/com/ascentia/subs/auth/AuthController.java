package com.ascentia.subs.auth;

import com.ascentia.subs.common.ClientIpResolver;
import com.ascentia.subs.common.RateLimitService;
import com.ascentia.subs.history.HistoryStore;
import com.ascentia.subs.jobs.JobArtifactService;
import com.ascentia.subs.jobs.JobStore;
import com.ascentia.subs.points.PointsStore;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
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

    public AuthController(
            AuthStore authStore,
            PointsStore pointsStore,
            JobStore jobStore,
            JobArtifactService jobArtifactService,
            HistoryStore historyStore,
            RateLimitService rateLimitService,
            ClientIpResolver clientIpResolver,
            Environment environment
    ) {
        this.authStore = authStore;
        this.pointsStore = pointsStore;
        this.jobStore = jobStore;
        this.jobArtifactService = jobArtifactService;
        this.historyStore = historyStore;
        this.rateLimitService = rateLimitService;
        this.clientIpResolver = clientIpResolver;
        this.environment = environment;
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

    @GetMapping("/google/url")
    GoogleAuthUrlResponse googleUrl(HttpServletRequest servletRequest) {
        String ip = clientIpResolver.resolve(servletRequest);
        rateLimitService.check("login", ip, 5, 60);
        String clientId = requiredProperty("GOOGLE_CLIENT_ID");
        String redirectUri = googleRedirectUri();
        String state = authStore.issueOauthState("google", null, servletRequest.getHeader("User-Agent"), ip, 600);
        String authUrl = "https://accounts.google.com/o/oauth2/auth"
                + "?client_id=" + encode(clientId)
                + "&redirect_uri=" + encode(redirectUri)
                + "&response_type=code"
                + "&scope=" + encode("openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/userinfo.profile")
                + "&access_type=offline"
                + "&include_granted_scopes=true"
                + "&state=" + encode(state);
        return new GoogleAuthUrlResponse(authUrl, state);
    }

    @PostMapping("/google/callback")
    TokenResponse googleCallback(@Valid @RequestBody GoogleCallbackRequest request, HttpServletRequest servletRequest) {
        throw new ResponseStatusException(HttpStatus.NOT_IMPLEMENTED, "Google OAuth callback is not yet ported");
    }

    private String requiredProperty(String key) {
        String value = environment.getProperty(key);
        if (value == null || value.isBlank()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Google OAuth not configured");
        }
        return value;
    }

    private String googleRedirectUri() {
        String explicit = environment.getProperty("GOOGLE_REDIRECT_URI");
        if (explicit != null && !explicit.isBlank()) {
            return explicit;
        }
        String base = environment.getProperty("FRONTEND_URL", environment.getProperty("NEXT_PUBLIC_SITE_URL", environment.getProperty("NEXT_PUBLIC_APP_URL")));
        if (base == null || base.isBlank()) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Google OAuth not configured");
        }
        return base.replaceAll("/+$", "") + "/login";
    }

    private static String encode(String value) {
        return URLEncoder.encode(value, StandardCharsets.UTF_8);
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

    public record GoogleCallbackRequest(@NotBlank @Size(max = 4096) String code,
                                        @NotBlank @Size(max = 1024) String state) {
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

    public record GoogleAuthUrlResponse(String auth_url, String state) {
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
