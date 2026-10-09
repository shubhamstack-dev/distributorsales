"""Every master screen, described once.

A spec says what a table's fields are, what makes a row unique, what it must
agree with, and what points at it. The API (routers/masters.py) and the React
screens (pages/masters) are both driven from here, so a rule added in this file
is enforced on the server and shown on the screen without touching either.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import models as M
from .. import models_master as X


@dataclass
class Field:
    name: str
    label: str
    type: str = "text"        # text | code | int | decimal | date | bool | select | ref
    required: bool = False
    ref: str | None = None    # slug of the master this field points at
    options: list[str] | None = None   # select: the only values allowed
    suggest: list[str] | None = None   # text: offered, not enforced
    narrow: dict | None = None         # ref: {"param": x, "from": y} — options filtered by another field
    in_list: bool = True
    derived: bool = False     # set by the server, not entered
    help: str | None = None
    default: object = None
    key: str | None = None    # ref: the target column this field holds (default its Id);
                              # "legacy_id" = the parent's Master ID, as the Excel tables use
    soft: bool = False        # ref: kept even when nothing has that id (yet)
    create_only: bool = False # set when the row is added, never changed after (the row's ID)
    count: int = 0            # aliases: how many alias columns there are
    cols: list[str] | None = None      # other headers this field is read from on upload


@dataclass
class Spec:
    slug: str
    title: str
    group: str
    model: type
    fields: list[Field]
    label: Callable = lambda o: f"{o.code} — {o.name}"
    search: list[str] = field(default_factory=lambda: ["code", "name"])
    order: list[str] = field(default_factory=lambda: ["code"])
    unique: list[tuple[tuple[str, ...], str]] = field(default_factory=list)
    validate: Callable | None = None       # (db, obj) -> None, raises HTTPException
    after_save: Callable | None = None     # (db, obj) -> None
    extra_refs: list[tuple] = field(default_factory=list)   # (model, attr, "what")
    option_filters: dict = field(default_factory=dict)      # param -> fn(select, value)
    description: str = ""
    bulk_by_sku: bool = False              # offers "assign every SKU of a group"
    year_bound: bool = False               # has year_id; offers "copy from year"
    sheets: list[str] = field(default_factory=list)   # sheet / file names an upload knows it by
    master_id: bool = False                # has legacy_id, the Master ID the Excel tables point at

    def f(self, name):
        return next(x for x in self.fields if x.name == name)


def bad(msg: str, code: int = 422):
    raise HTTPException(code, msg)


CLASSIFICATIONS = ["Chemist", "Stockist", "Hospital", "Institution", "Doctor", "Sub-stockist"]
FLAGS = ["P1", "P2", "X"]


def _year_rows_ok(db: Session, year_id: int):
    y = db.get(X.Year, year_id)
    if y and not y.active:
        bad(f"{y.label} is closed (inactive). Reopen the year before changing its alignment.")


# ------------------------------------------------------------- validators
def v_year(db, o):
    if not 2000 <= int(o.year_value) <= 2100:
        bad("Year has to be between 2000 and 2100.")
    if o.end_date <= o.start_date:
        bad("The year has to end after it starts.")


def after_year(db, o):
    # only one year is current; marking one clears the rest
    if o.is_current:
        db.execute(update(X.Year).where(X.Year.id != o.id).values(is_current=0))


def v_country(db, o):
    if not re.fullmatch(r"[A-Z]{3}", o.currency_code or ""):
        bad("Currency is a three-letter code such as INR or NPR.")


def v_rate(db, o):
    for c in (o.from_currency, o.to_currency):
        if not re.fullmatch(r"[A-Z]{3}", c or ""):
            bad("Currencies are three-letter codes such as INR or NPR.")
    if o.from_currency == o.to_currency:
        bad("A rate converts one currency into a different one.")
    if float(o.rate) <= 0:
        bad("The rate has to be more than zero.")
    known = set(db.execute(select(X.Country.currency_code)).scalars())
    for c in (o.from_currency, o.to_currency):
        if c not in known:
            bad(f"No country uses {c}. Add the country first, then its rate.")
    # one direction per pair, so INR->NPR and NPR->INR can never disagree
    rev = db.execute(select(X.CurrencyRate.id).where(
        X.CurrencyRate.from_currency == o.to_currency,
        X.CurrencyRate.to_currency == o.from_currency)).first()
    if rev:
        bad(f"Rates for this pair are kept as {o.to_currency} → {o.from_currency}; "
            f"the other direction is worked out from it. Enter the rate that way.")


def v_reporting(db, o):
    if o.flag not in FLAGS:
        bad("Flag is P1, P2 or X (others).")
    _year_rows_ok(db, o.year_id)


def v_reporting_sku(db, o):
    pr = db.get(X.ProductReporting, o.product_reporting_id)
    o.year_id = pr.year_id                      # derived: the line's year
    _year_rows_ok(db, o.year_id)


def v_employee(db, o):
    """A reporting line may not go round in a circle. Reporting to oneself is
    how EMPLOYEE_MASTER marks the top of the tree (91430 reports to 91430), so
    that is allowed, and a chain stops there."""
    boss = o.reporting_manager_id
    if boss is None or boss == o.id:
        return
    seen = {o.id}
    while boss:
        if boss in seen:
            bad("That reporting line goes round in a circle.")
        seen.add(boss)
        e = db.get(X.EmployeeMaster, boss)
        nxt = e.reporting_manager_id if e else None
        if nxt == boss:
            break
        boss = nxt


def v_product(db, o):
    # PRODUCT_GROUP_ID follows the brand's, as the old system kept it
    if o.product_brand_id is not None:
        b = db.get(X.ProductMasterBrand, o.product_brand_id)
        if b is not None and b.product_group_id is not None and o.product_group_id is None:
            o.product_group_id = b.product_group_id


def group_md_id(db, master_id) -> int | None:
    """md_product_group.Id for a PRODUCT_GROUP_ID (its Master ID)."""
    if master_id is None:
        return None
    return db.execute(select(X.ProductGroup.id)
                      .where(X.ProductGroup.legacy_id == master_id)).scalar()


def _sku_group(db, sku_id) -> int | None:
    s = db.get(X.ProductMaster, sku_id)
    if not s:
        return None
    gid = s.product_group_id
    if gid is None and s.product_brand_id is not None:
        b = db.get(X.ProductMasterBrand, s.product_brand_id)
        gid = b.product_group_id if b else None
    return group_md_id(db, gid)


def _pg_name(db, pg_id):
    g = db.get(X.ProductGroup, pg_id)
    return g.name if g else f"#{pg_id}"


def v_customer_assignment(db, o):
    _year_rows_ok(db, o.year_id)
    if _sku_group(db, o.sku_id) != o.product_group_id:
        bad("That SKU is not in the product group chosen.")
    if not db.execute(select(X.TeamProductGroup.id).where(
            X.TeamProductGroup.year_id == o.year_id, X.TeamProductGroup.team_id == o.team_id,
            X.TeamProductGroup.product_group_id == o.product_group_id)).first():
        t = db.get(X.Team, o.team_id)
        bad(f"Team {t.name} does not carry {_pg_name(db, o.product_group_id)} in this year. "
            f"Assign the product group to the team first (Teams › Product groups).")
    terr = db.get(X.Territory, o.territory_id)
    if not db.execute(select(X.TeamHeadquarter.id).where(
            X.TeamHeadquarter.year_id == o.year_id, X.TeamHeadquarter.team_id == o.team_id,
            X.TeamHeadquarter.headquarter_id == terr.headquarter_id)).first():
        t, hq = db.get(X.Team, o.team_id), db.get(X.Headquarter, terr.headquarter_id)
        bad(f"Territory {terr.name} is under HQ {hq.name}, which team {t.name} does not cover "
            f"in this year. Assign the HQ to the team first (Teams › Headquarters).")


def employee_team(db, e) -> X.Team | None:
    """EMPLOYEE_MASTER.TEAM is the team's name (or code), as the old system kept it."""
    if not e or not e.team:
        return None
    t = e.team.strip().upper()
    return db.execute(select(X.Team).where(
        (func.upper(X.Team.name) == t) | (func.upper(X.Team.code) == t))).scalars().first()


