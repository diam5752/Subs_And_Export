package com.ascentia.subs.history;

import com.ascentia.subs.common.JsonCodec;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

@Service
public class HistoryStore {

    private final JdbcClient jdbcClient;
    private final JsonCodec jsonCodec;

    public HistoryStore(JdbcClient jdbcClient, JsonCodec jsonCodec) {
        this.jdbcClient = jdbcClient;
        this.jsonCodec = jsonCodec;
    }

    public HistoryEvent recordEvent(String userId, String email, String kind, String summary, Map<String, Object> data) {
        HistoryEvent event = new HistoryEvent(utcIso(), userId, email, kind, summary, data);
        jdbcClient.sql("""
                INSERT INTO history (ts, user_id, email, kind, summary, data)
                VALUES (:ts, :userId, :email, :kind, :summary, :data)
                """)
                .param("ts", event.ts())
                .param("userId", event.userId())
                .param("email", event.email())
                .param("kind", event.kind())
                .param("summary", event.summary())
                .param("data", jsonCodec.toJsonb(event.data()))
                .update();
        return event;
    }

    public List<HistoryEvent> recentForUser(String userId, int limit) {
        return jdbcClient.sql("""
                SELECT ts, user_id, email, kind, summary, data
                FROM history
                WHERE user_id = :userId
                ORDER BY ts DESC
                LIMIT :limit
                """)
                .param("userId", userId)
                .param("limit", limit)
                .query((rs, rowNum) -> new HistoryEvent(
                        rs.getString("ts"),
                        rs.getString("user_id"),
                        rs.getString("email"),
                        rs.getString("kind"),
                        rs.getString("summary"),
                        jsonCodec.readMap(rs.getString("data"))
                ))
                .list();
    }

    private static String utcIso() {
        return OffsetDateTime.ofInstant(Instant.now(), ZoneOffset.UTC).toString();
    }

    public record HistoryEvent(String ts, String userId, String email, String kind, String summary, Map<String, Object> data) {
    }
}
