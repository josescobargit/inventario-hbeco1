from app.core.config import Settings


def test_supabase_pooler_urls_use_transaction_pooler_port() -> None:
    settings = Settings(
        database_url=(
            "postgresql+psycopg://postgres.project:secret"
            "@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require"
        ),
        migration_database_url=(
            "postgresql+psycopg://postgres.project:secret"
            "@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require"
        ),
    )

    assert ":6543/postgres" in settings.database_url
    assert ":6543/postgres" in settings.migration_database_url
