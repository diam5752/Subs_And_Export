package com.ascentia.subs;

import com.ascentia.subs.auth.AuthStore;
import com.ascentia.subs.auth.CurrentUser;
import com.ascentia.subs.history.HistoryStore;
import com.ascentia.subs.jobs.JobStore;
import com.ascentia.subs.points.PointsStore;
import com.ascentia.subs.usage.UsageLedgerStore;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.http.MediaType.APPLICATION_FORM_URLENCODED;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@DirtiesContext(classMode = DirtiesContext.ClassMode.AFTER_CLASS)
public abstract class IntegrationTestSupport {

    @Autowired
    protected MockMvc mockMvc;

    @Autowired
    protected ObjectMapper objectMapper;

    @Autowired
    protected JdbcClient jdbcClient;

    @Autowired
    protected AuthStore authStore;

    @Autowired
    protected PointsStore pointsStore;

    @Autowired
    protected JobStore jobStore;

    @Autowired
    protected HistoryStore historyStore;

    @Autowired
    protected UsageLedgerStore usageLedgerStore;

    @DynamicPropertySource
    static void registerProperties(DynamicPropertyRegistry registry) {
        registry.add("app.database-url", () -> requiredEnvironment("GSP_JAVA_TEST_DATABASE_URL"));
        registry.add("GOOGLE_CLIENT_ID", () -> "test-google-client");
        registry.add("FRONTEND_URL", () -> "http://localhost:3000");
        registry.add("app.allowed-origins", () -> "http://localhost:3000");
    }

    private static String requiredEnvironment(String name) {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) {
            throw new IllegalStateException(name + " is required for Java integration tests");
        }
        return value;
    }

    @BeforeEach
    void resetState() throws IOException {
        jdbcClient.sql("""
                TRUNCATE TABLE
                    usage_ledger,
                    token_usage,
                    point_transactions,
                    user_points,
                    gcs_uploads,
                    oauth_states,
                    sessions,
                    jobs,
                    history,
                    deleted_emails,
                    rate_limits,
                    users
                RESTART IDENTITY CASCADE
                """).update();
        cleanDirectory(Path.of("data", "uploads"));
        cleanDirectory(Path.of("data", "artifacts"));
    }

    protected AuthSession registerAndLogin(String name) throws Exception {
        String email = uniqueEmail();
        String password = "testpassword123";
        return registerAndLogin(email, password, name);
    }

    protected AuthSession registerAndLogin(String email, String password, String name) throws Exception {
        mockMvc.perform(post("/auth/register")
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsBytes(Map.of(
                                "email", email,
                                "password", password,
                                "name", name
                        ))))
                .andExpect(status().isOk());

        return login(email, password);
    }

    protected AuthSession login(String email, String password) throws Exception {
        String loginBody = mockMvc.perform(post("/auth/token")
                        .contentType(APPLICATION_FORM_URLENCODED)
                        .param("username", email)
                        .param("password", password))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString();

        JsonNode tokenResponse = objectMapper.readTree(loginBody);
        return new AuthSession(tokenResponse.get("access_token").asText(), tokenResponse.get("user_id").asText(), email, password);
    }

    protected CurrentUser currentUser(AuthSession session) {
        return authStore.authenticateToken(session.token()).orElseThrow();
    }

    protected void writeArtifactFile(String jobId, String name, byte[] content) throws IOException {
        Path path = Path.of("data", "artifacts", jobId, name);
        Files.createDirectories(path.getParent());
        Files.write(path, content);
    }

    protected void writeUploadFile(String jobId, String extension, byte[] content) throws IOException {
        Path path = Path.of("data", "uploads", jobId + "_input" + extension);
        Files.createDirectories(path.getParent());
        Files.write(path, content);
    }

    protected static String uniqueEmail() {
        return "user_" + UUID.randomUUID().toString().replace("-", "") + "@example.com";
    }

    private void cleanDirectory(Path root) throws IOException {
        if (Files.notExists(root)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(root)) {
            walk.sorted(Comparator.reverseOrder())
                    .filter(path -> !path.equals(root))
                    .forEach(path -> {
                        try {
                            Files.deleteIfExists(path);
                        } catch (IOException exception) {
                            throw new RuntimeException(exception);
                        }
                    });
        }
    }

    protected record AuthSession(String token, String userId, String email, String password) {
        String authorization() {
            return "Bearer " + token;
        }
    }
}