def v_employee_assignment(db, o):
    _year_rows_ok(db, o.year_id)
    if _sku_group(db, o.sku_id) != o.product_group_id:
        bad("That SKU is not in the product group chosen.")
    e = db.get(X.EmployeeMaster, o.employee_id)
    t = employee_team(db, e)
    if t and not db.execute(select(X.TeamProductGroup.id).where(
            X.TeamProductGroup.year_id == o.year_id, X.TeamProductGroup.team_id == t.id,
            X.TeamProductGroup.product_group_id == o.product_group_id)).first():
        bad(f"{e.name} is in team {t.name}, which does not carry "
            f"{_pg_name(db, o.product_group_id)} in this year.")


def _group_master_id(v):
    return select(X.ProductGroup.legacy_id).where(X.ProductGroup.id == int(v)).scalar_subquery()


def _sku_by_group(sel, v):
    return sel.where(X.ProductMaster.product_group_id == _group_master_id(v))


def _brand_by_group(sel, v):
    return sel.where(X.ProductMasterBrand.product_group_id == _group_master_id(v))


def _territory_by_zone(sel, v):
    return sel.join(X.Headquarter, X.Headquarter.id == X.Territory.headquarter_id) \
              .where(X.Headquarter.zone_id == int(v))


# ------------------------------------------------------------------ shared
CODE = Field("code", "Code", "code", required=True)
NAME = Field("name", "Name", required=True)
ACTIVE = Field("active", "Active", "bool", default=1, cols=["STATUS", "IS_ACTIVE"])
STATUS = Field("active", "Status", "bool", default=1, cols=["STATUS"],
               help="Active (1) or inactive (0)")
