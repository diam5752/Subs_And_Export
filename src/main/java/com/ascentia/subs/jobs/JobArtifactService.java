package com.ascentia.subs.jobs;

import com.ascentia.subs.config.AppProperties;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.stream.Stream;
import org.springframework.stereotype.Service;

@Service
public class JobArtifactService {

    private static final String[] INPUT_EXTENSIONS = {".mp4", ".mov", ".mkv"};

    private final AppProperties appProperties;

    public JobArtifactService(AppProperties appProperties) {
        this.appProperties = appProperties;
    }

    public JobStore.Job enrich(JobStore.Job job) {
        if (job == null || !"completed".equals(job.status()) || job.resultData() == null) {
            return job;
        }

        Map<String, Object> resultData = new LinkedHashMap<>(job.resultData());
        Path existingOutput = locateOutput(job.id(), resultData);
        if (existingOutput == null) {
            resultData.put("files_missing", true);
        } else if (!resultData.containsKey("output_size") || resultData.get("output_size") == null) {
            try {
                resultData.put("output_size", Files.size(existingOutput));
            } catch (IOException ignored) {
                // Keep the original payload if file metadata cannot be read.
            }
        }

        return new JobStore.Job(job.id(), job.userId(), job.status(), job.progress(), job.message(), job.createdAt(), job.updatedAt(), resultData);
    }

    public void deleteArtifacts(String jobId) {
        deleteRecursively(artifactsRoot().resolve(jobId));
        for (String extension : INPUT_EXTENSIONS) {
            deleteIfExists(uploadsDir().resolve(jobId + "_input" + extension));
        }
    }

    private Path locateOutput(String jobId, Map<String, Object> resultData) {
        Object videoPathValue = resultData.get("video_path");
        if (!(videoPathValue instanceof String) || ((String) videoPathValue).isBlank()) {
            videoPathValue = resultData.get("public_url");
        }

        if (videoPathValue instanceof String videoPath && !videoPath.isBlank()) {
            String cleaned = videoPath.replaceFirst("^/+", "");
            if (cleaned.startsWith("static/")) {
                cleaned = cleaned.substring("static/".length());
            }
            if (cleaned.startsWith("data/")) {
                cleaned = cleaned.substring("data/".length());
            }

            Path candidate = dataDir().resolve(cleaned).normalize();
            if (candidate.startsWith(dataDir()) && Files.isRegularFile(candidate)) {
                return candidate;
            }
        }

        Path fallback = artifactsRoot().resolve(jobId).resolve("processed.mp4");
        return Files.isRegularFile(fallback) ? fallback : null;
    }

    private Path dataDir() {
        return appProperties.dataDir().toAbsolutePath().normalize();
    }

    private Path uploadsDir() {
        return dataDir().resolve("uploads");
    }

    private Path artifactsRoot() {
        return dataDir().resolve("artifacts");
    }

    private void deleteRecursively(Path root) {
        if (Files.notExists(root)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(root)) {
            walk.sorted(Comparator.reverseOrder()).forEach(this::deleteIfExists);
        } catch (IOException ignored) {
            // Best-effort cleanup to preserve endpoint behavior.
        }
    }

    private void deleteIfExists(Path path) {
        try {
            Files.deleteIfExists(path);
        } catch (IOException ignored) {
            // Best-effort cleanup to preserve endpoint behavior.
        }
    }
}
