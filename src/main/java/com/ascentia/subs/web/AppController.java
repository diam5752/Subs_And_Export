package com.ascentia.subs.web;

import com.ascentia.subs.common.ClientIpResolver;
import com.ascentia.subs.common.RateLimitService;
import com.ascentia.subs.config.AppProperties;
import com.ascentia.subs.auth.CurrentUser;
import com.ascentia.subs.auth.CurrentUserAccess;
import com.ascentia.subs.jobs.JobStore;
import jakarta.servlet.http.HttpServletRequest;
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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import static org.springframework.http.HttpStatus.NOT_FOUND;

@RestController
public class AppController {

    private final AppProperties appProperties;
    private final RateLimitService rateLimitService;
    private final ClientIpResolver clientIpResolver;
    private final JobStore jobStore;

    public AppController(
            AppProperties appProperties,
            RateLimitService rateLimitService,
            ClientIpResolver clientIpResolver,
            JobStore jobStore
    ) {
        this.appProperties = appProperties;
        this.rateLimitService = rateLimitService;
        this.clientIpResolver = clientIpResolver;
        this.jobStore = jobStore;
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
            HttpServletRequest request,
            Authentication authentication
    ) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        String ip = clientIpResolver.resolve(request);
        rateLimitService.check("static", ip, appProperties.getStaticRateLimit(), appProperties.getStaticRateLimitWindow());

        Path dataDir = appProperties.dataDir().toAbsolutePath().normalize();
        String cleanedPath = filePath == null ? "" : filePath.replaceFirst("^/+", "");
        String artifactPrefix = "artifacts/";
        if (!cleanedPath.startsWith(artifactPrefix)) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }
        String artifactPath = cleanedPath.substring(artifactPrefix.length());
        int separator = artifactPath.indexOf('/');
        if (separator <= 0 || separator == artifactPath.length() - 1) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }
        String jobId = artifactPath.substring(0, separator);
        JobStore.Job job = jobStore.getJob(jobId)
                .filter(candidate -> currentUser.id().equals(candidate.userId()))
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "File not found"));

        Path artifactsRoot = dataDir.resolve("artifacts").normalize();
        Path jobRoot = artifactsRoot.resolve(job.id()).normalize();
        Path resolvedPath = artifactsRoot.resolve(artifactPath).normalize();
        if (!jobRoot.getParent().equals(artifactsRoot)
                || !resolvedPath.startsWith(jobRoot)
                || !Files.isDirectory(jobRoot, LinkOption.NOFOLLOW_LINKS)) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }
        if (Files.isDirectory(resolvedPath, LinkOption.NOFOLLOW_LINKS)) {
            throw new ResponseStatusException(NOT_FOUND, "Not found");
        }
        if (!Files.isRegularFile(resolvedPath, LinkOption.NOFOLLOW_LINKS)) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }

        try {
            Path current = jobRoot;
            Path relativeFile = jobRoot.relativize(resolvedPath);
            for (Path component : relativeFile) {
                current = current.resolve(component);
                if (Files.isSymbolicLink(current)) {
                    throw new ResponseStatusException(NOT_FOUND, "File not found");
                }
            }
            Path realJobRoot = jobRoot.toRealPath();
            Path realFile = resolvedPath.toRealPath();
            if (!realFile.startsWith(realJobRoot)) {
                throw new ResponseStatusException(NOT_FOUND, "File not found");
            }
        } catch (java.io.IOException exception) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }

        Resource resource = new FileSystemResource(resolvedPath);
        MediaType mediaType = MediaTypeFactory.getMediaType(resource).orElse(MediaType.APPLICATION_OCTET_STREAM);
        ResponseEntity.BodyBuilder response = ResponseEntity.ok()
                .contentType(mediaType)
                .header(HttpHeaders.CACHE_CONTROL, "private, no-store");
        if (download || isVideoDownload(resolvedPath.getFileName().toString())) {
            String downloadFilename = sanitizeDownloadFilename(
                    filename,
                    resolvedPath.getFileName().toString()
            );
            response.header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                    .filename(downloadFilename, StandardCharsets.UTF_8)
                    .build()
                    .toString());
        }
        return response.body(resource);
    }

    private static boolean isVideoDownload(String filename) {
        String normalized = filename.toLowerCase();
        return normalized.endsWith(".mp4")
                || normalized.endsWith(".mov")
                || normalized.endsWith(".avi")
                || normalized.endsWith(".webm")
                || normalized.endsWith(".mkv");
    }

    static String sanitizeDownloadFilename(String requested, String sourceFilename) {
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
}
