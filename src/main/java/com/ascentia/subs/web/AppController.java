package com.ascentia.subs.web;

import com.ascentia.subs.common.ClientIpResolver;
import com.ascentia.subs.common.RateLimitService;
import com.ascentia.subs.config.AppProperties;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.springframework.core.io.PathResource;
import org.springframework.core.io.Resource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.MediaTypeFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import static org.springframework.http.HttpStatus.FORBIDDEN;
import static org.springframework.http.HttpStatus.NOT_FOUND;

@RestController
public class AppController {

    private final AppProperties appProperties;
    private final RateLimitService rateLimitService;
    private final ClientIpResolver clientIpResolver;

    public AppController(AppProperties appProperties, RateLimitService rateLimitService, ClientIpResolver clientIpResolver) {
        this.appProperties = appProperties;
        this.rateLimitService = rateLimitService;
        this.clientIpResolver = clientIpResolver;
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
            HttpServletRequest request
    ) {
        String ip = clientIpResolver.resolve(request);
        rateLimitService.check("static", ip, appProperties.getStaticRateLimit(), appProperties.getStaticRateLimitWindow());

        Path dataDir = appProperties.dataDir().toAbsolutePath().normalize();
        String cleanedPath = filePath == null ? "" : filePath.replaceFirst("^/+", "");
        Path resolvedPath = dataDir.resolve(cleanedPath).normalize();
        if (!resolvedPath.startsWith(dataDir)) {
            throw new ResponseStatusException(FORBIDDEN, "Access denied");
        }
        if (Files.isDirectory(resolvedPath)) {
            throw new ResponseStatusException(NOT_FOUND, "Not found");
        }
        if (!Files.isRegularFile(resolvedPath)) {
            throw new ResponseStatusException(NOT_FOUND, "File not found");
        }

        PathResource resource = new PathResource(resolvedPath);
        MediaType mediaType = MediaTypeFactory.getMediaType(resource).orElse(MediaType.APPLICATION_OCTET_STREAM);
        ResponseEntity.BodyBuilder response = ResponseEntity.ok().contentType(mediaType);
        if (download || isVideoDownload(resolvedPath.getFileName().toString())) {
            response.header(HttpHeaders.CONTENT_DISPOSITION, ContentDisposition.attachment()
                    .filename(resolvedPath.getFileName().toString())
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
}
