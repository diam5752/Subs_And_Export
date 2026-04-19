package com.ascentia.subs.jobs;

import com.ascentia.subs.config.AppProperties;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class JobArtifactServiceUnitTest {

    private final JobArtifactService service = new JobArtifactService(new AppProperties());

    @AfterEach
    void cleanDataDirectory() throws IOException {
        Path dataDir = Path.of("data");
        if (Files.notExists(dataDir)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(dataDir)) {
            walk.sorted(Comparator.reverseOrder())
                    .filter(path -> !path.equals(dataDir))
                    .forEach(path -> {
                        try {
                            Files.deleteIfExists(path);
                        } catch (IOException exception) {
                            throw new RuntimeException(exception);
                        }
                    });
        }
    }

    @Test
    void enrichReturnsOriginalForNullIncompleteAndPresetOutputCases() throws Exception {
        assertThat(service.enrich(null)).isNull();

        JobStore.Job pending = new JobStore.Job("pending", "user", "pending", 0, null, 1, 1, Map.of("video_path", "/static/a.mp4"));
        assertThat(service.enrich(pending)).isSameAs(pending);

        JobStore.Job missingResult = new JobStore.Job("missing", "user", "completed", 100, "done", 1, 1, null);
        assertThat(service.enrich(missingResult)).isSameAs(missingResult);

        String presetJobId = uniqueJobId();
        Path presetFile = createFile(Path.of("data", "artifacts", presetJobId, "processed.mp4"), "video");
        JobStore.Job preset = new JobStore.Job(
                presetJobId,
                "user",
                "completed",
                100,
                "done",
                1,
                1,
                Map.of("video_path", "/static/artifacts/" + presetJobId + "/" + presetFile.getFileName(), "output_size", 999L)
        );
        assertThat(service.enrich(preset).resultData()).containsEntry("output_size", 999L);
    }

    @Test
    void enrichHandlesPublicUrlDataPrefixMissingFilesAndFallbackOutputs() throws Exception {
        String publicUrlJobId = uniqueJobId();
        Path publicFile = createFile(Path.of("data", "artifacts", publicUrlJobId, "processed.mp4"), "public");
        JobStore.Job publicUrlJob = new JobStore.Job(
                publicUrlJobId,
                "user",
                "completed",
                100,
                "done",
                1,
                1,
                Map.of("public_url", "/data/artifacts/" + publicUrlJobId + "/" + publicFile.getFileName())
        );
        assertThat(service.enrich(publicUrlJob).resultData()).containsEntry("output_size", Files.size(publicFile));

        String fallbackJobId = uniqueJobId();
        Path fallbackFile = createFile(Path.of("data", "artifacts", fallbackJobId, "processed.mp4"), "fallback");
        JobStore.Job fallbackJob = new JobStore.Job(
                fallbackJobId,
                "user",
                "completed",
                100,
                "done",
                1,
                1,
                Map.of("video_path", "/outside/" + fallbackFile.getFileName())
        );
        assertThat(service.enrich(fallbackJob).resultData()).containsEntry("output_size", Files.size(fallbackFile));

        JobStore.Job missingFileJob = new JobStore.Job(
                uniqueJobId(),
                "user",
                "completed",
                100,
                "done",
                1,
                1,
                Map.of("video_path", "/static/artifacts/missing/processed.mp4")
        );
        assertThat(service.enrich(missingFileJob).resultData()).containsEntry("files_missing", true);
    }

    @Test
    void enrichHandlesBlankVideoPathsNullSizesTraversalFallbackAndNonStringPaths() throws Exception {
        String sizedJobId = uniqueJobId();
        Path sizedFile = createFile(Path.of("data", "artifacts", sizedJobId, "processed.mp4"), "sized");

        Map<String, Object> nullSizeResult = new LinkedHashMap<>();
        nullSizeResult.put("video_path", "data/artifacts/" + sizedJobId + "/" + sizedFile.getFileName());
        nullSizeResult.put("output_size", null);
        JobStore.Job nullSizeJob = new JobStore.Job(sizedJobId, "user", "completed", 100, "done", 1, 1, nullSizeResult);
        assertThat(service.enrich(nullSizeJob).resultData()).containsEntry("output_size", Files.size(sizedFile));

        JobStore.Job blankVideoPathJob = new JobStore.Job(
                sizedJobId,
                "user",
                "completed",
                100,
                "done",
                1,
                1,
                Map.of("video_path", "   ", "public_url", "/data/artifacts/" + sizedJobId + "/" + sizedFile.getFileName())
        );
        assertThat(service.enrich(blankVideoPathJob).resultData()).containsEntry("output_size", Files.size(sizedFile));

        String fallbackJobId = uniqueJobId();
        Path fallbackFile = createFile(Path.of("data", "artifacts", fallbackJobId, "processed.mp4"), "fallback");
        JobStore.Job traversalPathJob = new JobStore.Job(
                fallbackJobId,
                "user",
                "completed",
                100,
                "done",
                1,
                1,
                Map.of("video_path", "../escape.mp4")
        );
        assertThat(service.enrich(traversalPathJob).resultData()).containsEntry("output_size", Files.size(fallbackFile));

        JobStore.Job nonStringVideoPath = new JobStore.Job(
                uniqueJobId(),
                "user",
                "completed",
                100,
                "done",
                1,
                1,
                Map.of("video_path", 123)
        );
        assertThat(service.enrich(nonStringVideoPath).resultData()).containsEntry("files_missing", true);
    }

    @Test
    void deleteArtifactsRemovesKnownUploadExtensionsAndArtifactDirectories() throws Exception {
        String jobId = uniqueJobId();
        Path artifact = createFile(Path.of("data", "artifacts", jobId, "processed.mp4"), "artifact");
        Path mp4 = createFile(Path.of("data", "uploads", jobId + "_input.mp4"), "mp4");
        Path mov = createFile(Path.of("data", "uploads", jobId + "_input.mov"), "mov");
        Path mkv = createFile(Path.of("data", "uploads", jobId + "_input.mkv"), "mkv");

        service.deleteArtifacts(jobId);

        assertThat(Files.exists(artifact)).isFalse();
        assertThat(Files.exists(mp4)).isFalse();
        assertThat(Files.exists(mov)).isFalse();
        assertThat(Files.exists(mkv)).isFalse();

        service.deleteArtifacts("missing-" + jobId);
    }

    private static Path createFile(Path path, String content) throws IOException {
        Files.createDirectories(path.getParent());
        return Files.write(path, content.getBytes(StandardCharsets.UTF_8));
    }

    private static String uniqueJobId() {
        return "job-" + UUID.randomUUID().toString().replace("-", "");
    }
}
