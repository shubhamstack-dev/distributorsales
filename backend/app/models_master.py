"""Master data: the structure sales are reported against.

Two kinds of table live here, and the difference matters:

* **Structure** — Zone > Headquarter > Territory, Product Group > Brand > SKU.
  A child names its parent with a foreign key, so each HQ sits in exactly one
  zone and each SKU in exactly one brand. These do not change year to year.
* **Alignment** — which team covers which product groups and HQs, which
  customer and which employee cover which SKU in which territory, and which
  reporting line a SKU rolls up to. These are realigned every year, so every
  alignment row carries a YearId and last year's alignment stays readable.

Column names are explicit (PascalCase) to match schema.sql and the existing
tables — except the four master tables taken over from MASTER DATA & TABLES.xlsx
(CUSTOMER_MASTER, EMPLOYEE_MASTER, PRODUCT_MASTER_BRAND, PRODUCT_MASTER), which
keep that workbook's table and column names exactly, aliases included as
columns. Their ZONE_ID, HQ_ID, TERRITORY_ID, PRODUCT_GROUP_ID, TEAM_ID, ROLE_ID
and DESIGNATION_ID hold the parent's *Master ID* (LegacyId on the md_* table),
which is the same number the old system used.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _code():
    return mapped_column("Code", String(20), nullable=False)


def _name(n=120):
    return mapped_column("Name", String(n), nullable=False)


def _active():
    return mapped_column("Active", Integer, nullable=False, default=1)


def _legacy():
    """The row's Id in the old SQL Server system. Set only by the legacy import,
    which uses it to update a row on a second run instead of adding it twice."""
    return mapped_column("LegacyId", Integer)


# ================================================================== setup
class Year(Base):
    __tablename__ = "md_year"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    year_value: Mapped[int] = mapped_column("YearValue", Integer, nullable=False, unique=True)
    label: Mapped[str] = mapped_column("Label", String(40), nullable=False)
    start_date: Mapped[date] = mapped_column("StartDate", Date, nullable=False)
    end_date: Mapped[date] = mapped_column("EndDate", Date, nullable=False)
    is_current: Mapped[int] = mapped_column("IsCurrent", Integer, nullable=False, default=0)
    active: Mapped[int] = _active()


class Company(Base):
    __tablename__ = "md_company"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_company_code"),)


class Country(Base):
    __tablename__ = "md_country"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name(80)
    currency_code: Mapped[str] = mapped_column("CurrencyCode", String(3), nullable=False)
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_country_code"),)


class CurrencyRate(Base):
    """1 FromCurrency = Rate ToCurrency, from EffectiveFrom until the next row.

    One direction is stored per pair (INR -> NPR); the other is its inverse,
    worked out when asked, so the two can never disagree.
    """
    __tablename__ = "md_currency_rate"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    from_currency: Mapped[str] = mapped_column("FromCurrency", String(3), nullable=False)
    to_currency: Mapped[str] = mapped_column("ToCurrency", String(3), nullable=False)
    rate: Mapped[float] = mapped_column("Rate", Numeric(18, 6), nullable=False)
    effective_from: Mapped[date] = mapped_column("EffectiveFrom", Date, nullable=False)
    note: Mapped[str | None] = mapped_column("Note", String(200))
    __table_args__ = (UniqueConstraint("FromCurrency", "ToCurrency", "EffectiveFrom",
                                       name="uq_rate_pair_date"),)


class CompanyCountry(Base):
    __tablename__ = "md_company_country"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column("CompanyId", ForeignKey("md_company.Id"), nullable=False)
    country_id: Mapped[int] = mapped_column("CountryId", ForeignKey("md_country.Id"), nullable=False)
    __table_args__ = (UniqueConstraint("CompanyId", "CountryId", name="uq_company_country"),)


# ============================================================== geography
class Zone(Base):
    __tablename__ = "md_zone"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    country_id: Mapped[int] = mapped_column("CountryId", ForeignKey("md_country.Id"), nullable=False)
    legacy_id: Mapped[int | None] = _legacy()
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_zone_code"),)


class Headquarter(Base):
    __tablename__ = "md_headquarter"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    zone_id: Mapped[int] = mapped_column("ZoneId", ForeignKey("md_zone.Id"), nullable=False)
    legacy_id: Mapped[int | None] = _legacy()
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_hq_code"),)


class Territory(Base):
    __tablename__ = "md_territory"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    headquarter_id: Mapped[int] = mapped_column(
        "HeadquarterId", ForeignKey("md_headquarter.Id"), nullable=False)
    legacy_id: Mapped[int | None] = _legacy()
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_territory_code"),)


# =============================================================== products
class ProductGroup(Base):
    __tablename__ = "md_product_group"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    company_id: Mapped[int | None] = mapped_column("CompanyId", ForeignKey("md_company.Id"))
    legacy_id: Mapped[int | None] = _legacy()
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_pg_code"),)


class ProductReporting(Base):
    """A reporting line for a year, with its priority flag: P1, P2 or X (others)."""
    __tablename__ = "md_product_reporting"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    year_id: Mapped[int] = mapped_column("YearId", ForeignKey("md_year.Id"), nullable=False)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    flag: Mapped[str] = mapped_column("Flag", String(2), nullable=False)
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("YearId", "Code", name="uq_pr_year_code"),)


class ProductReportingSku(Base):
    """A SKU rolls up to exactly one reporting line in a given year. YearId is
    copied from the reporting line so that rule can be a unique key."""
    __tablename__ = "md_product_reporting_sku"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    product_reporting_id: Mapped[int] = mapped_column(
        "ProductReportingId", ForeignKey("md_product_reporting.Id"), nullable=False)
    sku_id: Mapped[int] = mapped_column("SkuId", ForeignKey("PRODUCT_MASTER.PRODUCT_ID"), nullable=False)
    year_id: Mapped[int] = mapped_column("YearId", ForeignKey("md_year.Id"), nullable=False)
    __table_args__ = (UniqueConstraint("YearId", "SkuId", name="uq_prs_year_sku"),)


# ================================================================= people
class Designation(Base):
    __tablename__ = "md_designation"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name(80)
    level: Mapped[int] = mapped_column("Level", Integer, nullable=False, default=1)
    legacy_id: Mapped[int | None] = _legacy()
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_designation_code"),)


class Role(Base):
    __tablename__ = "md_role"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name(80)
    description: Mapped[str | None] = mapped_column("Description", String(300))
    legacy_id: Mapped[int | None] = _legacy()
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_role_code"),)


class Team(Base):
    __tablename__ = "md_team"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name(80)
    company_id: Mapped[int | None] = mapped_column("CompanyId", ForeignKey("md_company.Id"))
    legacy_id: Mapped[int | None] = _legacy()
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_team_code"),)


class TeamProductGroup(Base):
    __tablename__ = "md_team_product_group"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    year_id: Mapped[int] = mapped_column("YearId", ForeignKey("md_year.Id"), nullable=False)
    team_id: Mapped[int] = mapped_column("TeamId", ForeignKey("md_team.Id"), nullable=False)
    product_group_id: Mapped[int] = mapped_column(
        "ProductGroupId", ForeignKey("md_product_group.Id"), nullable=False)
    __table_args__ = (UniqueConstraint("YearId", "TeamId", "ProductGroupId", name="uq_tpg"),)


class TeamHeadquarter(Base):
    __tablename__ = "md_team_headquarter"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    year_id: Mapped[int] = mapped_column("YearId", ForeignKey("md_year.Id"), nullable=False)
    team_id: Mapped[int] = mapped_column("TeamId", ForeignKey("md_team.Id"), nullable=False)
    headquarter_id: Mapped[int] = mapped_column(
        "HeadquarterId", ForeignKey("md_headquarter.Id"), nullable=False)
    __table_args__ = (UniqueConstraint("YearId", "TeamId", "HeadquarterId", name="uq_thq"),)


# ============================================== the tables of MASTER DATA & TABLES.xlsx
# Table and column names are the workbook's own. The Id column is the
# workbook's id (CUSTOMER_ID ...), kept as uploaded, so a second upload updates
# the same rows. STATUS is mapped to `active` so every screen treats it alike.
CUSTOMER_ALIASES = 50
PRODUCT_ALIASES = 100


def _alias_cols(cls_ns: dict, prefix: str, n: int, width: int):
    for i in range(1, n + 1):
        cls_ns[f"alias_{i}"] = mapped_column(f"{prefix}{i}", String(width))


class CustomerMaster(Base):
    __tablename__ = "CUSTOMER_MASTER"
    id: Mapped[int] = mapped_column("CUSTOMER_ID", Integer, primary_key=True, autoincrement=True)
    customer_name: Mapped[str] = mapped_column("CUSTOMER_NAME", String(200), nullable=False)
    customer_sap_id: Mapped[str | None] = mapped_column("CUSTOMER_SAP_ID", String(50))
    zone_id: Mapped[int | None] = mapped_column("ZONE_ID", Integer)
    hq_id: Mapped[int | None] = mapped_column("HQ_ID", Integer)
    territory_id: Mapped[int | None] = mapped_column("TERRITORY_ID", Integer)
    sub_territory_id: Mapped[int | None] = mapped_column("SUB_TERRITORY_ID", Integer)
    customer_billing_name: Mapped[str | None] = mapped_column("CUSTOMER_BILLING_NAME", String(200))
    state_id: Mapped[int | None] = mapped_column("STATE_ID", Integer)
    cust_classification_id: Mapped[int | None] = mapped_column("CUST_CLASSIFICATION_ID", Integer)
    cust_remark_id: Mapped[int | None] = mapped_column("CUST_REMARK_ID", Integer)
    _alias_cols(locals(), "CUSTOMER_ALIAS_", CUSTOMER_ALIASES, 200)
    start_date: Mapped[date | None] = mapped_column("START_DATE", Date)
    end_date: Mapped[date | None] = mapped_column("END_DATE", Date)
    active: Mapped[int] = mapped_column("STATUS", Integer, nullable=False, default=1)
    __table_args__ = (Index("ix_customer_master_name", "CUSTOMER_NAME"),)


class EmployeeMaster(Base):
    """EMPLOYEE_MASTER without its PASSWORD column: passwords are never stored
    here (the upload reads past it)."""
    __tablename__ = "EMPLOYEE_MASTER"
    id: Mapped[int] = mapped_column("EMPLOYEE_ID", Integer, primary_key=True, autoincrement=True)
    employee_ft_nm: Mapped[str] = mapped_column("EMPLOYEE_FT_NM", String(80), nullable=False)
    employee_lt_nm: Mapped[str | None] = mapped_column("EMPLOYEE_LT_NM", String(80))
    email: Mapped[str | None] = mapped_column("EMAIL", String(120))
    active: Mapped[int] = mapped_column("STATUS", Integer, nullable=False, default=1)
    role_id: Mapped[int | None] = mapped_column("ROLE_ID", Integer)
    designation_id: Mapped[int | None] = mapped_column("DESIGNATION_ID", Integer)
    start_date: Mapped[date | None] = mapped_column("START_DATE", Date)
    end_date: Mapped[date | None] = mapped_column("END_DATE", Date)
    team: Mapped[str | None] = mapped_column("TEAM", String(80))
    reporting_manager_id: Mapped[int | None] = mapped_column("REPORTING_MANAGER_ID", Integer)
    rd_cs_editable: Mapped[int] = mapped_column("RD_CS_EDITABLE", Integer, nullable=False, default=0)
    employee_code: Mapped[str | None] = mapped_column("EMPLOYEE_CODE", String(30))
    territory_code: Mapped[str | None] = mapped_column("TERRITORY_CODE", String(30))

    @property
    def name(self) -> str:
        return " ".join(x for x in (self.employee_ft_nm, self.employee_lt_nm) if x)


class ProductMasterBrand(Base):
    __tablename__ = "PRODUCT_MASTER_BRAND"
    id: Mapped[int] = mapped_column("PRODUCT_BRAND_ID", Integer, primary_key=True, autoincrement=True)
    product_brand_name: Mapped[str] = mapped_column("PRODUCT_BRAND_NAME", String(120), nullable=False)
    product_group_id: Mapped[int | None] = mapped_column("PRODUCT_GROUP_ID", Integer)
    start_date: Mapped[date | None] = mapped_column("START_DATE", Date)
    end_date: Mapped[date | None] = mapped_column("END_DATE", Date)
    active: Mapped[int] = mapped_column("STATUS", Integer, nullable=False, default=1)
    reporting: Mapped[str | None] = mapped_column("REPORTING", String(30))
    team_id: Mapped[int | None] = mapped_column("TEAM_ID", Integer)
    nrv: Mapped[str | None] = mapped_column("NRV", String(30))
    no_of_sku: Mapped[int | None] = mapped_column("NO_OF_SKU", Integer)


class ProductMaster(Base):
    __tablename__ = "PRODUCT_MASTER"
    id: Mapped[int] = mapped_column("PRODUCT_ID", Integer, primary_key=True, autoincrement=True)
    sap_product_name: Mapped[str] = mapped_column("SAP_PRODUCT_NAME", String(250), nullable=False)
    _alias_cols(locals(), "PRODUCT_ALIAS_", PRODUCT_ALIASES, 250)
    product_brand_id: Mapped[int | None] = mapped_column("PRODUCT_BRAND_ID", Integer, index=True)
    product_group_id: Mapped[int | None] = mapped_column("PRODUCT_GROUP_ID", Integer)
    sap_product_id: Mapped[str | None] = mapped_column("SAP_PRODUCT_ID", String(30))
    nrv: Mapped[float | None] = mapped_column("NRV", Numeric(18, 4))
    start_date: Mapped[date | None] = mapped_column("START_DATE", Date)
    end_date: Mapped[date | None] = mapped_column("END_DATE", Date)
    active: Mapped[int] = mapped_column("STATUS", Integer, nullable=False, default=1)
    material_code: Mapped[str | None] = mapped_column("MATERIAL_CODE", String(50))


# ============================================================ alignment
class CustomerAssignment(Base):
    """One customer, one SKU, one year: which territory and team cover it.

    ProductGroupId is stored, not only derivable, so the rows can be filtered
    and summed by group without a three-table join; it is checked against the
    SKU's own group on every save.
    """
    __tablename__ = "md_customer_assignment"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    year_id: Mapped[int] = mapped_column("YearId", ForeignKey("md_year.Id"), nullable=False)
    customer_id: Mapped[int] = mapped_column("CustomerId", ForeignKey("CUSTOMER_MASTER.CUSTOMER_ID"), nullable=False)
    territory_id: Mapped[int] = mapped_column("TerritoryId", ForeignKey("md_territory.Id"), nullable=False)
    team_id: Mapped[int] = mapped_column("TeamId", ForeignKey("md_team.Id"), nullable=False)
    product_group_id: Mapped[int] = mapped_column(
        "ProductGroupId", ForeignKey("md_product_group.Id"), nullable=False)
    sku_id: Mapped[int] = mapped_column("SkuId", ForeignKey("PRODUCT_MASTER.PRODUCT_ID"), nullable=False)
    __table_args__ = (UniqueConstraint("YearId", "CustomerId", "SkuId", name="uq_ca_year_cust_sku"),
                      Index("ix_ca_territory", "YearId", "TerritoryId"))


class EmployeeAssignment(Base):
    """One employee, one territory, one SKU, one year."""
    __tablename__ = "md_employee_assignment"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    year_id: Mapped[int] = mapped_column("YearId", ForeignKey("md_year.Id"), nullable=False)
    employee_id: Mapped[int] = mapped_column("EmployeeId", ForeignKey("EMPLOYEE_MASTER.EMPLOYEE_ID"), nullable=False)
    territory_id: Mapped[int] = mapped_column("TerritoryId", ForeignKey("md_territory.Id"), nullable=False)
    product_group_id: Mapped[int] = mapped_column(
        "ProductGroupId", ForeignKey("md_product_group.Id"), nullable=False)
    sku_id: Mapped[int] = mapped_column("SkuId", ForeignKey("PRODUCT_MASTER.PRODUCT_ID"), nullable=False)
    __table_args__ = (UniqueConstraint("YearId", "EmployeeId", "TerritoryId", "SkuId",
                                       name="uq_ea_year_emp_terr_sku"),
                      Index("ix_ea_territory", "YearId", "TerritoryId"))