YEAR = Field("year_id", "Year", "ref", required=True, ref="year")
MASTER_ID = Field("legacy_id", "Master ID", "int",
                  help="The ID the master tables (CUSTOMER_MASTER, PRODUCT_MASTER …) use for "
                       "this row. Left blank, the next free number is given.")
START = Field("start_date", "Start date", "date", in_list=False, cols=["START_DATE"])
END = Field("end_date", "End date", "date", in_list=False, cols=["END_DATE"])


def _c(*fs):  # fresh copies, so specs never share a mutable Field
    return [Field(**vars(f)) for f in fs]


def _mid(*cols):
    f = Field(**vars(MASTER_ID))
    f.cols = list(cols)
    return f


def _named(*cols, label="Name"):
    return Field("name", label, required=True, cols=list(cols))


def _coded(*cols):
    return Field("code", "Code", "code", required=True, cols=list(cols),
                 help="Left blank on upload, one is made from the name.")


def _keyed(name, label, ref, *cols, in_list=True):
    """A column of the Excel tables holding a parent's Master ID."""
    return Field(name, label, "ref", ref=ref, key="legacy_id", soft=True,
                 cols=list(cols), in_list=in_list)


def _label_mid(o):
    return f"{o.legacy_id} · {o.code} — {o.name}" if o.legacy_id is not None \
        else f"{o.code} — {o.name}"


