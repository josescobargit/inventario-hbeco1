import sys

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.database import engine


def main() -> int:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        missing_rls = (
            connection.execute(
                text(
                    """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND NOT rowsecurity
                ORDER BY tablename
                """
                )
            )
            .scalars()
            .all()
        )
        exposed = (
            connection.execute(
                text(
                    """
                SELECT grantee || ':' || table_name || ':' || privilege_type
                FROM information_schema.role_table_grants
                WHERE table_schema = 'public'
                  AND grantee IN ('PUBLIC', 'anon', 'authenticated')
                ORDER BY grantee, table_name, privilege_type
                """
                )
            )
            .scalars()
            .all()
        )
        exposed_schema = (
            connection.execute(
                text(
                    """
                SELECT COALESCE(role.rolname, 'PUBLIC') || ':public:' || acl.privilege_type
                FROM pg_namespace AS namespace
                CROSS JOIN LATERAL aclexplode(
                    COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))
                ) AS acl
                LEFT JOIN pg_roles AS role ON role.oid = acl.grantee
                WHERE namespace.nspname = 'public'
                  AND (acl.grantee = 0 OR role.rolname IN ('anon', 'authenticated'))
                ORDER BY 1
                """
                )
            )
            .scalars()
            .all()
        )

    if missing_rls:
        print(f"database_security=failed tables_without_rls={','.join(missing_rls)}")
        return 1
    if exposed:
        print(f"database_security=failed exposed_privileges={','.join(exposed)}")
        return 1
    if exposed_schema:
        print(
            "database_security=failed exposed_schema_privileges="
            f"{','.join(exposed_schema)}"
        )
        return 1
    print("database_security=ok")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except OperationalError:
        print("database_security=unavailable reason=postgresql_not_reachable")
        sys.exit(2)
