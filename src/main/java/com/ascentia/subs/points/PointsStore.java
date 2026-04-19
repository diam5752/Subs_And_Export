package com.ascentia.subs.points;

import com.ascentia.subs.common.JsonCodec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class PointsStore {

    public static final int STARTING_POINTS_BALANCE = 500;
    public static final int TRIAL_CREDITS = 100;
    public static final String REFUND_REASON_PREFIX = "refund_";

    private final JdbcClient jdbcClient;
    private final JsonCodec jsonCodec;

    public PointsStore(JdbcClient jdbcClient, JsonCodec jsonCodec) {
        this.jdbcClient = jdbcClient;
        this.jsonCodec = jsonCodec;
    }

    @Transactional
    public int getBalance(String userId) {
        ensureAccount(userId, null, null);
        Integer balance = jdbcClient.sql("SELECT balance FROM user_points WHERE user_id = :userId")
                .param("userId", userId)
                .query(Integer.class)
                .optional()
                .orElse(0);
        return balance;
    }

    @Transactional
    public boolean ensureAccount(String userId, Boolean emailVerified, Integer startingBalanceOverride) {
        if (startingBalanceOverride != null && startingBalanceOverride < 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid starting balance");
        }
        boolean resolvedEmailVerified = resolveEmailVerified(userId, emailVerified);
        int startingBalance = startingBalanceOverride != null
                ? startingBalanceOverride
                : (resolvedEmailVerified ? STARTING_POINTS_BALANCE : TRIAL_CREDITS);
        String reason = startingBalanceOverride != null
                ? "initial_balance_override"
                : (resolvedEmailVerified ? "initial_balance" : "trial_balance");

        int now = now();
        Optional<String> created = jdbcClient.sql("""
                INSERT INTO user_points (user_id, balance, updated_at)
                VALUES (:userId, :balance, :updatedAt)
                ON CONFLICT (user_id) DO NOTHING
                RETURNING user_id
                """)
                .param("userId", userId)
                .param("balance", startingBalance)
                .param("updatedAt", now)
                .query(String.class)
                .optional();

        if (created.isPresent() && startingBalance > 0) {
            jdbcClient.sql("""
                    INSERT INTO point_transactions (id, user_id, delta, reason, meta, created_at)
                    VALUES (:id, :userId, :delta, :reason, :meta, :createdAt)
                    """)
                    .param("id", UUID.randomUUID().toString().replace("-", ""))
                    .param("userId", userId)
                    .param("delta", startingBalance)
                    .param("reason", reason)
                    .param("meta", jsonCodec.toJsonb(Map.of("kind", reason)))
                    .param("createdAt", now)
                    .update();
        }
        return created.isPresent();
    }

    @Transactional
    public int spend(String userId, int cost, String reason, Map<String, Object> meta) {
        validateAmount(cost, "cost");
        validateReason(reason);
        ensureAccount(userId, null, null);
        int now = now();
        int updated = jdbcClient.sql("""
                UPDATE user_points
                SET balance = balance - :cost, updated_at = :updatedAt
                WHERE user_id = :userId AND balance >= :cost
                """)
                .param("cost", cost)
                .param("updatedAt", now)
                .param("userId", userId)
                .update();
        if (updated != 1) {
            throw new ResponseStatusException(HttpStatus.PAYMENT_REQUIRED, "Insufficient points");
        }
        writeTransaction(UUID.randomUUID().toString().replace("-", ""), userId, -cost, reason, meta, now);
        return getBalance(userId);
    }

    @Transactional
    public SpendOnceResult spendOnce(String userId, int cost, String reason, String transactionId, Map<String, Object> meta) {
        validateAmount(cost, "cost");
        validateTransactionId(transactionId);
        validateReason(reason);
        ensureAccount(userId, null, null);

        int now = now();
        Optional<String> inserted = jdbcClient.sql("""
                INSERT INTO point_transactions (id, user_id, delta, reason, meta, created_at)
                VALUES (:id, :userId, :delta, :reason, :meta, :createdAt)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """)
                .param("id", transactionId)
                .param("userId", userId)
                .param("delta", -cost)
                .param("reason", reason)
                .param("meta", jsonCodec.toJsonb(meta))
                .param("createdAt", now)
                .query(String.class)
                .optional();

        boolean applied = inserted.isPresent();
        if (applied) {
            int updated = jdbcClient.sql("""
                    UPDATE user_points
                    SET balance = balance - :cost, updated_at = :updatedAt
                    WHERE user_id = :userId AND balance >= :cost
                    """)
                    .param("cost", cost)
                    .param("updatedAt", now)
                    .param("userId", userId)
                    .update();
            if (updated != 1) {
                throw new ResponseStatusException(HttpStatus.PAYMENT_REQUIRED, "Insufficient points");
            }
        }
        return new SpendOnceResult(getBalance(userId), applied);
    }

    @Transactional
    public int credit(String userId, int amount, String reason, Map<String, Object> meta) {
        validateAmount(amount, "amount");
        validateReason(reason);
        ensureAccount(userId, null, null);
        int now = now();
        jdbcClient.sql("""
                UPDATE user_points
                SET balance = balance + :amount, updated_at = :updatedAt
                WHERE user_id = :userId
                """)
                .param("amount", amount)
                .param("updatedAt", now)
                .param("userId", userId)
                .update();
        writeTransaction(UUID.randomUUID().toString().replace("-", ""), userId, amount, reason, meta, now);
        return getBalance(userId);
    }

    @Transactional
    public int refund(String userId, int amount, String originalReason, Map<String, Object> meta) {
        return credit(userId, amount, refundReason(originalReason), meta);
    }

    @Transactional
    public int refundOnce(String userId, int amount, String originalReason, String transactionId, Map<String, Object> meta) {
        validateAmount(amount, "amount");
        validateTransactionId(transactionId);
        validateReason(originalReason);
        ensureAccount(userId, null, null);

        int now = now();
        Optional<String> inserted = jdbcClient.sql("""
                INSERT INTO point_transactions (id, user_id, delta, reason, meta, created_at)
                VALUES (:id, :userId, :delta, :reason, :meta, :createdAt)
                ON CONFLICT (id) DO NOTHING
                RETURNING id
                """)
                .param("id", transactionId)
                .param("userId", userId)
                .param("delta", amount)
                .param("reason", refundReason(originalReason))
                .param("meta", jsonCodec.toJsonb(meta))
                .param("createdAt", now)
                .query(String.class)
                .optional();

        if (inserted.isPresent()) {
            jdbcClient.sql("""
                    UPDATE user_points
                    SET balance = balance + :amount, updated_at = :updatedAt
                    WHERE user_id = :userId
                    """)
                    .param("amount", amount)
                    .param("updatedAt", now)
                    .param("userId", userId)
                    .update();
        }
        return getBalance(userId);
    }

    public static String refundReason(String originalReason) {
        String cleaned = originalReason == null ? "" : originalReason.trim();
        String reason = REFUND_REASON_PREFIX + (cleaned.isEmpty() ? "unknown" : cleaned);
        return reason.length() > 64 ? reason.substring(0, 64) : reason;
    }

    public static String makeIdempotencyId(String... parts) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(String.join("|", parts).getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest.digest()).substring(0, 32);
        } catch (Exception exception) {
            throw new IllegalStateException("Failed to build idempotency id", exception);
        }
    }

    private void writeTransaction(String id, String userId, int delta, String reason, Map<String, Object> meta, int now) {
        jdbcClient.sql("""
                INSERT INTO point_transactions (id, user_id, delta, reason, meta, created_at)
                VALUES (:id, :userId, :delta, :reason, :meta, :createdAt)
                """)
                .param("id", id)
                .param("userId", userId)
                .param("delta", delta)
                .param("reason", reason)
                .param("meta", jsonCodec.toJsonb(meta))
                .param("createdAt", now)
                .update();
    }

    private boolean resolveEmailVerified(String userId, Boolean emailVerified) {
        if (emailVerified != null) {
            return emailVerified;
        }
        return jdbcClient.sql("SELECT email_verified FROM users WHERE id = :userId")
                .param("userId", userId)
                .query(Boolean.class)
                .optional()
                .orElse(Boolean.FALSE);
    }

    private static void validateAmount(int value, String fieldName) {
        if (value <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid " + fieldName);
        }
    }

    private static void validateReason(String reason) {
        if (reason == null || reason.isBlank() || reason.length() > 64) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid reason");
        }
    }

    private static void validateTransactionId(String transactionId) {
        if (transactionId == null || transactionId.isBlank() || transactionId.length() > 32) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid transaction id");
        }
    }

    private static int now() {
        return Math.toIntExact(Instant.now().getEpochSecond());
    }

    public record SpendOnceResult(int balance, boolean applied) {
    }
}
