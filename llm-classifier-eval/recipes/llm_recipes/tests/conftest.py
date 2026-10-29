import os
import tempfile
from typing import Iterator

import pytest
from peewee import SqliteDatabase
from prodigy.components.db import DB_TABLES, Database, disconnect, get_db, set_db


@pytest.fixture()
def database() -> Iterator[Database]:
    # A file rather than an in-memory database, which Prodigy's reconnects drop
    fd, path = tempfile.mkstemp(suffix="prodigy-test-db")
    if get_db() is not None:
        disconnect()
        set_db(None)
    sqlite = SqliteDatabase(path)
    with sqlite.bind_ctx(DB_TABLES):
        sqlite.create_tables(DB_TABLES)
        db = Database(sqlite)
        set_db(db)
        yield db
        disconnect()
    os.close(fd)
    os.remove(path)
