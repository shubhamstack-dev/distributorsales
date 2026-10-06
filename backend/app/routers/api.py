"""The API: sign in, inspect an upload, commit a batch, read it back, export it."""
from __future__ import annotations

import os
import shutil
import time
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config, models as M
from ..database import get_db
from ..services import excel, names as namesvc, parse
from ..services.auth import issue_token, password_ok
from ..services.rules import period

router = APIRouter(prefix="/api")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------ sign in
@router.post("/login")
def login(body: dict = Body(...)):
    if not config.APP_PASSWORD:
        raise HTTPException(503, "No APP_PASSWORD is configured on the server, so nobody can "
                                 "sign in. Set one and restart.")
    if not password_ok(body.get("password") or ""):
        raise HTTPException(401, "That password is not right")
    who = (body.get("who") or "user").strip() or "user"
    return {"token": issue_token(who), "who": who}


# -------------------------------------------------------------- distributors
def _dist_out(d: M.Distributor) -> dict:
    return {"id": d.id, "name": d.name, "cutoff_day": d.cutoff_day,
            "invoice_mode": d.invoice_mode, "negate_returns": bool(d.negate_returns),
            "pick_pattern": d.pick_pattern, "note": d.note, "active": bool(d.active),
            "rate_mode": d.rate_mode or "calc"}


@router.get("/distributors")
def distributors(db: Session = Depends(get_db)):
    rows = db.execute(select(M.Distributor).order_by(M.Distributor.name)).scalars().all()
    return [_dist_out(d) for d in rows]


@router.put("/distributors/{did}")
def update_distributor(did: int, body: dict = Body(...), db: Session = Depends(get_db)):
    d = db.get(M.Distributor, did)
    if not d:
        raise HTTPException(404, "No such distributor")
    if "cutoff_day" in body:
        c = int(body["cutoff_day"])
        if not 1 <= c <= 28:
            raise HTTPException(422, "The cut-off day has to be between 1 and 28")
        d.cutoff_day = c
    if "invoice_mode" in body:
        if body["invoice_mode"] not in ("seq", "file"):
            raise HTTPException(422, "Invoice mode is either seq or file")
        d.invoice_mode = body["invoice_mode"]
    if "rate_mode" in body:
        if body["rate_mode"] not in ("calc", "file"):
            raise HTTPException(422, "Rate is either calc (Amount / Quantity) or file")
        d.rate_mode = body["rate_mode"]
    if "negate_returns" in body:
        d.negate_returns = 1 if body["negate_returns"] else 0
    if "pick_pattern" in body:
        import re as _re
        p = (body["pick_pattern"] or "").strip()
        if p:
            try:
                _re.compile(p)
            except _re.error as e:
                raise HTTPException(422, f"That is not a valid pattern: {e}")
        d.pick_pattern = p or None
    if "note" in body:
        d.note = (body["note"] or "").strip() or None
    db.commit()
    return _dist_out(d)


# ------------------------------------------------------------ name lists
def _names_out(db: Session, did: int) -> dict:
    out = {}
    for kind in namesvc.KINDS:
        rows = db.execute(select(M.NameRef).where(M.NameRef.distributor_id == did,
                                                  M.NameRef.kind == kind)
                          .order_by(M.NameRef.name)).scalars().all()
        out[kind] = {"count": len(rows),
                     "file": rows[0].source_file if rows else None,
                     "uploaded_at_utc": rows[0].uploaded_at_utc if rows else None,
                     "sample": [r.name for r in rows[:5]]}
    return out


@router.get("/distributors/{did}/names")
def name_lists(did: int, db: Session = Depends(get_db)):
    if not db.get(M.Distributor, did):
        raise HTTPException(404, "No such distributor")
    return _names_out(db, did)


