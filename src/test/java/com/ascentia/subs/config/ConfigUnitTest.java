package com.ascentia.subs.config;

import javax.sql.DataSource;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;

class ConfigUnitTest {

    @Test
    void appPropertiesParsesEnvironmentListsAndConfiguredGetters() {
        AppProperties properties = new AppProperties();
        // REGRESSION: Java and Python defaults diverged from the public 95 MB
        // production ceiling.
        assertThat(properties.getMaxUploadMb()).isEqualTo(500);
        assertThat(properties.getMaxVideoDurationSeconds()).isEqualTo(600);
        properties.setEnv("local");
        properties.setDatabaseUrl("postgresql://localhost:5432/config");
        properties.setDatabaseUsername("db-user");
        properties.setDatabasePassword("db-pass");
        properties.setAllowedOrigins("http://localhost:3000, http://127.0.0.1:3000");
        properties.setTrustedHosts("localhost, testserver");
        properties.setProxyTrustedHosts("127.0.0.1, 10.0.0.0/8");
        properties.setForceHttps(true);
        properties.setMaxUploadMb(256);
        properties.setMaxVideoDurationSeconds(120);
        properties.setMaxConcurrentJobs(4);
        properties.setStaticRateLimit(30);
        properties.setStaticRateLimitWindow(120);
        properties.setSignupLimitPerIpPerDay(9);
        properties.setDefaultWidth(720);
        properties.setDefaultHeight(1280);
        properties.setMaxResolutionDimension(2048);
        properties.setDefaultTranscribeTier("pro");

        assertThat(properties.isDev()).isTrue();
        properties.setEnv("development");
        assertThat(properties.isDev()).isTrue();
        properties.setEnv("dev");
        assertThat(properties.isDev()).isTrue();
        properties.setEnv("production");
        assertThat(properties.isDev()).isFalse();

        assertThat(properties.env()).isEqualTo("production");
        assertThat(properties.getEnv()).isEqualTo("production");
        assertThat(properties.databaseUrl()).isEqualTo("postgresql://localhost:5432/config");
        assertThat(properties.databaseUsername()).isEqualTo("db-user");
        assertThat(properties.databasePassword()).isEqualTo("db-pass");
        assertThat(properties.getDatabaseUrl()).isEqualTo("postgresql://localhost:5432/config");
        assertThat(properties.getDatabaseUsername()).isEqualTo("db-user");
        assertThat(properties.getDatabasePassword()).isEqualTo("db-pass");
        assertThat(properties.allowedOriginsList()).containsExactly("http://localhost:3000", "http://127.0.0.1:3000");
        assertThat(properties.getAllowedOrigins()).contains("localhost:3000");
        assertThat(properties.trustedHostsList()).containsExactly("localhost", "testserver");
        assertThat(properties.proxyTrustedHostsList()).containsExactly("127.0.0.1", "10.0.0.0/8");
        assertThat(properties.getTrustedHosts()).isEqualTo("localhost, testserver");
        assertThat(properties.getProxyTrustedHosts()).isEqualTo("127.0.0.1, 10.0.0.0/8");
        assertThat(properties.isForceHttps()).isTrue();
        assertThat(properties.getMaxUploadMb()).isEqualTo(256);
        assertThat(properties.getMaxVideoDurationSeconds()).isEqualTo(120);
        assertThat(properties.getMaxConcurrentJobs()).isEqualTo(4);
        assertThat(properties.getStaticRateLimit()).isEqualTo(30);
        assertThat(properties.getStaticRateLimitWindow()).isEqualTo(120);
        assertThat(properties.getSignupLimitPerIpPerDay()).isEqualTo(9);
        assertThat(properties.getDefaultWidth()).isEqualTo(720);
        assertThat(properties.getDefaultHeight()).isEqualTo(1280);
        assertThat(properties.getMaxResolutionDimension()).isEqualTo(2048);
        assertThat(properties.getDefaultTranscribeTier()).isEqualTo("pro");
        assertThat(properties.dataDir().toString()).isEqualTo("data");
        assertThat(properties.watermarkPath().toString()).isEqualTo("gsubs-logo.png");
        assertThat(AppProperties.csvToList(null)).isEmpty();
        assertThat(AppProperties.csvToList(" one, , two ")).containsExactly("one", "two");
    }

