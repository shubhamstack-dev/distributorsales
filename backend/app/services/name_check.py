"""Before a conversion goes in: is every customer and product in the masters?

A name in the distributor's file is matched to CUSTOMER_MASTER / PRODUCT_MASTER
by services/name_match.py: name or alias, then the spellings MAPPING_MASTER's
history has met, then a match chosen by hand, then the name cleaned, shortened
or nearly alike — only where exactly one master fits. Both the name as read and
the name after the distributor's own name list are tried.

The conversion is refused, and nothing is written, when
* a customer or product matches nothing: create it in the masters, or add the
  file's spelling as an alias of the one it is;
* a matched customer has no territory for the product's group in
  CUSTOMER_TERR_ASSIGNMENT: MAPPING_MASTER could not say whose sales they are
  (the old data has no row without an HQ). Assign it on Customer Terr-PG;
* the distributor has no DIST_ID.
"""
from __future__ import annotations


from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as M, models_master as X
from .name_match import Matcher
from .names import norm


def matchers(db: Session, dist) -> tuple[Matcher, Matcher]:
    """Customer and product matchers fed with the masters (names and aliases),
    the history in MAPPING_MASTER and MAPPING_MASTER_MID (this distributor's
    first), and the matches chosen by hand. Inactive masters match too: an
    inactive product's sales are still its sales."""
    cust, prod = Matcher("customer"), Matcher("product")
    C, P = X.CustomerMaster, X.ProductMaster
    for m, model, name_attr, n in ((cust, C, "customer_name", X.CUSTOMER_ALIASES),
                                    (prod, P, "sap_product_name", X.PRODUCT_ALIASES)):
        cols = [getattr(model, name_attr)] + [getattr(model, f"alias_{i}") for i in range(1, n + 1)]
        for rid, *names in db.execute(select(model.id, *cols)):
            m.add_master(rid, *names)
    for T in (X.SalesMapping, X.MidSalesMapping):
        for m, name_col, id_col in ((cust, T.customer_name, T.customer_id),
                                    (prod, T.product_name, T.product_id)):
            for name, mid, dist_id, rows in db.execute(
                    select(name_col, id_col, T.dist_id, func.count())
                    .where(id_col.is_not(None)).group_by(name_col, id_col, T.dist_id)):
                m.add_history(name, mid, rows, own=dist.dist_id is not None and dist_id == dist.dist_id)
    for kind, name, mid in db.execute(select(M.NameMatch.kind, M.NameMatch.name, M.NameMatch.master_id)):
        (cust if kind == "customer" else prod).add_chosen(name, mid)
    return cust, prod


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
    cust, prod = matchers(db, dist)
    how: dict[str, dict] = {"customer": {}, "product": {}}   # name -> (master, level), shown after
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
        cid, clevel = cust.find(r["customer_as"], r["customer"])
        pid, plevel = prod.find(r["product_as"], r["product"])
        r["customer_id"], r["product_id"] = cid, pid
        for kind, mid, level, name, m in (("customer", cid, clevel, r["customer_as"], cust),
                                          ("product", pid, plevel, r["product_as"], prod)):
            if mid is not None:
                if level not in ("exact", "history"):
                    how[kind][name] = {"name": name, "master_id": mid,
                                       "master": m.names.get(mid), "level": level}
                continue
            book = new_c if kind == "customer" else new_p
            e = book.setdefault(norm(name), {"name": name, "rows": 0, "files": set(),
                                             "suggestions": m.suggest(name)})
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
        "matched_twice": [],
        # names placed by the cleaned / shortened / similar / chosen levels: listed on
        # the batch so a person can glance over them
        "matched_by_likeness": sorted(how["customer"].values(), key=lambda e: e["name"])
                               + sorted(how["product"].values(), key=lambda e: e["name"]),
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
