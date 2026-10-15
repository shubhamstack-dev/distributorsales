"""The columns added to an existing database on start (services/migrate.py)."""
import ast
import pathlib

from sqlalchemy import create_engine, inspect, text

from app.database import Base
from app import models, models_master        # noqa: F401  (the tables)
from app.services import migrate


def test_each_table_is_listed_once():
    """A table written twice in ADDED keeps only its last list, so the first
    list's columns are never added (batch.NprRate once was)."""
    src = pathlib.Path(migrate.__file__).read_text(encoding="utf-8")
    added = next(n.value for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "ADDED")
    keys = [k.value for k in added.keys if isinstance(k, ast.Constant)]
    assert len(keys) == len(set(keys)), [k for k in keys if keys.count(k) > 1]


def test_an_old_database_gets_every_listed_column(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(eng)
    dropped = set()
    for table, cols in migrate.ADDED.items():  # as a database from before these columns
        for col, _ in cols:
            try:                                # (SQLite cannot drop a foreign key's column)
                with eng.begin() as cx:
                    cx.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
                dropped.add((table, col))
            except Exception:
                pass
    assert {("batch", "NprRate"), ("distributor", "FileCurrency"), ("distributor", "DistId"),
            ("sales_row", "CustomerId"), ("sales_row", "ProductId")} <= dropped
    migrate.ensure_columns(eng)
    insp = inspect(eng)
    for table, cols in migrate.ADDED.items():
        have = {c["name"] for c in insp.get_columns(table)}
        assert {c for c, _ in cols} <= have, (table, {c for c, _ in cols} - have)
    assert "NprRate" in {c["name"] for c in insp.get_columns("batch")}
