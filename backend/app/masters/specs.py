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
from sqlalchemy import select

from .. import models as M
from .. import models_master as X
from . import view as V
from .view import Col


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
    locked_help: str = ""     # what the edit form says under a create_only field
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
    sheets: list[str] = field(default_factory=list)   # sheet / file names an upload knows it by
    master_id: bool = False                # has legacy_id, the Master ID the Excel tables point at
    bulk: bool = False                     # a data table of thousands of rows: uploaded in bulk
                                           # (services/bulk_load.py), left out of "every master"
    match: tuple[str, ...] = ()            # bulk: the columns that find a row again on re-upload
    filters: list[str] = field(default_factory=list)  # fields offered as filters above the list
    view: list = field(default_factory=list)          # list columns (view.Col); default: in_list
    name: Callable | None = None           # the row as a parent column shows it (view.name_of)
    can_add: bool = True                   # False: rows come only from an upload (HEAD_COUNT)
    can_delete: bool = True                # False: rows are edited, never removed on screen

    def f(self, name):
        return next(x for x in self.fields if x.name == name)


def bad(msg: str, code: int = 422):
    raise HTTPException(code, msg)




def v_year_number(db, o):
    if not 2000 <= int(o.year_number) <= 2100:
        bad("YEAR_NUMBER has to be a year between 2000 and 2100.")


def v_team_pg_hq(db, o):
    """The *_NAME columns follow the IDs, so the table reads on its own."""
    for idf, namef, model in (("team_id", "team_name", X.Team),
                              ("product_group_id", "product_group_name", X.ProductGroup),
                              ("hq_id", "hq_name", X.Headquarter)):
        v = getattr(o, idf)
        if v is not None:
            row = db.execute(select(model).where(model.legacy_id == v)).scalars().first()
            if row is not None:
                setattr(o, namef, row.name)


def v_head_count(db, o):
    if o.count is None or int(o.count) < 0:
        bad("COUNT has to be 0 or more.")


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


# ============================ the data tables of the old system (Book1.xlsx)
# Their *_ID columns name master rows the way the old system did: PRODUCT_ID,
# PRODUCT_BRAND_ID, CUSTOMER_ID and EMPLOYEE_ID are the master tables' own ids;
# HQ_ID, TERRITORY_ID, PRODUCT_GROUP_ID and TEAM_ID are Master IDs. All "soft":
# a sales row from 2016 naming a product no longer in the masters is kept.
ID_REFS = {
    "PRODUCT_ID": ("sku", None), "PRODUCT_BRAND_ID": ("brand", None),
    "CUSTOMER_ID": ("customer", None), "EMPLOYEE_ID": ("employee", None),
    "HQ_ID": ("headquarter", "legacy_id"), "TERRITORY_ID": ("territory", "legacy_id"),
    "PRODUCT_GROUP_ID": ("product_group", "legacy_id"), "TEAM_ID": ("team", "legacy_id"),
}
MONTH_NAMES = [m.title() for m in X.MONTHS]


def _table_fields(cols, listed=(), required=()) -> list[Field]:
    """One field per column of a workbook table, labelled with the column's own
    name. The table's ID is left to the caller."""
    out = []
    for name, kind in cols:
        if name == "ID":
            continue
        a = X.attr_of(name)
        if name in ID_REFS:
            slug, key = ID_REFS[name]
            f = Field(a, name, "ref", ref=slug, key=key, soft=True)
        elif name == "MONTH":
            f = Field(a, name, "select", options=MONTH_NAMES,
                      help="The month's name in full, e.g. January")
        else:
            f = Field(a, name, "int" if kind == "int" else "decimal" if kind == "num" else "text")
        f.in_list = name in listed
        f.required = name in required
        out.append(f)
    return out


ID_FIELD = Field("id", "ID", "int", create_only=True, help="Left blank, the next number is given.")
SALES_LISTED = ["YEAR", "MONTH", "DIST_NAME", "INVOICE_NO", "CUSTOMER_NAME", "PRODUCT_NAME",
                "HQ_NAME", "SALES_QTY", "FREE_QUANTITY", "RETURN_QUANTITY", "RATE"]