@router.post("/distributors/{did}/names")
async def upload_names(did: int, kind: str = Form(...), file: UploadFile = File(...),
                       db: Session = Depends(get_db)):
    """Replace one of the distributor's reference lists with the names in an
    Excel file. The next conversion uses it."""
    if not db.get(M.Distributor, did):
        raise HTTPException(404, "No such distributor")
    if kind not in namesvc.KINDS:
        raise HTTPException(422, "The list is either customer or product")
    data = await file.read()
    try:
        found = namesvc.read_names(data, kind)
    except Exception:
        raise HTTPException(422, "That is not an Excel workbook this can open (.xlsx).")
    if not found:
        raise HTTPException(422, f"No {kind} names were found in that workbook.")
    keep: dict[str, str] = {}
    for n in found:                      # first spelling of a duplicate wins
        keep.setdefault(namesvc.norm(n), n[:200])
    for old in db.execute(select(M.NameRef).where(M.NameRef.distributor_id == did,
                                                  M.NameRef.kind == kind)).scalars():
        db.delete(old)
    db.flush()
    now = _now()
    for k, n in keep.items():
        db.add(M.NameRef(distributor_id=did, kind=kind, name=n, norm_name=k[:200],
                         source_file=(file.filename or "")[:255], uploaded_at_utc=now))
    db.commit()
    return {**_names_out(db, did), "read": len(found), "kept": len(keep)}


def _mapper(db: Session, did: int, kind: str) -> namesvc.Mapper:
    rows = db.execute(select(M.NameRef).where(M.NameRef.distributor_id == did,
                                              M.NameRef.kind == kind)).scalars()
    return namesvc.Mapper({r.norm_name: r.name for r in rows})


# --------------------------------------------------------------- the upload
def _staging(token: str) -> str:
    return os.path.join(config.STAGING_DIR, token)


def _sweep_staging():
    """Uploads waiting to be committed are temporary. Anything older than a few
    hours is somebody who changed their mind, and is cleared out."""
    cutoff = time.time() - config.STAGING_HOURS * 3600
    root = config.STAGING_DIR
    if not os.path.isdir(root):
        return
    for name in os.listdir(root):
        p = os.path.join(root, name)
        try:
            if os.path.getmtime(p) < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


@router.post("/uploads/inspect")
async def inspect(files: list[UploadFile] = File(...), distributor_id: int = Form(...),
                  db: Session = Depends(get_db)):
    """Open what was sent and say what is in it. Nothing is stored in the
    database yet: this is the screen where somebody chooses the right files.
    A zip is opened and the workbooks and PDFs inside it are listed; only the
    files the distributor's rule names (for Gunjeshwari, the Batch PDF) are
    ticked."""
    d = db.get(M.Distributor, distributor_id)
    if not d:
        raise HTTPException(404, "No such distributor")
    _sweep_staging()
    token = uuid.uuid4().hex
    folder = _staging(token)
    os.makedirs(folder, exist_ok=True)

    cap = config.MAX_UPLOAD_MB * 1024 * 1024
    books, refused, source_names = [], [], []
    total = 0
    for up in files:
        data = await up.read()
        total += len(data)
        if total > cap:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(413, f"More than {config.MAX_UPLOAD_MB} MB in one go.")
        source_names.append(up.filename or "upload")
        found = parse.books_in(up.filename or "upload", data)
        if not found:
            refused.append(up.filename or "upload")
        books.extend(found)

    import re as _re
    pick = _re.compile(d.pick_pattern, _re.I) if d.pick_pattern else None
    out = []
    for name, data in books:
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(data)
        r = parse.read_book(name, data, bool(d.negate_returns))
        out.append({
            "name": name, "rows": len(r["rows"]), "omitted": r["omitted"],
            "error": r["error"],
            "layout": ", ".join(f'{s["name"]}: {s["rows"]} ({s["layout"]})'
                                for s in r["sheets"] if s["layout"]) or None,
            # The distributor's own rule names its files; everything else is
            # left unticked, because converting a stocks file silently would be
            # worse than asking.
            "suggested": bool(pick and pick.search(name) and not r["error"]),
        })
    return {"token": token, "source": ", ".join(source_names), "files": out,
            "refused": refused, "distributor": _dist_out(d)}


