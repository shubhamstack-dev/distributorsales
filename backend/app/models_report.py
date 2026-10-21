"""The Nepal Analyzer's email: where it is sent from and to (one row), and every
run of the analyzer — after a conversion or by hand — with its file and what
became of its email."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

DEFAULT_TO = "181296shubham@gmail.com"
DEFAULT_SUBJECT = "Nepal Analyzer Report — {month} {year}"


class ReportMailSettings(Base):
    """One row. Passwords and the client secret are kept encrypted with the
    server's SECRET_KEY (services/secret_box.py)."""
    __tablename__ = "report_mail_settings"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True)
    # after a conversion
    auto_on_convert: Mapped[int] = mapped_column("AutoOnConvert", Integer, nullable=False, default=1)
    calculate_first: Mapped[int] = mapped_column("CalculateFirst", Integer, nullable=False, default=1)
    send_mail: Mapped[int] = mapped_column("SendMail", Integer, nullable=False, default=1)
    download_after: Mapped[int] = mapped_column("DownloadAfter", Integer, nullable=False, default=1)
    # the email
    recipients: Mapped[str | None] = mapped_column("Recipients", Text)
    cc: Mapped[str | None] = mapped_column("Cc", Text)
    subject: Mapped[str | None] = mapped_column("Subject", String(250))
    # sending
    smtp_host: Mapped[str | None] = mapped_column("SmtpHost", String(200))
    smtp_port: Mapped[int | None] = mapped_column("SmtpPort", Integer)
    security: Mapped[str] = mapped_column("Security", String(20), nullable=False, default="starttls")
    auth: Mapped[str] = mapped_column("Auth", String(20), nullable=False, default="password")
    username: Mapped[str | None] = mapped_column("Username", String(200))
    password_enc: Mapped[str | None] = mapped_column("PasswordEnc", Text)
    from_address: Mapped[str | None] = mapped_column("FromAddress", String(200))
    from_name: Mapped[str | None] = mapped_column("FromName", String(120))
    tenant_id: Mapped[str | None] = mapped_column("TenantId", String(80))
    client_id: Mapped[str | None] = mapped_column("ClientId", String(80))
    client_secret_enc: Mapped[str | None] = mapped_column("ClientSecretEnc", Text)
    updated_at: Mapped[datetime | None] = mapped_column("UpdatedAt", DateTime)


class ReportJob(Base):
    """One run: calculate the month's actuals (if asked), make the workbook,
    email it (if asked). The workbook is kept, so it can be downloaded or sent
    again later."""
    __tablename__ = "report_job"
    id: Mapped[int] = mapped_column("Id", Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column("FinishedAt", DateTime)
    trigger: Mapped[str] = mapped_column("Trigger", String(20), nullable=False)        # convert | manual
    created_by: Mapped[str | None] = mapped_column("CreatedBy", String(80))
    batch_id: Mapped[int | None] = mapped_column("BatchId", Integer, index=True)
    distributor: Mapped[str | None] = mapped_column("Distributor", String(120))
    month: Mapped[str] = mapped_column("Month", String(20), nullable=False)
    year: Mapped[int] = mapped_column("Year", Integer, nullable=False)
    calculate: Mapped[int] = mapped_column("Calculate", Integer, nullable=False, default=1)
    send: Mapped[int] = mapped_column("Send", Integer, nullable=False, default=1)
    recipients: Mapped[str | None] = mapped_column("Recipients", Text)
    cc: Mapped[str | None] = mapped_column("Cc", Text)
    status: Mapped[str] = mapped_column("Status", String(20), nullable=False, default="queued")
    step: Mapped[str | None] = mapped_column("Step", String(60))
    log: Mapped[str | None] = mapped_column("Log", Text)                 # one line per step
    error: Mapped[str | None] = mapped_column("Error", Text)
    file_name: Mapped[str | None] = mapped_column("FileName", String(120))
    file_data: Mapped[bytes | None] = mapped_column(
        "FileData", LargeBinary().with_variant(mysql.LONGBLOB(), "mysql", "mariadb"))
    summary: Mapped[str | None] = mapped_column("Summary", Text)        # JSON: the email's tables
    mail_status: Mapped[str | None] = mapped_column("MailStatus", String(20))   # sent | failed | not sent
    mail_detail: Mapped[str | None] = mapped_column("MailDetail", Text)
    sent_at: Mapped[datetime | None] = mapped_column("SentAt", DateTime)