SALES_SEARCH = ["customer_name", "customer_master_name", "product_name", "dist_name",
                "invoice_no", "hq_name"]
BUDGET_LISTED = ["S_NO", "TARGET_YEAR", "EMPLOYEE_ID", "HQ_NAME", "PRODUCT_GROUP",
                 "PRODUCT_BRAND", "PRODUCT_NAME", "PRODUCT_BRAND_CATEGORY"]

# (slug, title, model, sheet names, filters, description)
ASSIGNMENT_SPECS = [
    ("customer_terr_assignment", "Customer territory assignment", X.CustomerTerrAssignment,
     ["CUSTOMER_TERR_ASSIGNMENT"], ["customer_id", "hq_id", "product_group_id", "team_id"],
     "CUSTOMER_TERR_ASSIGNMENT: which territory, HQ and team cover a customer for a product "
     "group."),
    ("customer_pg_assignment", "Customer product assignment", X.CustomerPgAssignment,
     ["CUSTOMER_PG_ASSIGNMENT"], ["customer_id", "product_group_id", "product_brand_id", "product_id"],
     "CUSTOMER_PG_ASSIGNMENT: which products of which brand and group each customer is "
     "assigned."),
    ("employee_terr_assignment", "Employee territory assignment", X.EmployeeTerrAssignment,
     ["EMPLOYEE_TERR_ASSIGNMENT"], ["employee_id", "hq_id", "territory_id"],
     "EMPLOYEE_TERR_ASSIGNMENT: which HQ and territory each employee covers."),
    ("employee_pg_assignment", "Employee product assignment", X.EmployeePgAssignment,
     ["EMPLOYEE_PG_ASSIGNMENT"], ["employee_id", "product_group_id", "product_brand_id", "product_id"],
     "EMPLOYEE_PG_ASSIGNMENT: which products of which brand and group each employee promotes."),
]


def _assignment_spec(slug, title, model, sheets, filters, description):
    cols = X.ASSIGNMENT_COLUMNS[model.__tablename__]
    attrs = tuple(X.attr_of(c) for c in cols)
    return Spec(slug, title, "Assignment", model,
                _table_fields([(c, "int") for c in cols], listed=cols, required=cols),
                label=lambda o: f"#{o.id}", search=[], order=list(attrs), bulk=True, match=attrs,
                unique=[(attrs, "That assignment is already there.")],
                filters=filters, sheets=sheets,
                description=description + " Every column together makes the row, so uploading "
                                          "the same sheet again adds nothing.")


