"""SQLite connection and transaction-scoped persistence package."""

# Keep this package initializer deliberately light. Importing the migration
# module here makes ``python -m app.db.migrations`` load it twice via runpy.
from app.db.connection import Database

__all__ = ["Database"]
