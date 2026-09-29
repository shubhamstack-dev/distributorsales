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
from sqlalchemy import select, update
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
    seen, boss = {o.id}, o.reports_to_id
    while boss:
        if boss in seen:
            bad("That reporting line goes round in a circle.")
        seen.add(boss)
        e = db.get(X.Employee, boss)
        boss = e.reports_to_id if e else None


def _sku_group(db, sku_id) -> int | None:
    s = db.get(X.Sku, sku_id)
    b = db.get(X.Brand, s.brand_id) if s else None
    return b.product_group_id if b else None


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


def v_employee_assignment(db, o):
    _year_rows_ok(db, o.year_id)
    if _sku_group(db, o.sku_id) != o.product_group_id:
        bad("That SKU is not in the product group chosen.")
    e = db.get(X.Employee, o.employee_id)
    if e and e.team_id and not db.execute(select(X.TeamProductGroup.id).where(
            X.TeamProductGroup.year_id == o.year_id, X.TeamProductGroup.team_id == e.team_id,
            X.TeamProductGroup.product_group_id == o.product_group_id)).first():
        t = db.get(X.Team, e.team_id)
        bad(f"{e.name} is in team {t.name}, which does not carry "
            f"{_pg_name(db, o.product_group_id)} in this year.")


def _sku_by_group(sel, v):
    return sel.join(X.Brand, X.Brand.id == X.Sku.brand_id).where(X.Brand.product_group_id == int(v))


def _territory_by_zone(sel, v):
    return sel.join(X.Headquarter, X.Headquarter.id == X.Territory.headquarter_id) \
              .where(X.Headquarter.zone_id == int(v))


# ------------------------------------------------------------------ shared
CODE = Field("code", "Code", "code", required=True)
NAME = Field("name", "Name", required=True)
ACTIVE = Field("active", "Active", "bool", default=1)
YEAR = Field("year_id", "Year", "ref", required=True, ref="year")


def _c(*fs):  # fresh copies, so specs never share a mutable Field
    return [Field(**vars(f)) for f in fs]


