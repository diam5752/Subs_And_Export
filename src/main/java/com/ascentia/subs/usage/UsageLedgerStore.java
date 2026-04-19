package com.ascentia.subs.usage;

import com.ascentia.subs.common.JsonCodec;
import com.ascentia.subs.points.PointsStore;
import com.ascentia.subs.points.PointsStore.SpendOnceResult;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class UsageLedgerStore {

    private final JdbcClient jdbcClient;
    private final JsonCodec jsonCodec;
    private final PointsStore pointsStore;

    public UsageLedgerStore(JdbcClient jdbcClient, JsonCodec jsonCodec, PointsStore pointsStore) {
        this.jdbcClient = jdbcClient;
        this.jsonCodec = jsonCodec;
        this.pointsStore = pointsStore;
    }

    @Transactional
    public ReserveResult reserve(
            String userId,
            String jobId,
            String action,
            String provider,
            String model,
            String tier,
            int credits,
            int minCredits,
            double costEstimateUsd,
            Map<String, Object> units,
            String idempotencyKey,
            String endpoint,
            String currency
    ) {
        Optional<ChargeReservation> existingReservation = existingReservation(idempotencyKey);
        if (existingReservation.isPresent()) {
            return new ReserveResult(existingReservation.get(), pointsStore.getBalance(userId));
        }

        String ledgerId = UUID.randomUUID().toString().replace("-", "");
        SpendOnceResult spendResult = pointsStore.spendOnce(
                userId,
                credits,
                action,
                PointsStore.makeIdempotencyId("reserve", idempotencyKey),
                Map.of(
                        "ledger_id", ledgerId,
                        "action", action,
                        "provider", provider,
                        "model", model == null ? "" : model,
                        "tier", tier == null ? "" : tier,
                        "kind", "reserve"
                )
        );

        int now = now();
        jdbcClient.sql("""
                INSERT INTO usage_ledger (
                    id, user_id, job_id, action, provider, endpoint, model, tier, units,
                    cost_usd, credits_reserved, credits_charged, min_credits, currency, status, error,
                    idempotency_key, created_at, updated_at
                ) VALUES (
                    :id, :userId, :jobId, :action, :provider, :endpoint, :model, :tier, :units,
                    :costUsd, :creditsReserved, 0, :minCredits, :currency, 'reserved', NULL,
                    :idempotencyKey, :createdAt, :updatedAt
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                """)
                .param("id", ledgerId)
                .param("userId", userId)
                .param("jobId", jobId)
                .param("action", action)
                .param("provider", provider)
                .param("endpoint", endpoint)
                .param("model", model)
                .param("tier", tier)
                .param("units", jsonCodec.toJsonb(units))
                .param("costUsd", costEstimateUsd)
                .param("creditsReserved", credits)
                .param("minCredits", minCredits)
                .param("currency", currency)
                .param("idempotencyKey", idempotencyKey)
                .param("createdAt", now)
                .param("updatedAt", now)
                .update();

        ChargeReservation reservation = new ChargeReservation(ledgerId, userId, jobId, action, provider, model, tier, credits, minCredits, idempotencyKey);
        return new ReserveResult(reservation, spendResult.balance());
    }

    @Transactional
    public int finalize(ChargeReservation reservation, int creditsCharged, double costUsd, Map<String, Object> units, String status) {
        int finalCredits = Math.max(creditsCharged, reservation.minCredits());
        int refundAmount = Math.max(0, reservation.reservedCredits() - finalCredits);
        int extraCharge = Math.max(0, finalCredits - reservation.reservedCredits());

        if (extraCharge > 0) {
            pointsStore.spendOnce(
                    reservation.userId(),
                    extraCharge,
                    reservation.action(),
                    PointsStore.makeIdempotencyId("overage", reservation.ledgerId(), String.valueOf(extraCharge)),
                    Map.of("ledger_id", reservation.ledgerId(), "action", reservation.action(), "kind", "overage")
            );
        }
        if (refundAmount > 0) {
            pointsStore.refundOnce(
                    reservation.userId(),
                    refundAmount,
                    reservation.action(),
                    PointsStore.makeIdempotencyId("refund", reservation.ledgerId(), String.valueOf(refundAmount)),
                    Map.of("ledger_id", reservation.ledgerId(), "action", reservation.action(), "kind", "adjustment")
            );
        }

        jdbcClient.sql("""
                UPDATE usage_ledger
                SET credits_charged = :creditsCharged,
                    cost_usd = :costUsd,
                    units = :units,
                    status = :status,
                    updated_at = :updatedAt
                WHERE id = :ledgerId
                """)
                .param("creditsCharged", finalCredits)
                .param("costUsd", costUsd)
                .param("units", jsonCodec.toJsonb(units))
                .param("status", status)
                .param("updatedAt", now())
                .param("ledgerId", reservation.ledgerId())
                .update();

        return pointsStore.getBalance(reservation.userId());
    }

    @Transactional
    public int fail(ChargeReservation reservation, String status, String error) {
        pointsStore.refundOnce(
                reservation.userId(),
                reservation.reservedCredits(),
                reservation.action(),
                PointsStore.makeIdempotencyId("refund", reservation.ledgerId(), "failed"),
                Map.of("ledger_id", reservation.ledgerId(), "action", reservation.action(), "kind", "failed")
        );

        jdbcClient.sql("""
                UPDATE usage_ledger
                SET status = :status, error = :error, updated_at = :updatedAt
                WHERE id = :ledgerId
                """)
                .param("status", status)
                .param("error", error == null ? null : error.substring(0, Math.min(500, error.length())))
                .param("updatedAt", now())
                .param("ledgerId", reservation.ledgerId())
                .update();

        return pointsStore.getBalance(reservation.userId());
    }

    @Transactional
    public int refundIfReserved(ChargeReservation reservation, String status, String error) {
        Optional<String> ledgerStatus = jdbcClient.sql("SELECT status FROM usage_ledger WHERE id = :ledgerId")
                .param("ledgerId", reservation.ledgerId())
                .query(String.class)
                .optional();
        if (ledgerStatus.isEmpty() || !"reserved".equalsIgnoreCase(ledgerStatus.get())) {
            return pointsStore.getBalance(reservation.userId());
        }
        return fail(reservation, status, error);
    }

    public List<UsageSummaryRow> summarize(int startTs, int endTs, String groupBy) {
        if (startTs > endTs) {
            throw new IllegalArgumentException("start_ts must be <= end_ts");
        }
        if (!List.of("day", "month", "user", "action").contains(groupBy)) {
            throw new IllegalArgumentException("Invalid group_by");
        }

        List<UsageLedgerRow> rows = jdbcClient.sql("""
                SELECT user_id, action, credits_reserved, credits_charged, cost_usd, created_at
                FROM usage_ledger
                WHERE created_at >= :startTs AND created_at <= :endTs
                """)
                .param("startTs", startTs)
                .param("endTs", endTs)
                .query((rs, rowNum) -> new UsageLedgerRow(
                        rs.getString("user_id"),
                        rs.getString("action"),
                        rs.getInt("credits_reserved"),
                        rs.getInt("credits_charged"),
                        rs.getDouble("cost_usd"),
                        rs.getInt("created_at")
                ))
                .list();

        Map<String, UsageSummaryRow> summary = new LinkedHashMap<>();
        for (UsageLedgerRow row : rows) {
            String bucket = switch (groupBy) {
                case "day" -> DateTimeFormatter.ofPattern("yyyy-MM-dd").format(LocalDateTime.ofEpochSecond(row.createdAt(), 0, ZoneOffset.UTC));
                case "month" -> DateTimeFormatter.ofPattern("yyyy-MM").format(LocalDateTime.ofEpochSecond(row.createdAt(), 0, ZoneOffset.UTC));
                case "user" -> row.userId();
                default -> row.action();
            };
            UsageSummaryRow current = summary.get(bucket);
            summary.put(bucket, current == null
                    ? new UsageSummaryRow(bucket, row.creditsReserved(), row.creditsCharged(), row.costUsd(), 1)
                    : new UsageSummaryRow(
                            bucket,
                            current.creditsReserved() + row.creditsReserved(),
                            current.creditsCharged() + row.creditsCharged(),
                            current.costUsd() + row.costUsd(),
                            current.count() + 1
                    ));
        }
        return summary.values().stream().toList();
    }

    public PointsStore pointsStore() {
        return pointsStore;
    }

    private Optional<ChargeReservation> existingReservation(String idempotencyKey) {
        return jdbcClient.sql("""
                SELECT id, user_id, job_id, action, provider, model, tier, credits_reserved, min_credits, idempotency_key
                FROM usage_ledger
                WHERE idempotency_key = :idempotencyKey
                """)
                .param("idempotencyKey", idempotencyKey)
                .query((rs, rowNum) -> new ChargeReservation(
                        rs.getString("id"),
                        rs.getString("user_id"),
                        rs.getString("job_id"),
                        rs.getString("action"),
                        rs.getString("provider"),
                        rs.getString("model"),
                        rs.getString("tier"),
                        rs.getInt("credits_reserved"),
                        rs.getInt("min_credits"),
                        rs.getString("idempotency_key")
                ))
                .optional();
    }

    private static int now() {
        return Math.toIntExact(Instant.now().getEpochSecond());
    }

    public record ChargeReservation(
            String ledgerId,
            String userId,
            String jobId,
            String action,
            String provider,
            String model,
            String tier,
            int reservedCredits,
            int minCredits,
            String idempotencyKey
    ) {
    }

    public record ChargePlan(ChargeReservation transcription, ChargeReservation socialCopy) {
    }

    public record UsageSummaryRow(String bucket, int creditsReserved, int creditsCharged, double costUsd, int count) {
    }

    public record ReserveResult(ChargeReservation reservation, int balance) {
    }

    private record UsageLedgerRow(String userId, String action, int creditsReserved, int creditsCharged, double costUsd, int createdAt) {
    }
}
