"""A run of the Nepal Analyzer: the month's actuals calculated (as Budgeting ›
Calculate Actuals does), the workbook made, kept on the job, and emailed with
the workbook attached.

A conversion starts one by itself when Analyzer Email says so (and Convert
did not untick it): actuals and workbook, emailed only if "Email it after
every conversion" is on (it is off: the one email of the month goes by Send
Mail once every distributor is converted). Send Mail (batch page, Nepal
Analyzer, Reports › Send Mail) starts one by hand for any month and year. Runs go one at
a time (two conversions in a row would otherwise calculate the same month at
once). The conversion is never held up or undone by its run: a run that fails
says why on the batch and on Analyzer Email, and can be sent again.
"""
from __future__ import annotations

import html
import json
import threading
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models_report as R
from ..services import mailer, secret_box
from . import nepal_analyzer as NA

LOCK = threading.Lock()


# ------------------------------------------------------------------ settings
def settings(db: Session) -> R.ReportMailSettings:
    s = db.get(R.ReportMailSettings, 1)
    if s is None:
        s = R.ReportMailSettings(id=1, auto_on_convert=1, calculate_first=1, send_mail=1, mail_on_convert=0,
                                 download_after=1,
                                 recipients=R.DEFAULT_TO, subject=R.DEFAULT_SUBJECT, security="starttls",
                                 auth="password", from_name="Distributor Sales")
        db.add(s)
        db.flush()
    return s


def smtp_config(s: R.ReportMailSettings) -> dict:
    return {"smtp_host": s.smtp_host, "smtp_port": s.smtp_port, "security": s.security, "auth": s.auth,
            "username": s.username, "password": secret_box.open_(s.password_enc),
            "from_address": s.from_address, "from_name": s.from_name, "tenant_id": s.tenant_id,
            "client_id": s.client_id, "client_secret": secret_box.open_(s.client_secret_enc)}


# ---------------------------------------------------------------------- jobs
def out(j: R.ReportJob) -> dict:
    return {"id": j.id, "created_at": j.created_at.isoformat(timespec="seconds"),
            "finished_at": j.finished_at.isoformat(timespec="seconds") if j.finished_at else None,
            "trigger": j.trigger, "created_by": j.created_by, "batch_id": j.batch_id,
            "distributor": j.distributor, "month": j.month, "year": j.year, "calculate": bool(j.calculate),
            "send": bool(j.send), "recipients": j.recipients, "cc": j.cc, "status": j.status, "step": j.step,
            "log": (j.log or "").splitlines(), "error": j.error, "file_name": j.file_name,
            "has_file": j.file_data is not None, "mail_status": j.mail_status, "mail_detail": j.mail_detail,
            "sent_at": j.sent_at.isoformat(timespec="seconds") if j.sent_at else None}


def create(db: Session, *, trigger: str, month: str, year: int, calculate: bool, send: bool,
           recipients: str | None = None, cc: str | None = None, batch=None, who: str | None = None
           ) -> R.ReportJob:
    s = settings(db)
    to = recipients if recipients is not None else s.recipients
    if send:
        if not mailer.addresses(to):
            raise mailer.MailError("Give at least one address to send the report to.")
        mailer.addresses(cc if cc is not None else s.cc)                     # checked now, not at sending
    j = R.ReportJob(created_at=datetime.now(), trigger=trigger, created_by=who, month=month, year=int(year),
                    calculate=int(bool(calculate)), send=int(bool(send)), recipients=to,
                    cc=cc if cc is not None else s.cc, status="queued", step="Waiting to start",
                    batch_id=batch.id if batch is not None else None,
                    distributor=batch.distributor.name if batch is not None else None)
    db.add(j)
    db.flush()
    return j