SPECS: list[Spec] = [
    # ------------------------------------------------------------ setup
    Spec("year", "Years", "Setup", X.Year, [
        Field("year_value", "Year", "int", required=True),
        Field("label", "Label", required=True, help="e.g. FY 2026-27"),
        Field("start_date", "Starts", "date", required=True),
        Field("end_date", "Ends", "date", required=True),
        Field("is_current", "Current year", "bool", default=0),
        Field("active", "Open", "bool", default=1, help="A closed year's alignment is read-only."),
    ], label=lambda o: o.label, search=["label"], order=["-year_value"],
        unique=[(("year_value",), "That year is already set up.")],
        validate=v_year, after_save=after_year,
        description="The years alignment is kept for. Marking one current clears the others."),

    Spec("distributor", "Distributors", "Setup", M.Distributor, [
        Field("name", "Name", required=True),
        Field("code", "Code", "code"),
        Field("country_id", "Country", "ref", ref="country"),
        Field("contact_person", "Contact person"),
        Field("phone", "Phone"),
        Field("email", "Email"),
        ACTIVE,
    ], label=lambda o: o.name, search=["name", "code"], order=["name"],
        unique=[(("name",), "A distributor with that name already exists."),
                (("code",), "Another distributor already has that code.")],
        extra_refs=[(M.Batch, "distributor_id", "converted batches")],
        description="Who sends the sales files. File-reading rules (cut-off, invoice numbering) "
                    "stay on the Rules screen; a new distributor starts on day 15, INV - 1."),

    Spec("company", "Companies", "Setup", X.Company, _c(CODE, NAME, ACTIVE),
         unique=[(("code",), "Another company already has that code.")]),

    Spec("country", "Countries", "Setup", X.Country, [
        *_c(CODE, NAME),
        Field("currency_code", "Currency", "code", required=True, help="Three letters: INR, NPR"),
        *_c(ACTIVE),
    ], unique=[(("code",), "Another country already has that code.")], validate=v_country,
        extra_refs=[]),

    Spec("currency_rate", "Currency rates", "Setup", X.CurrencyRate, [
        Field("from_currency", "1 unit of", "code", required=True),
        Field("to_currency", "equals … of", "code", required=True),
        Field("rate", "Rate", "decimal", required=True),
        Field("effective_from", "Effective from", "date", required=True),
        Field("note", "Note"),
    ], label=lambda o: f"1 {o.from_currency} = {o.rate} {o.to_currency}",
        search=["from_currency", "to_currency", "note"],
        order=["from_currency", "to_currency", "-effective_from"],
        unique=[(("from_currency", "to_currency", "effective_from"),
                 "There is already a rate for that pair from that date. Edit it instead.")],
        validate=v_rate,
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
        *_c(CODE, NAME), Field("country_id", "Country", "ref", required=True, ref="country"),
        *_c(ACTIVE)], unique=[(("code",), "Another zone already has that code.")]),

    Spec("headquarter", "Headquarters", "Geography", X.Headquarter, [
        *_c(CODE, NAME), Field("zone_id", "Zone", "ref", required=True, ref="zone"), *_c(ACTIVE)],
        unique=[(("code",), "Another HQ already has that code.")],
        description="Each HQ sits in one zone."),

    Spec("territory", "Territories", "Geography", X.Territory, [
        *_c(CODE, NAME),
        Field("headquarter_id", "Headquarter", "ref", required=True, ref="headquarter"),
        *_c(ACTIVE)],
        unique=[(("code",), "Another territory already has that code.")],
        option_filters={"zone_id": _territory_by_zone},
        description="Each territory sits under one HQ."),

    # --------------------------------------------------------- products
    Spec("product_group", "Product groups", "Products", X.ProductGroup, [
        *_c(CODE, NAME), Field("company_id", "Company", "ref", ref="company"), *_c(ACTIVE)],
        unique=[(("code",), "Another product group already has that code.")]),

    Spec("brand", "Brands", "Products", X.Brand, [
        *_c(CODE, NAME),
        Field("product_group_id", "Product group", "ref", required=True, ref="product_group"),
        *_c(ACTIVE)], unique=[(("code",), "Another brand already has that code.")],
        description="Each brand belongs to one product group."),

    Spec("sku", "SKUs", "Products", X.Sku, [
        *_c(CODE),
        Field("name", "Name", required=True),
        Field("brand_id", "Brand", "ref", required=True, ref="brand"),
        Field("pack_size", "Pack size", help="e.g. 10x10 TAB"),
        *_c(ACTIVE)], unique=[(("code",), "Another SKU already has that code.")],
        option_filters={"product_group_id": _sku_by_group},
        description="Each SKU belongs to one brand, and through it to one product group."),

    Spec("product_reporting", "Product reporting", "Products", X.ProductReporting, [
        *_c(YEAR, CODE, NAME),
        Field("flag", "Flag", "select", required=True, options=FLAGS,
              help="P1, P2, or X for others"),
        *_c(ACTIVE)],
        label=lambda o: f"{o.code} — {o.name} ({o.flag})",
        unique=[(("year_id", "code"), "That year already has a reporting line with that code.")],
        validate=v_reporting, year_bound=True,
        description="Reporting lines for a year, each flagged P1, P2 or X (others)."),

    Spec("product_reporting_sku", "Product reporting › SKUs", "Products", X.ProductReportingSku, [
        Field("product_reporting_id", "Reporting line", "ref", required=True,
              ref="product_reporting"),
        Field("sku_id", "SKU", "ref", required=True, ref="sku"),
        Field("year_id", "Year", "ref", ref="year", derived=True),
    ], label=lambda o: f"#{o.id}", search=[], order=["product_reporting_id", "sku_id"],
        unique=[(("year_id", "sku_id"),
                 "That SKU already reports under another line in this year.")],
        validate=v_reporting_sku,
        description="Which reporting line each SKU rolls up to. One line per SKU per year."),

    # -------------------------------------------------------- customers
    Spec("customer", "Customers", "Customers", X.Customer, [
        Field("code", "Customer ID", "code", required=True),
        Field("name", "Customer name", required=True),
        Field("classification", "Classification", required=True, suggest=CLASSIFICATIONS),
        Field("city", "City"),
        Field("country_id", "Country", "ref", ref="country"),
        *_c(ACTIVE)], search=["code", "name", "classification", "city"],
        unique=[(("code",), "Another customer already has that Customer ID.")]),

    # ----------------------------------------------------------- people
    Spec("designation", "Designations", "People", X.Designation, [
        *_c(CODE, NAME),
        Field("level", "Level", "int", required=True, default=1,
              help="1 = field; higher numbers sit higher up"),
        *_c(ACTIVE)], order=["level", "code"],
        unique=[(("code",), "Another designation already has that code.")]),

    Spec("role", "Roles", "People", X.Role, [
        *_c(CODE, NAME), Field("description", "Description", in_list=False), *_c(ACTIVE)],
        unique=[(("code",), "Another role already has that code.")]),

    Spec("team", "Teams", "People", X.Team, [
        *_c(CODE, NAME), Field("company_id", "Company", "ref", ref="company"), *_c(ACTIVE)],
        unique=[(("code",), "Another team already has that code.")]),

    Spec("team_product_group", "Team › Product groups", "People", X.TeamProductGroup, [
        *_c(YEAR),
        Field("team_id", "Team", "ref", required=True, ref="team"),
        Field("product_group_id", "Product group", "ref", required=True, ref="product_group"),
    ], label=lambda o: f"#{o.id}", search=[], order=["team_id", "product_group_id"],
        unique=[(("year_id", "team_id", "product_group_id"),
                 "That team already carries that product group in this year.")],
        validate=lambda db, o: _year_rows_ok(db, o.year_id), year_bound=True,
        description="Which product groups each team promotes, by year."),

    Spec("team_headquarter", "Team › Headquarters", "People", X.TeamHeadquarter, [
        *_c(YEAR),
        Field("team_id", "Team", "ref", required=True, ref="team"),
        Field("headquarter_id", "Headquarter", "ref", required=True, ref="headquarter"),
    ], label=lambda o: f"#{o.id}", search=[], order=["team_id", "headquarter_id"],
        unique=[(("year_id", "team_id", "headquarter_id"),
                 "That team already covers that HQ in this year.")],
        validate=lambda db, o: _year_rows_ok(db, o.year_id), year_bound=True,
        description="Which HQs each team covers, by year."),

    Spec("employee", "Employees", "People", X.Employee, [
        *_c(CODE, NAME),
        Field("designation_id", "Designation", "ref", required=True, ref="designation"),
        Field("role_id", "Role", "ref", ref="role"),
        Field("team_id", "Team", "ref", ref="team"),
        Field("headquarter_id", "HQ", "ref", ref="headquarter"),
        Field("reports_to_id", "Reports to", "ref", ref="employee"),
        Field("email", "Email", in_list=False),
        Field("phone", "Phone", in_list=False),
        Field("joining_date", "Joined", "date", in_list=False),
        *_c(ACTIVE)], search=["code", "name", "email"],
        unique=[(("code",), "Another employee already has that code.")],
        validate=v_employee),

    # -------------------------------------------------------- alignment
    Spec("customer_assignment", "Customer alignment", "Alignment", X.CustomerAssignment, [
        *_c(YEAR),
        Field("customer_id", "Customer", "ref", required=True, ref="customer"),
        Field("territory_id", "Territory", "ref", required=True, ref="territory"),
        Field("team_id", "Team", "ref", required=True, ref="team"),
        Field("product_group_id", "Product group", "ref", required=True, ref="product_group"),
        Field("sku_id", "SKU", "ref", required=True, ref="sku",
              narrow={"param": "product_group_id", "from": "product_group_id"}),
    ], label=lambda o: f"#{o.id}", search=[],
        order=["customer_id", "product_group_id", "sku_id"],
        unique=[(("year_id", "customer_id", "sku_id"),
                 "That customer's SKU is already assigned in this year. Edit that row instead.")],
        validate=v_customer_assignment, bulk_by_sku=True, year_bound=True,
        description="Kept at SKU level: one row per customer per SKU per year, naming the "
                    "territory and team that cover it. The team must carry the product group "
                    "and cover the territory's HQ in that year."),

    Spec("employee_assignment", "Employee alignment", "Alignment", X.EmployeeAssignment, [
        *_c(YEAR),
        Field("employee_id", "Employee", "ref", required=True, ref="employee"),
        Field("territory_id", "Territory", "ref", required=True, ref="territory"),
        Field("product_group_id", "Product group", "ref", required=True, ref="product_group"),
        Field("sku_id", "SKU", "ref", required=True, ref="sku",
              narrow={"param": "product_group_id", "from": "product_group_id"}),
    ], label=lambda o: f"#{o.id}", search=[],
        order=["employee_id", "territory_id", "sku_id"],
        unique=[(("year_id", "employee_id", "territory_id", "sku_id"),
                 "That employee already has that SKU in that territory this year.")],
        validate=v_employee_assignment, bulk_by_sku=True, year_bound=True,
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
            "searchable": bool(s.search),
            "fields": [{k: v for k, v in vars(f).items()} for f in s.fields],
        })
    return out
