"""Reports menu: the Nepal Analyzer, and its email.

    GET  /api/reports/nepal-analyzer?month=&year=      the workbook, made now
    POST /api/reports/analyzer-jobs                    a run by hand: {month, year, calculate,
                                                       send, recipients?, cc?}; runs after the reply
    GET  /api/reports/analyzer-jobs?batch_id=&limit=   the latest runs
    GET  /api/reports/analyzer-jobs/{id}               one run (polled while it runs)
    GET  /api/reports/analyzer-jobs/{id}/file          its workbook
    POST /api/reports/analyzer-jobs/{id}/send          email its workbook again {recipients?, cc?}
    GET  /api/reports/mail-settings                    Analyzer Email (no secrets in it)
    PUT  /api/reports/mail-settings                    save; an empty password keeps the one stored
    POST /api/reports/mail-settings/test               a test email {to}

A conversion starts a run itself (routers/api.py commit) when Analyzer Email
says so: calculate the month's actuals, make the workbook, email it.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, sessionmaker

from .. import models_report as R
from ..database import get_db
from ..reports import analyzer_job as AJ
from ..reports import nepal_analyzer as NA
from ..services import mailer, secret_box

router = APIRouter(prefix="/api/reports")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _month_year(month, year) -> tuple[str, int]:
    m = next((x for x in NA.MONTHS if x.lower() == str(month or "").strip().lower()), None)
    if not m:
        raise HTTPException(400, "Select the month.")
    try:
        y = int(year)
    except (TypeError, ValueError):
        raise HTTPException(400, "Select the year.")
    if not 2000 <= y <= 2100:
        raise HTTPException(400, "Select the year.")
    return m, y


def _xlsx(name: str, data: bytes) -> Response:
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/nepal-analyzer")
def nepal_analyzer(month: str = Query(""), year: str = Query(""), db: Session = Depends(get_db)):
    m, y = _month_year(month, year)
    return _xlsx(*NA.report(db, m, y))


# ----------------------------------------------------------------------- runs
def factory(db: Session):
    """Sessions on the same database for the run after the reply."""
    return sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)


@router.post("/analyzer-jobs")
def start(background: BackgroundTasks, body: dict = Body(...), db: Session = Depends(get_db)):
    m, y = _month_year(body.get("month"), body.get("year"))
    send = bool(body.get("send", True))
    try:
        j = AJ.create(db, trigger="manual", month=m, year=y, calculate=bool(body.get("calculate", True)),
                      send=send, recipients=body.get("recipients"), cc=body.get("cc"), who=body.get("who"))
    except mailer.MailError as e:
        db.rollback()
        raise HTTPException(422, str(e))
    db.commit()
    background.add_task(AJ.run, factory(db), j.id)
    return AJ.out(j)


@router.get("/analyzer-jobs")
def jobs(batch_id: int | None = None, limit: int = 30, db: Session = Depends(get_db)):
    return [AJ.out(j) for j in AJ.latest(db, batch_id, max(1, min(limit, 200)))]


def _job(db: Session, jid: int) -> R.ReportJob:
    j = db.get(R.ReportJob, jid)
    if not j:
        raise HTTPException(404, "No such run")
    return j


@router.get("/analyzer-jobs/{jid}")
def job(jid: int, db: Session = Depends(get_db)):
    return AJ.out(_job(db, jid))


@router.get("/analyzer-jobs/{jid}/file")
def job_file(jid: int, db: Session = Depends(get_db)):
    j = _job(db, jid)
    if j.file_data is None:
        raise HTTPException(404, "This run has no workbook" + (f": {j.error}" if j.error else " yet."))
    return _xlsx(j.file_name, j.file_data)


@router.post("/analyzer-jobs/{jid}/send")
def job_send(jid: int, background: BackgroundTasks, body: dict = Body(default={}),
             db: Session = Depends(get_db)):
    j = _job(db, jid)
    if j.file_data is None:
        raise HTTPException(409, "This run has no workbook to send.")
    if j.status in ("queued", "running"):
        raise HTTPException(409, "This run is still going.")
    try:
        if body.get("recipients") is not None:
            if not mailer.addresses(body["recipients"]):
                raise mailer.MailError("Give at least one address.")
            j.recipients = body["recipients"]
        if body.get("cc") is not None:
            mailer.addresses(body["cc"])
            j.cc = body["cc"]
    except mailer.MailError as e:
        raise HTTPException(422, str(e))
    j.send, j.status, j.step, j.mail_status = 1, "running", "Waiting to send", None
    db.commit()
    background.add_task(AJ.resend, factory(db), j.id)
    return AJ.out(j)


# ------------------------------------------------------------------- settings
FIELDS = ("auto_on_convert", "calculate_first", "send_mail", "download_after", "recipients", "cc", "subject",
          "smtp_host", "smtp_port", "security", "auth", "username", "from_address", "from_name",
          "tenant_id", "client_id")
FLAGS = ("auto_on_convert", "calculate_first", "send_mail", "download_after")


def _settings_out(s: R.ReportMailSettings) -> dict:
    d = {f: getattr(s, f) for f in FIELDS}
    for f in FLAGS:
        d[f] = bool(d[f])
    d["password_set"] = bool(s.password_enc)
    d["password_readable"] = secret_box.open_(s.password_enc) is not None if s.password_enc else None
    d["client_secret_set"] = bool(s.client_secret_enc)
    d["client_secret_readable"] = secret_box.open_(s.client_secret_enc) is not None \
        if s.client_secret_enc else None
    d["presets"] = mailer.PRESETS
    d["updated_at"] = s.updated_at.isoformat(timespec="seconds") if s.updated_at else None
    return d


@router.get("/mail-settings")
def get_settings(db: Session = Depends(get_db)):
    s = AJ.settings(db)
    db.commit()
    return _settings_out(s)


@router.put("/mail-settings")
def put_settings(body: dict = Body(...), db: Session = Depends(get_db)):
    s = AJ.settings(db)
    try:
        if "recipients" in body:
            mailer.addresses(body["recipients"])
        if "cc" in body:
            mailer.addresses(body["cc"])
        for f in ("from_address",):
            if body.get(f):
                mailer.addresses(body[f])
    except mailer.MailError as e:
        raise HTTPException(422, str(e))
    if body.get("security") not in (None, "starttls", "ssl", "none"):
        raise HTTPException(422, "Security is STARTTLS, SSL or none.")
    if body.get("auth") not in (None, "password", "m365_oauth", "none"):
        raise HTTPException(422, "Authentication is a password, Microsoft 365 OAuth or none.")
    if body.get("subject") is not None:
        try:
            body["subject"].format(month="September", year=2026, distributor="X")
        except (KeyError, IndexError, ValueError):
            raise HTTPException(422, "The subject can use {month}, {year} and {distributor} only.")
    for f in FIELDS:
        if f in body:
            v = body[f]
            if f in FLAGS:
                v = int(bool(v))
            elif f == "smtp_port":
                try:
                    v = int(v) if v not in (None, "") else None
                except (TypeError, ValueError):
                    raise HTTPException(422, "The port is a number, e.g. 587.")
            elif isinstance(v, str):
                v = v.strip() or None
            setattr(s, f, v)
    if body.get("password"):
        s.password_enc = secret_box.seal(body["password"])
    if body.get("clear_password"):
        s.password_enc = None
    if body.get("client_secret"):
        s.client_secret_enc = secret_box.seal(body["client_secret"])
    s.updated_at = datetime.now()
    db.commit()
    return _settings_out(s)


@router.post("/mail-settings/test")
def test_mail(body: dict = Body(...), db: Session = Depends(get_db)):
    s = AJ.settings(db)
    db.commit()
    try:
        to = mailer.addresses(body.get("to") or s.recipients)
        if not to:
            raise mailer.MailError("Give an address to send the test to.")
        cfg = AJ.smtp_config(s)
        msg = mailer.build(cfg, to, [], "Distributor Sales — test email",
                           "This is a test from Distributor Sales › Reports › Analyzer Email. "
                           "The Nepal Analyzer will be sent the same way.", None, [])
        said = mailer.send(cfg, msg)
    except mailer.MailError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "message": f"Test email sent to {', '.join(to)} ({said})."}