SPECS: list[Spec] = [
    # ------------------------------------------------------------ setup
    Spec("year", "Years", "Setup", X.Year, [
        Field("year_value", "Year", "int", required=True, cols=["YEAR"]),
        Field("label", "Label", required=True, help="e.g. FY 2026-27"),
        Field("start_date", "Starts", "date", required=True, cols=["START_DATE"]),
        Field("end_date", "Ends", "date", required=True, cols=["END_DATE"]),
        Field("is_current", "Current year", "bool", default=0),
        Field("active", "Open", "bool", default=1, help="A closed year's alignment is read-only."),
    ], label=lambda o: o.label, search=["label"], order=["-year_value"],
        unique=[(("year_value",), "That year is already set up.")],
        validate=v_year, after_save=after_year, sheets=["YEAR_MASTER", "YEARS"],
        description="The years alignment is kept for. Marking one current clears the others."),

    Spec("distributor", "Distributors", "Setup", M.Distributor, [
        Field("name", "Name", required=True, cols=["DISTRIBUTOR_NAME"]),
        Field("code", "Code", "code", cols=["DISTRIBUTOR_CODE"]),
        Field("country_id", "Country", "ref", ref="country"),
        Field("contact_person", "Contact person"),
        Field("phone", "Phone"),
        Field("email", "Email"),
        ACTIVE,
    ], label=lambda o: o.name, search=["name", "code"], order=["name"],
        unique=[(("name",), "A distributor with that name already exists."),
                (("code",), "Another distributor already has that code.")],
        extra_refs=[(M.Batch, "distributor_id", "converted batches")],
        sheets=["DISTRIBUTOR_MASTER"],
        description="Who sends the sales files. File-reading rules (cut-off, invoice numbering) "
                    "stay on the Rules screen; a new distributor starts on day 15, INV - 1."),

    Spec("company", "Companies", "Setup", X.Company, _c(CODE, NAME, ACTIVE),
         unique=[(("code",), "Another company already has that code.")],
         sheets=["COMPANY_MASTER"]),

    Spec("country", "Countries", "Setup", X.Country, [
        *_c(CODE, NAME),
        Field("currency_code", "Currency", "code", required=True, help="Three letters: INR, NPR"),
        *_c(ACTIVE),
    ], unique=[(("code",), "Another country already has that code.")], validate=v_country,
        sheets=["COUNTRY_MASTER"]),

    Spec("currency_rate", "Currency rates", "Setup", X.CurrencyRate, [
        Field("from_currency", "1 unit of", "code", required=True, cols=["FROM_CURRENCY"]),
        Field("to_currency", "equals … of", "code", required=True, cols=["TO_CURRENCY"]),
        Field("rate", "Rate", "decimal", required=True),
        Field("effective_from", "Effective from", "date", required=True),
        Field("note", "Note"),
    ], label=lambda o: f"1 {o.from_currency} = {o.rate} {o.to_currency}",
        search=["from_currency", "to_currency", "note"],
        order=["from_currency", "to_currency", "-effective_from"],
        unique=[(("from_currency", "to_currency", "effective_from"),
                 "There is already a rate for that pair from that date. Edit it instead.")],
        validate=v_rate, sheets=["CURRENCY_RATE", "RATES"],
        description="Kept in one direction per pair (INR → NPR); the other direction is its "
                    "inverse. A rate applies from its date until the next one."),

    Spec("company_country", "Company › Countries", "Setup", X.CompanyCountry, [
        Field("company_id", "Company", "ref", required=True, ref="company"),
        Field("country_id", "Country", "ref", required=True, ref="country"),
    ], label=lambda o: f"#{o.id}", search=[], order=["company_id", "country_id"],
        unique=[(("company_id", "country_id"), "That company is already assigned to that country.")],
        description="Which countries each company operates in."),

    # -------------------------------------------------------- geography
    Spec("zone", "Zones", "Geography", X.Zone, [
        _mid("ZONE_ID"), _coded("ZONE_CODE"), _named("ZONE_NAME", "ZONE"),
        Field("country_id", "Country", "ref", required=True, ref="country", default="IN"),
        *_c(ACTIVE)], label=_label_mid, search=["code", "name"],
        unique=[(("code",), "Another zone already has that code."),
                (("legacy_id",), "Another zone already has that Master ID.")],
        sheets=["ZONE", "ZONE_MASTER"], master_id=True,
        description="Zones. CUSTOMER_MASTER.ZONE_ID points at a zone's Master ID."),

    Spec("headquarter", "Headquarters", "Geography", X.Headquarter, [
        _mid("HQ_ID", "HEADQUARTER_ID"), _coded("HQ_CODE"), _named("HQ_NAME", "HEADQUARTER_NAME", "HQ"),
        Field("zone_id", "Zone", "ref", required=True, ref="zone", cols=["ZONE_ID"]),
        *_c(ACTIVE)], label=_label_mid, search=["code", "name"],
        unique=[(("code",), "Another HQ already has that code."),
                (("legacy_id",), "Another HQ already has that Master ID.")],
        sheets=["HQ", "HQ_MASTER", "HEADQUARTER"], master_id=True,
        description="Each HQ sits in one zone. CUSTOMER_MASTER.HQ_ID points at its Master ID."),

    Spec("territory", "Territories", "Geography", X.Territory, [
        _mid("TERRITORY_ID"), _coded("TERRITORY_CODE"), _named("TERRITORY_NAME", "TERRITORY"),
        Field("headquarter_id", "Headquarter", "ref", required=True, ref="headquarter",
              cols=["HQ_ID", "HEADQUARTER_ID"]),
        *_c(ACTIVE)], label=_label_mid, search=["code", "name"],
        unique=[(("code",), "Another territory already has that code."),
                (("legacy_id",), "Another territory already has that Master ID.")],
        option_filters={"zone_id": _territory_by_zone},
        sheets=["TERRITORY", "TERRITORY_MASTER"], master_id=True,
        description="Each territory sits under one HQ. CUSTOMER_MASTER.TERRITORY_ID points at "
                    "its Master ID."),

    # --------------------------------------------------------- products
    Spec("product_group", "Product groups", "Products", X.ProductGroup, [
        _mid("PRODUCT_GROUP_ID", "GROUP_ID"), _coded("PRODUCT_GROUP_CODE", "GROUP_CODE"),
        _named("PRODUCT_GROUP_NAME", "GROUP_NAME", "PRODUCT_GROUP"),
        Field("company_id", "Company", "ref", ref="company"),
        *_c(ACTIVE)], label=_label_mid, search=["code", "name"],
        unique=[(("code",), "Another product group already has that code."),
                (("legacy_id",), "Another product group already has that Master ID.")],
        sheets=["PRODUCT_MASTER_GROUP", "PRODUCT_GROUP", "PRODUCT_GROUPS"], master_id=True,
        description="PRODUCT_MASTER_BRAND.PRODUCT_GROUP_ID and PRODUCT_MASTER.PRODUCT_GROUP_ID "
                    "point at a group's Master ID."),

    Spec("brand", "Brands", "Products", X.ProductMasterBrand, [
        Field("id", "PRODUCT_BRAND_ID", "int", create_only=True, cols=["PRODUCT_BRAND_ID"],
              help="Left blank, the next number is given."),
        Field("product_brand_name", "PRODUCT_BRAND_NAME", required=True),
        _keyed("product_group_id", "PRODUCT_GROUP_ID", "product_group"),
        Field("start_date", "START_DATE", "date", in_list=False),
        Field("end_date", "END_DATE", "date", in_list=False),
        Field("reporting", "REPORTING", suggest=["P1", "P2", "X-OTHERS"]),
        _keyed("team_id", "TEAM_ID", "team", in_list=False),
        Field("nrv", "NRV", in_list=False),
        Field("no_of_sku", "NO_OF_SKU", "int"),
        Field("active", "STATUS", "bool", default=1),
    ], label=lambda o: f"{o.id} — {o.product_brand_name}",
        search=["product_brand_name", "reporting"], order=["product_brand_name"],
        option_filters={"product_group_id": _brand_by_group},
        sheets=["PRODUCT_MASTER_BRAND", "BRAND", "BRANDS", "BRAND_MASTER"],
        description="PRODUCT_MASTER_BRAND, as in MASTER DATA & TABLES.xlsx. Each brand belongs to "
                    "one product group (PRODUCT_GROUP_ID = the group's Master ID)."),

    Spec("sku", "Products (SKUs)", "Products", X.ProductMaster, [
        Field("id", "PRODUCT_ID", "int", create_only=True, help="Left blank, the next number is given."),
        Field("sap_product_name", "SAP_PRODUCT_NAME", required=True),
        Field("product_brand_id", "PRODUCT_BRAND_ID", "ref", ref="brand", soft=True),
        Field("product_group_id", "PRODUCT_GROUP_ID", "ref", ref="product_group", key="legacy_id",
              soft=True, help="Left blank, the brand's group is used."),
        Field("sap_product_id", "SAP_PRODUCT_ID"),
        Field("nrv", "NRV", "decimal"),
        Field("material_code", "MATERIAL_CODE", in_list=False),
        Field("start_date", "START_DATE", "date", in_list=False),
        Field("end_date", "END_DATE", "date", in_list=False),
        Field("active", "STATUS", "bool", default=1),
        Field("aliases", "PRODUCT_ALIAS_1 … 100", "aliases", count=X.PRODUCT_ALIASES,
              help="The names distributors write this product under, one per line "
                   "(PRODUCT_ALIAS_1 to PRODUCT_ALIAS_100)."),
    ], label=lambda o: f"{o.id} — {o.sap_product_name}",
        search=["sap_product_name", "sap_product_id", "material_code",
                *[f"alias_{i}" for i in range(1, X.PRODUCT_ALIASES + 1)]],
        order=["sap_product_name"], validate=v_product,
        option_filters={"product_group_id": _sku_by_group},
        sheets=["PRODUCT_MASTER", "PRODUCTS", "SKU", "SKUS", "SKU_MASTER"],
        description="PRODUCT_MASTER, as in MASTER DATA & TABLES.xlsx. Each product belongs to one "
                    "brand; its aliases are kept on the row (PRODUCT_ALIAS_1 to 100)."),

    Spec("product_reporting", "Product reporting", "Products", X.ProductReporting, [
        *_c(YEAR, CODE, NAME),
        Field("flag", "Flag", "select", required=True, options=FLAGS,
              help="P1, P2, or X for others"),
        *_c(ACTIVE)],
        label=lambda o: f"{o.code} — {o.name} ({o.flag})",
        unique=[(("year_id", "code"), "That year already has a reporting line with that code.")],
        validate=v_reporting, year_bound=True, sheets=["PRODUCT_REPORTING"],
        description="Reporting lines for a year, each flagged P1, P2 or X (others)."),

    Spec("product_reporting_sku", "Product reporting › SKUs", "Products", X.ProductReportingSku, [
        Field("product_reporting_id", "Reporting line", "ref", required=True,
              ref="product_reporting"),
        Field("sku_id", "SKU", "ref", required=True, ref="sku", cols=["PRODUCT_ID"]),
        Field("year_id", "Year", "ref", ref="year", derived=True),
    ], label=lambda o: f"#{o.id}", search=[], order=["product_reporting_id", "sku_id"],
        unique=[(("year_id", "sku_id"),
                 "That SKU already reports under another line in this year.")],
        validate=v_reporting_sku, sheets=["PRODUCT_REPORTING_SKU"],
        description="Which reporting line each SKU rolls up to. One line per SKU per year."),

    # -------------------------------------------------------- customers
    Spec("customer", "Customers", "Customers", X.CustomerMaster, [
        Field("id", "CUSTOMER_ID", "int", create_only=True, help="Left blank, the next number is given."),
        Field("customer_name", "CUSTOMER_NAME", required=True),
        Field("customer_sap_id", "CUSTOMER_SAP_ID"),
        _keyed("zone_id", "ZONE_ID", "zone", in_list=False),
        _keyed("hq_id", "HQ_ID", "headquarter"),
        _keyed("territory_id", "TERRITORY_ID", "territory"),
        Field("sub_territory_id", "SUB_TERRITORY_ID", "int", in_list=False),
        Field("customer_billing_name", "CUSTOMER_BILLING_NAME", in_list=False),
        Field("state_id", "STATE_ID", "int", in_list=False),
        Field("cust_classification_id", "CUST_CLASSIFICATION_ID", "int"),
        Field("cust_remark_id", "CUST_REMARK_ID", "int", in_list=False),
        Field("start_date", "START_DATE", "date", in_list=False),
        Field("end_date", "END_DATE", "date", in_list=False),
        Field("active", "STATUS", "bool", default=1),
        Field("aliases", "CUSTOMER_ALIAS_1 … 50", "aliases", count=X.CUSTOMER_ALIASES,
              help="The names distributors write this customer under, one per line "
                   "(CUSTOMER_ALIAS_1 to CUSTOMER_ALIAS_50)."),
    ], label=lambda o: f"{o.id} — {o.customer_name}",
        search=["customer_name", "customer_sap_id", "customer_billing_name",
                *[f"alias_{i}" for i in range(1, X.CUSTOMER_ALIASES + 1)]],
        order=["customer_name"],
        sheets=["CUSTOMER_MASTER", "CUSTOMERS", "CUSTOMER"],
        description="CUSTOMER_MASTER, as in MASTER DATA & TABLES.xlsx. ZONE_ID, HQ_ID and "
                    "TERRITORY_ID are Master IDs; aliases are kept on the row "
                    "(CUSTOMER_ALIAS_1 to 50)."),

    # ----------------------------------------------------------- people
    Spec("designation", "Designations", "People", X.Designation, [
        _mid("DESIGNATION_ID"), _coded("DESIGNATION_CODE"),
        _named("DESIGNATION_NAME", "DESIGNATION"),
        Field("level", "Level", "int", required=True, default=1,
              help="1 = field; higher numbers sit higher up"),
        *_c(ACTIVE)], label=_label_mid, search=["code", "name"], order=["level", "code"],
        unique=[(("code",), "Another designation already has that code."),
                (("legacy_id",), "Another designation already has that Master ID.")],
        sheets=["DESIGNATION", "DESIGNATION_MASTER"], master_id=True),

    Spec("role", "Roles", "People", X.Role, [
        _mid("ROLE_ID"), _coded("ROLE_CODE"), _named("ROLE_NAME", "ROLE"),
        Field("description", "Description", in_list=False),
        *_c(ACTIVE)], label=_label_mid, search=["code", "name"],
        unique=[(("code",), "Another role already has that code."),
                (("legacy_id",), "Another role already has that Master ID.")],
        sheets=["ROLE", "ROLE_MASTER"], master_id=True),

    Spec("team", "Teams", "People", X.Team, [
        _mid("TEAM_ID"), _coded("TEAM_CODE"), _named("TEAM_NAME", "TEAM"),
        Field("company_id", "Company", "ref", ref="company"),
        *_c(ACTIVE)], label=_label_mid, search=["code", "name"],
        unique=[(("code",), "Another team already has that code."),
                (("legacy_id",), "Another team already has that Master ID.")],
        sheets=["TEAM", "TEAM_MASTER"], master_id=True,
        description="EMPLOYEE_MASTER.TEAM names a team; PRODUCT_MASTER_BRAND.TEAM_ID is its "
                    "Master ID."),

    Spec("team_product_group", "Team › Product groups", "People", X.TeamProductGroup, [
        *_c(YEAR),
        Field("team_id", "Team", "ref", required=True, ref="team"),
        Field("product_group_id", "Product group", "ref", required=True, ref="product_group"),
    ], label=lambda o: f"#{o.id}", search=[], order=["team_id", "product_group_id"],
        unique=[(("year_id", "team_id", "product_group_id"),
                 "That team already carries that product group in this year.")],
        validate=lambda db, o: _year_rows_ok(db, o.year_id), year_bound=True,
        sheets=["TEAM_PRODUCT_GROUP"],
        description="Which product groups each team promotes, by year."),

    Spec("team_headquarter", "Team › Headquarters", "People", X.TeamHeadquarter, [
        *_c(YEAR),
        Field("team_id", "Team", "ref", required=True, ref="team"),
        Field("headquarter_id", "Headquarter", "ref", required=True, ref="headquarter"),
    ], label=lambda o: f"#{o.id}", search=[], order=["team_id", "headquarter_id"],
        unique=[(("year_id", "team_id", "headquarter_id"),
                 "That team already covers that HQ in this year.")],
        validate=lambda db, o: _year_rows_ok(db, o.year_id), year_bound=True,
        sheets=["TEAM_HEADQUARTER", "TEAM_HQ"],
        description="Which HQs each team covers, by year."),

    Spec("employee", "Employees", "People", X.EmployeeMaster, [
        Field("id", "EMPLOYEE_ID", "int", create_only=True, help="Left blank, the next number is given."),
        Field("employee_ft_nm", "EMPLOYEE_FT_NM", required=True, help="First name"),
        Field("employee_lt_nm", "EMPLOYEE_LT_NM", help="Last name"),
        Field("email", "EMAIL"),
        _keyed("role_id", "ROLE_ID", "role"),
        _keyed("designation_id", "DESIGNATION_ID", "designation"),
        Field("team", "TEAM", help="The team's name, e.g. PRIMARY CARE"),
        Field("reporting_manager_id", "REPORTING_MANAGER_ID", "ref", ref="employee", soft=True),
        Field("start_date", "START_DATE", "date", in_list=False),
        Field("end_date", "END_DATE", "date", in_list=False),
        Field("rd_cs_editable", "RD_CS_EDITABLE", "bool", default=0, in_list=False),
        Field("employee_code", "EMPLOYEE_CODE"),
        Field("territory_code", "TERRITORY_CODE", in_list=False),
        Field("active", "STATUS", "bool", default=1),
    ], label=lambda o: f"{o.id} — {o.name}",
        search=["employee_ft_nm", "employee_lt_nm", "email", "employee_code", "team"],
        order=["employee_ft_nm", "employee_lt_nm"], validate=v_employee,
        sheets=["EMPLOYEE_MASTER", "EMPLOYEES", "EMPLOYEE"],
        description="EMPLOYEE_MASTER, as in MASTER DATA & TABLES.xlsx. The PASSWORD column is never "
                    "stored: an upload reads past it."),

    # -------------------------------------------------------- alignment
    Spec("customer_assignment", "Customer alignment", "Alignment", X.CustomerAssignment, [
        *_c(YEAR),
        Field("customer_id", "Customer", "ref", required=True, ref="customer", cols=["CUSTOMER_ID"]),
        Field("territory_id", "Territory", "ref", required=True, ref="territory"),
        Field("team_id", "Team", "ref", required=True, ref="team"),
        Field("product_group_id", "Product group", "ref", required=True, ref="product_group"),
        Field("sku_id", "SKU", "ref", required=True, ref="sku", cols=["PRODUCT_ID"],
              narrow={"param": "product_group_id", "from": "product_group_id"}),
    ], label=lambda o: f"#{o.id}", search=[],
        order=["customer_id", "product_group_id", "sku_id"],
        unique=[(("year_id", "customer_id", "sku_id"),
                 "That customer's SKU is already assigned in this year. Edit that row instead.")],
        validate=v_customer_assignment, bulk_by_sku=True, year_bound=True,
        sheets=["CUSTOMER_ALIGNMENT", "CUSTOMER_ASSIGNMENT"],
        description="Kept at SKU level: one row per customer per SKU per year, naming the "
                    "territory and team that cover it. The team must carry the product group "
                    "and cover the territory's HQ in that year."),

    Spec("employee_assignment", "Employee alignment", "Alignment", X.EmployeeAssignment, [
        *_c(YEAR),
        Field("employee_id", "Employee", "ref", required=True, ref="employee", cols=["EMPLOYEE_ID"]),
        Field("territory_id", "Territory", "ref", required=True, ref="territory"),
        Field("product_group_id", "Product group", "ref", required=True, ref="product_group"),
        Field("sku_id", "SKU", "ref", required=True, ref="sku", cols=["PRODUCT_ID"],
              narrow={"param": "product_group_id", "from": "product_group_id"}),
    ], label=lambda o: f"#{o.id}", search=[],
        order=["employee_id", "territory_id", "sku_id"],
        unique=[(("year_id", "employee_id", "territory_id", "sku_id"),
                 "That employee already has that SKU in that territory this year.")],
        validate=v_employee_assignment, bulk_by_sku=True, year_bound=True,
        sheets=["EMPLOYEE_ALIGNMENT", "EMPLOYEE_ASSIGNMENT"],
        description="Kept at SKU level: one row per employee per territory per SKU per year."),
]

BY_SLUG: dict[str, Spec] = {s.slug: s for s in SPECS}


def get(slug: str) -> Spec:
    s = BY_SLUG.get(slug)
    if not s:
        raise HTTPException(404, "No such master")
    return s


def meta() -> list[dict]:
    """What the screens need to draw themselves — no callables."""
    out = []
    for s in SPECS:
        out.append({
            "slug": s.slug, "title": s.title, "group": s.group, "description": s.description,
            "bulk_by_sku": s.bulk_by_sku, "year_bound": s.year_bound,
            "searchable": bool(s.search), "master_id": s.master_id,
            "table": s.model.__tablename__,
            "fields": [{k: v for k, v in vars(f).items()} for f in s.fields],
        })
    return out