SPECS: list[Spec] = [
    # ------------------------------------------------------------ setup
    Spec("year", "Year", "Others", X.YearMaster, [
        Field("id", "YEAR_ID", "int", create_only=True, help="Left blank, the next number is given."),
        Field("year_number", "YEAR_NUMBER", "int", required=True),
        Field("active", "STATUS", "bool", default=1),
    ], label=lambda o: str(o.year_number), name=lambda o: str(o.year_number),
        search=[], order=["-year_number"], validate=v_year_number,
        unique=[(("year_number",), "That year is already there.")],
        sheets=["YEAR_MASTER", "YEARS"], description="YEAR_MASTER of the old system."),

    Spec("reporting", "Product Reporting", "Product", X.BrandReporting, [
        Field("id", "ID", "int", create_only=True, help="Left blank, the next number is given."),
        Field("reporting", "REPORTING", required=True, help="e.g. P1, P2, N1, X-OTHERS"),
        Field("active", "STATUS", "bool", default=1),
    ], label=lambda o: o.reporting, name=lambda o: o.reporting, search=["reporting"],
        order=["id"], unique=[(("reporting",), "That reporting line is already there.")],
        sheets=["PRODUCT_MASTER_BRAND_REPORTING", "PRODUCT_REPORTING", "REPORTING"],
        description="PRODUCT_MASTER_BRAND_REPORTING: the lines a brand reports under. "
                    "A brand's REPORTING names one of these."),

    Spec("customer_classification", "Customer Classification", "Master data",
         X.CustomerClassification, [
        Field("id", "ID", "int", create_only=True, help="Left blank, the next number is given."),
        Field("description", "DESCRIPTION", required=True, help="e.g. INSTITUTIONAL"),
        Field("active", "STATUS", "bool", default=1),
    ], label=lambda o: o.description, name=lambda o: o.description, search=["description"],
        order=["id"], unique=[(("description",), "That classification is already there.")],
        sheets=["CUSTOMER_CLASSIFICATION", "CUST_CLASSIFICATION"],
        description="CUSTOMER_CLASSIFICATION: CUSTOMER_MASTER.CUST_CLASSIFICATION_ID points at ID."),

    Spec("distributor", "Distributors", "Setup", M.Distributor, [
        Field("name", "Name", required=True, cols=["DISTRIBUTOR_NAME"]),
        Field("dist_id", "DIST_ID", "int", cols=["DIST_ID", "DISTRIBUTOR_ID"],
              help="The distributor's number in the old system, as MAPPING_MASTER.DIST_ID "
                   "carries it (e.g. 18671704). Converting needs it."),
        Field("file_currency", "FILE_CURRENCY", "select", options=["NPR", "INR"],
              help="The currency of the amounts in this distributor's files. INR files "
                   "(Yetichem) have their rates turned into NPR for MAPPING_MASTER at the "
                   "Currency rate of the day. Empty is NPR."),
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
        Field("reporting", "REPORTING", suggest=["N1", "P1", "P2", "X-OTHERS"],
              help="A line of Product Reporting: N1, P1, P2 or X-OTHERS"),
        _keyed("team_id", "TEAM_ID", "team", in_list=False),
        Field("nrv", "NRV", in_list=False),
        Field("no_of_sku", "NO_OF_SKU", "int"),
        Field("active", "STATUS", "bool", default=1),
    ], label=lambda o: f"{o.id} — {o.product_brand_name}", name=lambda o: o.product_brand_name,
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
    ], label=lambda o: f"{o.id} — {o.sap_product_name}", name=lambda o: o.sap_product_name,
        search=["sap_product_name", "sap_product_id", "material_code",
                *[f"alias_{i}" for i in range(1, X.PRODUCT_ALIASES + 1)]],
        order=["sap_product_name"], validate=v_product,
        option_filters={"product_group_id": _sku_by_group},
        sheets=["PRODUCT_MASTER", "PRODUCTS", "SKU", "SKUS", "SKU_MASTER"],
        description="PRODUCT_MASTER, as in MASTER DATA & TABLES.xlsx. Each product belongs to one "
                    "brand; its aliases are kept on the row (PRODUCT_ALIAS_1 to 100)."),

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
        Field("cust_classification_id", "CUST_CLASSIFICATION_ID", "ref", ref="customer_classification",
              soft=True),
        Field("cust_remark_id", "CUST_REMARK_ID", "int", in_list=False),
        Field("start_date", "START_DATE", "date", in_list=False),
        Field("end_date", "END_DATE", "date", in_list=False),
        Field("active", "STATUS", "bool", default=1),
        Field("aliases", "CUSTOMER_ALIAS_1 … 50", "aliases", count=X.CUSTOMER_ALIASES,
              help="The names distributors write this customer under, one per line "
                   "(CUSTOMER_ALIAS_1 to CUSTOMER_ALIAS_50)."),
    ], label=lambda o: f"{o.id} — {o.customer_name}", name=lambda o: o.customer_name,
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

    Spec("employee", "Employees", "People", X.EmployeeMaster, name=lambda o: o.full_name, fields=[
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

    # ------------------- assignment: the old system's assignment tables
    *[_assignment_spec(*a) for a in ASSIGNMENT_SPECS],

    Spec("team_pg_hq", "Team PG HQ assignment", "Assignment", X.TeamPgHqAssignment, [
        Field("id", "S_NO", "int", create_only=True, help="Left blank, the next number is given."),
        _keyed("team_id", "TEAM_ID", "team"),
        Field("team_name", "TEAM_NAME", in_list=False, help="Left blank, filled from TEAM_ID."),
        _keyed("product_group_id", "PRODUCT_GROUP_ID", "product_group"),
        Field("product_group_name", "PRODUCT_GROUP_NAME", in_list=False,
              help="Left blank, filled from PRODUCT_GROUP_ID."),
        _keyed("hq_id", "HQ_ID", "headquarter"),
        Field("hq_name", "HQ_NAME", in_list=False, help="Left blank, filled from HQ_ID."),
    ], label=lambda o: f"#{o.id}", search=["team_name", "product_group_name", "hq_name"],
        order=["team_id", "product_group_id", "hq_id"], validate=v_team_pg_hq,
        unique=[(("team_id", "product_group_id", "hq_id"),
                 "That team already has that product group in that HQ.")],
        filters=["team_id", "product_group_id", "hq_id"], sheets=["TEAM_PG_HQ_ASSIGNMENT"],
        description="TEAM_PG_HQ_ASSIGNMENT: which product group each team promotes in which HQ."),

    # ------------------------------------------------- sales and budget
    Spec("sales", "Sales", "Sales & budget", X.SalesMapping,
         [*_c(ID_FIELD), *_table_fields(X.SALES_COLUMNS, SALES_LISTED)],
         label=lambda o: f"{o.id} — {o.customer_name or ''} · {o.product_name or ''}",
         search=SALES_SEARCH, order=["-id"], bulk=True, match=("id",),
         filters=["year", "month", "dist_name", "hq_id", "product_group_id"],
         sheets=["MAPPING_MASTER", "SALES", "SALES_MASTER"],
         description="MAPPING_MASTER: every sales line, one row per invoice line, with the IDs "
                     "and names of the product, customer, HQ and territory it was mapped to. "
                     "A row is found again by its ID, so uploading the same file twice adds nothing."),

    Spec("mid_sales", "Mid sales", "Sales & budget", X.MidSalesMapping,
         [*_c(ID_FIELD), *_table_fields(X.MID_SALES_COLUMNS, SALES_LISTED + ["MID"])],
         label=lambda o: f"{o.id} — {o.customer_name or ''} · {o.product_name or ''}",
         search=SALES_SEARCH, order=["-id"], bulk=True, match=("id",),
         filters=["year", "month", "dist_name", "hq_id", "product_group_id"],
         sheets=["MAPPING_MASTER_MID", "MID_SALES", "MIDSALES", "MID_MONTH_SALES"],
         description="MAPPING_MASTER_MID: the mid-month sales, the same columns as Sales plus MID."),

    Spec("head_count", "Head Count", "Budgeting", X.HeadCount, [
        Field("division", "DIVISION", required=True, create_only=True,
              locked_help="From the workbook; only COUNT is changed here."),
        Field("hq", "HQ", required=True, create_only=True,
              locked_help="From the workbook; only COUNT is changed here."),
        Field("count", "COUNT", "int", required=True),
    ], label=lambda o: f"{o.division} · {o.hq}", search=["division", "hq"],
        order=["division", "hq"], validate=v_head_count, bulk=True, match=("division", "hq"),
        can_add=False, can_delete=False,
        sheets=["HEAD_COUNT", "HEADCOUNT"],
        description="HEAD_COUNT: people per division in each HQ, with a TOTAL row per division. "
                    "Rows come from the workbook (Upload Excel); here only COUNT is changed."),

    Spec("budget", "Budget", "Sales & budget", X.Budget,
         _table_fields(X.BUDGET_COLUMNS, BUDGET_LISTED, required=["S_NO", "EMPLOYEE_ID", "HQ_ID"]),
         label=lambda o: f"{o.s_no} — {o.product_name or ''} ({o.hq_name or ''}, {o.target_year})",
         search=["product_name", "product_brand", "product_group", "hq_name"],
         order=["-target_year", "employee_id", "s_no"], bulk=True,
         match=("s_no", "employee_id", "hq_id"),
         unique=[(("s_no", "employee_id", "hq_id"),
                  "That S_NO already has a row for this employee and HQ. Edit that row instead.")],
         filters=["target_year", "employee_id", "hq_id", "product_group_id"],
         sheets=["BUDGET_MASTER", "BUDGET_MASTER_TEST_NEW", "BUDGET", "BUDGETS"],
         description="BUDGET_MASTER: target units and value by month, with the actuals, mid-month "
                     "actuals, expiry and returns beside them. S_NO repeats across the HQs and "
                     "employees a line is split over, so a row is S_NO + EMPLOYEE_ID + HQ_ID."),
]


# ===================================================== the old system's layout
# Each screen as the old Abbott application had it: its name, the menu column it
# sits in (Administration: Organisation structure, Product, Master data, Others;
# then Assignment, Budgeting, Sales) and its list columns. "Assignment tables"
# are the four *_ASSIGNMENT tables: the Assignment menu shows them joined, as
# Customer Terr-PG and Employee Terr-PG (routers/terr_pg.py), and those pages
# link to each table for adding and editing rows. The order here is the
# menu's order; the order of SPECS above (parents first) is the upload's.
def _cols(*cols):
    return [Col(label, path, primary) for label, path, *rest in cols for primary in [bool(rest)]]


A = "Active Status", "active"
LAYOUT = {
    # ---------------------------------------------- Organisation structure
    "company": ("Company", "Organisation structure",
                _cols(("Company Id", "id"), ("Company", "name", 1), A)),
    "zone": ("Zone", "Organisation structure",
             _cols(("Zone Id", "legacy_id"), ("Zone Name", "name", 1), A)),
    "headquarter": ("Head Quarter", "Organisation structure",
                    _cols(("HQ Id", "legacy_id"), ("HQ Name", "name", 1), ("Zone", "zone_id"), A)),
    "territory": ("Territory", "Organisation structure",
                  _cols(("Zone", "headquarter_id>zone_id"), ("HQ", "headquarter_id"),
                        ("Territory Id", "legacy_id"), ("Territory Name", "name", 1), A)),
    # ------------------------------------------------------------- Product
    "product_group": ("Division/Product Group", "Product",
                      _cols(("Product Group Id", "legacy_id"), ("Product Group Name", "name", 1), A)),
    "brand": ("Product Brand", "Product",
              _cols(("Product Group Name", "product_group_id"), ("Product Brand Id", "id"),
                    ("Product Brand Name", "product_brand_name", 1), ("Team", "team_id"),
                    ("Reporting", "reporting"), A)),
    "reporting": ("Product Reporting", "Product",
                  _cols(("Reporting Id", "id"), ("Reporting", "reporting", 1), A)),
    "sku": ("SKU", "Product",
            _cols(("Product Group Name", "product_group_id|product_brand_id>product_group_id"),
                  ("Product Brand Name", "product_brand_id"), ("Product Id", "id"),
                  ("Product Name", "sap_product_name", 1), ("Team", "product_brand_id>team_id"),
                  ("Reporting", "product_brand_id>reporting"), ("NRV", "nrv"), A)),
    # --------------------------------------------------------- Master data
    "customer": ("Customer/Hospital", "Master data",
                 _cols(("Customer Id", "id"), ("Customer Name", "customer_name", 1),
                       ("Customer Classification", "cust_classification_id"), A)),
    "customer_classification": ("Customer Classification", "Master data",
                                _cols(("Customer Classification Id", "id"),
                                      ("Customer Classification", "description", 1), A)),
    "distributor": ("Distributor/Vendor", "Master data",
                    _cols(("Distributor Id", "dist_id"), ("Distributor Name", "name", 1),
                          ("File currency", "file_currency"), A)),
    "employee": ("Employee", "Master data",
                 _cols(("Employee Id", "id"), ("Employee SAP Id", "employee_code"),
                       ("Employee Name", "full_name", 1), ("Email", "email"),
                       ("Role", "role_id"), ("Designation", "designation_id"), ("Team", "team"),
                       ("Reporting Manager", "reporting_manager_id"), A)),
    # -------------------------------------------------------------- Others
    "country": ("Country", "Others", _cols(("Country Id", "id"), ("Country", "name", 1), A)),
    "designation": ("Designation", "Others",
                    _cols(("Designation Id", "legacy_id"), ("Designation", "name", 1), A)),
    "role": ("Role", "Others", _cols(("Role Id", "legacy_id"), ("Role", "name", 1), A)),
    "team": ("Team", "Others", _cols(("Team Id", "legacy_id"), ("Team Name", "name", 1), A)),
    "year": ("Year", "Others", _cols(("Year Id", "id"), ("Year", "year_number", 1), A)),
    "currency_rate": ("Currency rates", "Others", []),
    "company_country": ("Company › Countries", "Others",
                        _cols(("Company", "company_id", 1), ("Country", "country_id"))),
    # ---------------------------------------------------------- Assignment
    "team_pg_hq": ("Team PG HQ", "Assignment",
                   _cols(("Team", "team_id|team_name", 1), ("Product Group", "product_group_id|product_group_name"),
                         ("HQ", "hq_id|hq_name"))),
    "customer_terr_assignment": ("Customer Terr-PG › Territory rows", "Assignment tables",
                                 _cols(("Customer Name", "customer_id", 1), ("HQ", "hq_id"),
                                       ("Territory", "territory_id"),
                                       ("Product Group", "product_group_id"), ("Team", "team_id"))),
    "customer_pg_assignment": ("Customer Terr-PG › Product rows", "Assignment tables",
                               _cols(("Customer Name", "customer_id", 1),
                                     ("Product Group", "product_group_id"),
                                     ("Product Brand", "product_brand_id"), ("Product", "product_id"))),
    "employee_terr_assignment": ("Employee Terr-PG › Territory rows", "Assignment tables",
                                 _cols(("Employee Name", "employee_id", 1), ("HQ", "hq_id"),
                                       ("Territory", "territory_id"))),
    "employee_pg_assignment": ("Employee Terr-PG › Product rows", "Assignment tables",
                               _cols(("Employee Name", "employee_id", 1),
                                     ("Product Group", "product_group_id"),
                                     ("Product Brand", "product_brand_id"), ("Product", "product_id"))),
    # ----------------------------------------------------- Budgeting, Sales
    "budget": ("Budget", "Budgeting", []),
    "head_count": ("Head Count", "Budgeting",
                   _cols(("Division", "division", 1), ("HQ", "hq"), ("Count", "count"))),
    "sales": ("Sales", "Sales", []),
    "mid_sales": ("Mid sales", "Sales", []),
}
MENU_ORDER = list(LAYOUT)

for _s in SPECS:
    _t, _g, _v = LAYOUT[_s.slug]
    _s.title, _s.group, _s.view = _t, _g, (_v or V.default(_s))

BY_SLUG: dict[str, Spec] = {s.slug: s for s in SPECS}


def get(slug: str) -> Spec:
    s = BY_SLUG.get(slug)
    if not s:
        raise HTTPException(404, "No such master")
    return s


def meta() -> list[dict]:
    """What the screens need to draw themselves — no callables."""
    out = []
    for s in sorted(SPECS, key=lambda s: MENU_ORDER.index(s.slug)):     # the menu's order
        out.append({
            "slug": s.slug, "title": s.title, "group": s.group, "description": s.description,
            "view": [{"label": c.label, "kind": V.kind(s, c.path), "primary": c.primary}
                     for c in s.view],
            "searchable": bool(s.search), "master_id": s.master_id,
            "bulk": s.bulk, "filters": s.filters, "can_add": s.can_add, "can_delete": s.can_delete,
            "table": s.model.__tablename__,
            "fields": [{k: v for k, v in vars(f).items()} for f in s.fields],
        })
    return out
