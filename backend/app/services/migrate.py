"""Bring an existing database up to the current tables.

`create_all` creates tables that are missing but never alters one that is
there, so a database from the first release would keep a `distributor` table
without the new master columns and every query naming them would fail. This
adds what is missing, and nothing else: it never drops or changes a column,
so running it on every start is safe.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# table -> [(column, DDL type)]
ADDED = {
    "distributor": [
        ("Code", "VARCHAR(20) NULL"),
        ("CountryId", "INT NULL"),
        ("ContactPerson", "VARCHAR(120) NULL"),
        ("Phone", "VARCHAR(30) NULL"),
        ("Email", "VARCHAR(120) NULL"),
    ],
}
# MySQL only: foreign keys for columns added above (SQLite cannot add them later)
FKS = [("distributor", "fk_dist_country", "CountryId", "md_country", "Id")]


def ensure_columns(engine: Engine) -> list[str]:
    done: list[str] = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as cx:
        for table, cols in ADDED.items():
            if table not in tables:
                continue
            have = {c["name"].lower() for c in insp.get_columns(table)}
            for col, ddl in cols:
                if col.lower() not in have:
                    cx.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    done.append(f"{table}.{col}")
        if engine.dialect.name == "mysql":
            for table, name, col, ref, refcol in FKS:
                names = {fk.get("name") for fk in inspect(cx).get_foreign_keys(table)}
                if name not in names:
                    cx.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                                    f"FOREIGN KEY ({col}) REFERENCES {ref}({refcol})"))
                    done.append(f"{table}.{name}")
    return done
