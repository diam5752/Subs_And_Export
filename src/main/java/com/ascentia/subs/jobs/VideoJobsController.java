package com.ascentia.subs.jobs;

import com.ascentia.subs.auth.CurrentUser;
import com.ascentia.subs.auth.CurrentUserAccess;
import com.ascentia.subs.history.HistoryStore;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.Authentication;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@Validated
@RestController
@RequestMapping("/videos")
public class VideoJobsController {

    private final JobStore jobStore;
    private final JobArtifactService jobArtifactService;
    private final HistoryStore historyStore;

    public VideoJobsController(JobStore jobStore, JobArtifactService jobArtifactService, HistoryStore historyStore) {
        this.jobStore = jobStore;
        this.jobArtifactService = jobArtifactService;
        this.historyStore = historyStore;
    }

    @GetMapping("/jobs")
    List<JobResponse> listJobs(Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        return jobStore.listJobsForUser(currentUser.id(), 1_000).stream()
                .map(jobArtifactService::enrich)
                .map(JobResponse::from)
                .toList();
    }

    @GetMapping("/jobs/paginated")
    PaginatedJobsResponse listJobsPaginated(
            @RequestParam(name = "page", defaultValue = "1") int page,
            @RequestParam(name = "page_size", defaultValue = "5") int pageSize,
            Authentication authentication
    ) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        int resolvedPage = Math.max(1, page);
        int resolvedPageSize = Math.min(100, Math.max(1, pageSize));
        int total = jobStore.countJobsForUser(currentUser.id());
        int totalPages = total > 0 ? ((total + resolvedPageSize - 1) / resolvedPageSize) : 1;
        int offset = (resolvedPage - 1) * resolvedPageSize;

        List<JobResponse> items = jobStore.listJobsForUserPaginated(currentUser.id(), offset, resolvedPageSize).stream()
                .map(jobArtifactService::enrich)
                .map(JobResponse::from)
                .toList();

        return new PaginatedJobsResponse(items, total, resolvedPage, resolvedPageSize, totalPages);
    }

    @PostMapping("/jobs/batch-delete")
    BatchDeleteResponse batchDeleteJobs(@Valid @RequestBody BatchDeleteRequest request, Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        if (request.job_ids().isEmpty()) {
            return new BatchDeleteResponse("success", 0, List.of());
        }
        if (request.job_ids().size() > 50) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Cannot delete more than 50 jobs at once");
        }

        List<JobStore.Job> jobs = jobStore.getJobs(request.job_ids(), currentUser.id());
        jobs.forEach(job -> jobArtifactService.deleteArtifacts(job.id()));
        List<String> deletedIds = jobs.stream().map(JobStore.Job::id).toList();
        int deletedCount = jobStore.deleteJobs(deletedIds, currentUser.id());

        if (deletedCount > 0) {
            historyStore.recordEvent(
                    currentUser.id(),
                    currentUser.email(),
                    "jobs_batch_deleted",
                    "Deleted " + deletedCount + " jobs",
                    Map.of("job_ids", deletedIds, "count", deletedCount)
            );
        }

        return new BatchDeleteResponse("deleted", deletedCount, deletedIds);
    }

    @GetMapping("/jobs/{jobId}")
    JobResponse getJob(@PathVariable String jobId, Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        JobStore.Job job = ownedJob(jobId, currentUser.id());
        return JobResponse.from(jobArtifactService.enrich(job));
    }

    @DeleteMapping("/jobs/{jobId}")
    Map<String, String> deleteJob(@PathVariable String jobId, Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        ownedJob(jobId, currentUser.id());
        jobArtifactService.deleteArtifacts(jobId);
        jobStore.deleteJob(jobId);
        historyStore.recordEvent(currentUser.id(), currentUser.email(), "job_deleted", "Deleted job " + jobId, Map.of("job_id", jobId));
        return Map.of("status", "deleted", "job_id", jobId);
    }

    @PostMapping("/jobs/{jobId}/cancel")
    JobResponse cancelJob(@PathVariable String jobId, Authentication authentication) {
        CurrentUser currentUser = CurrentUserAccess.require(authentication);
        JobStore.Job job = ownedJob(jobId, currentUser.id());
        if (!List.of("pending", "processing").contains(job.status())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Cannot cancel job with status '" + job.status() + "'");
        }

        jobStore.updateJob(jobId, "cancelled", null, "Cancelled by user", null);
        historyStore.recordEvent(currentUser.id(), currentUser.email(), "job_cancelled", "Cancelled job " + jobId, Map.of("job_id", jobId));
        return JobResponse.from(jobArtifactService.enrich(jobStore.getJob(jobId).orElseThrow()));
    }

    private JobStore.Job ownedJob(String jobId, String userId) {
        return jobStore.getJob(jobId)
                .filter(job -> userId.equals(job.userId()))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Job not found"));
    }

    public record BatchDeleteRequest(List<@NotBlank String> job_ids) {
    }

    public record BatchDeleteResponse(String status, int deleted_count, List<String> job_ids) {
    }

    public record PaginatedJobsResponse(List<JobResponse> items, int total, int page, int page_size, int total_pages) {
    }

    public record JobResponse(String id, String status, int progress, String message, int created_at, int updated_at, Map<String, Object> result_data, Integer balance) {
        static JobResponse from(JobStore.Job job) {
            return new JobResponse(job.id(), job.status(), job.progress(), job.message(), job.createdAt(), job.updatedAt(), job.resultData(), null);
        }
    }
}
