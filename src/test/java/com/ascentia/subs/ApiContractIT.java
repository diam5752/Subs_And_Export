package com.ascentia.subs;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.Cookie;
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
        AuthSession owner = registerAndLogin("Static Owner");
        AuthSession other = registerAndLogin("Static Other");
        jobStore.createJob("static-contract", owner.userId());
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
                .andExpect(status().isUnauthorized());

        mockMvc.perform(get("/static/artifacts/static-contract/hello.txt")
                        .header(HttpHeaders.AUTHORIZATION, other.authorization()))
                .andExpect(status().isNotFound());

        mockMvc.perform(get("/static/artifacts/static-contract/hello.txt")
                        .cookie(new Cookie("gsubs_media_session", owner.token())))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "private, no-store"))
                .andExpect(header().string(HttpHeaders.CONTENT_TYPE, org.hamcrest.Matchers.containsString("text/plain")))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.content().string("hello"));

        mockMvc.perform(get("/static/artifacts/static-contract/hello.txt")
                        .header(HttpHeaders.AUTHORIZATION, owner.authorization())
                        .param("download", "true"))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CONTENT_DISPOSITION, org.hamcrest.Matchers.containsString("attachment")));

        mockMvc.perform(get("/static/artifacts/static-contract/hello.txt")
                        .header(HttpHeaders.AUTHORIZATION, owner.authorization())
                        .param("download", "true")
                        .param("filename", "Ε Isous_subs.txt"))
                .andExpect(status().isOk())
                .andExpect(header().string(
                        HttpHeaders.CONTENT_DISPOSITION,
                        org.hamcrest.Matchers.containsString("%CE%95%20Isous_subs.txt")
                ));

        String grantBody = mockMvc.perform(post("/videos/jobs/static-contract/download-grant")
                        .header(HttpHeaders.AUTHORIZATION, owner.authorization())
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsBytes(Map.of(
                                "artifact_path", "/static/artifacts/static-contract/hello.txt",
                                "filename", "Δοκιμή_subs.txt"
                        ))))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "private, no-store"))
                .andExpect(header().string("Referrer-Policy", "no-referrer"))
                .andExpect(jsonPath("$.expires_in").value(300))
                .andReturn()
                .getResponse()
                .getContentAsString();
        String grantUrl = objectMapper.readTree(grantBody).get("download_url").asText();
        mockMvc.perform(get(grantUrl))
                .andExpect(status().isOk())
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "private, no-store"))
                .andExpect(header().string("Referrer-Policy", "no-referrer"))
                .andExpect(header().string("X-Robots-Tag", "noindex, nofollow"))
                .andExpect(header().string(
                        HttpHeaders.CONTENT_DISPOSITION,
                        org.hamcrest.Matchers.containsString("%CE%94%CE%BF%CE%BA%CE%B9%CE%BC%CE%AE_subs.txt")
                ))
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.content().string("hello"));

        int signatureStart = grantUrl.lastIndexOf('.') + 1;
        char signatureFirst = grantUrl.charAt(signatureStart);
        String tamperedGrantUrl = grantUrl.substring(0, signatureStart)
                + (signatureFirst == 'a' ? 'b' : 'a')
                + grantUrl.substring(signatureStart + 1);
        mockMvc.perform(get(tamperedGrantUrl))
                .andExpect(status().isUnauthorized());

        mockMvc.perform(post("/videos/jobs/static-contract/download-grant")
                        .header(HttpHeaders.AUTHORIZATION, other.authorization())
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsBytes(Map.of(
                                "artifact_path", "/static/artifacts/static-contract/hello.txt",
                                "filename", "video.txt"
                        ))))
                .andExpect(status().isNotFound());

        for (String invalidPath : List.of(
                "/static/artifacts/other-job/hello.txt",
                "/static/artifacts/static-contract/bad\\name.txt",
                "/static/artifacts/static-contract/%68ello.txt",
                "/static/artifacts/static-contract/hello.txt?download=true",
                "/static/artifacts/static-contract/hello.txt#fragment",
                "/static/artifacts/static-contract/https://evil.example/file.txt",
                "/static/artifacts/static-contract//hello.txt",
                "/static/artifacts/static-contract/./hello.txt",
                "/static/artifacts/static-contract/../hello.txt"
        )) {
            mockMvc.perform(post("/videos/jobs/static-contract/download-grant")
                            .header(HttpHeaders.AUTHORIZATION, owner.authorization())
                            .contentType(APPLICATION_JSON)
                            .content(objectMapper.writeValueAsBytes(Map.of(
                                    "artifact_path", invalidPath,
                                    "filename", "video.txt"
                            ))))
                    .andExpect(status().isBadRequest());
        }

        mockMvc.perform(get("/static/test-listing")
                        .header(HttpHeaders.AUTHORIZATION, owner.authorization()))
                .andExpect(status().isNotFound());
    }

    @Test
    void authLifecycleExportAndDeletionContract() throws Exception {
        AuthSession session = registerAndLogin("Auth User");

        mockMvc.perform(get("/auth/me").header(HttpHeaders.AUTHORIZATION, session.authorization()))
                .andExpect(status().isOk())
                .andExpect(header().string(
                        HttpHeaders.SET_COOKIE,
                        org.hamcrest.Matchers.containsString("gsubs_media_session=")
                ))
                .andExpect(jsonPath("$.email").value(session.email()))
                .andExpect(jsonPath("$.name").value("Auth User"));

        mockMvc.perform(get("/auth/points").header(HttpHeaders.AUTHORIZATION, session.authorization()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.balance").value(0));

        mockMvc.perform(put("/auth/me")
                        .header(HttpHeaders.AUTHORIZATION, session.authorization())
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsBytes(Map.of("name", "Updated User"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("Updated User"));

        String googleNonceBody = mockMvc.perform(get("/auth/google/nonce"))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString();
        JsonNode googleNonce = objectMapper.readTree(googleNonceBody);
        assertThat(googleNonce.get("client_id").asText()).isEqualTo("test-google-client");
        assertThat(googleNonce.get("nonce").asText()).isNotBlank();
        assertThat(googleNonce.get("expires_in").asInt()).isEqualTo(600);

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
    void logoutRevokesOnlyThePresentedSessionAndExpiresTheMediaCookie() throws Exception {
        AuthSession current = registerAndLogin("Logout User");
        AuthSession other = login(current.email(), current.password());

        // REGRESSION: the Java compatibility surface issued a 30-day media
        // cookie but exposed no normal endpoint that revoked its exact session.
        mockMvc.perform(post("/auth/logout"))
                .andExpect(status().isUnauthorized());

        // The media cookie is intentionally read-only and path-scoped. It must
        // never authenticate a mutation even though this stateless bearer API
        // does not use a synchronizer CSRF token.
        mockMvc.perform(post("/auth/logout")
                        .cookie(new Cookie("gsubs_media_session", current.token())))
                .andExpect(status().isUnauthorized());

        mockMvc.perform(post("/auth/logout")
                        .header(HttpHeaders.AUTHORIZATION, current.authorization()))
                .andExpect(status().isOk())
                .andExpect(header().string(
                        HttpHeaders.SET_COOKIE,
                        org.hamcrest.Matchers.allOf(
                                org.hamcrest.Matchers.containsString("gsubs_media_session="),
                                org.hamcrest.Matchers.containsString("Max-Age=0"),
                                org.hamcrest.Matchers.containsString("Path=/static")
                        )
                ))
                .andExpect(header().string(HttpHeaders.CACHE_CONTROL, "no-store"))
                .andExpect(jsonPath("$.status").value("success"));

        mockMvc.perform(get("/auth/me")
                        .header(HttpHeaders.AUTHORIZATION, current.authorization()))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/auth/me")
                        .header(HttpHeaders.AUTHORIZATION, other.authorization()))
                .andExpect(status().isOk());
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
