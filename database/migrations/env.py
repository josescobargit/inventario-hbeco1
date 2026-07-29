from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.database import Base
from app.modules.audit.infrastructure import models as audit_models  # noqa: F401
from app.modules.auth.infrastructure import models as auth_models  # noqa: F401
from app.modules.catalog.infrastructure import models as catalog_models  # noqa: F401
from app.modules.inventory.infrastructure import models as inventory_models  # noqa: F401
from app.modules.inventory_operations.infrastructure import models as operation_models  # noqa: F401
from app.modules.invoices.infrastructure import models as invoice_models  # noqa: F401
from app.modules.incidents.infrastructure import models as incident_models  # noqa: F401
from app.modules.dispatches.infrastructure import models as dispatch_models  # noqa: F401
from app.modules.deliveries.infrastructure import models as delivery_models  # noqa: F401
from app.modules.returns.infrastructure import models as return_models  # noqa: F401
from app.modules.documents.infrastructure import models as document_models  # noqa: F401
from app.modules.documents.infrastructure import job_models as document_job_models  # noqa: F401
from app.modules.reservations.infrastructure import models as reservation_models  # noqa: F401
from app.modules.settings.infrastructure import models as settings_models  # noqa: F401
from app.modules.purchase_orders.infrastructure import models as purchase_order_models  # noqa: F401
from app.modules.stock_adjustments.infrastructure import models as adjustment_models  # noqa: F401
from app.modules.stock_imports.infrastructure import models as import_models  # noqa: F401
from app.modules.supplier_invoices.infrastructure import (
    models as supplier_invoice_models,
)  # noqa: F401


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
database_url = settings.migration_database_url or settings.database_url
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
