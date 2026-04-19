package com.ascentia.subs;

import com.ascentia.subs.auth.CurrentUser;
import com.ascentia.subs.jobs.JobStore;
import com.ascentia.subs.points.PointsStore;
import com.ascentia.subs.usage.UsageLedgerStore;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class StoreBehaviorIT extends IntegrationTestSupport {

    @Test
    void authStoreSupportsPasswordSessionsOauthAndDeletedEmails() {
        CurrentUser local = authStore.registerLocalUser(uniqueEmail(), "testpassword123", "Local User");
        assertThat(authStore.authenticateLocal(local.email(), "testpassword123")).isPresent();

        String token = authStore.issueSession(local, "JUnit");
        assertThat(authStore.authenticateToken(token)).isPresent();

        authStore.updateName(local.id(), "Renamed User");
        assertThat(authStore.findUserById(local.id())).get().extracting(CurrentUser::name).isEqualTo("Renamed User");

        authStore.updatePassword(local.id(), "newpassword456");
        authStore.revokeAllSessions(local.id());
        assertThat(authStore.authenticateToken(token)).isEmpty();
        assertThat(authStore.authenticateLocal(local.email(), "newpassword456")).isPresent();

        String oauthState = authStore.issueOauthState("google", null, "JUnit", "127.0.0.1", 300);
        assertThat(authStore.consumeOauthState("google", oauthState, null, "JUnit", "127.0.0.1")).isTrue();
        assertThat(authStore.consumeOauthState("google", oauthState, null, "JUnit", "127.0.0.1")).isFalse();

        CurrentUser google = authStore.upsertGoogleUser(uniqueEmail(), "Google User", "google-sub");
        assertThat(pointsStore.getBalance(google.id())).isEqualTo(PointsStore.STARTING_POINTS_BALANCE);

        authStore.deleteUser(local.id());
        assertThat(authStore.findUserById(local.id())).isEmpty();

        CurrentUser reregistered = authStore.registerLocalUser(local.email(), "anotherpassword123", "Recreated");
        assertThat(pointsStore.getBalance(reregistered.id())).isZero();
    }

    @Test
    void pointsUsageLedgerJobsHistoryAndRateLimitBehaveConsistently() {
        CurrentUser user = authStore.registerLocalUser(uniqueEmail(), "testpassword123", "Points User");

        assertThat(pointsStore.getBalance(user.id())).isEqualTo(PointsStore.TRIAL_CREDITS);
        assertThat(pointsStore.spend(user.id(), 10, "transcription", Map.of("job_id", "j1"))).isEqualTo(90);

        PointsStore.SpendOnceResult firstSpend = pointsStore.spendOnce(
                user.id(),
                15,
                "fact_check",
                PointsStore.makeIdempotencyId("fact", "j1"),
                Map.of("job_id", "j1")
        );
        PointsStore.SpendOnceResult repeatedSpend = pointsStore.spendOnce(
                user.id(),
                15,
                "fact_check",
                PointsStore.makeIdempotencyId("fact", "j1"),
                Map.of("job_id", "j1")
        );
        assertThat(firstSpend.applied()).isTrue();
        assertThat(repeatedSpend.applied()).isFalse();
        assertThat(repeatedSpend.balance()).isEqualTo(firstSpend.balance());

        assertThat(pointsStore.refund(user.id(), 5, "fact_check", Map.of("job_id", "j1"))).isEqualTo(80);
        assertThat(pointsStore.refundOnce(
                user.id(),
                5,
                "fact_check",
                PointsStore.makeIdempotencyId("refund", "j1"),
                Map.of("job_id", "j1")
        )).isEqualTo(85);

        jobStore.createJob("job-usage", user.id());
        UsageLedgerStore.ReserveResult reserved = usageLedgerStore.reserve(
                user.id(),
                "job-usage",
                "social_copy",
                "openai",
                "gpt-5.1-mini",
                "standard",
                20,
                10,
                0.25d,
                Map.of("seconds", 30),
                "usage-key",
                "/videos/jobs/job-usage/social-copy",
                "USD"
        );
        assertThat(reserved.balance()).isEqualTo(65);

        int afterFinalize = usageLedgerStore.finalize(
                reserved.reservation(),
                12,
                0.10d,
                Map.of("seconds", 25),
                "completed"
        );
        assertThat(afterFinalize).isEqualTo(73);
        jobStore.updateJob("job-usage", "completed", 100, "completed", null);

        jobStore.createJob("job-fail", user.id());
        UsageLedgerStore.ReserveResult failed = usageLedgerStore.reserve(
                user.id(),
                "job-fail",
                "fact_check",
                "openai",
                "gpt-5.1-mini",
                "standard",
                10,
                10,
                0.20d,
                Map.of("seconds", 10),
                "usage-fail",
                "/videos/jobs/job-fail/fact-check",
                "USD"
        );
        int afterFail = usageLedgerStore.refundIfReserved(failed.reservation(), "failed", "boom");
        assertThat(afterFail).isEqualTo(73);
        jobStore.updateJob("job-fail", "failed", 100, "boom", null);
        assertThat(usageLedgerStore.summarize(0, Integer.MAX_VALUE, "action"))
                .extracting(UsageLedgerStore.UsageSummaryRow::bucket)
                .contains("social_copy", "fact_check");

        String activeJobId = "job-active";
        jobStore.createJob(activeJobId, user.id());
        jobStore.updateJob(activeJobId, "processing", 25, "running", Map.of("step", "encode"));
        assertThat(jobStore.countJobsForUser(user.id())).isEqualTo(3);
        assertThat(jobStore.countActiveJobsForUser(user.id())).isEqualTo(1);
        assertThat(jobStore.listJobsCreatedBefore(Integer.MAX_VALUE)).extracting(JobStore.Job::id).contains(activeJobId);

        historyStore.recordEvent(user.id(), user.email(), "job_started", "Started job", Map.of("job_id", activeJobId));
        assertThat(historyStore.recentForUser(user.id(), 10)).hasSize(1);

        jobStore.deleteJob(activeJobId);
        assertThat(jobStore.getJob(activeJobId)).isEmpty();

        rateLimitServiceBlocksAfterThreshold(user.id());
    }

    @Test
    void usageLedgerAndJobStoreCoverReservationLifecycleAndSummaryBranches() {
        CurrentUser user = authStore.registerLocalUser(uniqueEmail(), "testpassword123", "Ledger User");

        String refundJobId = "job-refund";
        jobStore.createJob(refundJobId, user.id());
        UsageLedgerStore.ReserveResult refundReservation = usageLedgerStore.reserve(
                user.id(),
                refundJobId,
                "transcription",
                "openai",
                "gpt-5.1-mini",
                null,
                20,
                5,
                0.20d,
                Map.of("seconds", 20),
                "ledger-refund",
                "/videos/jobs/" + refundJobId,
                "USD"
        );
        UsageLedgerStore.ReserveResult duplicateReservation = usageLedgerStore.reserve(
                user.id(),
                refundJobId,
                "transcription",
                "openai",
                "gpt-5.1-mini",
                null,
                20,
                5,
                0.20d,
                Map.of("seconds", 20),
                "ledger-refund",
                "/videos/jobs/" + refundJobId,
                "USD"
        );
        assertThat(duplicateReservation.reservation().ledgerId()).isEqualTo(refundReservation.reservation().ledgerId());
        assertThat(duplicateReservation.balance()).isEqualTo(refundReservation.balance());
        assertThat(usageLedgerStore.finalize(refundReservation.reservation(), 6, 0.06d, Map.of("seconds", 6), "completed"))
                .isEqualTo(94);
        jobStore.updateJob(refundJobId, "completed", 100, "completed", null);

        String overageJobId = "job-overage";
        jobStore.createJob(overageJobId, user.id());
        UsageLedgerStore.ReserveResult overageReservation = usageLedgerStore.reserve(
                user.id(),
                overageJobId,
                "social_copy",
                "openai",
                "gpt-5.1-mini",
                "standard",
                10,
                5,
                0.10d,
                Map.of("seconds", 10),
                "ledger-overage",
                "/videos/jobs/" + overageJobId,
                "USD"
        );
        assertThat(usageLedgerStore.finalize(overageReservation.reservation(), 15, 0.15d, Map.of("seconds", 15), "completed"))
                .isEqualTo(79);
        jobStore.updateJob(overageJobId, "completed", 100, "completed", null);

        String failedJobId = "job-failed";
        jobStore.createJob(failedJobId, user.id());
        UsageLedgerStore.ReserveResult failedReservation = usageLedgerStore.reserve(
                user.id(),
                failedJobId,
                "fact_check",
                "openai",
                "gpt-5.1-mini",
                "pro",
                12,
                10,
                0.12d,
                Map.of("seconds", 12),
                "ledger-failed",
                "/videos/jobs/" + failedJobId,
                "USD"
        );
        assertThat(usageLedgerStore.refundIfReserved(failedReservation.reservation(), "failed", "x".repeat(600)))
                .isEqualTo(79);
        jobStore.updateJob(failedJobId, "failed", 100, "failed", null);
        assertThat(usageLedgerStore.refundIfReserved(refundReservation.reservation(), "ignored", "ignored"))
                .isEqualTo(79);
        assertThat(usageLedgerStore.refundIfReserved(
                new UsageLedgerStore.ChargeReservation("missing", user.id(), null, "noop", "openai", null, null, 0, 0, "missing"),
                "ignored",
                null
        )).isEqualTo(79);

        assertThat(jdbcClient.sql("SELECT char_length(error) FROM usage_ledger WHERE id = :ledgerId")
                .param("ledgerId", failedReservation.reservation().ledgerId())
                .query(Integer.class)
                .single()).isEqualTo(500);
        assertThat(jdbcClient.sql("SELECT status FROM usage_ledger WHERE id = :ledgerId")
                .param("ledgerId", failedReservation.reservation().ledgerId())
                .query(String.class)
                .single()).isEqualTo("failed");
        assertThat(usageLedgerStore.pointsStore()).isSameAs(pointsStore);
        assertThat(new UsageLedgerStore.ChargePlan(refundReservation.reservation(), overageReservation.reservation()).socialCopy())
                .isEqualTo(overageReservation.reservation());

        String currentDay = DateTimeFormatter.ofPattern("yyyy-MM-dd")
                .format(LocalDateTime.ofEpochSecond(Instant.now().getEpochSecond(), 0, ZoneOffset.UTC));
        String currentMonth = DateTimeFormatter.ofPattern("yyyy-MM")
                .format(LocalDateTime.ofEpochSecond(Instant.now().getEpochSecond(), 0, ZoneOffset.UTC));

        assertThat(usageLedgerStore.summarize(0, Integer.MAX_VALUE, "day"))
                .singleElement()
                .extracting(UsageLedgerStore.UsageSummaryRow::bucket)
                .isEqualTo(currentDay);
        assertThat(usageLedgerStore.summarize(0, Integer.MAX_VALUE, "month"))
                .singleElement()
                .extracting(UsageLedgerStore.UsageSummaryRow::bucket)
                .isEqualTo(currentMonth);
        assertThat(usageLedgerStore.summarize(0, Integer.MAX_VALUE, "user"))
                .singleElement()
                .extracting(UsageLedgerStore.UsageSummaryRow::bucket)
                .isEqualTo(user.id());
        assertThat(usageLedgerStore.summarize(0, Integer.MAX_VALUE, "action"))
                .extracting(UsageLedgerStore.UsageSummaryRow::bucket)
                .containsExactlyInAnyOrder("transcription", "social_copy", "fact_check");
        assertThatThrownBy(() -> usageLedgerStore.summarize(10, 9, "day"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("start_ts");
        assertThatThrownBy(() -> usageLedgerStore.summarize(0, 10, "invalid"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("group_by");

        String noOpJobId = "job-noop";
        jobStore.createJob(noOpJobId, user.id());
        jobStore.updateJob(noOpJobId, null, null, null, null);
        jobStore.updateJob("missing-job", "completed", 100, "done", Map.of("ignored", true));
        jobStore.updateJob(noOpJobId, null, 20, null, null);
        assertThat(jobStore.getJob(noOpJobId)).get().extracting(JobStore.Job::progress).isEqualTo(20);
        assertThat(jobStore.getJobs(List.of(), user.id())).isEmpty();
        assertThat(jobStore.deleteJobs(List.of(), user.id())).isZero();
        assertThat(jobStore.countActiveJobsForUser(user.id())).isEqualTo(1);
        assertThat(jobStore.listJobsCreatedBefore(Integer.MAX_VALUE)).extracting(JobStore.Job::id)
                .contains(refundJobId, overageJobId, failedJobId, noOpJobId);
    }

    @Test
    void authAndPointsStoresCoverValidationAndMismatchPaths() {
        CurrentUser user = authStore.registerLocalUser(uniqueEmail(), "letters123456", null);
        assertThat(user.name()).isEqualTo(user.email().substring(0, user.email().indexOf('@')));
        assertThat(authStore.authenticateLocal(user.email(), "wrongpassword123")).isEmpty();
        assertThat(authStore.authenticateToken(null)).isEmpty();
        assertThat(authStore.authenticateToken(" ")).isEmpty();

        assertThatThrownBy(() -> authStore.registerLocalUser("bad-email", "letters123456", "Bad"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Invalid email");
        assertThatThrownBy(() -> authStore.registerLocalUser(uniqueEmail(), "short1", "Bad"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("at least 12");
        assertThatThrownBy(() -> authStore.registerLocalUser(uniqueEmail(), "lettersonlyyy", "Bad"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("letters and numbers");
        assertThatThrownBy(() -> authStore.registerLocalUser(uniqueEmail(), "123456789012", "Bad"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("letters and numbers");
        assertThatThrownBy(() -> authStore.registerLocalUser(uniqueEmail(), "letters123456", "x".repeat(101)))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("100 characters");
        assertThatThrownBy(() -> authStore.registerLocalUser(user.email(), "letters123456", "Duplicate"))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("already exists");

        CurrentUser googleUser = authStore.upsertGoogleUser(user.email(), "Google User", "google-sub-updated");
        assertThat(googleUser.provider()).isEqualTo("google");
        assertThat(authStore.findUserById(user.id())).get()
                .extracting(CurrentUser::provider, CurrentUser::passwordHash, CurrentUser::emailVerified)
                .containsExactly("google", null, true);

        String stateWithUserId = authStore.issueOauthState("google", user.id(), "JUnit", "127.0.0.1", 1);
        assertThat(authStore.consumeOauthState("github", stateWithUserId, user.id(), "JUnit", "127.0.0.1")).isFalse();

        String stateWithUserMismatch = authStore.issueOauthState("google", user.id(), "JUnit", "127.0.0.1", 60);
        assertThat(authStore.consumeOauthState("google", stateWithUserMismatch, "other-user", "JUnit", "127.0.0.1")).isFalse();

        String stateWithAgentMismatch = authStore.issueOauthState("google", null, "JUnit", "127.0.0.1", 60);
        assertThat(authStore.consumeOauthState("google", stateWithAgentMismatch, null, "Other", "127.0.0.1")).isFalse();

        String stateWithIpMismatch = authStore.issueOauthState("google", null, "JUnit", "127.0.0.1", 60);
        assertThat(authStore.consumeOauthState("google", stateWithIpMismatch, null, "JUnit", "127.0.0.2")).isFalse();

        String validState = authStore.issueOauthState("google", null, "JUnit", "127.0.0.1", 60);
        assertThat(authStore.consumeOauthState("google", validState, null, "JUnit", "127.0.0.1")).isTrue();
        assertThat(authStore.consumeOauthState("google", validState, null, "JUnit", "127.0.0.1")).isFalse();

        assertThatThrownBy(() -> pointsStore.ensureAccount(user.id(), null, -1))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Invalid starting balance");
        assertThatThrownBy(() -> pointsStore.spend(user.id(), 1_000, "spend", Map.of()))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Insufficient points");
        assertThatThrownBy(() -> pointsStore.spend(user.id(), 0, "spend", Map.of()))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Invalid cost");
        assertThatThrownBy(() -> pointsStore.credit(user.id(), 0, "credit", Map.of()))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Invalid amount");
        assertThatThrownBy(() -> pointsStore.spendOnce(user.id(), 1, "spend", "", Map.of()))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("transaction id");
        assertThatThrownBy(() -> pointsStore.refundOnce(user.id(), 1, "", "txid", Map.of()))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Invalid reason");

        assertThat(PointsStore.refundReason(null)).isEqualTo("refund_unknown");
        assertThat(PointsStore.refundReason("   ")).isEqualTo("refund_unknown");
        assertThat(PointsStore.refundReason("x".repeat(100))).hasSize(64);
        assertThat(PointsStore.makeIdempotencyId("a", "b"))
                .hasSize(32)
                .isEqualTo(PointsStore.makeIdempotencyId("a", "b"));
    }

    private void rateLimitServiceBlocksAfterThreshold(String subject) {
        assertThatThrownBy(() -> {
            for (int attempt = 0; attempt < 3; attempt++) {
                new com.ascentia.subs.common.RateLimitService(jdbcClient).check("login", subject, 2, 60);
            }
        }).isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("Too many requests");
    }
}
