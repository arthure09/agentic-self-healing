-- Dijalankan sekali saat volume data PostgreSQL pertama kali dibuat.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Rasio pemakaian koneksi terhadap max_connections (dipakai untuk TC-01).
CREATE OR REPLACE VIEW v_connection_usage AS
SELECT
  count(*)                                   AS active_connections,
  current_setting('max_connections')::int    AS max_connections,
  round(count(*) * 100.0 / current_setting('max_connections')::int, 2) AS usage_percent
FROM pg_stat_activity;