@router.post("/uploads/{token}/commit")
def commit(token: str, body: dict = Body(...), db: Session = Depends(get_db)):
    """Convert the chosen files and keep the result."""
    folder = _staging(token)
    if not os.path.isdir(folder):
        raise HTTPException(410, "That upload has expired. Send the files again.")
    d = db.get(M.Distributor, int(body.get("distributor_id") or 0))
    if not d:
        raise HTTPException(404, "No such distributor")
    chosen = [n for n in (body.get("files") or []) if os.path.basename(n) == n]
    if not chosen:
        raise HTTPException(422, "Choose at least one file to convert.")

    try:
        as_of = date.fromisoformat(body.get("as_of") or date.today().isoformat())
    except ValueError:
        raise HTTPException(422, "The date is not a real date")
    cutoff = int(body.get("cutoff_day") or d.cutoff_day)
    invoice_mode = body.get("invoice_mode") or d.invoice_mode
    negate = bool(body.get("negate_returns", d.negate_returns))
    rate_mode = d.rate_mode or "calc"
    p = period(as_of, cutoff)
    map_customer, map_product = _mapper(db, d.id, "customer"), _mapper(db, d.id, "product")

    batch = M.Batch(distributor_id=d.id, source_name=(body.get("source") or "")[:255],
                    as_of=as_of, month_name=p["month"], year=p["year"],
                    mid_month=p["mid_month"], cutoff_day=cutoff, invoice_mode=invoice_mode,
                    created_by=(body.get("who") or "user")[:120], created_at_utc=_now(),
                    notes=("The month stepped back past January; Year is the current year as "
                           "the rule says." if p["wrapped"] else None))
    db.add(batch)
    db.flush()

    seq, omitted, tot_q, tot_a = 0, 0, 0.0, 0.0
    on_disk = sorted(os.listdir(folder))
    for name in on_disk:
        used = name in chosen
        path = os.path.join(folder, name)
        with open(path, "rb") as fh:
            data = fh.read()
        r = parse.read_book(name, data, negate) if used else None
        bf = M.BatchFile(batch_id=batch.id, file_name=name, used=1 if used else 0,
                         layout=(", ".join(s["layout"] for s in r["sheets"] if s["layout"])
                                 if r else None),
                         rows=len(r["rows"]) if r else 0, omitted=r["omitted"] if r else 0,
                         detail=(r["error"] if r else "not chosen"))
        db.add(bf)
        if not used:
            continue
        omitted += r["omitted"]
        for x in r["rows"]:
            seq += 1
            inv = x["invoice"] if (invoice_mode == "file" and x["invoice"]) else f"INV - {seq}"
            if rate_mode == "file" and x.get("rate") is not None:
                rate = x["rate"]
            else:
                rate = 0.0 if x["qty"] == 0 else x["amount"] / x["qty"]
            tot_q += x["qty"]
            tot_a += x["amount"]
            db.add(M.SalesRow(
                batch_id=batch.id, seq=seq, distributor_name=d.name, invoice_no=inv[:40],
                month_name=p["month"], year=p["year"], mid_month=p["mid_month"],
                customer_name=map_customer(x["customer"])[:200],
                product_name=map_product(x["product"])[:200],
                quantity=x["qty"], free_quantity=x["free"], rate=rate,
                b_amount=x["amount"], amount=x["amount"], source_file=name,
                is_return=1 if x["is_return"] else 0))
    if seq == 0:
        db.rollback()
        raise HTTPException(409, "Nothing could be read from the files you chose.")
    mapped = [m for m in (map_customer.summary("customer"), map_product.summary("product")) if m]
    if rate_mode == "file":
        mapped.append("Rate read from the file where it has a rate column.")
    if mapped:
        batch.notes = " ".join(([batch.notes] if batch.notes else []) + mapped)
    batch.row_count, batch.omitted_count = seq, omitted
    batch.total_qty, batch.total_amount = tot_q, round(tot_a, 2)
    db.commit()
    shutil.rmtree(folder, ignore_errors=True)
    return {"batch_id": batch.id, "rows": seq, "omitted": omitted,
            "total_qty": tot_q, "total_amount": round(tot_a, 2),
            "month": p["month"], "year": p["year"], "mid_month": p["mid_month"],
            "wrapped": p["wrapped"],
            "unmatched_customers": sorted(map_customer.missed),
            "unmatched_products": sorted(map_product.missed)}


