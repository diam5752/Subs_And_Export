package com.ascentia.subs.jobs;

import com.ascentia.subs.common.JsonCodec;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

@Service
public class JobStore {

    private final JdbcClient jdbcClient;
    private final JsonCodec jsonCodec;

    public JobStore(JdbcClient jdbcClient, JsonCodec jsonCodec) {
        this.jdbcClient = jdbcClient;
        this.jsonCodec = jsonCodec;
    }

    public Job createJob(String jobId, String userId) {
        int now = now();
        jdbcClient.sql("""
                INSERT INTO jobs (id, user_id, status, created_at, updated_at, progress, message, result_data)
                VALUES (:id, :userId, 'pending', :createdAt, :updatedAt, 0, NULL, :resultData)
                """)
                .param("id", jobId)
                .param("userId", userId)
                .param("createdAt", now)
                .param("updatedAt", now)
                .param("resultData", jsonCodec.toJsonb(null))
                .update();
        return new Job(jobId, userId, "pending", 0, null, now, now, null);
    }

    public void updateJob(String jobId, String status, Integer progress, String message, Map<String, Object> resultData) {
        if (status == null && progress == null && message == null && resultData == null) {
            return;
        }
        Optional<Job> existing = getJob(jobId);
        if (existing.isEmpty()) {
            return;
        }
        Job job = existing.get();
        jdbcClient.sql("""
                UPDATE jobs
                SET status = :status,
                    progress = :progress,
                    message = :message,
                    result_data = :resultData,
                    updated_at = :updatedAt
                WHERE id = :id
                """)
                .param("id", jobId)
                .param("status", status == null ? job.status() : status)
                .param("progress", progress == null ? job.progress() : progress)
                .param("message", message == null ? job.message() : message)
                .param("resultData", jsonCodec.toJsonb(resultData == null ? job.resultData() : resultData))
                .param("updatedAt", now())
                .update();
    }

    public Optional<Job> getJob(String jobId) {
        return jdbcClient.sql("""
                SELECT id, user_id, status, progress, message, created_at, updated_at, result_data
                FROM jobs
                WHERE id = :id
                """)
                .param("id", jobId)
                .query((rs, rowNum) -> new Job(
                        rs.getString("id"),
                        rs.getString("user_id"),
                        rs.getString("status"),
                        rs.getInt("progress"),
                        rs.getString("message"),
                        rs.getInt("created_at"),
                        rs.getInt("updated_at"),
                        nullableMap(rs.getString("result_data"))
                ))
                .optional();
    }

    public List<Job> listJobsForUser(String userId, int limit) {
        return jdbcClient.sql("""
                SELECT id, user_id, status, progress, message, created_at, updated_at, result_data
                FROM jobs
                WHERE user_id = :userId
                ORDER BY created_at DESC
                LIMIT :limit
                """)
                .param("userId", userId)
                .param("limit", limit)
                .query((rs, rowNum) -> new Job(
                        rs.getString("id"),
                        rs.getString("user_id"),
                        rs.getString("status"),
                        rs.getInt("progress"),
                        rs.getString("message"),
                        rs.getInt("created_at"),
                        rs.getInt("updated_at"),
                        nullableMap(rs.getString("result_data"))
                ))
                .list();
    }

    public List<Job> listJobsForUserPaginated(String userId, int offset, int limit) {
        return jdbcClient.sql("""
                SELECT id, user_id, status, progress, message, created_at, updated_at, result_data
                FROM jobs
                WHERE user_id = :userId
                ORDER BY created_at DESC
                OFFSET :offset
                LIMIT :limit
                """)
                .param("userId", userId)
                .param("offset", offset)
                .param("limit", limit)
                .query((rs, rowNum) -> new Job(
                        rs.getString("id"),
                        rs.getString("user_id"),
                        rs.getString("status"),
                        rs.getInt("progress"),
                        rs.getString("message"),
                        rs.getInt("created_at"),
                        rs.getInt("updated_at"),
                        nullableMap(rs.getString("result_data"))
                ))
                .list();
    }

    public List<Job> getJobs(List<String> jobIds, String userId) {
        if (jobIds.isEmpty()) {
            return List.of();
        }
        return jdbcClient.sql("""
                SELECT id, user_id, status, progress, message, created_at, updated_at, result_data
                FROM jobs
                WHERE id IN (:jobIds) AND user_id = :userId
                """)
                .param("jobIds", jobIds)
                .param("userId", userId)
                .query((rs, rowNum) -> new Job(
                        rs.getString("id"),
                        rs.getString("user_id"),
                        rs.getString("status"),
                        rs.getInt("progress"),
                        rs.getString("message"),
                        rs.getInt("created_at"),
                        rs.getInt("updated_at"),
                        nullableMap(rs.getString("result_data"))
                ))
                .list();
    }

    public void deleteJob(String jobId) {
        jdbcClient.sql("DELETE FROM jobs WHERE id = :id").param("id", jobId).update();
    }

    public int deleteJobs(List<String> jobIds, String userId) {
        if (jobIds.isEmpty()) {
            return 0;
        }
        return jdbcClient.sql("DELETE FROM jobs WHERE id IN (:jobIds) AND user_id = :userId")
                .param("jobIds", jobIds)
                .param("userId", userId)
                .update();
    }

    public int countJobsForUser(String userId) {
        return jdbcClient.sql("SELECT COUNT(*) FROM jobs WHERE user_id = :userId")
                .param("userId", userId)
                .query(Integer.class)
                .single();
    }

    public int countActiveJobsForUser(String userId) {
        return jdbcClient.sql("SELECT COUNT(*) FROM jobs WHERE user_id = :userId AND status IN ('pending','processing')")
                .param("userId", userId)
                .query(Integer.class)
                .single();
    }

    public List<Job> listJobsCreatedBefore(int cutoffTimestamp) {
        return jdbcClient.sql("""
                SELECT id, user_id, status, progress, message, created_at, updated_at, result_data
                FROM jobs
                WHERE created_at < :cutoff
                """)
                .param("cutoff", cutoffTimestamp)
                .query((rs, rowNum) -> new Job(
                        rs.getString("id"),
                        rs.getString("user_id"),
                        rs.getString("status"),
                        rs.getInt("progress"),
                        rs.getString("message"),
                        rs.getInt("created_at"),
                        rs.getInt("updated_at"),
                        nullableMap(rs.getString("result_data"))
                ))
                .list();
    }

    private Map<String, Object> nullableMap(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        return jsonCodec.readMap(json);
    }

    private static int now() {
        return Math.toIntExact(Instant.now().getEpochSecond());
    }

    public record Job(
            String id,
            String userId,
            String status,
            int progress,
            String message,
            int createdAt,
            int updatedAt,
            Map<String, Object> resultData
    ) {
    }
}
