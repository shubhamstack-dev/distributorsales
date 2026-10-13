"""Upload for the data tables: Sales (MAPPING_MASTER), Mid sales, Budget and
the four *_ASSIGNMENT tables of the old system.

These run to a hundred thousand rows, so they are not read the way a master is
(one row at a time, flushed and checked against its parents). Here a sheet is
read in one pass, the rows already stored are fetched in chunks, and the new
and changed rows are written in batches. The rules are the same as the master
upload's:

* **Check first.** A check reads everything and counts what an import would
  add, update and leave out, and writes nothing.
* **Safe to run again.** A row is found by the spec's `match` columns (the ID
  for sales; S_NO + EMPLOYEE_ID + HQ_ID for the budget; the whole row for an
  assignment) and updated in place, never added twice. Nothing is deleted.
* **Only the columns sent are changed.**
* **One bad row does not stop the rest.** It is named, with the reason.
* An ID naming a product, customer, HQ … that is not in the masters is kept as
  given and reported once, not refused: old sales name old products.
"""
from __future__ import annotations

from sqlalchemy import bindparam, insert, select, update
from sqlalchemy.orm import Session

from ..masters import specs as S
from . import master_io as IO

CHUNK = 1000


class RowError(Exception):
    pass


def new_tally(spec, label) -> dict:
    return {"master": spec.title, "slug": spec.slug, "sheet": label, "rows": 0, "added": 0,
            "updated": 0, "unchanged": 0, "skipped": 0, "errors": [], "warnings": [], "ignored": []}


# ------------------------------------------------------------ the values
def _int(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if not v.is_integer():
            raise ValueError
        return int(v)
    return IO.to_int(v)


def _num(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(",", "").strip())


def _converter(spec, f):
    """value -> stored value for one field, raising RowError with the reason."""
    kind = {"int": "a whole number", "decimal": "a number", "ref": "a whole number (an ID)",
            "date": "a date", "bool": "1 or 0"}
    width = None
    if f.type in ("text", "code", "select"):
        width = getattr(spec.model.__mapper__.attrs[f.name].columns[0].type, "length", None)
    options = {o.upper(): o for o in (f.options or [])}

    def conv(raw):
        try:
            if f.type in ("int", "ref"):
                v = _int(raw)
                return None if (f.type == "ref" and v == 0) else v     # 0 is the old system's "none"
            if f.type == "decimal":
                return _num(raw)
            if f.type == "date":
                return IO.to_date(raw)
            if f.type == "bool":
                return None if raw is None else IO.to_bool(raw)
        except (TypeError, ValueError, ArithmeticError):
            raise RowError(f"{f.label} should be {kind.get(f.type, 'a valid value')}, not '{raw}'.")
        v = IO.to_text(raw)
        if v is None:
            return None
        if f.type == "select":
            if v.upper() not in options:
                raise RowError(f"{f.label} has to be one of {', '.join(f.options)}, not {v}.")
            return options[v.upper()]
        if f.type == "code":
            v = v.upper()
        if width and len(v) > width:
            raise RowError(f"{f.label} is longer than {width} characters.")
        return v
    return conv


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)), abs(float(b)))
    return str(a) == str(b)