# ------------------------------------------------------------------ batches
def _batch_out(b: M.Batch) -> dict:
    return {"id": b.id, "distributor": b.distributor.name, "distributor_id": b.distributor_id,
            "source": b.source_name, "as_of": b.as_of, "month": b.month_name, "year": b.year,
            "mid_month": b.mid_month, "cutoff_day": b.cutoff_day, "invoice_mode": b.invoice_mode,
            "rows": b.row_count, "omitted": b.omitted_count,
            "total_qty": float(b.total_qty), "total_amount": float(b.total_amount),
            "created_by": b.created_by, "created_at_utc": b.created_at_utc, "notes": b.notes}


@router.get("/batches")
def batches(distributor_id: int | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = select(M.Batch).order_by(M.Batch.id.desc()).limit(min(limit, 200))
    if distributor_id:
        q = q.where(M.Batch.distributor_id == distributor_id)
    return [_batch_out(b) for b in db.execute(q).scalars()]


@router.get("/batches/{bid}")
def batch(bid: int, db: Session = Depends(get_db)):
    b = db.get(M.Batch, bid)
    if not b:
        raise HTTPException(404, "No such batch")
    out = _batch_out(b)
    out["files"] = [{"name": f.file_name, "used": bool(f.used), "layout": f.layout,
                     "rows": f.rows, "omitted": f.omitted, "detail": f.detail}
                    for f in sorted(b.files, key=lambda f: (not f.used, f.file_name))]
    return out


@router.get("/batches/{bid}/rows")
def batch_rows(bid: int, page: int = 1, size: int = 100, q: str | None = None,
               db: Session = Depends(get_db)):
    if not db.get(M.Batch, bid):
        raise HTTPException(404, "No such batch")
    size = max(1, min(size, 500))
    sel = select(M.SalesRow).where(M.SalesRow.batch_id == bid)
    if q:
        like = f"%{q.strip()}%"
        sel = sel.where(M.SalesRow.customer_name.like(like) | M.SalesRow.product_name.like(like))
    total = db.execute(select(func.count()).select_from(sel.subquery())).scalar()
    rows = db.execute(sel.order_by(M.SalesRow.seq).offset((page - 1) * size).limit(size)).scalars()
    return {"total": total, "page": page, "size": size,
            "rows": [{"seq": r.seq, "distributor_name": r.distributor_name,
                      "invoice_no": r.invoice_no, "month": r.month_name, "year": r.year,
                      "mid_month": r.mid_month, "customer_name": r.customer_name,
                      "product_name": r.product_name, "quantity": float(r.quantity),
                      "free_quantity": float(r.free_quantity), "rate": float(r.rate),
                      "b_amount": float(r.b_amount), "amount": float(r.amount),
                      "source_file": r.source_file, "is_return": bool(r.is_return)}
                     for r in rows]}


@router.get("/batches/{bid}/export")
def export(bid: int, db: Session = Depends(get_db)):
    b = db.get(M.Batch, bid)
    if not b:
        raise HTTPException(404, "No such batch")
    rows = db.execute(select(M.SalesRow).where(M.SalesRow.batch_id == bid)
                      .order_by(M.SalesRow.seq)).scalars().all()
    data = excel.build(b, rows, b.files)
    name = f"{b.distributor.name}_Sales_{b.month_name}{b.year}.xlsx"
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.delete("/batches/{bid}", status_code=204)
def delete_batch(bid: int, db: Session = Depends(get_db)):
    b = db.get(M.Batch, bid)
    if not b:
        raise HTTPException(404, "No such batch")
    db.delete(b)
    db.commit()