    @Test
    void normalizeJdbcUrlSupportsLegacyPythonFormats() {
        assertThat(ApplicationConfig.normalizeJdbcUrl("jdbc:postgresql://localhost:5432/db"))
                .isEqualTo("jdbc:postgresql://localhost:5432/db");
        assertThat(ApplicationConfig.normalizeJdbcUrl("postgresql://localhost:5432/db"))
                .isEqualTo("jdbc:postgresql://localhost:5432/db");
        assertThat(ApplicationConfig.normalizeJdbcUrl("postgresql+psycopg://localhost:5432/db"))
                .isEqualTo("jdbc:postgresql://localhost:5432/db");
        assertThat(ApplicationConfig.normalizeJdbcUrl("postgresql+psycopg://gsp:secret@localhost:5432/db?sslmode=require&application_name=subs"))
                .isEqualTo("jdbc:postgresql://localhost:5432/db?sslmode=require&application_name=subs");
        assertThatThrownBy(() -> ApplicationConfig.normalizeJdbcUrl("sqlite:///tmp/test.db"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("Only PostgreSQL URLs are supported");
    }

    @Test
    void resolveJdbcConnectionExtractsCredentialsAndSupportsExplicitOverrides() {
        AppProperties fromUrl = new AppProperties();
        fromUrl.setDatabaseUrl("postgresql+psycopg://gsp:secret@localhost:5432/db?sslmode=require");

        assertThat(ApplicationConfig.resolveJdbcConnection(fromUrl))
                .extracting(
                        ApplicationConfig.JdbcConnectionSettings::jdbcUrl,
                        ApplicationConfig.JdbcConnectionSettings::username,
                        ApplicationConfig.JdbcConnectionSettings::password
                )
                .containsExactly("jdbc:postgresql://localhost:5432/db?sslmode=require", "gsp", "secret");

        AppProperties overridden = new AppProperties();
        overridden.setDatabaseUrl("jdbc:postgresql://localhost:5432/db");
        overridden.setDatabaseUsername("override-user");
        overridden.setDatabasePassword("override-secret");

        assertThat(ApplicationConfig.resolveJdbcConnection(overridden))
                .extracting(
                        ApplicationConfig.JdbcConnectionSettings::jdbcUrl,
                        ApplicationConfig.JdbcConnectionSettings::username,
                        ApplicationConfig.JdbcConnectionSettings::password
                )
                .containsExactly("jdbc:postgresql://localhost:5432/db", "override-user", "override-secret");
    }

    @Test
    void applicationConfigCoversHostQueryAndBeanBranches() {
        ApplicationConfig config = new ApplicationConfig();

        AppProperties noCredentials = new AppProperties();
        noCredentials.setDatabaseUrl("postgresql://localhost");
        assertThat(ApplicationConfig.resolveJdbcConnection(noCredentials))
                .extracting(
                        ApplicationConfig.JdbcConnectionSettings::jdbcUrl,
                        ApplicationConfig.JdbcConnectionSettings::username,
                        ApplicationConfig.JdbcConnectionSettings::password
                )
                .containsExactly("jdbc:postgresql://localhost/", null, null);

        AppProperties ipv6 = new AppProperties();
        ipv6.setDatabaseUrl("postgresql://useronly@[::1]:5432/db?sslmode=require&flag&user=ignored&password=ignored");
        assertThat(ApplicationConfig.resolveJdbcConnection(ipv6))
                .extracting(
                        ApplicationConfig.JdbcConnectionSettings::jdbcUrl,
                        ApplicationConfig.JdbcConnectionSettings::username,
                        ApplicationConfig.JdbcConnectionSettings::password
                )
                .containsExactly("jdbc:postgresql://[::1]:5432/db?sslmode=require&flag", "ignored", "ignored");

        assertThatThrownBy(() -> ApplicationConfig.normalizeJdbcUrl(" "))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("DATABASE_URL is required");
        assertThatThrownBy(() -> ApplicationConfig.normalizeJdbcUrl(null))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("DATABASE_URL is required");
        assertThatThrownBy(() -> ApplicationConfig.normalizeJdbcUrl("jdbc:postgresql:///missing-host"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("must include a host");

        AppProperties usernameQueryParam = new AppProperties();
        usernameQueryParam.setDatabaseUrl("postgresql://localhost:5432/db?username=query-user&password&application_name=subs");
        assertThat(ApplicationConfig.resolveJdbcConnection(usernameQueryParam))
                .extracting(
                        ApplicationConfig.JdbcConnectionSettings::jdbcUrl,
                        ApplicationConfig.JdbcConnectionSettings::username,
                        ApplicationConfig.JdbcConnectionSettings::password
                )
                .containsExactly("jdbc:postgresql://localhost:5432/db?application_name=subs", "query-user", null);

        assertThat(config.jdbcClient(mock(DataSource.class)).getClass().getSimpleName()).contains("JdbcClient");
        assertThat(config.objectMapper()).isNotNull();
    }
}
