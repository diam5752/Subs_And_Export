package com.ascentia.subs.auth;

import com.ascentia.subs.points.PointsStore;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Pattern;
import org.bouncycastle.crypto.generators.SCrypt;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class AuthStore {

    private static final Pattern EMAIL_PATTERN = Pattern.compile("^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$");
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();
    private static final int SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;
    private static final int SCRYPT_N = 1 << 14;
    private static final int SCRYPT_R = 8;
    private static final int SCRYPT_P = 1;
    private static final int SCRYPT_DK_LEN = 64;

    private final JdbcClient jdbcClient;
    private final PointsStore pointsStore;

    public AuthStore(JdbcClient jdbcClient, PointsStore pointsStore) {
        this.jdbcClient = jdbcClient;
        this.pointsStore = pointsStore;
    }

    @Transactional
    public CurrentUser registerLocalUser(String email, String password, String name) {
        String normalizedEmail = normalizeEmail(email);
        validatePasswordStrength(password);
        String finalName = normalizeName(name, normalizedEmail);
        if (findUserByEmail(normalizedEmail).isPresent()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "User already exists");
        }

        boolean deletedEmail = emailWasDeleted(normalizedEmail);
        CurrentUser user = new CurrentUser(
                randomHex(16),
                normalizedEmail,
                finalName,
                "local",
                hashPassword(password),
                null,
                utcIso(),
                false
        );

        jdbcClient.sql("""
                INSERT INTO users (id, email, name, provider, password_hash, google_sub, created_at, email_verified)
                VALUES (:id, :email, :name, :provider, :passwordHash, NULL, :createdAt, FALSE)
                """)
                .param("id", user.id())
                .param("email", user.email())
                .param("name", user.name())
                .param("provider", user.provider())
                .param("passwordHash", user.passwordHash())
                .param("createdAt", user.createdAt())
                .update();

        pointsStore.ensureAccount(user.id(), false, deletedEmail ? 0 : null);
        return withoutSecret(user);
    }

    @Transactional
    public CurrentUser upsertGoogleUser(String email, String name, String sub) {
        String normalizedEmail = normalizeEmail(email);
        String finalName = normalizeName(name, normalizedEmail);
        Optional<CurrentUser> existing = findUserByEmail(normalizedEmail);
        if (existing.isPresent()) {
            jdbcClient.sql("""
                    UPDATE users
                    SET name = :name, provider = 'google', password_hash = NULL, google_sub = :googleSub, email_verified = TRUE
                    WHERE id = :id
                    """)
                    .param("name", finalName)
                    .param("googleSub", sub)
                    .param("id", existing.get().id())
                    .update();
            return findUserById(existing.get().id()).map(AuthStore::withoutSecret).orElseThrow();
        }

        boolean deletedEmail = emailWasDeleted(normalizedEmail);
        CurrentUser user = new CurrentUser(randomHex(16), normalizedEmail, finalName, "google", null, sub, utcIso(), true);
        jdbcClient.sql("""
                INSERT INTO users (id, email, name, provider, password_hash, google_sub, created_at, email_verified)
                VALUES (:id, :email, :name, 'google', NULL, :googleSub, :createdAt, TRUE)
                """)
                .param("id", user.id())
                .param("email", user.email())
                .param("name", user.name())
                .param("googleSub", sub)
                .param("createdAt", user.createdAt())
                .update();
        pointsStore.ensureAccount(user.id(), true, deletedEmail ? 0 : null);
        return withoutSecret(user);
    }

    public Optional<CurrentUser> authenticateLocal(String email, String password) {
        Optional<CurrentUser> candidate = findUserByEmail(normalizeEmail(email));
        String targetHash = candidate.map(CurrentUser::passwordHash).filter(value -> value != null && !value.isBlank()).orElseGet(() -> hashPassword("dummy_password_123"));
        boolean valid = verifyPassword(password, targetHash);
        if (candidate.isPresent() && candidate.get().passwordHash() != null && valid) {
            return candidate.map(AuthStore::withoutSecret);
        }
        return Optional.empty();
    }

    public Optional<CurrentUser> authenticateToken(String token) {
        if (token == null || token.isBlank()) {
            return Optional.empty();
        }
        int now = now();
        return jdbcClient.sql("""
                SELECT u.id, u.email, u.name, u.provider, u.password_hash, u.google_sub, u.created_at, u.email_verified
                FROM users u
                JOIN sessions s ON s.user_id = u.id
                WHERE s.token_hash = :tokenHash AND s.expires_at > :now
                ORDER BY s.created_at DESC
                LIMIT 1
                """)
                .param("tokenHash", hashToken(token))
                .param("now", now)
                .query((rs, rowNum) -> new CurrentUser(
                        rs.getString("id"),
                        rs.getString("email"),
                        rs.getString("name"),
                        rs.getString("provider"),
                        rs.getString("password_hash"),
                        rs.getString("google_sub"),
                        rs.getString("created_at"),
                        rs.getBoolean("email_verified")
                ))
                .optional()
                .map(AuthStore::withoutSecret);
    }

    @Transactional
    public String issueSession(CurrentUser user, String userAgent) {
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(randomBytes(32));
        int now = now();
        jdbcClient.sql("""
                INSERT INTO sessions (token_hash, user_id, created_at, expires_at, user_agent)
                VALUES (:tokenHash, :userId, :createdAt, :expiresAt, :userAgent)
                """)
                .param("tokenHash", hashToken(token))
                .param("userId", user.id())
                .param("createdAt", now)
                .param("expiresAt", now + SESSION_TTL_SECONDS)
                .param("userAgent", userAgent)
                .update();
        return token;
    }

    @Transactional
    public void revokeAllSessions(String userId) {
        jdbcClient.sql("DELETE FROM sessions WHERE user_id = :userId")
                .param("userId", userId)
                .update();
    }

    @Transactional
    public void updateName(String userId, String newName) {
        String normalized = normalizeName(newName, "");
        jdbcClient.sql("UPDATE users SET name = :name WHERE id = :userId")
                .param("name", normalized)
                .param("userId", userId)
                .update();
    }

    @Transactional
    public void updatePassword(String userId, String newPassword) {
        validatePasswordStrength(newPassword);
        jdbcClient.sql("UPDATE users SET password_hash = :passwordHash WHERE id = :userId")
                .param("passwordHash", hashPassword(newPassword))
                .param("userId", userId)
                .update();
    }

    @Transactional
    public void deleteUser(String userId) {
        findUserById(userId).ifPresent(user -> {
            jdbcClient.sql("""
                    INSERT INTO deleted_emails (email_hash, deleted_at)
                    VALUES (:emailHash, :deletedAt)
                    ON CONFLICT (email_hash) DO UPDATE SET deleted_at = EXCLUDED.deleted_at
                    """)
                    .param("emailHash", emailFingerprint(user.email()))
                    .param("deletedAt", now())
                    .update();
            jdbcClient.sql("DELETE FROM users WHERE id = :userId").param("userId", userId).update();
        });
    }

    public Optional<CurrentUser> findUserById(String userId) {
        return jdbcClient.sql("""
                SELECT id, email, name, provider, password_hash, google_sub, created_at, email_verified
                FROM users
                WHERE id = :userId
                """)
                .param("userId", userId)
                .query((rs, rowNum) -> new CurrentUser(
                        rs.getString("id"),
                        rs.getString("email"),
                        rs.getString("name"),
                        rs.getString("provider"),
                        rs.getString("password_hash"),
                        rs.getString("google_sub"),
                        rs.getString("created_at"),
                        rs.getBoolean("email_verified")
                ))
                .optional();
    }

    public Optional<CurrentUser> findUserByEmail(String email) {
        return jdbcClient.sql("""
                SELECT id, email, name, provider, password_hash, google_sub, created_at, email_verified
                FROM users
                WHERE email = :email
                LIMIT 1
                """)
                .param("email", email)
                .query((rs, rowNum) -> new CurrentUser(
                        rs.getString("id"),
                        rs.getString("email"),
                        rs.getString("name"),
                        rs.getString("provider"),
                        rs.getString("password_hash"),
                        rs.getString("google_sub"),
                        rs.getString("created_at"),
                        rs.getBoolean("email_verified")
                ))
                .optional();
    }

    @Transactional
    public String issueOauthState(String provider, String userId, String userAgent, String ip, int ttlSeconds) {
        String state = Base64.getUrlEncoder().withoutPadding().encodeToString(randomBytes(32));
        int now = now();
        jdbcClient.sql("""
                INSERT INTO oauth_states (state, provider, user_id, created_at, expires_at, user_agent, ip)
                VALUES (:state, :provider, :userId, :createdAt, :expiresAt, :userAgent, :ip)
                """)
                .param("state", state)
                .param("provider", provider)
                .param("userId", userId)
                .param("createdAt", now)
                .param("expiresAt", now + Math.max(30, ttlSeconds))
                .param("userAgent", userAgent)
                .param("ip", ip)
                .update();
        jdbcClient.sql("DELETE FROM oauth_states WHERE expires_at <= :now").param("now", now).update();
        return state;
    }

    @Transactional
    public boolean consumeOauthState(String provider, String state, String userId, String userAgent, String ip) {
        Optional<OAuthState> row = jdbcClient.sql("""
                SELECT state, provider, user_id, created_at, expires_at, user_agent, ip
                FROM oauth_states
                WHERE state = :state
                LIMIT 1
                """)
                .param("state", state)
                .query((rs, rowNum) -> new OAuthState(
                        rs.getString("state"),
                        rs.getString("provider"),
                        rs.getString("user_id"),
                        rs.getInt("created_at"),
                        rs.getInt("expires_at"),
                        rs.getString("user_agent"),
                        rs.getString("ip")
                ))
                .optional();
        if (row.isEmpty()) {
            return false;
        }
        OAuthState oauthState = row.get();
        boolean valid = oauthState.expiresAt() > now()
                && oauthState.provider().equals(provider)
                && (oauthState.userId() == null || oauthState.userId().equals(userId))
                && (oauthState.userAgent() == null || oauthState.userAgent().equals(userAgent))
                && (oauthState.ip() == null || oauthState.ip().equals(ip));
        if (valid) {
            jdbcClient.sql("DELETE FROM oauth_states WHERE state = :state").param("state", state).update();
        }
        return valid;
    }

    private boolean emailWasDeleted(String email) {
        return jdbcClient.sql("SELECT email_hash FROM deleted_emails WHERE email_hash = :emailHash")
                .param("emailHash", emailFingerprint(email))
                .query(String.class)
                .optional()
                .isPresent();
    }

    private static CurrentUser withoutSecret(CurrentUser user) {
        return new CurrentUser(user.id(), user.email(), user.name(), user.provider(), null, user.googleSub(), user.createdAt(), user.emailVerified());
    }

    private static String normalizeEmail(String email) {
        String normalized = email == null ? "" : email.trim().toLowerCase();
        if (normalized.isEmpty() || normalized.length() > 255 || !EMAIL_PATTERN.matcher(normalized).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid email format");
        }
        return normalized;
    }

    private static String normalizeName(String name, String fallbackEmail) {
        String candidate = name == null ? "" : name.trim();
        if (candidate.isEmpty() && fallbackEmail.contains("@")) {
            candidate = fallbackEmail.substring(0, fallbackEmail.indexOf('@'));
        }
        if (candidate.isBlank() || candidate.length() > 100) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Name must be at most 100 characters long");
        }
        return candidate;
    }

    private static void validatePasswordStrength(String password) {
        if (password == null || password.length() < 12 || password.length() > 128) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Password must be at least 12 characters long");
        }
        boolean hasLetter = password.chars().anyMatch(Character::isLetter);
        boolean hasDigit = password.chars().anyMatch(Character::isDigit);
        if (!hasLetter || !hasDigit) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Password must include both letters and numbers");
        }
    }

    static String hashPassword(String password) {
        byte[] salt = randomBytes(16);
        byte[] derived = SCrypt.generate(password.getBytes(StandardCharsets.UTF_8), salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DK_LEN);
        return "scrypt$%d$%d$%d$%s$%s".formatted(SCRYPT_N, SCRYPT_R, SCRYPT_P, HexFormat.of().formatHex(salt), HexFormat.of().formatHex(derived));
    }

    static boolean verifyPassword(String password, String encoded) {
        if (encoded == null || encoded.isBlank()) {
            return false;
        }
        if (encoded.startsWith("scrypt$")) {
            String[] parts = encoded.split("\\$", 6);
            if (parts.length != 6) {
                return false;
            }
            try {
                int n = Integer.parseInt(parts[1]);
                int r = Integer.parseInt(parts[2]);
                int p = Integer.parseInt(parts[3]);
                byte[] salt = HexFormat.of().parseHex(parts[4]);
                byte[] expected = HexFormat.of().parseHex(parts[5]);
                byte[] derived = SCrypt.generate(password.getBytes(StandardCharsets.UTF_8), salt, n, r, p, expected.length);
                return MessageDigest.isEqual(expected, derived);
            } catch (Exception ignored) {
                return false;
            }
        }
        int delimiter = encoded.indexOf('$');
        if (delimiter < 0) {
            return false;
        }
        String salt = encoded.substring(0, delimiter);
        return MessageDigest.isEqual(encoded.getBytes(StandardCharsets.UTF_8), hashPasswordLegacy(password, salt).getBytes(StandardCharsets.UTF_8));
    }

    private static String hashPasswordLegacy(String password, String salt) {
        return salt + "$" + sha256Hex(salt + ":" + password);
    }

    public static String hashToken(String token) {
        return sha256Hex("session:" + token);
    }

    private static String emailFingerprint(String email) {
        return sha256Hex(email.trim().toLowerCase());
    }

    private static String sha256Hex(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception exception) {
            throw new IllegalStateException("Failed to compute SHA-256", exception);
        }
    }

    private static byte[] randomBytes(int size) {
        byte[] value = new byte[size];
        SECURE_RANDOM.nextBytes(value);
        return value;
    }

    private static String randomHex(int bytes) {
        return HexFormat.of().formatHex(randomBytes(bytes));
    }

    private static int now() {
        return Math.toIntExact(Instant.now().getEpochSecond());
    }

    private static String utcIso() {
        return OffsetDateTime.ofInstant(Instant.now(), ZoneOffset.UTC).toString();
    }

    private record OAuthState(String state, String provider, String userId, int createdAt, int expiresAt, String userAgent, String ip) {
    }
}
