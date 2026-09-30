"""Bring the old SQL Server (Abbott) masters into the md_* tables.

The old tables are exported from SQL Server Management Studio as Excel or CSV
files, one per table, each named after its table (PRODUCT_MASTER.xlsx), or as
one workbook with a sheet per table. This reads them and writes the masters.

How it maps:

    PRODUCT_MASTER_GROUP      -> md_product_group
    PRODUCT_MASTER_BRAND      -> md_brand (+ one reporting line per brand, P1/P2/X,
                                 for the chosen year; TEAM_ID -> team carries group)
    PRODUCT_MASTER            -> md_sku, PRODUCT_ALIAS_1..100 -> md_sku_alias
    ZONE / HQ / TERRITORY     -> md_zone / md_headquarter / md_territory
    CUSTOMER_MASTER           -> md_customer, CUSTOMER_ALIAS_1..50 -> md_customer_alias
    STATE, CLASSIFICATION, REMARK, SUB_TERRITORY -> names stored on the customer
    ROLE / DESIGNATION / TEAM -> md_role / md_designation / md_team
    EMPLOYEE_MASTER           -> md_employee (PASSWORD is never carried over)

Rules it keeps:

* **Safe to run again.** Every row keeps its old Id in LegacyId, so a second
  run updates what the first one wrote instead of adding it twice. Rows typed
  in on the screens are matched by name (lookups) or code and adopted, not
  duplicated. Nothing is ever deleted.
* **Nothing is lost for want of a file.** A customer pointing at HQ 12 when no
  HQ file was sent gets a placeholder "HQ #12"; sending the HQ file later names
  it. Placeholders are counted in the report.
* **Try before writing.** A dry run does the whole import and rolls it back,
  so the report shows exactly what would happen.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models_master as X

# ---------------------------------------------------------------- reading
NULLS = {"", "NULL", "NONE", "NAN"}


def _norm_header(h) -> str:
    return re.sub(r"[\[\]\s]+", "", str(h or "")).upper()


def _cell(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return None if v.upper() in NULLS else v
    return v


def _rows_from_csv(data: bytes) -> list[dict]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    first = text.split("\n", 1)[0]
    delim = "\t" if first.count("\t") > first.count(",") else ","
    rd = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in rd]
    if not rows:
        return []
    heads = [_norm_header(h) for h in rows[0]]
    return [{h: _cell(v) for h, v in zip(heads, r)} for r in rows[1:] if any(x.strip() for x in r)]


def _rows_from_sheet(ws) -> list[dict]:
    it = ws.iter_rows(values_only=True)
    try:
        heads = [_norm_header(h) for h in next(it)]
    except StopIteration:
        return []
    out = []
    for r in it:
        if r is None or all(v is None or (isinstance(v, str) and not v.strip()) for v in r):
            continue
        out.append({h: _cell(v) for h, v in zip(heads, r) if h})
    return out


def read_files(files: list[tuple[str, bytes]]) -> list[tuple[str, list[dict]]]:
    """(table name, rows) for every table found. A workbook with several sheets
    gives one table per sheet, named after the sheet; otherwise the file name."""
    out = []
    for name, data in files:
        stem = re.sub(r"\.[^.]+$", "", name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
        low = name.lower()
        if low.endswith((".xlsx", ".xlsm")):
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            sheets = wb.worksheets
            if len(sheets) == 1:
                out.append((stem, _rows_from_sheet(sheets[0])))
            else:
                for ws in sheets:
                    out.append((ws.title, _rows_from_sheet(ws)))
            wb.close()
        else:
            out.append((stem, _rows_from_csv(data)))
    return out


# ------------------------------------------------------ which table is it
# checked in order; the first pattern that matches the (upper-cased) name wins
KINDS = [
    ("brand_reporting", r"BRAND_REPORTING"),
    ("brand", r"PRODUCT_MASTER_BRAND$|^(PRODUCT_)?BRAND(_MASTER)?$"),
    ("product_group", r"PRODUCT_MASTER_GROUP$|^(PRODUCT_)?GROUP(_MASTER)?$|PRODUCT_GROUP"),
    ("product", r"^PRODUCT_MASTER$|^PRODUCTS?$|^SKU(_MASTER)?$"),
    ("customer", r"^CUSTOMER_MASTER$|^CUSTOMERS?$"),
    ("employee", r"^EMPLOYEE_MASTER$|^EMPLOYEES?$"),
    ("sub_territory", r"SUB_?TERRITORY"),
    ("territory", r"TERRITORY|TERR_MASTER"),
    ("hq", r"^HQ(_MASTER)?$|HEADQUARTER"),
    ("zone", r"^ZONE(_MASTER)?$|ZONE_MASTER"),
    ("state", r"^STATE(_MASTER)?$"),
    ("classification", r"CLASSIFICATION"),
    ("remark", r"REMARK"),
    ("role", r"^ROLE(_MASTER)?$"),
    ("designation", r"DESIGNATION"),
    ("team", r"^TEAM(_MASTER)?$"),
]
SUPPORTED = {k for k, _ in KINDS} - {"brand_reporting"}


def kind_of(table: str) -> str | None:
    t = table.upper().strip()
    t = re.sub(r"^(DBO\.|\[DBO\]\.)", "", t)
    for k, rx in KINDS:
        if re.search(rx, t):
            return k
    return None


# --------------------------------------------------------------- helpers
def _pick(cols, *exact, contains=None, not_end=None):
    for e in exact:
        if e in cols:
            return e
    if contains:
        for c in cols:
            if contains in c and not (not_end and c.endswith(not_end)):
                return c
    return None


def _int(v):
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _str(v, n=None):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    if not s:
        return None
    return s[:n] if n else s


def _bool(v, default=1):
    if v is None:
        return default
    if isinstance(v, bool):
        return int(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "active", "1.0"):
        return 1
    if s in ("0", "false", "no", "n", "inactive", "0.0"):
        return 0
    return default


def _date(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()[:19]
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(s if " " in fmt or "T" in fmt else s[:11].strip(), fmt).date()
        except ValueError:
            continue
    return None


def _slug(s: str, n=20) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^A-Z0-9]+", "-", s.upper())).strip("-")[:n].strip("-")


# ---------------------------------------------------------------- report
@dataclass
class Tally:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    placeholders: int = 0
    aliases: int = 0
    notes: list[str] = field(default_factory=list)

    def note(self, msg):
        if len(self.notes) < 25:
            self.notes.append(msg)
        elif len(self.notes) == 25:
            self.notes.append("… more of the same not listed")


# ============================================================= the import
class Importer:
    def __init__(self, db: Session, year_id: int | None = None):
        self.db = db
        self.t: dict[str, Tally] = {}
        self.messages: list[str] = []
        self.year_id = year_id
        self.lookups: dict[str, dict[int, str]] = {}   # state / classification / …
        self.cache: dict[type, dict] = {}

    def tally(self, k) -> Tally:
        return self.t.setdefault(k, Tally())

    # --- caches: legacy id -> row, code set, name -> row
    def _load(self, model):
        if model in self.cache:
            return self.cache[model]
        rows = list(self.db.execute(select(model)).scalars())
        c = {"legacy": {}, "codes": set(), "names": {}}
        for r in rows:
            if getattr(r, "legacy_id", None) is not None:
                c["legacy"][r.legacy_id] = r
            if hasattr(r, "code") and r.code:
                c["codes"].add(r.code.upper())
            if hasattr(r, "name") and r.name:
                c["names"].setdefault(r.name.strip().upper(), r)
        self.cache[model] = c
        return c

    def _code(self, model, *wanted) -> str:
        """The first wanted code that is free; the last one is made free."""
        codes = self._load(model)["codes"]
        for w in wanted:
            if not w:
                continue
            w = str(w).strip().upper()[:20]
            if w and w not in codes:
                codes.add(w)
                return w
        base = str(wanted[-1]).upper()[:17]
        i = 2
        while f"{base}-{i}" in codes:
            i += 1
        codes.add(f"{base}-{i}")
        return f"{base}-{i}"

    def _remember(self, model, obj):
        c = self._load(model)
        if obj.legacy_id is not None:
            c["legacy"][obj.legacy_id] = obj
        if getattr(obj, "name", None):
            c["names"].setdefault(obj.name.strip().upper(), obj)

    def _find(self, model, legacy_id, name=None, by_name=True):
        c = self._load(model)
        if legacy_id is not None and legacy_id in c["legacy"]:
            return c["legacy"][legacy_id]
        if by_name and name:
            o = c["names"].get(name.strip().upper())
            if o is not None and getattr(o, "legacy_id", None) in (None, legacy_id):
                return o
        return None

    # --- defaults the new tables need and the old ones never had
    def country_in(self) -> int:
        c = self.db.execute(select(X.Country).where(X.Country.code == "IN")).scalar_one_or_none()
        if not c:
            c = X.Country(code="IN", name="India", currency_code="INR", active=1)
            self.db.add(c)
            self.db.flush()
        return c.id

    def year(self) -> int:
        if self.year_id:
            return self.year_id
        y = self.db.execute(select(X.Year).where(X.Year.is_current == 1)).scalars().first() \
            or self.db.execute(select(X.Year).where(X.Year.active == 1)
                               .order_by(X.Year.year_value.desc())).scalars().first()
        if not y:
            n = date.today().year
            y = X.Year(year_value=n, label=str(n), start_date=date(n, 1, 1),
                       end_date=date(n, 12, 31), is_current=1, active=1)
            self.db.add(y)
            self.db.flush()
            self.messages.append(f"No year was set up, so year {n} (1 Jan – 31 Dec) was "
                                 f"created and marked current. Edit it on the Years screen "
                                 f"if your year runs differently.")
        self.year_id = y.id
        return y.id

    # --- placeholders for a row pointed at but never sent
    def zone(self, lid) -> int:
        o = self._find(X.Zone, lid, by_name=False)
        if o is None:
            o = X.Zone(code=self._code(X.Zone, f"Z{lid}" if lid else "Z-NONE"),
                       name=f"Zone #{lid}" if lid else "Unassigned zone",
                       country_id=self.country_in(), active=1, legacy_id=lid)
            self.db.add(o)
            self.db.flush()
            self._remember(X.Zone, o)
            self.tally("zone").placeholders += 1
        return o.id

    def hq(self, lid, zone_lid=None) -> int:
        o = self._find(X.Headquarter, lid, by_name=False)
        if o is None:
            o = X.Headquarter(code=self._code(X.Headquarter, f"HQ{lid}" if lid else "HQ-NONE"),
                              name=f"HQ #{lid}" if lid else "Unassigned HQ",
                              zone_id=self.zone(zone_lid), active=1, legacy_id=lid)
            self.db.add(o)
            self.db.flush()
            self._remember(X.Headquarter, o)
            self.tally("hq").placeholders += 1
        return o.id

    def territory(self, lid, hq_lid=None, zone_lid=None) -> int:
        o = self._find(X.Territory, lid, by_name=False)
        if o is None:
            o = X.Territory(code=self._code(X.Territory, f"T{lid}"), name=f"Territory #{lid}",
                            headquarter_id=self.hq(hq_lid, zone_lid), active=1, legacy_id=lid)
            self.db.add(o)
            self.db.flush()
            self._remember(X.Territory, o)
            self.tally("territory").placeholders += 1
        return o.id

    def _simple(self, model, kind, prefix, label, lid, **extra) -> int:
        o = self._find(model, lid, by_name=False)
        if o is None:
            o = model(code=self._code(model, f"{prefix}{lid}" if lid else f"{prefix}-NONE"),
                      name=f"{label} #{lid}" if lid else f"Unassigned {label.lower()}",
                      active=1, legacy_id=lid, **extra)
            self.db.add(o)
            self.db.flush()
            self._remember(model, o)
            self.tally(kind).placeholders += 1
        return o.id

    def group(self, lid):
        return self._simple(X.ProductGroup, "product_group", "PG", "Product group", lid)

    def brand(self, lid, group_lid):
        o = self._find(X.Brand, lid, by_name=False)
        if o is None:
            o = X.Brand(code=self._code(X.Brand, f"B{lid}"), name=f"Brand #{lid}",
                        product_group_id=self.group(group_lid), active=1, legacy_id=lid)
            self.db.add(o)
            self.db.flush()
            self._remember(X.Brand, o)
            self.tally("brand").placeholders += 1
        return o.id

    def role(self, lid):
        return self._simple(X.Role, "role", "R", "Role", lid) if lid else None

    def designation(self, lid):
        return self._simple(X.Designation, "designation", "D", "Designation", lid, level=1)

    def team(self, lid):
        return self._simple(X.Team, "team", "TM", "Team", lid) if lid else None

    def team_by_name(self, name) -> int | None:
        if not name:
            return None
        c = self._load(X.Team)
        if name.isdigit() and int(name) in c["legacy"]:
            return c["legacy"][int(name)].id
        key = name.strip().upper()
        o = c["names"].get(key) or next(
            (r for r in c["legacy"].values() if (r.code or "").upper() == key), None)
        if o is None:
            o = next((r for r in self.db.execute(select(X.Team).where(X.Team.code == key[:20]))
                      .scalars()), None)
        if o is None:
            o = X.Team(code=self._code(X.Team, _slug(name), "TM"), name=name.strip()[:80], active=1)
            self.db.add(o)
            self.db.flush()
            c["names"][key] = o
            self.tally("team").added += 1
        return o.id

    # ------------------------------------------------------ lookup tables
    def lookup(self, kind, model, rows, id_names, prefix, parent=None, extra=None, hint=""):
        """Zone, HQ, territory, group, role, designation, team: an id, a name,
        maybe a code, maybe a parent. Found by column names, not position."""
        t = self.tally(kind)
        if not rows:
            return
        cols = list(rows[0].keys())
        idc = _pick(cols, *id_names, "ID") or next((c for c in cols if c.endswith("_ID")), None)
        # prefer the table's own name column: a territory row may also carry HQ_NAME
        namec = next((c for c in cols if hint and hint in c and "NAME" in c), None) \
            or _pick(cols, contains="NAME", not_end="_ID") or _pick(cols, "DESCRIPTION", "DESC")
        codec = next((c for c in cols if hint and hint in c and "CODE" in c), None) \
            or _pick(cols, contains="CODE", not_end="_ID")
        statc = _pick(cols, "STATUS", "ACTIVE", "IS_ACTIVE")
        if not idc or not namec:
            t.note(f"Could not find the id and name columns (saw: {', '.join(cols[:12])}).")
            t.skipped += len(rows)
            return
        for r in rows:
            lid = _int(r.get(idc))
            name = _str(r.get(namec), 120)
            if lid is None or not name:
                t.skipped += 1
                continue
            values = {"name": name, "active": _bool(r.get(statc)) if statc else 1}
            if parent:
                values.update(parent(r))
            o = self._find(model, lid, name)
            if o is None:
                o = model(code=self._code(model, _str(r.get(codec)) if codec else None,
                                          _slug(name), f"{prefix}{lid}"),
                          legacy_id=lid, **values, **(extra(r) if extra else {}))
                self.db.add(o)
                t.added += 1
            else:
                was_placeholder = o.name.endswith(f"#{lid}")
                for k, v in values.items():
                    setattr(o, k, v)
                o.legacy_id = lid
                if was_placeholder and codec and _str(r.get(codec)):
                    want = _str(r.get(codec)).upper()[:20]
                    if want not in self._load(model)["codes"]:
                        self._load(model)["codes"].add(want)
                        o.code = want
                t.updated += 1
            self.db.flush()
            self._remember(model, o)

    def names_only(self, kind, rows, id_names):
        """State, classification, remark, sub-territory: kept as names."""
        t = self.tally(kind)
        if not rows:
            return
        cols = list(rows[0].keys())
        idc = _pick(cols, *id_names, "ID") or next((c for c in cols if c.endswith("_ID")), None)
        namec = _pick(cols, contains="NAME", not_end="_ID") \
            or _pick(cols, contains="DESC") or _pick(cols, contains="REMARK", not_end="_ID") \
            or _pick(cols, contains="CLASSIFICATION", not_end="_ID")
        if not idc or not namec:
            t.note(f"Could not find the id and name columns (saw: {', '.join(cols[:12])}).")
            return
        d = self.lookups.setdefault(kind, {})
        for r in rows:
            lid, name = _int(r.get(idc)), _str(r.get(namec))
            if lid is not None and name:
                d[lid] = name
                t.added += 1

    # ------------------------------------------------------------ brands
    def brands(self, rows):
        t = self.tally("brand")
        lines = None
        for r in rows:
            lid = _int(r.get("PRODUCT_BRAND_ID"))
            name = _str(r.get("PRODUCT_BRAND_NAME"), 120)
            if lid is None or not name:
                t.skipped += 1
                t.note(f"Row without PRODUCT_BRAND_ID or name: {r}")
                continue
            values = dict(name=name, product_group_id=self.group(_int(r.get("PRODUCT_GROUP_ID"))),
                          nrv=_str(r.get("NRV"), 20), start_date=_date(r.get("START_DATE")),
                          end_date=_date(r.get("END_DATE")), active=_bool(r.get("STATUS")))
            o = self._find(X.Brand, lid, name)
            if o is None:
                o = X.Brand(code=self._code(X.Brand, _slug(name), f"B{lid}"), legacy_id=lid, **values)
                self.db.add(o)
                t.added += 1
            else:
                for k, v in values.items():
                    setattr(o, k, v)
                o.legacy_id = lid
                t.updated += 1
            self.db.flush()
            self._remember(X.Brand, o)

            rep = _str(r.get("REPORTING"))
            if rep and lines is None:
                year = self.year()
                lines = {pr.code: pr for pr in self.db.execute(
                    select(X.ProductReporting).where(X.ProductReporting.year_id == year)).scalars()}
            if rep:
                flag = "P1" if rep.upper().startswith("P1") else "P2" if rep.upper().startswith("P2") else "X"
                pr = lines.get(o.code)
                if pr is None:
                    pr = X.ProductReporting(year_id=year, code=o.code, name=o.name, flag=flag, active=1)
                    self.db.add(pr)
                    lines[o.code] = pr
                    self.tally("product_reporting").added += 1
                else:
                    pr.flag, pr.name = flag, o.name
                    self.tally("product_reporting").updated += 1
            team_lid = _int(r.get("TEAM_ID"))
            if team_lid:
                year = self.year()
                tid = self.team(team_lid)
                have = self.db.execute(select(X.TeamProductGroup.id).where(
                    X.TeamProductGroup.year_id == year, X.TeamProductGroup.team_id == tid,
                    X.TeamProductGroup.product_group_id == o.product_group_id)).first()
                if not have:
                    self.db.add(X.TeamProductGroup(year_id=year, team_id=tid,
                                                   product_group_id=o.product_group_id))
                    self.tally("team_product_group").added += 1
        self.db.flush()

    # -------------------------------------------------------------- SKUs
    def products(self, rows):
        t = self.tally("product")
        pending = []
        for r in rows:
            lid = _int(r.get("PRODUCT_ID"))
            name = _str(r.get("SAP_PRODUCT_NAME"), 250)
            aliases = [_str(v, 250) for k, v in r.items() if k.startswith("PRODUCT_ALIAS")]
            aliases = [a for a in aliases if a]
            if not name and aliases:
                name = aliases[0]
            if lid is None or not name:
                t.skipped += 1
                t.note(f"PRODUCT_ID {r.get('PRODUCT_ID')}: no id or no name, left out.")
                continue
            values = dict(
                name=name,
                brand_id=self.brand(_int(r.get("PRODUCT_BRAND_ID")), _int(r.get("PRODUCT_GROUP_ID"))),
                sap_product_id=_str(r.get("SAP_PRODUCT_ID"), 25),
                material_code=_str(r.get("MATERIAL_CODE"), 50),
                nrv=_str(r.get("NRV"), 20),
                start_date=_date(r.get("START_DATE")), end_date=_date(r.get("END_DATE")),
                active=_bool(r.get("STATUS")))
            o = self._find(X.Sku, lid, by_name=False)
            if o is None:
                sap = values["sap_product_id"]
                o = X.Sku(code=self._code(X.Sku, sap if sap and len(sap) <= 20 else None, f"P{lid}"),
                          legacy_id=lid, **values)
                self.db.add(o)
                t.added += 1
            else:
                for k, v in values.items():
                    setattr(o, k, v)
                t.updated += 1
            self._remember(X.Sku, o)
            pending.append((o, aliases))
        self.db.flush()

        # brand's reporting line, if the brand had one
        if not self.db.execute(select(X.ProductReporting.id)).first():
            t.aliases += self._aliases(X.SkuAlias, "sku_id", pending)
            return
        year = self.year()
        lines = {pr.code: pr for pr in self.db.execute(
            select(X.ProductReporting).where(X.ProductReporting.year_id == year)).scalars()}
        mapped = {s for (s,) in self.db.execute(
            select(X.ProductReportingSku.sku_id).where(X.ProductReportingSku.year_id == year))}
        brands = {b.id: b for b in self.db.execute(select(X.Brand)).scalars()}
        for o, aliases in pending:
            b = brands.get(o.brand_id)
            pr = lines.get(b.code) if b else None
            if pr is not None and o.id not in mapped:
                self.db.add(X.ProductReportingSku(product_reporting_id=pr.id, sku_id=o.id, year_id=year))
                mapped.add(o.id)
                self.tally("product_reporting_sku").added += 1
        t.aliases += self._aliases(X.SkuAlias, "sku_id", pending)

    def _aliases(self, model, fk, pending) -> int:
        have = {(getattr(a, fk), a.alias.upper()) for a in self.db.execute(select(model)).scalars()}
        n = 0
        for o, aliases in pending:
            for a in aliases:
                key = (o.id, a.upper())
                if key in have:
                    continue
                have.add(key)
                self.db.add(model(**{fk: o.id, "alias": a}))
                n += 1
        self.db.flush()
        return n

    # --------------------------------------------------------- customers
    def customers(self, rows):
        t = self.tally("customer")
        L = self.lookups
        pending = []
        for r in rows:
            lid = _int(r.get("CUSTOMER_ID"))
            name = _str(r.get("CUSTOMER_NAME"), 200)
            if lid is None or not name:
                t.skipped += 1
                t.note(f"CUSTOMER_ID {r.get('CUSTOMER_ID')}: no id or no name, left out.")
                continue
            z, h, te = _int(r.get("ZONE_ID")), _int(r.get("HQ_ID")), _int(r.get("TERRITORY_ID"))
            cls_id = _int(r.get("CUST_CLASSIFICATION_ID"))
            cls = L.get("classification", {}).get(cls_id) or (f"Class {cls_id}" if cls_id else "Unclassified")
            sub, st, rem = (_int(r.get("SUB_TERRITORY_ID")), _int(r.get("STATE_ID")),
                            _int(r.get("CUST_REMARK_ID")))
            values = dict(
                name=name, classification=cls[:40],
                sap_id=_str(r.get("CUSTOMER_SAP_ID"), 50),
                billing_name=_str(r.get("CUSTOMER_BILLING_NAME"), 200),
                zone_id=self.zone(z) if z else None,
                headquarter_id=self.hq(h, z) if h else None,
                territory_id=self.territory(te, h, z) if te else None,
                sub_territory=_str(L.get("sub_territory", {}).get(sub) or sub, 120),
                state=_str(L.get("state", {}).get(st) or st, 80),
                remark=_str(L.get("remark", {}).get(rem) or rem, 200),
                start_date=_date(r.get("START_DATE")), end_date=_date(r.get("END_DATE")),
                active=_bool(r.get("STATUS")))
            aliases = [_str(v, 200) for k, v in r.items() if k.startswith("CUSTOMER_ALIAS")]
            aliases = [a for a in aliases if a]
            o = self._find(X.Customer, lid, by_name=False)
            if o is None:
                o = X.Customer(code=self._code(X.Customer, values["sap_id"] if values["sap_id"]
                                               and len(values["sap_id"]) <= 20 else None, f"C{lid}"),
                               legacy_id=lid, **values)
                self.db.add(o)
                t.added += 1
            else:
                for k, v in values.items():
                    setattr(o, k, v)
                t.updated += 1
            pending.append((o, aliases))
            if len(pending) % 1000 == 0:
                self.db.flush()
        self.db.flush()
        t.aliases += self._aliases(X.CustomerAlias, "customer_id", pending)

    # --------------------------------------------------------- employees
    def employees(self, rows):
        t = self.tally("employee")
        terr_by_code = {x.code.upper(): x for x in self.db.execute(select(X.Territory)).scalars()}
        done = []
        for r in rows:
            lid = _int(r.get("EMPLOYEE_ID"))
            name = " ".join(x for x in (_str(r.get("EMPLOYEE_FT_NM")), _str(r.get("EMPLOYEE_LT_NM"))) if x)
            if lid is None or not name:
                t.skipped += 1
                t.note(f"EMPLOYEE_ID {r.get('EMPLOYEE_ID')}: no id or no name, left out.")
                continue
            tcode = _str(r.get("TERRITORY_CODE"), 20)
            terr = terr_by_code.get(tcode.upper()) if tcode else None
            values = dict(
                name=name[:120], email=_str(r.get("EMAIL"), 120),
                designation_id=self.designation(_int(r.get("DESIGNATION_ID"))),
                role_id=self.role(_int(r.get("ROLE_ID"))),
                team_id=self.team_by_name(_str(r.get("TEAM"))),
                joining_date=_date(r.get("START_DATE")), end_date=_date(r.get("END_DATE")),
                territory_code=tcode, rd_cs_editable=_bool(r.get("RD_CS_EDITABLE"), 0),
                active=_bool(r.get("STATUS")))
            if terr is not None:
                values["headquarter_id"] = terr.headquarter_id
            o = self._find(X.Employee, lid, by_name=False)
            if o is None:
                ec = _str(r.get("EMPLOYEE_CODE"))
                o = X.Employee(code=self._code(X.Employee, ec, f"E{lid}"), legacy_id=lid, **values)
                self.db.add(o)
                t.added += 1
            else:
                for k, v in values.items():
                    setattr(o, k, v)
                t.updated += 1
            self._remember(X.Employee, o)
            done.append((o, _int(r.get("REPORTING_MANAGER_ID")), lid))
        self.db.flush()
        by_lid = self._load(X.Employee)["legacy"]
        missing = 0
        for o, boss, lid in done:
            if boss and boss != lid:
                b = by_lid.get(boss)
                if b is not None:
                    o.reports_to_id = b.id
                else:
                    missing += 1
        if missing:
            t.note(f"{missing} employees report to a manager id not in the file; left blank.")
        self.db.flush()

    # --------------------------------------------------------------- run
    def run(self, tables: list[tuple[str, list[dict]]]) -> dict:
        by_kind: dict[str, list[dict]] = {}
        files = []
        for name, rows in tables:
            k = kind_of(name)
            files.append({"table": name, "rows": len(rows),
                          "read_as": k if k in SUPPORTED else None})
            if k in SUPPORTED:
                by_kind.setdefault(k, []).extend(rows)
            elif k == "brand_reporting":
                self.messages.append(f"{name}: not needed — the P1/P2/X flag is taken from "
                                     f"PRODUCT_MASTER_BRAND.REPORTING.")
            else:
                self.messages.append(f"{name}: not a table this import knows, left alone.")

        cin = None
        # names first, so customers can use them
        self.names_only("state", by_kind.get("state"), ["STATE_ID"])
        self.names_only("classification", by_kind.get("classification"),
                        ["CUST_CLASSIFICATION_ID", "CLASSIFICATION_ID"])
        self.names_only("remark", by_kind.get("remark"), ["CUST_REMARK_ID", "REMARK_ID"])
        self.names_only("sub_territory", by_kind.get("sub_territory"), ["SUB_TERRITORY_ID"])

        if by_kind.get("zone"):
            cin = self.country_in()
        self.lookup("zone", X.Zone, by_kind.get("zone"), ["ZONE_ID"], "Z", hint="ZONE",
                    extra=lambda r: {"country_id": cin} if cin else {})
        self.lookup("hq", X.Headquarter, by_kind.get("hq"), ["HQ_ID", "HEADQUARTER_ID"], "HQ",
                    hint="HQ", parent=lambda r: {"zone_id": self.zone(_int(r.get("ZONE_ID")))})
        self.lookup("territory", X.Territory, by_kind.get("territory"), ["TERRITORY_ID"], "T",
                    hint="TERR",
                    parent=lambda r: {"headquarter_id": self.hq(
                        _int(r.get("HQ_ID") or r.get("HEADQUARTER_ID")), _int(r.get("ZONE_ID")))})
        self.lookup("product_group", X.ProductGroup, by_kind.get("product_group"),
                    ["PRODUCT_GROUP_ID", "GROUP_ID"], "PG", hint="GROUP")
        self.lookup("role", X.Role, by_kind.get("role"), ["ROLE_ID"], "R", hint="ROLE")
        self.lookup("designation", X.Designation, by_kind.get("designation"),
                    ["DESIGNATION_ID"], "D", hint="DESIGNATION")
        self.lookup("team", X.Team, by_kind.get("team"), ["TEAM_ID"], "TM", hint="TEAM")

        if by_kind.get("brand"):
            self.brands(by_kind["brand"])
        if by_kind.get("product"):
            self.products(by_kind["product"])
        if by_kind.get("customer"):
            self.customers(by_kind["customer"])
        if by_kind.get("employee"):
            self.employees(by_kind["employee"])

        placeholders = sum(x.placeholders for x in self.t.values())
        if placeholders:
            self.messages.append(
                f"{placeholders} rows were pointed at but not sent (named like \"HQ #12\"). "
                f"Send those tables and run the import again to give them their real names.")
        self.messages.append("Passwords from EMPLOYEE_MASTER are never copied.")
        return {"files": files, "tables": {k: vars(v) for k, v in self.t.items()},
                "messages": self.messages, "year_id": self.year_id}


def run_import(db: Session, files: list[tuple[str, bytes]], dry_run: bool = True,
               year_id: int | None = None) -> dict:
    tables = read_files(files)
    imp = Importer(db, year_id)
    try:
        out = imp.run(tables)
        if dry_run:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    out["dry_run"] = dry_run
    return out


if __name__ == "__main__":      # python -m app.services.legacy_import FILE... [--commit]
    import argparse
    import json

    from ..database import SessionLocal
    from .. import models  # noqa: F401
    ap = argparse.ArgumentParser(description="Import the old SQL Server masters.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--commit", action="store_true", help="write; without it, a dry run")
    ap.add_argument("--year-id", type=int)
    a = ap.parse_args()
    s = SessionLocal()
    try:
        res = run_import(s, [(f, open(f, "rb").read()) for f in a.files],
                         dry_run=not a.commit, year_id=a.year_id)
        print(json.dumps(res, indent=2, default=str))
    finally:
        s.close()
