from alembic import context
from sqlalchemy import engine_from_config, pool
from app.config import settings
from app.database import Base
from app import models

config = context.config
config.set_main_option('sqlalchemy.url', settings.database_url_resolved.replace('%', '%%'))
target_metadata = Base.metadata
if context.is_offline_mode():
    context.configure(url=settings.database_url_resolved, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix='sqlalchemy.', poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
