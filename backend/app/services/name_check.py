"""Before a conversion goes in: is every customer and product in the masters?

A name in the distributor's file is matched to CUSTOMER_MASTER by its
CUSTOMER_NAME or any of CUSTOMER_ALIAS_1..50, and to PRODUCT_MASTER by its
SAP_PRODUCT_NAME or any of PRODUCT_ALIAS_1..100, with spaces, punctuation and
case ignored (services/names.norm, as the distributor name lists match). Both
the name as read and the name after the distributor's own name list are tried.

The conversion is refused, and nothing is written, when
* a customer or product matches nothing: create it in the masters, or add the
  file's spelling as an alias of the one it is;
* a matched customer has no territory for the product's group in
  CUSTOMER_TERR_ASSIGNMENT: MAPPING_MASTER could not say whose sales they are
  (the old data has no row without an HQ). Assign it on Customer Terr-PG;
* the distributor has no DIST_ID.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models_master as X
from .names import norm


class Index:
    """norm(name or alias) -> the master's ID. Inactive rows match too: an
    inactive product's sales are still its sales."""

    def __init__(self, db: Session, model, name_attr: str, prefix: str, count: int):
        self.ids: dict[str, set[int]] = defaultdict(set)
        cols = [getattr(model, name_attr)] + [getattr(model, f"alias_{i}") for i in range(1, count + 1)]
        for row in db.execute(select(model.id, *cols)):
            rid, *names = row
            for n in names:
                k = norm(n)
                if k:
                    self.ids[k].add(rid)
        self.twice: set[str] = set()              # names two masters both claim

    def find(self, *names) -> int | None:
        for n in names:
            hit = self.ids.get(norm(n))
            if hit:
                if len(hit) > 1:
                    self.twice.add(str(n))
                return min(hit)
        return None


def _groups(db: Session) -> dict[int, int | None]:
    """product ID -> its product group (Master ID): the SKU's own, else its brand's."""
    P, B = X.ProductMaster, X.ProductMasterBrand
    return {pid: (g if g is not None else bg) for pid, g, bg in db.execute(
        select(P.id, P.product_group_id, B.product_group_id)
        .outerjoin(B, P.product_brand_id == B.id))}


def check(db: Session, rows: list[dict], dist) -> dict:
    """rows: dicts with customer / product (as read) and customer_as / product_as
    (after the distributor's name list), and file. Sets customer_id / product_id
    on each row. Returns what stops the conversion, empty lists when nothing does."""
    cust = Index(db, X.CustomerMaster, "customer_name", "CUSTOMER_ALIAS_", X.CUSTOMER_ALIASES)
    prod = Index(db, X.ProductMaster, "sap_product_name", "PRODUCT_ALIAS_", X.PRODUCT_ALIASES)
    groups = _groups(db)
    assigned = {(c, g) for c, g in db.execute(select(X.CustomerTerrAssignment.customer_id,
                                                     X.CustomerTerrAssignment.product_group_id))}
    gname = dict(db.execute(select(X.ProductGroup.legacy_id, X.ProductGroup.name)).all())
    home = {}            # customer -> the territory CUSTOMER_MASTER gives it, offered first

    new_c: dict[str, dict] = {}
    new_p: dict[str, dict] = {}
    no_group: dict[str, dict] = {}
    unassigned: dict[tuple, dict] = {}
    for r in rows:
        r["customer_id"] = cid = cust.find(r["customer_as"], r["customer"])
        r["product_id"] = pid = prod.find(r["product_as"], r["product"])
        if cid is None:
            e = new_c.setdefault(norm(r["customer_as"]), {"name": r["customer_as"], "rows": 0, "files": set()})
            e["rows"] += 1
            e["files"].add(r["file"])
        if pid is None:
            e = new_p.setdefault(norm(r["product_as"]), {"name": r["product_as"], "rows": 0, "files": set()})
            e["rows"] += 1
            e["files"].add(r["file"])
        if cid is None or pid is None:
            continue
        g = groups.get(pid)
        if g is None:
            e = no_group.setdefault(r["product_as"], {"name": r["product_as"], "rows": 0})
            e["rows"] += 1
        elif (cid, g) not in assigned:
            if cid not in home:
                home[cid] = db.execute(select(X.CustomerMaster.territory_id)
                                       .where(X.CustomerMaster.id == cid)).scalar()
            e = unassigned.setdefault((cid, g), {"customer": r["customer_as"], "customer_id": cid,
                                                 "product_group": gname.get(g, str(g)),
                                                 "product_group_id": g, "rows": 0,
                                                 "territory_id": home[cid]})
            e["rows"] += 1

    def listed(d):
        out = sorted(d.values(), key=lambda e: str(e.get("name") or e.get("customer")).upper())
        for e in out:
            if "files" in e:
                e["files"] = sorted(e["files"])
        return out

    problems = {
        "new_customers": listed(new_c),
        "new_products": listed(new_p),
        "products_without_group": listed(no_group),
        "customers_not_assigned": listed(unassigned),
        "dist_id_missing": dist.dist_id is None,
        "matched_twice": sorted(cust.twice | prod.twice),
    }
    return problems


def blocking(p: dict) -> bool:
    return bool(p["new_customers"] or p["new_products"] or p["products_without_group"]
                or p["customers_not_assigned"] or p["dist_id_missing"])


def message(p: dict, dist_name: str) -> str:
    parts = []
    if p["new_customers"]:
        parts.append(f"{len(p['new_customers'])} customer(s) are not in Customer/Hospital by name or "
                     f"alias: create them, or add the file's spelling as an alias of the right customer")
    if p["new_products"]:
        parts.append(f"{len(p['new_products'])} product(s) are not in SKU by name or alias: create "
                     f"them, or add the file's spelling as an alias of the right SKU")
    if p["products_without_group"]:
        parts.append(f"{len(p['products_without_group'])} product(s) have no product group: give the "
                     f"SKU or its brand one")
    if p["customers_not_assigned"]:
        parts.append(f"{len(p['customers_not_assigned'])} customer / product group pair(s) have no "
                     f"territory: assign them on Customer Terr-PG")
    if p["dist_id_missing"]:
        parts.append(f"{dist_name} has no DIST_ID: set it on Distributor/Vendor")
    return "Nothing was converted. " + "; ".join(parts) + "."
