package com.ascentia.subs.common;

import java.time.Instant;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class RateLimitService {

    private final JdbcClient jdbcClient;

    public RateLimitService(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    public void check(String action, String subject, int limit, int windowSeconds) {
        long now = Instant.now().getEpochSecond();
        long minWindowStart = now - windowSeconds;
        long expiresAt = now + windowSeconds;
        String fullKey = action + ":" + subject;

        jdbcClient.sql("DELETE FROM rate_limits WHERE expires_at < :now")
                .param("now", now)
                .update();

        Integer currentCount = jdbcClient.sql("""
                INSERT INTO rate_limits (key, count, window_start, expires_at)
                VALUES (:key, 1, :now, :expiresAt)
                ON CONFLICT (key) DO UPDATE SET
                    count = CASE WHEN rate_limits.window_start < :minWindowStart THEN 1 ELSE rate_limits.count + 1 END,
                    window_start = CASE WHEN rate_limits.window_start < :minWindowStart THEN :now ELSE rate_limits.window_start END,
                    expires_at = :expiresAt
                RETURNING count
                """)
                .param("key", fullKey)
                .param("now", now)
                .param("expiresAt", expiresAt)
                .param("minWindowStart", minWindowStart)
                .query(Integer.class)
                .single();

        if (currentCount != null && currentCount > limit) {
            throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "Too many requests. Please try again later.");
        }
    }
}
