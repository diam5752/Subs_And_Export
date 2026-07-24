package com.ascentia.subs;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.options;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ApiContractIT extends IntegrationTestSupport {

    @Test
    void healthRootCorsAndStaticContracts() throws Exception {
        writeArtifactFile("static-contract", "hello.txt", "hello".getBytes(StandardCharsets.UTF_8));
        java.nio.file.Files.createDirectories(java.nio.file.Path.of("data", "test-listing"));

        mockMvc.perform(get("/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("ok"))
                .andExpect(jsonPath("$.service").value("greek-sub-publisher-api"));

        mockMvc.perform(get("/"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.message").value("Welcome to the Greek Sub Publisher API"));

        mockMvc.perform(options("/auth/token")
                        .header(HttpHeaders.ORIGIN, "http://localhost:3000")
                        .header(HttpHeaders.ACCESS_CONTROL_REQUEST_METHOD, "POST"))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.ACCESS_CONTROL_ALLOW_ORIGIN, "http://localhost:3000"));

        mockMvc.perform(get("/static/artifacts/static-contract/hello.txt"))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CONTENT_TYPE, org.hamcrest.Matchers.containsString("text/plain")))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.content().string("hello"));

        mockMvc.perform(get("/static/artifacts/static-contract/hello.txt").param("download", "true"))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CONTENT_DISPOSITION, org.hamcrest.Matchers.containsString("attachment")));

        mockMvc.perform(get("/static/artifacts/static-contract/hello.txt")
                        .param("download", "true")
                        .param("filename", "Ε Isous_subs.txt"))
                .andExpect(status().isOk())
                .andExpect(header().string(
                        HttpHeaders.CONTENT_DISPOSITION,
                        org.hamcrest.Matchers.containsString("%CE%95%20Isous_subs.txt")
                ));

        mockMvc.perform(get("/static/test-listing"))
                .andExpect(status().isNotFound());
    }

    @Test
    void authLifecycleExportAndDeletionContract() throws Exception {
        AuthSession session = registerAndLogin("Auth User");

        mockMvc.perform(get("/auth/me").header(HttpHeaders.AUTHORIZATION, session.authorization()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.email").value(session.email()))
                .andExpect(jsonPath("$.name").value("Auth User"));

        mockMvc.perform(get("/auth/points").header(HttpHeaders.AUTHORIZATION, session.authorization()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.balance").value(100));

        mockMvc.perform(put("/auth/me")
                        .header(HttpHeaders.AUTHORIZATION, session.authorization())
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsBytes(Map.of("name", "Updated User"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("Updated User"));

        String googleUrlBody = mockMvc.perform(get("/auth/google/url"))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString();
        JsonNode googleUrl = objectMapper.readTree(googleUrlBody);
        assertThat(googleUrl.get("auth_url").asText()).contains("client_id=test-google-client");
        assertThat(googleUrl.get("state").asText()).isNotBlank();

        mockMvc.perform(post("/auth/google/callback")
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsBytes(Map.of("code", "abc", "state", "xyz"))))
                .andExpect(status().isNotImplemented());

        String jobId = "job-" + session.userId();
        jobStore.createJob(jobId, session.userId());
        jobStore.updateJob(
                jobId,
                "completed",
                100,
                "done",
                Map.of("video_path", "/static/artifacts/" + jobId + "/processed.mp4")
        );
        writeArtifactFile(jobId, "processed.mp4", "video".getBytes(StandardCharsets.UTF_8));
        writeUploadFile(jobId, ".mp4", "upload".getBytes(StandardCharsets.UTF_8));
        historyStore.recordEvent(session.userId(), session.email(), "job_completed", "Completed job " + jobId, Map.of("job_id", jobId));

        String exportBody = mockMvc.perform(get("/auth/export").header(HttpHeaders.AUTHORIZATION, session.authorization()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.profile.email").value(session.email()))
                .andExpect(jsonPath("$.profile.created_at").isNotEmpty())
                .andExpect(jsonPath("$.jobs[0].id").value(jobId))
                .andReturn()
                .getResponse()
                .getContentAsString();
        JsonNode exportJson = objectMapper.readTree(exportBody);
        assertThat(exportJson.get("history").size()).isEqualTo(1);

        mockMvc.perform(put("/auth/password")
                        .header(HttpHeaders.AUTHORIZATION, session.authorization())
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsBytes(Map.of(
                                "password", "newpassword456",
                                "confirmPassword", "newpassword456"
                        ))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("success"));

        mockMvc.perform(get("/auth/me").header(HttpHeaders.AUTHORIZATION, session.authorization()))
                .andExpect(status().isUnauthorized());

        AuthSession refreshedSession = login(session.email(), "newpassword456");

        mockMvc.perform(delete("/auth/me").header(HttpHeaders.AUTHORIZATION, refreshedSession.authorization()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("deleted"));

        mockMvc.perform(get("/auth/me").header(HttpHeaders.AUTHORIZATION, refreshedSession.authorization()))
                .andExpect(status().isUnauthorized());

        assertThat(java.nio.file.Files.exists(java.nio.file.Path.of("data", "artifacts", jobId, "processed.mp4"))).isFalse();
        assertThat(java.nio.file.Files.exists(java.nio.file.Path.of("data", "uploads", jobId + "_input.mp4"))).isFalse();
    }

    @Test
    void historyAndVideoJobRoutesRespectOwnershipAndMutations() throws Exception {
        AuthSession owner = registerAndLogin("Owner");
        AuthSession other = registerAndLogin("Other");

        String completedJobId = "job-completed-" + owner.userId();
        jobStore.createJob(completedJobId, owner.userId());
        jobStore.updateJob(
                completedJobId,
                "completed",
                100,
                "completed",
                Map.of("video_path", "/static/artifacts/" + completedJobId + "/processed.mp4")
        );
        writeArtifactFile(completedJobId, "processed.mp4", "processed".getBytes(StandardCharsets.UTF_8));

        String cancelJobId = "job-cancel-" + owner.userId();
        jobStore.createJob(cancelJobId, owner.userId());
        jobStore.updateJob(cancelJobId, "processing", 50, "working", null);

        String batchJobId = "job-batch-" + owner.userId();
        jobStore.createJob(batchJobId, owner.userId());
        historyStore.recordEvent(owner.userId(), owner.email(), "job_created", "Created jobs", Map.of("job_id", completedJobId));

        mockMvc.perform(get("/history").header(HttpHeaders.AUTHORIZATION, owner.authorization()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].kind").value("job_created"));

        String jobsBody = mockMvc.perform(get("/videos/jobs").header(HttpHeaders.AUTHORIZATION, owner.authorization()))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString();
        JsonNode jobsJson = objectMapper.readTree(jobsBody);
        assertThat(jobsJson).hasSize(3);
        JsonNode completedJob = java.util.stream.StreamSupport.stream(jobsJson.spliterator(), false)
                .filter(node -> completedJobId.equals(node.get("id").asText()))
                .findFirst()
                .orElseThrow();
        assertThat(completedJob.get("result_data").get("output_size").asLong()).isEqualTo(9L);

        mockMvc.perform(get("/videos/jobs/paginated")
                        .header(HttpHeaders.AUTHORIZATION, owner.authorization())
                        .param("page", "0")
                        .param("page_size", "200"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.page").value(1))
                .andExpect(jsonPath("$.page_size").value(100))
                .andExpect(jsonPath("$.total").value(3))
                .andExpect(jsonPath("$.total_pages").value(1));

        mockMvc.perform(get("/videos/jobs/" + completedJobId).header(HttpHeaders.AUTHORIZATION, other.authorization()))
                .andExpect(status().isNotFound());

        mockMvc.perform(post("/videos/jobs/" + cancelJobId + "/cancel").header(HttpHeaders.AUTHORIZATION, owner.authorization()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("cancelled"))
                .andExpect(jsonPath("$.message").value("Cancelled by user"));

        writeUploadFile(completedJobId, ".mp4", "upload".getBytes(StandardCharsets.UTF_8));
        mockMvc.perform(delete("/videos/jobs/" + completedJobId).header(HttpHeaders.AUTHORIZATION, owner.authorization()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("deleted"))
                .andExpect(jsonPath("$.job_id").value(completedJobId));

        assertThat(java.nio.file.Files.exists(java.nio.file.Path.of("data", "artifacts", completedJobId, "processed.mp4"))).isFalse();

        mockMvc.perform(post("/videos/jobs/batch-delete")
                        .header(HttpHeaders.AUTHORIZATION, owner.authorization())
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsBytes(Map.of("job_ids", List.of(cancelJobId, batchJobId)))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.deleted_count").value(2))
                .andExpect(jsonPath("$.job_ids.length()").value(2));

        assertThat(jobStore.countJobsForUser(owner.userId())).isZero();
    }
}
