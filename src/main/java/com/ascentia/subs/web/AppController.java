package com.ascentia.subs.web;

import com.ascentia.subs.common.ClientIpResolver;
import com.ascentia.subs.common.RateLimitService;
import com.ascentia.subs.config.AppProperties;
import com.ascentia.subs.auth.CurrentUser;
import com.ascentia.subs.auth.CurrentUserAccess;
import com.ascentia.subs.jobs.JobStore;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.text.Normalizer;
import java.util.Map;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.MediaTypeFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import static org.springframework.http.HttpStatus.NOT_FOUND;
import static org.springframework.http.HttpStatus.UNAUTHORIZED;

@RestController
public class AppController {

    private final AppProperties appProperties;
    private final RateLimitService rateLimitService;
    private final ClientIpResolver clientIpResolver;
    private final JobStore jobStore;
    private final DownloadGrantService downloadGrantService;

    public AppController(
            AppProperties appProperties,
            RateLimitService rateLimitService,
            ClientIpResolver clientIpResolver,
            JobStore jobStore,
            DownloadGrantService downloadGrantService
    ) {
        this.appProperties = appProperties;
        this.rateLimitService = rateLimitService;
        this.clientIpResolver = clientIpResolver;
        this.jobStore = jobStore;
        this.downloadGrantService = downloadGrantService;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of(
                "status", "ok",
                "service", "greek-sub-publisher-api",
                "app_env", appProperties.env()
        );
    }

    @GetMapping("/")
    public Map<String, String> root() {
        return Map.of("message", "Welcome to the Greek Sub Publisher API");
    }

