package com.ascentia.subs.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import javax.sql.DataSource;
import org.flywaydb.core.Flyway;
import org.springframework.boot.task.ThreadPoolTaskExecutorBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

@Configuration
public class ApplicationConfig {

    @Bean
    DataSource dataSource(AppProperties properties) {
        JdbcConnectionSettings connection = resolveJdbcConnection(properties);
        HikariConfig hikariConfig = new HikariConfig();
        hikariConfig.setJdbcUrl(connection.jdbcUrl());
        if (hasText(connection.username())) {
            hikariConfig.setUsername(connection.username());
        }
        if (connection.password() != null) {
            hikariConfig.setPassword(connection.password());
        }
        hikariConfig.setMaximumPoolSize(8);
        hikariConfig.setMinimumIdle(2);
        hikariConfig.setPoolName("subs-and-export");
        hikariConfig.setConnectionTimeout(30_000);
        return new HikariDataSource(hikariConfig);
    }

    @Bean
    JdbcClient jdbcClient(DataSource dataSource) {
        return JdbcClient.create(dataSource);
    }

    @Bean(initMethod = "migrate")
    Flyway flyway(DataSource dataSource) {
        return Flyway.configure()
                .dataSource(dataSource)
                .baselineOnMigrate(true)
                .baselineVersion("1")
                .locations("classpath:db/migration")
                .load();
    }

    @Bean
    ObjectMapper objectMapper() {
        return new ObjectMapper().findAndRegisterModules();
    }

    @Bean
    ThreadPoolTaskExecutor mediaTaskExecutor(ThreadPoolTaskExecutorBuilder builder) {
        return builder
                .corePoolSize(2)
                .maxPoolSize(4)
                .queueCapacity(32)
                .threadNamePrefix("media-")
                .build();
    }

    static String normalizeJdbcUrl(String value) {
        return jdbcUrlParts(value).jdbcUrl();
    }

    static JdbcConnectionSettings resolveJdbcConnection(AppProperties properties) {
        JdbcConnectionSettings parsedConnection = jdbcUrlParts(properties.databaseUrl());
        String username = firstNonBlank(properties.databaseUsername(), parsedConnection.username());
        String password = firstNonBlank(properties.databasePassword(), parsedConnection.password());
        return new JdbcConnectionSettings(parsedConnection.jdbcUrl(), username, password);
    }

    private static JdbcConnectionSettings jdbcUrlParts(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("GSP_DATABASE_URL or DATABASE_URL is required");
        }
        if (value.startsWith("jdbc:postgresql://")) {
            URI uri = URI.create(value.substring("jdbc:".length()));
            return toJdbcConnection(uri);
        }
        if (value.startsWith("postgresql+psycopg://")) {
            URI uri = URI.create(value.replaceFirst("^postgresql\\+psycopg://", "postgresql://"));
            return toJdbcConnection(uri);
        }
        if (value.startsWith("postgresql://")) {
            return toJdbcConnection(URI.create(value));
        }
        throw new IllegalStateException("Only PostgreSQL URLs are supported: " + value);
    }

    private static JdbcConnectionSettings toJdbcConnection(URI uri) {
        if (!"postgresql".equalsIgnoreCase(uri.getScheme())) {
            throw new IllegalStateException("Only PostgreSQL URLs are supported: " + uri);
        }

        String host = uri.getHost();
        if (!hasText(host)) {
            throw new IllegalStateException("PostgreSQL URL must include a host: " + uri);
        }

        StringBuilder jdbcUrl = new StringBuilder("jdbc:postgresql://")
                .append(formatHost(host));
        if (uri.getPort() >= 0) {
            jdbcUrl.append(':').append(uri.getPort());
        }

        String rawPath = uri.getRawPath();
        jdbcUrl.append(hasText(rawPath) ? rawPath : "/");

        String sanitizedQuery = sanitizeQuery(uri.getRawQuery());
        if (hasText(sanitizedQuery)) {
            jdbcUrl.append('?').append(sanitizedQuery);
        }

        String[] credentials = parseUserInfo(uri.getRawUserInfo());
        String username = firstNonBlank(extractQueryParam(uri.getRawQuery(), "user"), extractQueryParam(uri.getRawQuery(), "username"), credentials[0]);
        String password = firstNonBlank(extractQueryParam(uri.getRawQuery(), "password"), credentials[1]);
        return new JdbcConnectionSettings(jdbcUrl.toString(), username, password);
    }

    private static String sanitizeQuery(String rawQuery) {
        if (!hasText(rawQuery)) {
            return null;
        }

        return Arrays.stream(rawQuery.split("&"))
                .filter(pair -> {
                    String key = pair.contains("=") ? pair.substring(0, pair.indexOf('=')) : pair;
                    String decodedKey = URLDecoder.decode(key, StandardCharsets.UTF_8);
                    return !"user".equalsIgnoreCase(decodedKey)
                            && !"username".equalsIgnoreCase(decodedKey)
                            && !"password".equalsIgnoreCase(decodedKey);
                })
                .filter(ApplicationConfig::hasText)
                .reduce((left, right) -> left + "&" + right)
                .orElse(null);
    }

    private static String extractQueryParam(String rawQuery, String key) {
        if (!hasText(rawQuery)) {
            return null;
        }

        return Arrays.stream(rawQuery.split("&"))
                .map(pair -> pair.split("=", 2))
                .filter(parts -> URLDecoder.decode(parts[0], StandardCharsets.UTF_8).equalsIgnoreCase(key))
                .map(parts -> parts.length > 1 ? URLDecoder.decode(parts[1], StandardCharsets.UTF_8) : "")
                .findFirst()
                .orElse(null);
    }

    private static String[] parseUserInfo(String rawUserInfo) {
        if (!hasText(rawUserInfo)) {
            return new String[] {null, null};
        }

        String[] parts = rawUserInfo.split(":", 2);
        String username = URLDecoder.decode(parts[0], StandardCharsets.UTF_8);
        String password = parts.length > 1 ? URLDecoder.decode(parts[1], StandardCharsets.UTF_8) : null;
        return new String[] {username, password};
    }

    private static String formatHost(String host) {
        return host.contains(":") && !host.startsWith("[") ? "[" + host + "]" : host;
    }

    private static String firstNonBlank(String... values) {
        return Arrays.stream(values)
                .filter(ApplicationConfig::hasText)
                .findFirst()
                .orElse(null);
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    record JdbcConnectionSettings(String jdbcUrl, String username, String password) {}
}
