-- ============================================================================
-- DocIntel Enterprise Row-Level Security (RLS) Policies
-- ============================================================================
-- Enforce multi-tenant isolation inside the PostgreSQL engine as a second
-- layer of defense behind SQLAlchemy query filters.
--
-- Usage:
--   1. Ensure your production app connects with a non-superuser role (e.g., docintel_app),
--      because PostgreSQL superusers bypass RLS unless FORCE ROW LEVEL SECURITY is set.
--   2. Run this script against your production database:
--      psql "$DATABASE_URL_SYNC" -f infra/postgres/rls_policies.sql
--   3. App sessions automatically execute:
--      SELECT set_config('app.current_org_id', '<uuid>', false);
-- ============================================================================

DO $$
DECLARE
    tbl text;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['documents', 'chunks', 'conversations', 'usage_events', 'audit_logs']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY;', tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation_policy ON %I;', tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation_policy ON %I
             USING (org_id = NULLIF(current_setting(''app.current_org_id'', true), '''')::uuid)
             WITH CHECK (org_id = NULLIF(current_setting(''app.current_org_id'', true), '''')::uuid);',
            tbl
        );
    END LOOP;
END
$$;
