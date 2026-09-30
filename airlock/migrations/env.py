from alembic import context
from airlock.storage import metadata
connection=context.config.attributes.get('connection')
if connection is None:
    raise RuntimeError('Run the supported Store.initialize / CLI initialization entry point with an explicit connection')
context.configure(connection=connection,target_metadata=metadata,render_as_batch=True)
with context.begin_transaction():context.run_migrations()
