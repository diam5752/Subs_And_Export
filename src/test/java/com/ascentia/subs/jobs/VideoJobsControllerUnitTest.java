package com.ascentia.subs.jobs;

import com.ascentia.subs.auth.CurrentUser;
import com.ascentia.subs.history.HistoryStore;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class VideoJobsControllerUnitTest {

    @Test
    void listJobsPaginatedReturnsSingleEmptyPageWhenNoJobsExist() {
        JobStore jobStore = mock(JobStore.class);
        when(jobStore.countJobsForUser("user-1")).thenReturn(0);
        when(jobStore.listJobsForUserPaginated("user-1", 0, 1)).thenReturn(List.of());

        VideoJobsController controller = new VideoJobsController(jobStore, mock(JobArtifactService.class), mock(HistoryStore.class));
        VideoJobsController.PaginatedJobsResponse response = controller.listJobsPaginated(0, 0, authentication());

        assertThat(response.items()).isEmpty();
        assertThat(response.total()).isZero();
        assertThat(response.page()).isEqualTo(1);
        assertThat(response.page_size()).isEqualTo(1);
        assertThat(response.total_pages()).isEqualTo(1);
    }

    @Test
    void batchDeleteReturnsEarlyRejectsOversizedRequestsAndSkipsHistoryWhenNothingOwned() {
        JobStore jobStore = mock(JobStore.class);
        HistoryStore historyStore = mock(HistoryStore.class);
        VideoJobsController controller = new VideoJobsController(jobStore, mock(JobArtifactService.class), historyStore);

        assertThat(controller.batchDeleteJobs(new VideoJobsController.BatchDeleteRequest(List.of()), authentication()))
                .extracting(
                        VideoJobsController.BatchDeleteResponse::status,
                        VideoJobsController.BatchDeleteResponse::deleted_count,
                        VideoJobsController.BatchDeleteResponse::job_ids
                )
                .containsExactly("success", 0, List.of());

        assertThatThrownBy(() -> controller.batchDeleteJobs(
                new VideoJobsController.BatchDeleteRequest(java.util.Collections.nCopies(51, "job")),
                authentication()
        )).isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Cannot delete more than 50 jobs at once");

        when(jobStore.getJobs(List.of("missing-1", "missing-2"), "user-1")).thenReturn(List.of());
        when(jobStore.deleteJobs(List.of(), "user-1")).thenReturn(0);

        assertThat(controller.batchDeleteJobs(
                new VideoJobsController.BatchDeleteRequest(List.of("missing-1", "missing-2")),
                authentication()
        )).extracting(
                VideoJobsController.BatchDeleteResponse::status,
                VideoJobsController.BatchDeleteResponse::deleted_count,
                VideoJobsController.BatchDeleteResponse::job_ids
        ).containsExactly("deleted", 0, List.of());

        verifyNoInteractions(historyStore);
    }

    @Test
    void cancelJobRejectsCompletedJobs() {
        JobStore jobStore = mock(JobStore.class);
        when(jobStore.getJob("job-1")).thenReturn(Optional.of(new JobStore.Job(
                "job-1",
                "user-1",
                "completed",
                100,
                "done",
                1,
                1,
                Map.of()
        )));

        VideoJobsController controller = new VideoJobsController(jobStore, mock(JobArtifactService.class), mock(HistoryStore.class));

        assertThatThrownBy(() -> controller.cancelJob("job-1", authentication()))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Cannot cancel job with status 'completed'");
    }

    private static Authentication authentication() {
        return new UsernamePasswordAuthenticationToken(
                new CurrentUser("user-1", "user@example.com", "User", "local", null, null, "2026-01-01T00:00:00Z", true),
                "token"
        );
    }
}
