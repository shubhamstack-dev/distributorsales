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
        ("RateMode", "VARCHAR(10) NOT NULL DEFAULT 'calc'"),
    ],
    # legacy import (the old SQL Server data): its ids and the fields it kept
    **{t: [("LegacyId", "INT NULL")] for t in (
        "md_zone", "md_headquarter", "md_territory", "md_product_group",
        "md_designation", "md_role", "md_team")},
    "md_brand": [("Nrv", "VARCHAR(20) NULL"), ("StartDate", "DATE NULL"),
                 ("EndDate", "DATE NULL"), ("LegacyId", "INT NULL")],
    "md_sku": [("SapProductId", "VARCHAR(25) NULL"), ("MaterialCode", "VARCHAR(50) NULL"),
               ("Nrv", "VARCHAR(20) NULL"), ("StartDate", "DATE NULL"),
               ("EndDate", "DATE NULL"), ("LegacyId", "INT NULL")],
    "md_customer": [("SapId", "VARCHAR(50) NULL"), ("BillingName", "VARCHAR(200) NULL"),
                    ("ZoneId", "INT NULL"), ("HeadquarterId", "INT NULL"),
                    ("TerritoryId", "INT NULL"), ("SubTerritory", "VARCHAR(120) NULL"),
                    ("State", "VARCHAR(80) NULL"), ("Remark", "VARCHAR(200) NULL"),
                    ("StartDate", "DATE NULL"), ("EndDate", "DATE NULL"),
                    ("LegacyId", "INT NULL")],
    "md_employee": [("EndDate", "DATE NULL"), ("TerritoryCode", "VARCHAR(20) NULL"),
                    ("RdCsEditable", "INT NOT NULL DEFAULT 0"), ("LegacyId", "INT NULL")],
}
# MySQL only: columns made wider after release -> (table, column, DDL, length)
WIDEN = [("md_sku", "Name", "VARCHAR(250) NOT NULL", 250)]
# MySQL only: foreign keys for columns added above (SQLite cannot add them later)
FKS = [("distributor", "fk_dist_country", "CountryId", "md_country", "Id"),
       ("md_customer", "fk_cust_zone", "ZoneId", "md_zone", "Id"),
       ("md_customer", "fk_cust_hq", "HeadquarterId", "md_headquarter", "Id"),
       ("md_customer", "fk_cust_territory", "TerritoryId", "md_territory", "Id")]


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
            for table, col, ddl, n in WIDEN:
                if table not in tables:
                    continue
                cur = next((c for c in inspect(cx).get_columns(table) if c["name"] == col), None)
                if cur is not None and (getattr(cur["type"], "length", None) or n) < n:
                    cx.execute(text(f"ALTER TABLE {table} MODIFY {col} {ddl}"))
                    done.append(f"{table}.{col} widened")
            for table, name, col, ref, refcol in FKS:
                if table not in tables:
                    continue
                # a table made by create_all already has the key, under MySQL's
                # own name for it, so look for the column rather than the name
                fks = inspect(cx).get_foreign_keys(table)
                if not any(fk.get("name") == name or fk.get("constrained_columns") == [col]
                           for fk in fks):
                    cx.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                                    f"FOREIGN KEY ({col}) REFERENCES {ref}({refcol})"))
                    done.append(f"{table}.{name}")
    return done