def after_convert(db: Session, batch, month: str, year: int, wanted: dict | None, who: str | None):
    """The run a conversion asks for, or None. Never raises: a conversion is
    not undone over its email."""
    try:
        s = settings(db)
        wanted = wanted or {}
        on = wanted.get("enabled", bool(s.auto_on_convert))
        if not on:
            db.commit()
            return None
        j = create(db, trigger="convert", month=month, year=year,
                   calculate=wanted.get("calculate", bool(s.calculate_first)),
                   send=wanted.get("send", bool(s.mail_on_convert)), batch=batch, who=who)
        db.commit()
        return j
    except Exception as e:                           # noqa: BLE001
        db.rollback()
        print(f"[analyzer] could not start the run after batch {batch.id}: {e}", flush=True)
        return None


def _note(db: Session, j: R.ReportJob, step: str, line: str | None = None):
    j.step = step
    if line:
        j.log = ((j.log + "\n") if j.log else "") + f"{datetime.now():%H:%M:%S}  {line}"
    db.commit()


def run(session_factory, job_id: int):
    """Do the run (in the background, after the response)."""
    with LOCK:
        db: Session = session_factory()
        try:
            _run(db, db.get(R.ReportJob, job_id))
        finally:
            db.close()


def _run(db: Session, j: R.ReportJob):
    from ..routers.budget import calculate_actuals            # here: the routers import this module
    j.status = "running"
    _note(db, j, "Starting", f"{j.month} {j.year}"
          + (f", after batch {j.batch_id} ({j.distributor})" if j.batch_id else ", started by hand"))
    try:
        if j.calculate:
            _note(db, j, "Calculating actuals")
            try:
                r = calculate_actuals({"year": j.year, "month": j.month}, db)
            except HTTPException as e:
                raise RuntimeError(f"Calculate Actuals: {e.detail}") from e
            _note(db, j, "Actuals calculated", r["message"])
        _note(db, j, "Making the workbook")
        sheets = NA.build(db, j.month, j.year)
        j.file_name = NA.file_name(j.month, j.year)
        j.file_data = NA.workbook(sheets)
        summary = summarise(sheets, j.month)
        j.summary = json.dumps(summary)
        _note(db, j, "Workbook made", f"{j.file_name}, {len(j.file_data) // 1024} KB. " + summary["line"])
    except Exception as e:                                      # noqa: BLE001
        db.rollback()
        j.status, j.error, j.finished_at = "failed", str(e), datetime.now()
        j.mail_status = "not sent" if j.send else None
        _note(db, j, "Failed", f"Stopped: {e}")
        return
    if j.send:
        deliver(db, j, summary)
    j.status = "done" if j.mail_status in (None, "sent") else "failed"
    j.finished_at = datetime.now()
    _note(db, j, "Done" if j.status == "done" else "Mail not sent")


def deliver(db: Session, j: R.ReportJob, summary: dict | None = None):
    """Email the job's workbook to its recipients."""
    s = settings(db)
    _note(db, j, "Sending the email")
    try:
        to, cc = mailer.addresses(j.recipients), mailer.addresses(j.cc)
        if not to:
            raise mailer.MailError("No address to send to.")
        if summary is None:
            summary = json.loads(j.summary) if j.summary else {"line": "", "html": "", "text": ""}
        subject = (s.subject or R.DEFAULT_SUBJECT).format(month=j.month, year=j.year,
                                                          distributor=j.distributor or "")
        msg = mailer.build(smtp_config(s), to, cc, subject, body_text(j, summary), body_html(j, summary),
                           [(j.file_name, j.file_data)])
        said = mailer.send(smtp_config(s), msg)
        j.mail_status, j.sent_at = "sent", datetime.now()
        j.mail_detail = f"Sent to {', '.join(to + cc)} ({said})."
        _note(db, j, "Email sent", j.mail_detail)
    except (mailer.MailError, KeyError, ValueError) as e:
        j.mail_status, j.mail_detail = "failed", str(e)
        _note(db, j, "Email failed", f"Email not sent: {e}")


def resend(session_factory, job_id: int):
    with LOCK:
        db: Session = session_factory()
        try:
            j = db.get(R.ReportJob, job_id)
            deliver(db, j)
            j.status = "done" if j.mail_status == "sent" else "failed"
            j.finished_at = datetime.now()
            _note(db, j, "Done" if j.status == "done" else "Mail not sent")
        finally:
            db.close()