    @GetMapping("/static/{*filePath}")
    public ResponseEntity<Resource> serveStatic(
            @PathVariable String filePath,
            @RequestParam(name = "download", defaultValue = "false") boolean download,
            @RequestParam(name = "filename", required = false) String filename,
            @RequestParam(name = "grant", required = false) String grant,
            HttpServletRequest request,
            Authentication authentication
    ) {
        String ip = clientIpResolver.resolve(request);
        rateLimitService.check("static", ip, appProperties.getStaticRateLimit(), appProperties.getStaticRateLimitWindow());

        String cleanedPath = filePath == null ? "" : filePath.replaceFirst("^/+", "");
        DownloadGrantService.Claims grantClaims = validateOptionalGrant(grant, cleanedPath);
        String authorizedUserId = resolveAuthorizedUserId(grantClaims, authentication);
        String jobId = artifactJobId(cleanedPath);
        JobStore.Job job = jobStore.getJob(jobId)
                .filter(candidate -> authorizedUserId.equals(candidate.userId()))
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "File not found"));
        Path resolvedPath = resolveRegularArtifact(cleanedPath, job.id());
        return buildStaticResponse(resolvedPath, download, filename, grantClaims);
    }

    private DownloadGrantService.Claims validateOptionalGrant(String grant, String cleanedPath) {
        if (grant == null || grant.isBlank()) {
            return null;
        }
        try {
            return downloadGrantService.validate(grant, cleanedPath);
        } catch (IllegalArgumentException ignored) {
            // A valid signed-in owner may still use a stale bookmarked URL.
            return null;
        }
    }

    private static String resolveAuthorizedUserId(
            DownloadGrantService.Claims grantClaims,
            Authentication authentication
    ) {
        if (grantClaims != null) {
            return grantClaims.userId();
        }
        if (authentication != null && authentication.getPrincipal() instanceof CurrentUser user) {
            return user.id();
        }
        throw new ResponseStatusException(UNAUTHORIZED, "Authentication required");
    }

    private static String artifactJobId(String cleanedPath) {
        String artifactPrefix = "artifacts/";
        if (!cleanedPath.startsWith(artifactPrefix)) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }
        String artifactPath = cleanedPath.substring(artifactPrefix.length());
        int separator = artifactPath.indexOf('/');
        if (separator <= 0 || separator == artifactPath.length() - 1) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }
        return artifactPath.substring(0, separator);
    }

    private static ResponseEntity<Resource> buildStaticResponse(
            Path resolvedPath,
            boolean download,
            String filename,
            DownloadGrantService.Claims grantClaims
    ) {
        Resource resource = new FileSystemResource(resolvedPath);
        MediaType mediaType = MediaTypeFactory.getMediaType(resource).orElse(MediaType.APPLICATION_OCTET_STREAM);
        ResponseEntity.BodyBuilder response = ResponseEntity.ok()
                .contentType(mediaType)
                .header(HttpHeaders.CACHE_CONTROL, "private, no-store");
        if (grantClaims != null || download || isVideoDownload(resolvedPath.getFileName().toString())) {
            String downloadFilename = sanitizeDownloadFilename(
                    grantClaims == null ? filename : grantClaims.filename(),
                    resolvedPath.getFileName().toString()
            );
            response.header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                    .filename(downloadFilename, StandardCharsets.UTF_8)
                    .build()
                    .toString());
        }
        if (grantClaims != null) {
            response.header("Referrer-Policy", "no-referrer");
            response.header("X-Robots-Tag", "noindex, nofollow");
        }
        return response.body(resource);
    }

    public ResponseEntity<Resource> serveStatic(
            String filePath,
            boolean download,
            String filename,
            HttpServletRequest request,
            Authentication authentication
    ) {
        return serveStatic(filePath, download, filename, null, request, authentication);
    }

    @PostMapping("/videos/jobs/{jobId}/download-grant")
    public ResponseEntity<DownloadGrantResponse> createDownloadGrant(
            @PathVariable String jobId,
            @Valid @RequestBody DownloadGrantRequest request,
            Authentication authentication
    ) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        jobStore.getJob(jobId)
                .filter(candidate -> currentUser.id().equals(candidate.userId()))
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "Job not found"));
        String filePath = canonicalDownloadPath(request.artifact_path(), jobId);
        Path resolvedPath = resolveRegularArtifact(filePath, jobId);
        String safeFilename = sanitizeDownloadFilename(
                request.filename(),
                resolvedPath.getFileName().toString()
        );
        DownloadGrantService.IssuedGrant issued = downloadGrantService.issue(
                currentUser.id(),
                filePath,
                safeFilename
        );
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, "private, no-store")
                .header("Referrer-Policy", "no-referrer")
                .body(new DownloadGrantResponse(
                        "/static/" + filePath + "?grant=" + issued.token(),
                        issued.expiresIn()
                ));
    }

    private String canonicalDownloadPath(String artifactPath, String jobId) {
        String prefix = "/static/artifacts/" + jobId + "/";
        if (artifactPath == null
                || !artifactPath.startsWith(prefix)
                || artifactPath.contains("\\")
                || artifactPath.contains("%")
                || artifactPath.contains("?")
                || artifactPath.contains("#")
                || artifactPath.contains("://")) {
            throw new ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST, "Invalid artifact path");
        }
        String filePath = artifactPath.substring("/static/".length());
        for (String part : filePath.split("/", -1)) {
            if (part.isBlank() || ".".equals(part) || "..".equals(part)) {
                throw new ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST, "Invalid artifact path");
            }
        }
        return filePath;
    }

    private Path resolveRegularArtifact(String filePath, String jobId) {
        Path artifactsRoot = appProperties.dataDir().toAbsolutePath().normalize().resolve("artifacts");
        Path jobRoot = artifactsRoot.resolve(jobId).normalize();
        Path resolvedPath = appProperties.dataDir().toAbsolutePath().normalize().resolve(filePath).normalize();
        if (!jobRoot.getParent().equals(artifactsRoot)
                || !resolvedPath.startsWith(jobRoot)
                || !Files.isDirectory(jobRoot, LinkOption.NOFOLLOW_LINKS)
                || !Files.isRegularFile(resolvedPath, LinkOption.NOFOLLOW_LINKS)) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }
        try {
            Path current = jobRoot;
            for (Path component : jobRoot.relativize(resolvedPath)) {
                current = current.resolve(component);
                if (Files.isSymbolicLink(current)) {
                    throw new ResponseStatusException(NOT_FOUND, "File not found");
                }
            }
            if (!resolvedPath.toRealPath().startsWith(jobRoot.toRealPath())) {
                throw new ResponseStatusException(NOT_FOUND, "File not found");
            }
        } catch (java.io.IOException exception) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }
        return resolvedPath;
    }

    private static boolean isVideoDownload(String filename) {
        String normalized = filename.toLowerCase();
        return normalized.endsWith(".mp4")
                || normalized.endsWith(".mov")
                || normalized.endsWith(".avi")
                || normalized.endsWith(".webm")
                || normalized.endsWith(".mkv");
    }

    public static String sanitizeDownloadFilename(String requested, String sourceFilename) {
        String sourceName = Path.of(sourceFilename).getFileName().toString();
        String candidate = requested == null || requested.isBlank() ? sourceName : requested;
        candidate = Normalizer.normalize(candidate, Normalizer.Form.NFC).replace('\\', '/');
        candidate = candidate.substring(candidate.lastIndexOf('/') + 1);

        StringBuilder safe = new StringBuilder(candidate.length());
        String unsafeCharacters = "<>:\"/\\|?*";
        for (int index = 0; index < candidate.length(); index++) {
            char character = candidate.charAt(index);
            if (character < 32 || character == 127 || unsafeCharacters.indexOf(character) >= 0) {
                safe.append('_');
            } else {
                safe.append(character);
            }
        }
        candidate = safe.toString().trim().replaceAll("[. ]+$", "");
        if (candidate.isBlank() || candidate.equals(".") || candidate.equals("..")) {
            candidate = sourceName;
        }

        String sourceExtension = extensionOf(sourceName);
        if (!sourceExtension.isEmpty() && !extensionOf(candidate).equalsIgnoreCase(sourceExtension)) {
            String candidateExtension = extensionOf(candidate);
            String candidateStem = candidateExtension.isEmpty()
                    ? candidate
                    : candidate.substring(0, candidate.length() - candidateExtension.length());
            candidate = candidateStem + sourceExtension;
        }

        int maximumLength = 180;
        if (candidate.length() > maximumLength) {
            String extension = extensionOf(candidate);
            int stemLength = Math.max(1, maximumLength - extension.length());
            candidate = candidate.substring(0, stemLength).stripTrailing() + extension;
        }
        return candidate;
    }

    private static String extensionOf(String filename) {
        int extensionIndex = filename.lastIndexOf('.');
        return extensionIndex > 0 ? filename.substring(extensionIndex) : "";
    }

    public record DownloadGrantRequest(
            @NotBlank @Size(max = 1_024) String artifact_path,
            @NotBlank @Size(max = 255) String filename
    ) {
    }

    public record DownloadGrantResponse(String download_url, int expires_in) {
    }
}
