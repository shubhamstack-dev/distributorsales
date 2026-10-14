"""What each master's list shows, laid out as the old Abbott screens had it:
S.No, the row's Id, its name, the parents by name (a territory's Zone and HQ,
a SKU's Product Group, Brand, Team and Reporting), and its Active Status.

A column is a path through the masters:

    "name"                          a field of the row
    "headquarter_id"                a reference, shown by the parent's name
    "headquarter_id>zone_id"        the HQ's zone, by name
    "product_group_id|product_brand_id>product_group_id"
                                    the first of these that has a value

Every step is one query for the whole page, not one per row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select


@dataclass
class Col:
    label: str
    path: str
    primary: bool = False          # the row's own name: the column that stands out


def name_of(spec, o) -> str | None:
    """A row as a parent column shows it: its name, without the Id."""
    if o is None:
        return None
    if spec.name is not None:
        return spec.name(o)
    v = getattr(o, "name", None)
    return v if v is not None else spec.label(o)


def _field(spec, name):
    return next((f for f in spec.fields if f.name == name), None)


def kind(spec, path: str) -> str:
    """How the screen draws a column: id, name, text, int, num, bool, date."""
    from . import specs as S
    steps = path.split("|")[0].split(">")
    cur = spec
    for st in steps[:-1]:
        f = _field(cur, st)
        cur = S.get(f.ref)
    last = steps[-1]
    if last in ("id", "legacy_id"):
        return "id"
    f = _field(cur, last)
    if f is None:
        return "text"
    return {"ref": "name", "bool": "bool", "decimal": "num", "int": "int",
            "date": "date"}.get(f.type, "text")


def _plain(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def rows(db, spec, objs) -> list[list]:
    """The view's cells for each row, in the view's column order."""
    from . import specs as S
    cache: dict[tuple, dict] = {}

    def parents(target, key, values):
        """key value -> row of `target`, fetched once per (target, key)."""
        known = cache.setdefault((target.slug, key), {})
        want = {v for v in values if v is not None} - set(known)
        if want:
            col = getattr(target.model, key)
            for t in db.execute(select(target.model).where(col.in_(want))).scalars():
                known[getattr(t, key)] = t
        return known

    out = [[None] * len(spec.view) for _ in objs]
    fallback = [[None] * len(spec.view) for _ in objs]   # an ID no master knows, shown last
    for ci, col in enumerate(spec.view):
        for alt in col.path.split("|"):
            cur, cur_spec = list(objs), spec
            steps = alt.split(">")
            for st in steps[:-1]:                  # walk to the parent named
                f = _field(cur_spec, st)
                target = S.get(f.ref)
                key = f.key or "id"
                vals = [getattr(o, st) if o is not None else None for o in cur]
                m = parents(target, key, vals)
                cur = [m.get(v) if v is not None else None for v in vals]
                cur_spec = target
            last = steps[-1]
            f = _field(cur_spec, last)
            if f is not None and f.type == "ref":   # shown by the parent's name
                target = S.get(f.ref)
                key = f.key or "id"
                vals = [getattr(o, last) if o is not None else None for o in cur]
                m = parents(target, key, vals)
                cells = [name_of(target, m.get(v)) if v is not None else None for v in vals]
                for i, v in enumerate(vals):
                    if v is not None and cells[i] is None and fallback[i][ci] is None:
                        fallback[i][ci] = v
            else:
                cells = [_plain(getattr(o, last)) if o is not None else None for o in cur]
            for i, v in enumerate(cells):
                if out[i][ci] is None and v not in (None, ""):
                    out[i][ci] = v
    for i, row in enumerate(out):        # nothing better was found: the ID as given
        for ci, v in enumerate(row):
            if v is None:
                row[ci] = fallback[i][ci]
    return out


def default(spec) -> list[Col]:
    """For a screen with no layout of its own: the listed fields, refs by name."""
    return [Col(f.label, f.name) for f in spec.fields if f.in_list and f.type != "aliases"]
