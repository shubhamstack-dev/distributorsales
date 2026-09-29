"""One API for every master, driven by masters/specs.py.

    GET    /api/masters/meta                    what the screens draw
    GET    /api/masters/{slug}                  list: ?q= &page= &size= &<field>=
    GET    /api/masters/{slug}/options          id + label, for drop-downs
    POST   /api/masters/{slug}                  add
    PUT    /api/masters/{slug}/{id}             change
    DELETE /api/masters/{slug}/{id}             remove, refused while anything points at it
    POST   /api/masters/{slug}/delete-many      remove several
    POST   /api/masters/{slug}/bulk             alignment: one row per SKU of a group
    POST   /api/masters/{slug}/copy-year        alignment: last year's rows into this year
    GET    /api/currency/rate | /convert        INR <-> NPR on a date
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models_master as X
from ..database import get_db
from ..masters import specs as S
from ..masters.specs import Spec, bad

router = APIRouter(prefix="/api")


# ================================================================ helpers
def _col(spec: Spec, name: str):
    return getattr(spec.model, name)


def _maxlen(spec: Spec, name: str) -> int | None:
    col = spec.model.__mapper__.attrs[name].columns[0]
    return getattr(col.type, "length", None)


def _has_active(spec: Spec) -> bool:
    return "active" in spec.model.__mapper__.attrs


def _coerce(db: Session, spec: Spec, f: S.Field, raw):
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        if f.type == "bool":
            return 0
        if f.required:
            bad(f"{f.label} is required.")
        return None
    try:
        if f.type in ("text", "code", "select"):
            v = str(raw).strip()
            if f.type == "code":
                v = v.upper()
            n = _maxlen(spec, f.name)
            if n and len(v) > n:
                bad(f"{f.label} can be at most {n} characters.")
            if f.type == "select" and v not in (f.options or []):
                bad(f"{f.label} has to be one of: {', '.join(f.options)}.")
            return v
        if f.type == "int":
            return int(raw)
        if f.type == "decimal":
            return Decimal(str(raw))
        if f.type == "bool":
            return 1 if raw in (True, 1, "1", "true", "True", "yes") else 0
        if f.type == "date":
            return raw if isinstance(raw, date) else date.fromisoformat(str(raw)[:10])
        if f.type == "ref":
            rid = int(raw)
            target = S.get(f.ref)
            if not db.get(target.model, rid):
                bad(f"The {f.label.lower()} chosen no longer exists.")
            return rid
    except HTTPException:
        raise
    except (ValueError, TypeError, ArithmeticError):
        bad(f"{f.label} is not a valid {'date' if f.type == 'date' else 'number' if f.type in ('int', 'decimal') else 'value'}.")
    return raw


def _apply(db: Session, spec: Spec, obj, body: dict, creating: bool):
    for f in spec.fields:
        if f.derived:
            continue
        if f.name in body:
            setattr(obj, f.name, _coerce(db, spec, f, body[f.name]))
        elif creating:
            setattr(obj, f.name, _coerce(db, spec, f, f.default))


def _check_unique(db: Session, spec: Spec, obj):
    for cols, msg in spec.unique:
        vals = [getattr(obj, c) for c in cols]
        if any(v is None for v in vals):
            continue
        conds = []
        for c, v in zip(cols, vals):
            col = _col(spec, c)
            conds.append(func.lower(col) == v.lower() if isinstance(v, str) else col == v)
        q = select(spec.model.id).where(*conds)
        if obj.id:
            q = q.where(spec.model.id != obj.id)
        if db.execute(q).first():
            bad(msg, 409)


def _validate(db: Session, spec: Spec, obj):
    if spec.validate:
        spec.validate(db, obj)
    _check_unique(db, spec, obj)


def _save(db: Session, spec: Spec, obj):
    db.flush()
    if spec.after_save:
        spec.after_save(db, obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        bad("That would clash with a row already stored.", 409)


def _labels(db: Session, spec: Spec, rows) -> dict[str, dict[int, str]]:
    """For every ref field, id -> label of the row it points at, in one query each."""
    out = {}
    for f in spec.fields:
        if f.type != "ref":
            continue
        ids = {getattr(r, f.name) for r in rows} - {None}
        target = S.get(f.ref)
        found = db.execute(select(target.model).where(target.model.id.in_(ids))).scalars() \
            if ids else []
        out[f.name] = {t.id: target.label(t) for t in found}
    return out


def _out(spec: Spec, o, labels) -> dict:
    d = {"id": o.id}
    for f in spec.fields:
        v = getattr(o, f.name)
        if isinstance(v, Decimal):
            v = float(v)
        elif isinstance(v, date):
            v = v.isoformat()
        d[f.name] = v
        if f.type == "ref":
            d[f.name + "__label"] = labels.get(f.name, {}).get(v) if v is not None else None
    if _has_active(spec) and "active" not in d:
        d["active"] = o.active
    d["__label"] = spec.label(o)
    return d


def _filtered(spec: Spec, sel, params):
    for k, v in params.items():
        if v in (None, ""):
            continue
        if k in spec.option_filters:
            sel = spec.option_filters[k](sel, v)
            continue
        f = next((x for x in spec.fields if x.name == k), None)
        if f and f.type in ("ref", "int", "select", "bool", "code"):
            try:
                val = int(v) if f.type in ("ref", "int", "bool") else str(v).upper() \
                    if f.type == "code" else v
            except ValueError:
                bad(f"{f.label} filter is not a number.")
            sel = sel.where(_col(spec, k) == val)
    return sel


def _ordered(spec: Spec, sel):
    for o in spec.order:
        col = _col(spec, o.lstrip("-"))
        sel = sel.order_by(col.desc() if o.startswith("-") else col)
    return sel.order_by(spec.model.id)


def _references(db: Session, slug: str, rid: int) -> list[str]:
    """What still points at this row, in words."""
    found = []
    for s in S.SPECS:
        for f in s.fields:
            if f.type == "ref" and f.ref == slug:
                n = db.execute(select(func.count()).select_from(s.model)
                               .where(_col(s, f.name) == rid)).scalar()
                if n:
                    found.append(f"{n} in {s.title}")
    for model, attr, what in S.get(slug).extra_refs:
        n = db.execute(select(func.count()).select_from(model)
                       .where(getattr(model, attr) == rid)).scalar()
        if n:
            found.append(f"{n} {what}")
    return found


# ================================================================== routes
@router.get("/masters/meta")
def meta():
    return S.meta()


@router.get("/masters/{slug}/options")
def options(slug: str, request: Request, q: str | None = None, limit: int = 500,
            include_inactive: bool = False, db: Session = Depends(get_db)):
    spec = S.get(slug)
    sel = select(spec.model)
    if _has_active(spec) and not include_inactive:
        sel = sel.where(spec.model.active == 1)
    params = {k: v for k, v in request.query_params.items()
              if k not in ("q", "limit", "include_inactive")}
    sel = _filtered(spec, sel, params)
    if q and spec.search:
        like = f"%{q.strip()}%"
        sel = sel.where(or_(*[_col(spec, c).like(like) for c in spec.search]))
    rows = db.execute(_ordered(spec, sel).limit(max(1, min(limit, 2000)))).scalars().all()
    return [{"id": r.id, "label": spec.label(r)} for r in rows]


@router.get("/masters/{slug}")
def list_rows(slug: str, request: Request, q: str | None = None, page: int = 1,
              size: int = 50, db: Session = Depends(get_db)):
    spec = S.get(slug)
    size = max(1, min(size, 500))
    params = {k: v for k, v in request.query_params.items() if k not in ("q", "page", "size")}
    sel = _filtered(spec, select(spec.model), params)
    if q and spec.search:
        like = f"%{q.strip()}%"
        sel = sel.where(or_(*[_col(spec, c).like(like) for c in spec.search]))
    total = db.execute(select(func.count()).select_from(sel.subquery())).scalar()
    rows = db.execute(_ordered(spec, sel).offset((max(page, 1) - 1) * size).limit(size)) \
        .scalars().all()
    labels = _labels(db, spec, rows)
    return {"total": total, "page": page, "size": size,
            "rows": [_out(spec, r, labels) for r in rows]}


@router.post("/masters/{slug}", status_code=201)
def create(slug: str, body: dict = Body(...), db: Session = Depends(get_db)):
    spec = S.get(slug)
    obj = spec.model()
    obj.id = None
    _apply(db, spec, obj, body, creating=True)
    _validate(db, spec, obj)
    db.add(obj)
    _save(db, spec, obj)
    return _out(spec, obj, _labels(db, spec, [obj]))


@router.put("/masters/{slug}/{rid}")
def change(slug: str, rid: int, body: dict = Body(...), db: Session = Depends(get_db)):
    spec = S.get(slug)
    obj = db.get(spec.model, rid)
    if not obj:
        raise HTTPException(404, "That row no longer exists.")
    _apply(db, spec, obj, body, creating=False)
    try:
        _validate(db, spec, obj)
    except HTTPException:
        db.rollback()
        raise
    _save(db, spec, obj)
    return _out(spec, obj, _labels(db, spec, [obj]))


def _delete_one(db: Session, spec: Spec, rid: int):
    obj = db.get(spec.model, rid)
    if not obj:
        raise HTTPException(404, "That row no longer exists.")
    refs = _references(db, spec.slug, rid)
    if refs:
        how = " Mark it inactive instead." if _has_active(spec) else ""
        bad(f"{spec.label(obj)} is still in use: {'; '.join(refs)}.{how}", 409)
    db.delete(obj)


@router.delete("/masters/{slug}/{rid}", status_code=204)
def delete(slug: str, rid: int, db: Session = Depends(get_db)):
    spec = S.get(slug)
    _delete_one(db, spec, rid)
    db.commit()


@router.post("/masters/{slug}/delete-many")
def delete_many(slug: str, body: dict = Body(...), db: Session = Depends(get_db)):
    """All or nothing: if any row is still in use, none are removed."""
    spec = S.get(slug)
    ids = [int(i) for i in (body.get("ids") or [])][:5000]
    if not ids:
        bad("Choose at least one row.")
    try:
        for rid in ids:
            _delete_one(db, spec, rid)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return {"deleted": len(ids)}


@router.post("/masters/{slug}/bulk")
def bulk(slug: str, body: dict = Body(...), db: Session = Depends(get_db)):
    """Assign every active SKU of a product group (or one brand of it) in one go.
    Rows that already exist are left alone and counted as skipped."""
    spec = S.get(slug)
    if not spec.bulk_by_sku:
        bad("This master is not kept at SKU level.")
    pg = body.get("product_group_id")
    if not pg:
        bad("Choose a product group.")
    sel = select(X.Sku.id).join(X.Brand, X.Brand.id == X.Sku.brand_id) \
        .where(X.Brand.product_group_id == int(pg), X.Sku.active == 1)
    if body.get("brand_id"):
        sel = sel.where(X.Sku.brand_id == int(body["brand_id"]))
    if body.get("sku_ids"):
        sel = sel.where(X.Sku.id.in_([int(i) for i in body["sku_ids"]]))
    skus = db.execute(sel.order_by(X.Sku.code)).scalars().all()
    if not skus:
        bad("That product group has no active SKUs to assign.")
    created = skipped = 0
    try:
        for sid in skus:
            obj = spec.model()
            obj.id = None
            _apply(db, spec, obj, {**body, "sku_id": sid}, creating=True)
            if spec.validate:
                spec.validate(db, obj)          # a bad team or year stops the lot
            try:
                _check_unique(db, spec, obj)
            except HTTPException:
                skipped += 1
                continue
            db.add(obj)
            db.flush()
            created += 1
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return {"created": created, "skipped": skipped, "skus": len(skus)}


@router.post("/masters/{slug}/copy-year")
def copy_year(slug: str, body: dict = Body(...), db: Session = Depends(get_db)):
    """Start a year from the one before: copy its rows, skipping any that are
    already there or that do not hold in the new year (with the reason)."""
    spec = S.get(slug)
    if not spec.year_bound:
        bad("This master is not kept by year.")
    src, dst = int(body.get("from_year_id") or 0), int(body.get("to_year_id") or 0)
    if not (db.get(X.Year, src) and db.get(X.Year, dst)):
        bad("Choose both years.")
    if src == dst:
        bad("Copy from a different year.")
    S._year_rows_ok(db, dst)
    created, skipped, reasons = 0, 0, []
    idmap: dict[int, int] = {}
    keep = [f.name for f in spec.fields if not f.derived and f.name != "year_id"] + \
        (["active"] if _has_active(spec) and "active" not in [f.name for f in spec.fields] else [])
    rows = db.execute(select(spec.model).where(spec.model.year_id == src)
                      .order_by(spec.model.id)).scalars().all()
    for r in rows:
        obj = spec.model()
        obj.id = None
        for k in keep:
            setattr(obj, k, getattr(r, k))
        obj.year_id = dst
        try:
            _validate(db, spec, obj)
        except HTTPException as e:
            skipped += 1
            if len(reasons) < 5 and e.detail not in reasons:
                reasons.append(e.detail)
            continue
        db.add(obj)
        db.flush()
        idmap[r.id] = obj.id
        created += 1
    # a reporting line brings its SKUs with it
    if slug == "product_reporting":
        for m in db.execute(select(X.ProductReportingSku)
                            .where(X.ProductReportingSku.year_id == src)).scalars().all():
            if m.product_reporting_id not in idmap:
                continue
            if db.execute(select(X.ProductReportingSku.id).where(
                    X.ProductReportingSku.year_id == dst,
                    X.ProductReportingSku.sku_id == m.sku_id)).first():
                continue
            db.add(X.ProductReportingSku(product_reporting_id=idmap[m.product_reporting_id],
                                         sku_id=m.sku_id, year_id=dst))
    db.commit()
    return {"created": created, "skipped": skipped, "reasons": reasons}


# ================================================================ currency
def rate_on(db: Session, frm: str, to: str, on: date) -> dict:
    frm, to = frm.upper(), to.upper()
    if frm == to:
        return {"rate": 1.0, "from": frm, "to": to, "effective_from": None, "via": "same"}
    for a, b, inverse in ((frm, to, False), (to, frm, True)):
        r = db.execute(select(X.CurrencyRate).where(
            X.CurrencyRate.from_currency == a, X.CurrencyRate.to_currency == b,
            X.CurrencyRate.effective_from <= on)
            .order_by(X.CurrencyRate.effective_from.desc())).scalars().first()
        if r:
            v = float(r.rate)
            return {"rate": round(1 / v, 8) if inverse else v, "from": frm, "to": to,
                    "effective_from": r.effective_from.isoformat(),
                    "via": "inverse" if inverse else "direct"}
    raise HTTPException(404, f"No {frm}/{to} rate is in force on {on.isoformat()}.")


def _day(on: str | None) -> date:
    try:
        return date.fromisoformat(on) if on else date.today()
    except ValueError:
        bad("The date is not a real date.")


@router.get("/currency/rate")
def currency_rate(frm: str = "INR", to: str = "NPR", on: str | None = None,
                  db: Session = Depends(get_db)):
    return rate_on(db, frm, to, _day(on))


@router.get("/currency/convert")
def currency_convert(amount: float, frm: str = "NPR", to: str = "INR", on: str | None = None,
                     db: Session = Depends(get_db)):
    r = rate_on(db, frm, to, _day(on))
    return {**r, "amount": amount, "converted": round(amount * r["rate"], 2)}
