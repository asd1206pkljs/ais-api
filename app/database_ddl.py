"""Raw DDL shared by migrations and the test bootstrap (create_all cannot
express triggers). One statement per entry: asyncpg prepares statements one
at a time."""

AUDIT_IMMUTABLE_STATEMENTS = (
    """
CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only (% rejected)', TG_OP;
END;
$$ LANGUAGE plpgsql
""",
    "DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs",
    """
CREATE TRIGGER trg_audit_logs_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable()
""",
    "DROP TRIGGER IF EXISTS trg_audit_logs_no_truncate ON audit_logs",
    """
CREATE TRIGGER trg_audit_logs_no_truncate
    BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_immutable()
""",
)

AUDIT_IMMUTABLE_DROP_STATEMENTS = (
    "DROP TRIGGER IF EXISTS trg_audit_logs_no_truncate ON audit_logs",
    "DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs",
    "DROP FUNCTION IF EXISTS audit_logs_immutable()",
)