# ------------------------------------------------------------------ the email
def summarise(sheets: list, month: str) -> dict:
    """The month at a glance, for the body of the email."""
    by = {s.name: s for s in sheets}
    nl = by["NEPAL LEVEL"]
    r = dict(zip(nl.columns, nl.rows[NA.MONTHS.index(month)]))
    fmt = lambda v: "—" if v is None else f"{v:,.2f}"            # noqa: E731
    head = [("Month target (INR lakh)", fmt(r["MONTH TARGET"])), ("Month sale (INR lakh)", fmt(r["MONTH SALE"])),
            ("Month % ach", fmt(r["MONTH % ACH"])), ("YTD target", fmt(r["YTD TARGET"])),
            ("YTD sale", fmt(r["YTD SALE"])), ("YTD % ach", fmt(r["YTD % ACH"]))]
    dl = by["DISTRIBUTOR LEVEL"]
    dists = [dict(zip(dl.columns, x)) for x in dl.rows]
    hq = by["HQ LEVEL"]
    divs = [dict(zip(hq.columns, x)) for x, k in zip(hq.rows, hq.kinds) if k]
    m = month
    line = f"{month}: sale {fmt(r['MONTH SALE'])} lakh against {fmt(r['MONTH TARGET'])} ({fmt(r['MONTH % ACH'])} %)."
    text = "\n".join(f"  {a}: {b}" for a, b in head)
    text += "\n\nDistributors (INR lakh):\n" + "\n".join(
        f"  {d['DISTRIBUTOR NAME']}: {fmt(d['SALES VALUE(INR)'])}" for d in dists)
    td = 'style="padding:4px 10px;border:1px solid #d0d7de"'
    th = 'style="padding:4px 10px;border:1px solid #d0d7de;background:#89CFF0;text-align:left"'

    def table(heads, rows):
        return ('<table style="border-collapse:collapse;font:13px Georgia,serif;margin:6px 0 14px">'
                + "<tr>" + "".join(f"<th {th}>{html.escape(h)}</th>" for h in heads) + "</tr>"
                + "".join("<tr>" + "".join(f"<td {td}>{html.escape(str(c))}</td>" for c in row) + "</tr>"
                          for row in rows) + "</table>")
    body = (table([a for a, _ in head], [[b for _, b in head]])
            + "<b>Distributors</b>" + table(["Distributor", "Sales (INR lakh)", "Sales (NPR lakh)"],
                                            [[d["DISTRIBUTOR NAME"], fmt(d["SALES VALUE(INR)"]),
                                              fmt(d["SALES VALUE(NPR)"])] for d in dists])
            + "<b>Divisions</b>" + table(["Division", f"{m} target", f"{m} sale", f"{m} % ach",
                                          "YTD target", "YTD sale", "YTD % ach"],
                                         [[d["DIVISION"], fmt(d[f"{m} TARGET(INR)"]),
                                           fmt(d[f"{m} ACTUAL SALE(INR)"]), fmt(d[f"{m} % ACH"]),
                                           fmt(d["YTD TARGET(INR)"]), fmt(d["YTD ACTUAL SALE(INR)"]),
                                           fmt(d["YTD % ACH"])] for d in divs]))
    return {"line": line, "text": text, "html": body}


def _why(j: R.ReportJob) -> str:
    if j.batch_id:
        return f"made after converting batch {j.batch_id} ({j.distributor})"
    return "sent from the Nepal Analyzer page"


def body_text(j: R.ReportJob, summary: dict) -> str:
    return (f"Nepal Analyzer Report for {j.month} {j.year}, {_why(j)}.\n"
            + ("The month's actuals were calculated first.\n" if j.calculate else "")
            + (f"\n{summary['text']}\n" if summary.get("text") else "")
            + f"\nThe full report is attached: {j.file_name}.\n\n— Distributor Sales")


