"""The tables. Column names are explicit so the SQL in schema.sql matches."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Distributor(Base):
    """A distributor and the rules its files are read under.

    The rules are data, not code: the three distributors send different shapes
    of file and are governed by different cut-offs, and a rule buried in a
    function is a rule nobody can correct without a deployment.
    """
    __tablename__ = "distributor"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column("Name", String(60), nullable=False, unique=True)
    cutoff_day: Mapped[int] = mapped_column("CutoffDay", Integer, nullable=False, default=15)
    invoice_mode: Mapped[str] = mapped_column("InvoiceMode", String(10), nullable=False, default="seq")
    negate_returns: Mapped[int] = mapped_column("NegateReturns", Integer, nullable=False, default=1)
    # A regular expression naming the files this distributor's rule asks for.
    pick_pattern: Mapped[str | None] = mapped_column("PickPattern", String(200))
    note: Mapped[str | None] = mapped_column("Note", String(500))
    active: Mapped[int] = mapped_column("Active", Integer, nullable=False, default=1)


class Batch(Base):
    """One conversion: the files chosen, the rules applied, the rows produced."""
    __tablename__ = "batch"
    __table_args__ = (Index("ix_batch_dist", "DistributorId", "CreatedAtUtc"),)
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    distributor_id: Mapped[int] = mapped_column(
        "DistributorId", ForeignKey("distributor.Id"), nullable=False)
    source_name: Mapped[str] = mapped_column("SourceName", String(255), nullable=False, default="")
    as_of: Mapped[date] = mapped_column("AsOf", Date, nullable=False)
    month_name: Mapped[str] = mapped_column("MonthName", String(12), nullable=False)
    year: Mapped[int] = mapped_column("Year", Integer, nullable=False)
    mid_month: Mapped[str] = mapped_column("MidMonth", String(1), nullable=False)
    cutoff_day: Mapped[int] = mapped_column("CutoffDay", Integer, nullable=False)
    invoice_mode: Mapped[str] = mapped_column("InvoiceMode", String(10), nullable=False)
    row_count: Mapped[int] = mapped_column("RowCount", Integer, nullable=False, default=0)
    omitted_count: Mapped[int] = mapped_column("OmittedCount", Integer, nullable=False, default=0)
    total_qty: Mapped[float] = mapped_column("TotalQty", Numeric(18, 3), nullable=False, default=0)
    total_amount: Mapped[float] = mapped_column("TotalAmount", Numeric(18, 2), nullable=False, default=0)
    created_by: Mapped[str] = mapped_column("CreatedBy", String(120), nullable=False, default="")
    created_at_utc: Mapped[datetime] = mapped_column("CreatedAtUtc", DateTime, nullable=False)
    notes: Mapped[str | None] = mapped_column("Notes", Text)

    distributor: Mapped[Distributor] = relationship()
    files: Mapped[list["BatchFile"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan")
    rows: Mapped[list["SalesRow"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan")


class BatchFile(Base):
    """Every workbook that was offered, and whether it was used.

    Kept for both outcomes on purpose: when a total looks wrong the first
    question is which files went in, and the second is which did not.
    """
    __tablename__ = "batch_file"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        "BatchId", ForeignKey("batch.Id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column("FileName", String(255), nullable=False)
    used: Mapped[int] = mapped_column("Used", Integer, nullable=False, default=0)
    layout: Mapped[str | None] = mapped_column("Layout", String(30))
    rows: Mapped[int] = mapped_column("Rows", Integer, nullable=False, default=0)
    omitted: Mapped[int] = mapped_column("Omitted", Integer, nullable=False, default=0)
    detail: Mapped[str | None] = mapped_column("Detail", String(500))

    batch: Mapped[Batch] = relationship(back_populates="files")


class SalesRow(Base):
    """One output row, exactly the twelve columns the sheet carries."""
    __tablename__ = "sales_row"
    __table_args__ = (UniqueConstraint("BatchId", "Seq", name="uq_row_seq"),
                      Index("ix_row_batch", "BatchId"))
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        "BatchId", ForeignKey("batch.Id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column("Seq", Integer, nullable=False)
    distributor_name: Mapped[str] = mapped_column("DistributorName", String(60), nullable=False)
    invoice_no: Mapped[str] = mapped_column("InvoiceNo", String(40), nullable=False)
    month_name: Mapped[str] = mapped_column("MonthName", String(12), nullable=False)
    year: Mapped[int] = mapped_column("Year", Integer, nullable=False)
    mid_month: Mapped[str] = mapped_column("MidMonth", String(1), nullable=False)
    customer_name: Mapped[str] = mapped_column("CustomerName", String(200), nullable=False)
    product_name: Mapped[str] = mapped_column("ProductName", String(200), nullable=False)
    quantity: Mapped[float] = mapped_column("Quantity", Numeric(18, 3), nullable=False, default=0)
    free_quantity: Mapped[float] = mapped_column("FreeQuantity", Numeric(18, 3), nullable=False, default=0)
    # Stored as well as derivable: the sheet has to reproduce byte for byte
    # later, and a rate recomputed from rounded money would drift.
    rate: Mapped[float] = mapped_column("Rate", Numeric(18, 6), nullable=False, default=0)
    b_amount: Mapped[float] = mapped_column("BAmount", Numeric(18, 2), nullable=False, default=0)
    amount: Mapped[float] = mapped_column("Amount", Numeric(18, 2), nullable=False, default=0)
    source_file: Mapped[str | None] = mapped_column("SourceFile", String(255))
    is_return: Mapped[int] = mapped_column("IsReturn", Integer, nullable=False, default=0)

    batch: Mapped[Batch] = relationship(back_populates="rows")
