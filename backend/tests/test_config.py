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


def test_supabase_direct_database_urls_use_pooler_on_render() -> None:
    settings = Settings(
        database_url=(
            "postgresql://postgres:secret%25value@db.project.supabase.co:5432/postgres"
        ),
        migration_database_url=(
            "postgresql://postgres:secret%25value@db.project.supabase.co:5432/postgres"
        ),
    )

    assert settings.database_url == (
        "postgresql+psycopg://postgres.project:secret%25value"
        "@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
    )
    assert settings.migration_database_url == settings.database_url