def body_html(j: R.ReportJob, summary: dict) -> str:
    return (f'<div style="font:14px Georgia,serif;color:#1f2933">'
            f"<p>Nepal Analyzer Report for <b>{html.escape(j.month)} {j.year}</b>, {html.escape(_why(j))}."
            + (" The month's actuals were calculated first." if j.calculate else "") + "</p>"
            + summary.get("html", "")
            + f"<p>The full report is attached: <b>{html.escape(j.file_name or '')}</b>.</p>"
            "<p style=\"color:#6b7280\">— Distributor Sales</p></div>")


def stop_unfinished(db: Session) -> int:
    """At startup: a run the server was in the middle of when it stopped will
    never finish; say so, so it can be started or sent again."""
    n = 0
    for j in db.execute(select(R.ReportJob).where(R.ReportJob.status.in_(["queued", "running"]))).scalars():
        j.status, j.finished_at = "failed", datetime.now()
        j.error = j.error or ("The server restarted during this run." if j.file_data is None else None)
        if j.send and j.mail_status not in ("sent",):
            j.mail_status = j.mail_status or "not sent"
            j.mail_detail = j.mail_detail or "The server restarted before the email went: use Send."
        j.log = ((j.log + "\n") if j.log else "") + f"{datetime.now():%H:%M:%S}  Stopped: the server restarted."
        n += 1
    db.commit()
    return n


def month_status(db: Session, month: str | None, year: int | None) -> dict:
    """For Send Mail: each active distributor's conversion of the month (its
    rows in MAPPING_MASTER and MAPPING_MASTER_MID, its latest batch), and the
    month's last email. With no month given, the month of the latest batch."""
    from sqlalchemy import func
    from .. import models as M, models_master as X
    if not month or not year:
        last = db.execute(select(M.Batch).order_by(M.Batch.id.desc()).limit(1)).scalars().first()
        if last is None:
            return {"month": None, "year": None, "distributors": [], "all_converted": False, "last_mail": None}
        month, year = last.month_name, last.year
    month = month.strip().title()
    rows = {}
    for T, k in ((X.SalesMapping, "rows"), (X.MidSalesMapping, "mid_rows")):
        for name, n in db.execute(select(T.dist_name, func.count()).where(T.year == year, T.month == month)
                                  .group_by(T.dist_name)):
            rows.setdefault((name or "").strip().casefold(), {"rows": 0, "mid_rows": 0})[k] += n
    out = []
    for d in db.execute(select(M.Distributor).where(M.Distributor.active == 1).order_by(M.Distributor.name)).scalars():
        b = db.execute(select(M.Batch).where(M.Batch.distributor_id == d.id, M.Batch.year == year,
                                             func.lower(M.Batch.month_name) == month.lower())
                       .order_by(M.Batch.id.desc()).limit(1)).scalars().first()
        r = rows.get(d.name.strip().casefold(), {"rows": 0, "mid_rows": 0})
        out.append({"id": d.id, "name": d.name, **r, "converted": r["rows"] > 0,
                    "last_batch": {"id": b.id, "as_of": b.as_of.isoformat(), "mid_month": b.mid_month,
                                   "rows": b.row_count} if b else None})
    sent = db.execute(select(R.ReportJob).where(R.ReportJob.year == year, R.ReportJob.month == month,
                                                R.ReportJob.mail_status == "sent")
                      .order_by(R.ReportJob.id.desc()).limit(1)).scalars().first()
    return {"month": month, "year": year, "distributors": out,
            "all_converted": bool(out) and all(x["converted"] for x in out),
            "last_mail": {"id": sent.id, "sent_at": sent.sent_at.isoformat(timespec="seconds"),
                          "recipients": sent.recipients} if sent else None}


def latest(db: Session, batch_id: int | None = None, limit: int = 30) -> list[R.ReportJob]:
    q = select(R.ReportJob).order_by(R.ReportJob.id.desc()).limit(limit)
    if batch_id is not None:
        q = q.where(R.ReportJob.batch_id == batch_id)
    return list(db.execute(q).scalars())
