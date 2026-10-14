"""Add and remove assignments the way the old Abbott forms did, in bulk.

    POST /api/assign/{kind}/{action}      kind:   customer | employee | team_pg_hq
                                          action: create | delete | assign_all | clean
    body: the form, plus "dry_run": true to only count

Every action can be checked first (dry_run): it says how many rows it would add
or remove and why any were left out, and writes nothing. The screens check, ask,
then run.

customer   (Customer Terr-PG: the old "Customer Territory Pg" form)
    create      customers × territories × product groups. Each territory brings
                its HQ; the team is the one given, else every team TEAM_PG_HQ
                lists for that group in that HQ. Every active SKU of each group
                goes into CUSTOMER_PG_ASSIGNMENT with its brand.
    delete      the same rows out; a group's products go once the customer has
                no territory row left for that group.
    assign_all  every customer (or those given) gets every HQ — each territory
                of it, with each group and team TEAM_PG_HQ lists there — and every
                active SKU.
    clean       every customer assignment row (or those of the customers given).

employee   (Employee Terr-PG: the old "Emp/Terr-Pg Assignment" form)
    create      employees × HQs (each with its territories) into
                EMPLOYEE_TERR_ASSIGNMENT; employees × every active SKU of the
                groups into EMPLOYEE_PG_ASSIGNMENT. One group or many.
    delete      those HQs and groups out for those employees.
    clean       every employee assignment row (or those of the employees given).

team_pg_hq (the old "Team Hq Pg" form)
    create      team × HQs × groups into TEAM_PG_HQ_ASSIGNMENT, names filled in.
    delete      those rows out.
    clean       every row (or those of the team given).

IDs are as the tables keep them: customers, employees, brands and SKUs by their
own ID; HQs, territories, product groups and teams by Master ID.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import and_, delete, insert, select
from sqlalchemy.orm import Session

from .. import models_master as X
from ..database import get_db

router = APIRouter(prefix="/api")
CHUNK = 2000


def bad(msg: str):
    raise HTTPException(422, msg)


def _ids(body: dict, name: str, required: str | None = None) -> list[int]:
    v = body.get(name)
    if v in (None, "", []):
        if required:
            bad(f"Choose {required}.")
        return []
    if not isinstance(v, list):
        v = [v]
    try:
        return sorted({int(x) for x in v if x not in (None, "")})
    except (TypeError, ValueError):
        bad(f"{name} should be a list of IDs.")


# -------------------------------------------------------- what the masters say
def _territories(db, hqs: list[int] | None = None, terrs: list[int] | None = None):
    """[(territory Master ID, its HQ's Master ID)] for active territories."""
    T, H = X.Territory, X.Headquarter
    sel = select(T.legacy_id, H.legacy_id).join(H, T.headquarter_id == H.id) \
        .where(T.legacy_id.is_not(None), H.legacy_id.is_not(None), T.active == 1)
    if hqs is not None:
        sel = sel.where(H.legacy_id.in_(hqs))
    if terrs is not None:
        sel = sel.where(T.legacy_id.in_(terrs))
    return [tuple(r) for r in db.execute(sel)]


def _products(db, groups: list[int] | None = None):
    """[(product ID, brand ID, group Master ID)] for active SKUs. A SKU with no
    group of its own is in its brand's group."""
    P, B = X.ProductMaster, X.ProductMasterBrand
    rows = db.execute(select(P.id, P.product_brand_id, P.product_group_id, B.product_group_id)
                      .outerjoin(B, P.product_brand_id == B.id).where(P.active == 1)).all()
    out = []
    for pid, bid, g, bg in rows:
        grp = g if g is not None else bg
        if grp is None or (groups is not None and grp not in groups):
            continue
        out.append((pid, bid, grp))
    return out


def _teams(db) -> dict[tuple[int, int], list[int]]:
    """(group, HQ) -> the teams TEAM_PG_HQ_ASSIGNMENT lists there."""
    t = X.TeamPgHqAssignment
    out: dict = {}
    for team, pg, hq in db.execute(select(t.team_id, t.product_group_id, t.hq_id)):
        out.setdefault((pg, hq), []).append(team)
    return out


def _active_ids(db, model) -> list[int]:
    return list(db.execute(select(model.id).where(model.active == 1)).scalars())


def _named(db, model, ids, what):
    have = set(db.execute(select(model.id).where(model.id.in_(ids))).scalars()) if ids else set()
    gone = [i for i in ids if i not in have]
    if gone:
        bad(f"{what} {', '.join(map(str, gone[:10]))} not found.")


# ---------------------------------------------------------------- writing
def _insert_new(db, model, cols: list[str], rows: list[tuple], dry: bool) -> int:
    """Rows not in the table yet go in; returns how many are (or would be) new.
    Every assignment table is unique on the columns given, so this is a set
    difference against what is stored for the same first column."""
    if not rows:
        return 0
    rows = list(dict.fromkeys(rows))
    first = getattr(model, cols[0])
    attrs = [getattr(model, c) for c in cols]
    have: set = set()
    firsts = sorted({r[0] for r in rows})
    for i in range(0, len(firsts), CHUNK):
        have |= set(tuple(r) for r in db.execute(select(*attrs).where(first.in_(firsts[i:i + CHUNK]))))
    new = [r for r in rows if r not in have]
    if not dry:
        tbl = model.__table__
        names = [model.__mapper__.attrs[c].columns[0].name for c in cols]
        for i in range(0, len(new), CHUNK):
            db.execute(insert(tbl), [dict(zip(names, r)) for r in new[i:i + CHUNK]])
    return len(new)


def _remove(db, model, where, dry: bool) -> int:
    ids = list(db.execute(select(model.id).where(where)).scalars())
    if not dry:
        for i in range(0, len(ids), CHUNK):
            db.execute(delete(model).where(model.id.in_(ids[i:i + CHUNK])))
    return len(ids)


def _done(db, dry, **counts):
    if dry:
        db.rollback()
    else:
        db.commit()
    return {"dry_run": dry, **counts}


# ------------------------------------------------------------------ customer
CT, CP = X.CustomerTerrAssignment, X.CustomerPgAssignment
CT_COLS = ["customer_id", "territory_id", "hq_id", "product_group_id", "team_id"]
CP_COLS = ["customer_id", "product_group_id", "product_brand_id", "product_id"]


def _customer_rows(db, customers, terr_hq, groups, team, notes):
    """Territory rows and product rows for customers × territories × groups."""
    teams = _teams(db)
    trows, used_groups = [], set()
    for terr, hq in terr_hq:
        for g in groups:
            ts = [team] if team else teams.get((g, hq), [])
            if not ts:
                notes.add(f"No team has product group {g} in HQ {hq} (Team PG HQ), so that "
                          f"group was left out there. Choose a team, or add it to Team PG HQ.")
                continue
            used_groups.add(g)
            trows += [(c, terr, hq, g, t) for c in customers for t in ts]
    prows = [(c, g, b, p) for (p, b, g) in _products(db, sorted(used_groups)) for c in customers]
    return trows, prows


def customer(db: Session, action: str, body: dict, dry: bool):
    notes: set[str] = set()
    if action in ("create", "delete"):
        customers = _ids(body, "customer_ids", "a customer")
        terrs = _ids(body, "territory_ids", "a territory")
        groups = _ids(body, "product_group_ids", "a product group")
        team = (_ids(body, "team_id") or [None])[0]
        _named(db, X.CustomerMaster, customers, "Customer")
        terr_hq = _territories(db, terrs=terrs)
        if not terr_hq:
            bad("Those territories are not in Territory (or are inactive).")
        if action == "create":
            trows, prows = _customer_rows(db, customers, terr_hq, groups, team, notes)
            a = _insert_new(db, CT, CT_COLS, trows, dry)
            b = _insert_new(db, CP, CP_COLS, prows, dry)
            return _done(db, dry, territory_rows_added=a, product_rows_added=b, notes=sorted(notes))
        w = and_(CT.customer_id.in_(customers), CT.territory_id.in_([t for t, _ in terr_hq]),
                 CT.product_group_id.in_(groups), *([CT.team_id == team] if team else []))
        going = set(db.execute(select(CT.id).where(w)).scalars())
        # a group's products go once the customer has no territory row left for it
        left = {(c, g) for i_, c, g in db.execute(
            select(CT.id, CT.customer_id, CT.product_group_id)
            .where(CT.customer_id.in_(customers), CT.product_group_id.in_(groups)))
            if i_ not in going}
        a = len(going)
        if not dry:
            ids = sorted(going)
            for k in range(0, len(ids), CHUNK):
                db.execute(delete(CT).where(CT.id.in_(ids[k:k + CHUNK])))
        b = 0
        for g in groups:
            bare = [c for c in customers if (c, g) not in left]
            for k in range(0, len(bare), CHUNK):
                b += _remove(db, CP, and_(CP.product_group_id == g,
                                          CP.customer_id.in_(bare[k:k + CHUNK])), dry)
        return _done(db, dry, territory_rows_removed=a, product_rows_removed=b, notes=[])
    if action == "assign_all":
        customers = _ids(body, "customer_ids") or _active_ids(db, X.CustomerMaster)
        if not customers:
            bad("There are no active customers to assign.")
        teams = _teams(db)
        terr_hq = _territories(db)
        trows = [(c, terr, hq, g, t) for terr, hq in terr_hq
                 for (g, h), ts in teams.items() if h == hq for t in ts for c in customers]
        if not teams:
            notes.add("Team PG HQ is empty, so no territory rows could be made: upload "
                      "TEAM_PG_HQ_ASSIGNMENT first.")
        prows = [(c, g, b, p) for (p, b, g) in _products(db) for c in customers]
        a = _insert_new(db, CT, CT_COLS, trows, dry)
        b = _insert_new(db, CP, CP_COLS, prows, dry)
        return _done(db, dry, customers=len(customers), territory_rows_added=a,
                     product_rows_added=b, notes=sorted(notes))
    if action == "clean":
        customers = _ids(body, "customer_ids")
        wt = CT.customer_id.in_(customers) if customers else CT.id.is_not(None)
        wp = CP.customer_id.in_(customers) if customers else CP.id.is_not(None)
        return _done(db, dry, territory_rows_removed=_remove(db, CT, wt, dry),
                     product_rows_removed=_remove(db, CP, wp, dry), notes=[])
    bad("No such action.")


# ------------------------------------------------------------------ employee
ET, EP = X.EmployeeTerrAssignment, X.EmployeePgAssignment
ET_COLS = ["employee_id", "hq_id", "territory_id"]
EP_COLS = ["employee_id", "product_id", "product_brand_id", "product_group_id"]


def employee(db: Session, action: str, body: dict, dry: bool):
    if action in ("create", "delete"):
        emps = _ids(body, "employee_ids", "an employee")
        hqs = _ids(body, "hq_ids")
        groups = _ids(body, "product_group_ids")
        if not hqs and not groups:
            bad("Choose a headquarter, a product group, or both.")
        _named(db, X.EmployeeMaster, emps, "Employee")
        notes = []
        terr_hq = _territories(db, hqs=hqs) if hqs else []
        if hqs and not terr_hq:
            notes.append("Those HQs have no active territory with a Master ID, so no territory "
                         "rows were made for them.")
        if action == "create":
            a = _insert_new(db, ET, ET_COLS, [(e, hq, t) for t, hq in terr_hq for e in emps], dry)
            b = _insert_new(db, EP, EP_COLS,
                            [(e, p, br, g) for (p, br, g) in _products(db, groups) for e in emps]
                            if groups else [], dry)
            return _done(db, dry, territory_rows_added=a, product_rows_added=b, notes=notes)
        a = _remove(db, ET, and_(ET.employee_id.in_(emps), ET.hq_id.in_(hqs)), dry) if hqs else 0
        b = _remove(db, EP, and_(EP.employee_id.in_(emps), EP.product_group_id.in_(groups)), dry) \
            if groups else 0
        return _done(db, dry, territory_rows_removed=a, product_rows_removed=b, notes=[])
    if action == "clean":
        emps = _ids(body, "employee_ids")
        wt = ET.employee_id.in_(emps) if emps else ET.id.is_not(None)
        wp = EP.employee_id.in_(emps) if emps else EP.id.is_not(None)
        return _done(db, dry, territory_rows_removed=_remove(db, ET, wt, dry),
                     product_rows_removed=_remove(db, EP, wp, dry), notes=[])
    bad("No such action.")


# ---------------------------------------------------------------- team PG HQ
TP = X.TeamPgHqAssignment


def team_pg_hq(db: Session, action: str, body: dict, dry: bool):
    if action in ("create", "delete"):
        teams = _ids(body, "team_ids", "a team")
        hqs = _ids(body, "hq_ids", "a headquarter")
        groups = _ids(body, "product_group_ids", "a product group")
        if action == "delete":
            w = and_(TP.team_id.in_(teams), TP.hq_id.in_(hqs), TP.product_group_id.in_(groups))
            return _done(db, dry, rows_removed=_remove(db, TP, w, dry), notes=[])
        names = {}
        for model, ids in ((X.Team, teams), (X.Headquarter, hqs), (X.ProductGroup, groups)):
            names[model] = dict(db.execute(select(model.legacy_id, model.name)
                                           .where(model.legacy_id.in_(ids))).all())
            gone = [i for i in ids if i not in names[model]]
            if gone:
                bad(f"Master ID {', '.join(map(str, gone))} is not in {model.__name__}.")
        have = set(db.execute(select(TP.team_id, TP.product_group_id, TP.hq_id)
                              .where(TP.team_id.in_(teams))))
        new = [(t, g, h) for t in teams for g in groups for h in hqs if (t, g, h) not in have]
        if not dry:
            for t, g, h in new:
                db.add(TP(team_id=t, team_name=names[X.Team][t], product_group_id=g,
                          product_group_name=names[X.ProductGroup][g], hq_id=h,
                          hq_name=names[X.Headquarter][h]))
        return _done(db, dry, rows_added=len(new), notes=[])
    if action == "clean":
        teams = _ids(body, "team_ids")
        w = TP.team_id.in_(teams) if teams else TP.id.is_not(None)
        return _done(db, dry, rows_removed=_remove(db, TP, w, dry), notes=[])
    bad("No such action.")


KINDS = {"customer": customer, "employee": employee, "team_pg_hq": team_pg_hq}


@router.post("/assign/{kind}/{action}")
def run(kind: str, action: str, body: dict = Body(default={}), db: Session = Depends(get_db)):
    fn = KINDS.get(kind)
    if fn is None:
        raise HTTPException(404, "No such assignment page")
    if kind != "customer" and action == "assign_all":
        bad("Assign all is for customers.")
    return fn(db, action, body or {}, bool(body.get("dry_run")) if body else False)

