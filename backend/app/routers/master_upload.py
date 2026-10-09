"""Upload any master from Excel, and download any master as Excel.

    POST /api/masters/upload        files[], dry_run (default true), slug (optional)
    GET  /api/masters/export-all    every master, one sheet each
    GET  /api/masters/{slug}/export one master; also its upload template

One workbook can carry every master — MASTER DATA & TABLES.xlsx with its
CUSTOMER_MASTER, EMPLOYEE_MASTER, PRODUCT_MASTER_BRAND and PRODUCT_MASTER
sheets is read as it is — or a file per master. Sheets are read parents first
(zones before HQs, brands before products), whatever order they come in.

Rules it keeps:

* **Check first.** A dry run does the whole upload and rolls it back, so the
  report shows exactly what an import would do.
* **Safe to run again.** A row is found by its ID (CUSTOMER_ID …), its Master
  ID, its code — whichever the sheet carries — and updated, not added twice.
  Nothing is ever deleted.
* **One bad row does not stop the rest.** It is left out and named, with the
  reason, and the rows around it go in.
* **Only the columns sent are changed.** A sheet without a REPORTING column
  leaves every brand's REPORTING as it was.

This router is included before the masters router: /masters/upload and
/masters/export-all would otherwise be read as a master called "upload".
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..masters import specs as S
from ..services import master_io as IO
from .masters import _maxlen, _validate, f_named, next_master_id

router = APIRouter(prefix="/api")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ORDER = {s.slug: i for i, s in enumerate(S.SPECS)}
# children of the same master that must come after it: brands before products
AFTER = {"sku": "brand"}


class RowError(Exception):
    pass


def _slugify_code(name: str, taken: set[str], n: int) -> str:
    base = re.sub(r"-+", "-", re.sub(r"[^A-Z0-9]+", "-", (name or "ROW").upper())).strip("-")[:n] or "ROW"
    code, i = base, 2
    while code in taken:
        suffix = f"-{i}"
        code = base[:n - len(suffix)] + suffix
        i += 1
    taken.add(code)
    return code


class Sheet:
    """One sheet being read into one master."""

    def __init__(self, db: Session, spec, label: str, rows: list[list]):
        self.db, self.spec, self.label, self.rows = db, spec, label, rows
        self.fields = {f.name: f for f in spec.fields}
        self.alias_field = next((f for f in spec.fields if f.type == "aliases"), None)
        self.tally = {"master": spec.title, "slug": spec.slug, "sheet": label, "rows": 0,
                      "added": 0, "updated": 0, "unchanged": 0, "skipped": 0,
                      "errors": [], "warnings": [], "ignored": []}
        self._codes = None
        self._pending = {}                 # (field label, target slug, id) -> still to check

    def warn(self, msg):
        w = self.tally["warnings"]
        if msg not in w and len(w) < 12:
            w.append(msg)

    def fail(self, n, msg):
        self.tally["skipped"] += 1
        e = self.tally["errors"]
        if len(e) < 30:
            e.append(f"Row {n}: {msg}")
        elif len(e) == 30:
            e.append("… more rows left out for the same kind of reason")

    # ---------------------------------------------------------- one value
    def value(self, attr, raw, year_id=None):
        f = self.fields.get(attr)
        if f is None:                       # an alias column, or a column with no field
            if attr.startswith("alias_"):
                return IO.to_text(raw)
            return raw
        try:
            if f.type == "ref":
                return self.ref(f, raw, year_id)
            if f.type == "int":
                return IO.to_int(raw)
            if f.type == "decimal":
                return IO.to_decimal(raw)
            if f.type == "date":
                return IO.to_date(raw)
            if f.type == "bool":
                return None if raw is None else IO.to_bool(raw)
            v = IO.to_text(raw)
            if v is None:
                return None
            if f.type == "code":
                v = v.upper()
            n = _maxlen(self.spec, attr)
            if n and len(v) > n:
                raise RowError(f"{f.label} is longer than {n} characters.")
            if f.type == "select" and v not in (f.options or []):
                raise RowError(f"{f.label} has to be one of {', '.join(f.options)}, not {v}.")
            return v
        except RowError:
            raise
        except (TypeError, ValueError):
            kind = {"int": "a whole number", "decimal": "a number", "date": "a date",
                    "bool": "1 or 0"}.get(f.type, "a valid value")
            raise RowError(f"{f.label} should be {kind}, not '{raw}'.")

    def ref(self, f, raw, year_id):
        if raw is None:
            return None
        target = S.get(f.ref)
        if f.key:                                       # a Master ID, as the Excel tables keep it
            try:
                num = IO.to_int(raw)
            except (TypeError, ValueError):
                num = None
            if num is not None:
                if num == 0:
                    return None                         # the old system's "none"
                self._pending[(f.label, target.slug, num)] = True
                return num
            row = IO.find_row(self.db, target, raw)
            if row is None:
                raise RowError(f"{f.label} '{raw}' is not a {target.title.lower()} code or name.")
            return getattr(row, f.key)
        row = IO.find_row(self.db, target, raw, year_id=year_id)
        if row is None:
            if f.soft:
                try:
                    num = IO.to_int(raw)
                except (TypeError, ValueError):
                    num = None
                if num is not None:
                    if num != 0:
                        self._pending[(f.label, target.slug, num)] = True
                    return num or None
            raise RowError(f"{f.label} '{raw}' was not found in {target.title}.")
        return row.id

    # ------------------------------------------------------------ the row
    def existing(self, vals):
        m = self.spec.model
        if "id" in self.fields and vals.get("id") is not None:
            return self.db.get(m, vals["id"])
        if self.spec.master_id and vals.get("legacy_id") is not None:
            r = IO.find_row(self.db, self.spec, vals["legacy_id"])
            if r is not None and r.legacy_id == vals["legacy_id"]:
                return r
        for cols, _ in self.spec.unique:
            if all(vals.get(c) is not None for c in cols):
                from sqlalchemy import func, select
                conds = [(func.lower(getattr(m, c)) == vals[c].lower()) if isinstance(vals[c], str)
                         else getattr(m, c) == vals[c] for c in cols]
                r = self.db.execute(select(m).where(*conds)).scalars().first()
                if r is not None:
                    return r
        if self.spec.master_id and vals.get("name") and vals.get("legacy_id") is None:
            from sqlalchemy import func, select
            r = self.db.execute(select(m).where(func.upper(m.name) == vals["name"].upper())) \
                .scalars().first()
            if r is not None:
                return r
        return None

    def codes(self):
        if self._codes is None:
            from sqlalchemy import select
            self._codes = {c.upper() for c in self.db.execute(select(self.spec.model.code)).scalars() if c}
        return self._codes

    def run(self):
        spec, db = self.spec, self.db
        hmap = IO.header_map(spec)
        for k in IO.IGNORED:
            hmap.pop(IO.norm(k), None)
        hr, cmap, unused = IO.find_header(self.rows, hmap)
        if hr < 0:
            self.tally["errors"].append(
                f"No header row naming {spec.title.lower()} columns was found in the first rows.")
            return self.tally
        for h in unused:
            k = IO.norm(h)
            reason = next((r for c, r in IO.IGNORED.items() if IO.norm(c) == k), None)
            self.tally["ignored"].append(reason or f"{h}: not a column of {spec.title}, read past.")
        year_col = next((i for i, a in cmap.items() if a == "year_id"), None)
        for n, row in enumerate(self.rows[hr + 1:], start=hr + 2):
            if not row or all(v is None for v in row):
                continue
            self.tally["rows"] += 1
            try:
                self.one(n, row, cmap, year_col)
            except RowError as e:
                self.fail(n, str(e))
            except HTTPException as e:
                self.fail(n, str(e.detail))
        self.db.flush()
        missing: dict[tuple, list] = {}
        for label, slug, num in self._pending:
            if not IO.find_row(self.db, S.get(slug), num):
                missing.setdefault((label, slug), []).append(num)
        for (label, slug), nums in missing.items():
            t = S.get(slug)
            nums = sorted(nums)
            shown = ", ".join(str(x) for x in nums[:10]) + (f" and {len(nums) - 10} more" if len(nums) > 10 else "")
            what = "Master ID" if t.master_id else "ID"
            self.warn(f"{label} {shown}: not in {t.title} yet, kept as given. Upload {t.title} "
                      f"with those {what}s to give them names.")
        return self.tally

    def one(self, n, row, cmap, year_col):
        spec, db = self.spec, self.db
        year_id = None
        if year_col is not None and year_col < len(row):
            year_id = self.ref(self.fields["year_id"], row[year_col], None)
        vals, aliases = {}, {}
        for i, attr in cmap.items():
            raw = row[i] if i < len(row) else None
            if attr.startswith("alias_") and self.alias_field:
                aliases[int(attr.split("_")[1])] = IO.to_text(raw)
                continue
            vals[attr] = self.value(attr, raw, year_id)
        obj = self.existing(vals)
        creating = obj is None
        if creating:
            obj = spec.model()
            obj.id = vals.get("id")
            if obj.id is not None and db.get(spec.model, obj.id):
                raise RowError(f"ID {obj.id} is taken.")
            before = None
        else:
            before = {p.key: getattr(obj, p.key) for p in spec.model.__mapper__.column_attrs}
        try:
            for attr, v in vals.items():
                f = self.fields.get(attr)
                if f is not None and (f.derived or (f.create_only and not creating)):
                    continue
                if f is not None and f.type == "bool" and v is None:
                    v = f.default if f.default is not None else 0
                setattr(obj, attr, v)
            if aliases:
                cleaned, seen = [], set()
                for _, a in sorted(aliases.items()):
                    if a and a.upper() not in seen:
                        seen.add(a.upper())
                        cleaned.append(a)
                for i in range(1, self.alias_field.count + 1):
                    setattr(obj, f"alias_{i}", cleaned[i - 1] if i <= len(cleaned) else None)
            if creating:
                self.defaults(obj, vals)
            for f in spec.fields:
                if f.required and not f.derived and f.type != "aliases" \
                        and getattr(obj, f.name, None) in (None, ""):
                    raise RowError(f"{f.label} is empty.")
            _validate(db, spec, obj)
        except Exception:
            if before is not None:                     # put an existing row back as it was
                for k, v in before.items():
                    setattr(obj, k, v)
            raise
        if creating:
            db.add(obj)
            self.tally["added"] += 1
        else:
            after = {p.key: getattr(obj, p.key) for p in spec.model.__mapper__.column_attrs}
            changed = any(_differs(before[k], after[k]) for k in after)
            self.tally["updated" if changed else "unchanged"] += 1
        db.flush()
        if spec.after_save:
            spec.after_save(db, obj)

    def defaults(self, obj, vals):
        """What a new row needs that the sheet did not give."""
        spec = self.spec
        for f in spec.fields:
            if f.derived or f.name in vals or f.type == "aliases":
                continue
            if f.type == "bool":
                setattr(obj, f.name, f.default if f.default is not None else 0)
            elif f.type == "ref" and isinstance(f.default, str):
                setattr(obj, f.name, IO.natural_id(self.db, S.get(f.ref), f.default))
            elif f.default is not None and getattr(obj, f.name, None) is None:
                setattr(obj, f.name, f.default)
        if f_named(spec, "code") and f_named(spec, "code").required and not getattr(obj, "code", None):
            obj.code = _slugify_code(getattr(obj, "name", None) or str(obj.legacy_id or ""),
                                     self.codes(), _maxlen(spec, "code") or 20)
        elif getattr(obj, "code", None) and "code" in spec.model.__mapper__.attrs:
            self.codes().add(obj.code.upper())
        if spec.master_id and getattr(obj, "legacy_id", None) is None:
            obj.legacy_id = next_master_id(self.db, spec)


def _differs(a, b) -> bool:
    if a is None or b is None:
        return a is not b
    try:
        return float(a) != float(b)
    except (TypeError, ValueError):
        return str(a) != str(b)


def run_upload(db: Session, files: list[tuple[str, bytes]], dry_run: bool = True,
               slug: str | None = None) -> dict:
    forced = S.get(slug) if slug else None
    found, report_files, messages = [], [], []
    for name, data in files:
        try:
            tables = IO.read_tables(name, data)
        except Exception as e:
            report_files.append({"file": name, "sheet": "", "master": None, "rows": 0,
                                 "note": f"Not a workbook or CSV this can open ({type(e).__name__})."})
            continue
        for stem, title, rows, n_sheets in tables:
            label = f"{name} › {title}" if n_sheets > 1 else name
            if forced:
                spec = forced
            else:
                spec = IO.detect(S.SPECS, title, stem) if n_sheets > 1 \
                    else IO.detect(S.SPECS, stem, title)
            body = sum(1 for r in rows[1:] if r and any(v is not None for v in r))
            report_files.append({"file": name, "sheet": title, "master": spec.title if spec else None,
                                 "slug": spec.slug if spec else None, "rows": body,
                                 "note": None if spec else "Not a master this knows by name; left alone. "
                                         "Name the sheet after its table (e.g. CUSTOMER_MASTER)."})
            if spec:
                found.append((spec, label, rows))
    if not found:
        raise HTTPException(422, "No sheet in what was sent is named after a master. Name each sheet "
                                 "after its table — CUSTOMER_MASTER, EMPLOYEE_MASTER, "
                                 "PRODUCT_MASTER_BRAND, PRODUCT_MASTER, ZONE … — or upload from "
                                 "that master's own screen.")

    def order(item):
        spec = item[0]
        o = ORDER[spec.slug]
        return (ORDER[AFTER[spec.slug]] + 0.5) if spec.slug in AFTER and o < ORDER[AFTER[spec.slug]] else o
    found.sort(key=order)
    tallies = []
    try:
        for spec, label, rows in found:
            tallies.append(Sheet(db, spec, label, rows).run())
        if dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    if any(t["skipped"] for t in tallies):
        messages.append("Rows with a problem were left out and are listed below; the rest "
                        + ("would go in." if dry_run else "went in."))
    return {"dry_run": dry_run, "files": report_files, "tables": tallies, "messages": messages}


# ================================================================== routes
@router.post("/masters/upload")
async def upload(files: list[UploadFile] = File(...), dry_run: bool = Form(True),
                 slug: str | None = Form(None), db: Session = Depends(get_db)):
    cap, total, got = config.MAX_UPLOAD_MB * 1024 * 1024, 0, []
    for up in files:
        data = await up.read()
        total += len(data)
        if total > cap:
            raise HTTPException(413, f"The files come to more than {config.MAX_UPLOAD_MB} MB.")
        name = up.filename or "file"
        if not name.lower().endswith((".xlsx", ".xlsm", ".csv", ".txt")):
            raise HTTPException(422, f"{name}: send Excel (.xlsx) or CSV files.")
        got.append((name, data))
    try:
        return run_upload(db, got, dry_run=dry_run, slug=slug or None)
    except HTTPException:
        raise
    except Exception as e:                       # the report is the useful part
        raise HTTPException(422, f"The upload stopped and nothing was saved: {e}")


def _xlsx(data: bytes, name: str) -> Response:
    return Response(content=data, media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/masters/export-all")
def export_all(db: Session = Depends(get_db)):
    return _xlsx(IO.export(db, S.SPECS), "MASTER_DATA.xlsx")


@router.get("/masters/{slug}/export")
def export_one(slug: str, db: Session = Depends(get_db)):
    spec = S.get(slug)
    name = spec.model.__tablename__ if IO.is_excel_table(spec) else spec.slug.upper()
    return _xlsx(IO.export(db, S.SPECS, only={slug}), f"{name}.xlsx")
