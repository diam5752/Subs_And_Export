DO $$
BEGIN
    IF EXISTS (
        SELECT google_sub
        FROM users
        WHERE google_sub IS NOT NULL
        GROUP BY google_sub
        HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'Cannot enforce unique Google subjects while duplicate identities exist';
    END IF;
END
$$;

DROP INDEX IF EXISTS ix_users_google_sub;
CREATE UNIQUE INDEX ix_users_google_sub ON users (google_sub);
