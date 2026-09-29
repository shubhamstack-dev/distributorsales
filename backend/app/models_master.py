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
tables.
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
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_zone_code"),)


class Headquarter(Base):
    __tablename__ = "md_headquarter"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    zone_id: Mapped[int] = mapped_column("ZoneId", ForeignKey("md_zone.Id"), nullable=False)
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_hq_code"),)


class Territory(Base):
    __tablename__ = "md_territory"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    headquarter_id: Mapped[int] = mapped_column(
        "HeadquarterId", ForeignKey("md_headquarter.Id"), nullable=False)
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_territory_code"),)


# =============================================================== products
class ProductGroup(Base):
    __tablename__ = "md_product_group"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    company_id: Mapped[int | None] = mapped_column("CompanyId", ForeignKey("md_company.Id"))
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_pg_code"),)


class Brand(Base):
    __tablename__ = "md_brand"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    product_group_id: Mapped[int] = mapped_column(
        "ProductGroupId", ForeignKey("md_product_group.Id"), nullable=False)
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_brand_code"),)


class Sku(Base):
    __tablename__ = "md_sku"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name(200)
    brand_id: Mapped[int] = mapped_column("BrandId", ForeignKey("md_brand.Id"), nullable=False)
    pack_size: Mapped[str | None] = mapped_column("PackSize", String(40))
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_sku_code"),)


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
    sku_id: Mapped[int] = mapped_column("SkuId", ForeignKey("md_sku.Id"), nullable=False)
    year_id: Mapped[int] = mapped_column("YearId", ForeignKey("md_year.Id"), nullable=False)
    __table_args__ = (UniqueConstraint("YearId", "SkuId", name="uq_prs_year_sku"),)


# ============================================================== customers
class Customer(Base):
    __tablename__ = "md_customer"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column("CustomerCode", String(30), nullable=False)
    name: Mapped[str] = _name(200)
    classification: Mapped[str] = mapped_column("Classification", String(40), nullable=False)
    city: Mapped[str | None] = mapped_column("City", String(80))
    country_id: Mapped[int | None] = mapped_column("CountryId", ForeignKey("md_country.Id"))
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("CustomerCode", name="uq_customer_code"),)


# ================================================================= people
class Designation(Base):
    __tablename__ = "md_designation"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name(80)
    level: Mapped[int] = mapped_column("Level", Integer, nullable=False, default=1)
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_designation_code"),)


class Role(Base):
    __tablename__ = "md_role"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name(80)
    description: Mapped[str | None] = mapped_column("Description", String(300))
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_role_code"),)


class Team(Base):
    __tablename__ = "md_team"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name(80)
    company_id: Mapped[int | None] = mapped_column("CompanyId", ForeignKey("md_company.Id"))
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


class Employee(Base):
    __tablename__ = "md_employee"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = _code()
    name: Mapped[str] = _name()
    designation_id: Mapped[int] = mapped_column(
        "DesignationId", ForeignKey("md_designation.Id"), nullable=False)
    role_id: Mapped[int | None] = mapped_column("RoleId", ForeignKey("md_role.Id"))
    team_id: Mapped[int | None] = mapped_column("TeamId", ForeignKey("md_team.Id"))
    headquarter_id: Mapped[int | None] = mapped_column("HeadquarterId", ForeignKey("md_headquarter.Id"))
    reports_to_id: Mapped[int | None] = mapped_column("ReportsToId", ForeignKey("md_employee.Id"))
    email: Mapped[str | None] = mapped_column("Email", String(120))
    phone: Mapped[str | None] = mapped_column("Phone", String(30))
    joining_date: Mapped[date | None] = mapped_column("JoiningDate", Date)
    active: Mapped[int] = _active()
    __table_args__ = (UniqueConstraint("Code", name="uq_employee_code"),)


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
    customer_id: Mapped[int] = mapped_column("CustomerId", ForeignKey("md_customer.Id"), nullable=False)
    territory_id: Mapped[int] = mapped_column("TerritoryId", ForeignKey("md_territory.Id"), nullable=False)
    team_id: Mapped[int] = mapped_column("TeamId", ForeignKey("md_team.Id"), nullable=False)
    product_group_id: Mapped[int] = mapped_column(
        "ProductGroupId", ForeignKey("md_product_group.Id"), nullable=False)
    sku_id: Mapped[int] = mapped_column("SkuId", ForeignKey("md_sku.Id"), nullable=False)
    __table_args__ = (UniqueConstraint("YearId", "CustomerId", "SkuId", name="uq_ca_year_cust_sku"),
                      Index("ix_ca_territory", "YearId", "TerritoryId"))


class EmployeeAssignment(Base):
    """One employee, one territory, one SKU, one year."""
    __tablename__ = "md_employee_assignment"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    year_id: Mapped[int] = mapped_column("YearId", ForeignKey("md_year.Id"), nullable=False)
    employee_id: Mapped[int] = mapped_column("EmployeeId", ForeignKey("md_employee.Id"), nullable=False)
    territory_id: Mapped[int] = mapped_column("TerritoryId", ForeignKey("md_territory.Id"), nullable=False)
    product_group_id: Mapped[int] = mapped_column(
        "ProductGroupId", ForeignKey("md_product_group.Id"), nullable=False)
    sku_id: Mapped[int] = mapped_column("SkuId", ForeignKey("md_sku.Id"), nullable=False)
    __table_args__ = (UniqueConstraint("YearId", "EmployeeId", "TerritoryId", "SkuId",
                                       name="uq_ea_year_emp_terr_sku"),
                      Index("ix_ea_territory", "YearId", "TerritoryId"))