# ----------------------------------------------------------------- loader
class BulkSheet:
    def __init__(self, db: Session, spec, label: str, rows: list[list]):
        self.db, self.spec, self.label, self.rows = db, spec, label, rows
        self.tally = new_tally(spec, label)
        self.fields = {f.name: f for f in spec.fields}
        self.mapper = spec.model.__mapper__
        self.colname = {p.key: p.columns[0].name for p in self.mapper.column_attrs}

    def warn(self, msg):
        if msg not in self.tally["warnings"] and len(self.tally["warnings"]) < 12:
            self.tally["warnings"].append(msg)

    def fail(self, n, msg):
        self.tally["skipped"] += 1
        e = self.tally["errors"]
        if len(e) < 30:
            e.append(f"Row {n}: {msg}")
        elif len(e) == 30:
            e.append("… more rows left out for the same kind of reason")

    def run(self, dry_run: bool) -> dict:
        spec = self.spec
        hmap = IO.header_map(spec)
        hr, cmap, unused = IO.find_header(self.rows, hmap)
        if hr < 0:
            self.tally["errors"].append(
                f"No header row naming {spec.title.lower()} columns was found in the first rows.")
            return self.tally
        for h in unused:
            self.tally["ignored"].append(f"{h}: not a column of {spec.model.__tablename__}, read past.")
        conv = {i: _converter(spec, self.fields[a]) for i, a in cmap.items()}
        sent = list(dict.fromkeys(cmap.values()))           # attributes this sheet carries
        match = list(spec.match)
        missing_key = [a for a in match if a not in sent and a != "id"]
        if missing_key:
            labels = ", ".join(self.fields[a].label for a in missing_key)
            self.tally["errors"].append(f"The sheet has no {labels} column, which is how a "
                                        f"{spec.title.lower()} row is found again. Nothing was read.")
            return self.tally
        required = [f for f in spec.fields if f.required]

        # 1. read every row, keeping the last of any that repeat a key
        found: dict[tuple, dict] = {}
        fresh: list[dict] = []                  # rows with no key at all (sales without an ID)
        repeats = 0
        for n, row in enumerate(self.rows[hr + 1:], start=hr + 2):
            if not row or all(v is None for v in row):
                continue
            self.tally["rows"] += 1
            try:
                vals = {}
                for i, a in cmap.items():
                    vals[a] = conv[i](row[i] if i < len(row) else None)
                for f in required:
                    if f.name in vals and vals[f.name] is None:
                        raise RowError(f"{f.label} is empty.")
            except RowError as e:
                self.fail(n, str(e))
                continue
            key = tuple(vals.get(a) for a in match)
            if match == ["id"] and key[0] is None:
                fresh.append(vals)
                continue
            if any(k is None for k in key):
                self.fail(n, f"{', '.join(self.fields[a].label for a in match)} cannot be empty.")
                continue
            if key in found:
                repeats += 1
            found[key] = vals
        if repeats:
            self.warn(f"{repeats} row{'s' if repeats != 1 else ''} repeated an earlier row's "
                      f"{' + '.join(self.fields[a].label if a != 'id' else 'ID' for a in match)}; "
                      f"the last one was kept.")

        # 2. what is stored already, fetched by the first key column in chunks
        model = spec.model
        first = getattr(model, match[0])
        cols = [model.id] + [getattr(model, a) for a in dict.fromkeys(match + sent) if a != "id"]
        stored: dict[tuple, dict] = {}
        firsts = sorted({k[0] for k in found})
        for i in range(0, len(firsts), CHUNK):
            part = firsts[i:i + CHUNK]
            for r in self.db.execute(select(*cols).where(first.in_(part))).mappings():
                d = {c.key: r[c.key] for c in cols}
                stored[tuple(d[a] for a in match)] = d

        # 3. sort into added / updated / unchanged
        inserts, updates = list(fresh), []
        for key, vals in found.items():
            old = stored.get(key)
            if old is None:
                inserts.append(vals)
            elif all(_same(old.get(a), v) for a, v in vals.items()):
                self.tally["unchanged"] += 1
            else:
                updates.append({"_pk": old["id"], **vals})
        self.tally["added"] = len(inserts)
        self.tally["updated"] = len(updates)

        # 4. write, in batches
        if not dry_run:
            tbl = model.__table__
            for i in range(0, len(inserts), CHUNK):
                self.db.execute(insert(tbl), [{self.colname[a]: v for a, v in r.items()}
                                              for r in inserts[i:i + CHUNK]])
            change = [a for a in sent if a != "id"]
            if updates and change:
                stmt = update(tbl).where(tbl.c[self.colname["id"]] == bindparam("_pk")) \
                    .values({self.colname[a]: bindparam(f"v_{a}") for a in change})
                for i in range(0, len(updates), CHUNK):
                    self.db.execute(stmt, [{"_pk": u["_pk"], **{f"v_{a}": u.get(a) for a in change}}
                                           for u in updates[i:i + CHUNK]])
            self.db.flush()

        # 5. IDs naming nothing in the masters: kept, and said once
        self.report_unknown([*fresh, *found.values()], sent)
        return self.tally

    def report_unknown(self, rows, sent):
        for a in sent:
            f = self.fields.get(a)
            if f is None or f.type != "ref":
                continue
            ids = {r.get(a) for r in rows} - {None}
            if not ids:
                continue
            target = S.get(f.ref)
            col = getattr(target.model, f.key) if f.key else target.model.id
            have: set = set()
            ordered = sorted(ids)
            for i in range(0, len(ordered), CHUNK):
                have |= set(self.db.execute(select(col).where(col.in_(ordered[i:i + CHUNK]))).scalars())
            gone = sorted(ids - have)
            if gone:
                shown = ", ".join(str(x) for x in gone[:10]) + \
                    (f" and {len(gone) - 10} more" if len(gone) > 10 else "")
                what = "Master ID" if target.master_id else "ID"
                self.warn(f"{f.label} {shown}: not in {target.title}, kept as given. Upload "
                          f"{target.title} with those {what}s to give them names.")


def load(db: Session, spec, label: str, rows: list[list], dry_run: bool) -> dict:
    return BulkSheet(db, spec, label, rows).run(dry_run)
