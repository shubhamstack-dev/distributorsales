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
        ("MidCutoffDay", "INT NULL"),
        ("SalesSheet", "INT NULL"),
        ("ReturnSheet", "INT NULL"),
        ("ProductKeepDot", "INT NOT NULL DEFAULT 0"),
    ],
    "batch": [("MidCutoffDay", "INT NULL")],
    # the Master ID the Excel master tables point at
    **{t: [("LegacyId", "INT NULL")] for t in (
        "md_zone", "md_headquarter", "md_territory", "md_product_group",
        "md_designation", "md_role", "md_team")},
}
# MySQL only: columns made wider after release -> (table, column, DDL, length)
WIDEN = [("distributor", "Note", "VARCHAR(700) NULL", 700)]
# MySQL only: foreign keys for columns added above (SQLite cannot add them later)
FKS = [("distributor", "fk_dist_country", "CountryId", "md_country", "Id")]
# The alignment tables pointed at md_customer / md_sku / md_employee before the
# four tables of MASTER DATA & TABLES.xlsx replaced them. Those keys are dropped
# so rows can point at CUSTOMER_MASTER / PRODUCT_MASTER / EMPLOYEE_MASTER. The
# old md_customer, md_customer_alias, md_sku, md_sku_alias, md_brand and
# md_employee tables are left in place, unused (see migrations/003).
OLD_TARGETS = {"md_customer", "md_sku", "md_employee", "md_brand"}
REPOINT = [("md_customer_assignment", "CustomerId", "CUSTOMER_MASTER", "CUSTOMER_ID"),
           ("md_customer_assignment", "SkuId", "PRODUCT_MASTER", "PRODUCT_ID"),
           ("md_employee_assignment", "EmployeeId", "EMPLOYEE_MASTER", "EMPLOYEE_ID"),
           ("md_employee_assignment", "SkuId", "PRODUCT_MASTER", "PRODUCT_ID"),
           ("md_product_reporting_sku", "SkuId", "PRODUCT_MASTER", "PRODUCT_ID")]


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
                    done.append(f"column {table}.{col} added")
        if engine.dialect.name == "mysql":
            for table, col, ddl, n in WIDEN:
                if table not in tables:
                    continue
                cur = next((c for c in inspect(cx).get_columns(table) if c["name"] == col), None)
                if cur is not None and (getattr(cur["type"], "length", None) or n) < n:
                    cx.execute(text(f"ALTER TABLE {table} MODIFY {col} {ddl}"))
                    done.append(f"column {table}.{col} widened")
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
                    done.append(f"key {table}.{name} added")
            archived: set[str] = set()
            for table, col, ref, refcol in REPOINT:
                if table not in tables:
                    continue
                fks = inspect(cx).get_foreign_keys(table)
                for fk in fks:
                    if fk.get("constrained_columns") == [col] and fk.get("referred_table") in OLD_TARGETS:
                        if table not in archived:
                            # The rows' ids name the OLD md_customer / md_sku /
                            # md_employee rows. Left in place, CustomerId 1 would
                            # read as CUSTOMER_MASTER 1 - another customer - once
                            # the workbook is uploaded. They are moved, once, to
                            # <table>_before_master_tables, with nothing lost.
                            keep = f"{table}_before_master_tables"
                            cx.execute(text(f"CREATE TABLE IF NOT EXISTS {keep} AS SELECT * FROM {table}"))
                            n = cx.execute(text(f"DELETE FROM {table}")).rowcount
                            archived.add(table)
                            if n:
                                done.append(f"{n} rows of {table} pointed at the old masters; moved to "
                                            f"{keep}. Re-enter that alignment against the new masters")
                        cx.execute(text(f"ALTER TABLE {table} DROP FOREIGN KEY {fk['name']}"))
                        done.append(f"{table}.{fk['name']} (pointed at {fk['referred_table']}) dropped")
                fks = inspect(cx).get_foreign_keys(table)
                if any(fk.get("constrained_columns") == [col] for fk in fks):
                    continue
                orphans = cx.execute(text(
                    f"SELECT COUNT(*) FROM {table} t LEFT JOIN {ref} r ON r.{refcol} = t.{col} "
                    f"WHERE r.{refcol} IS NULL")).scalar()
                if orphans:
                    done.append(f"{table}.{col}: {orphans} rows point at the old table, so no key "
                                f"to {ref} was added; re-enter that alignment")
                    continue
                cx.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT fk_{table[3:]}_{col.lower()} "
                                f"FOREIGN KEY ({col}) REFERENCES {ref}({refcol})"))
                done.append(f"{table}.{col} now points at {ref}")
    return done
