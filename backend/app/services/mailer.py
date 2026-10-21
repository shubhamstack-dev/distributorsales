"""Sending an email with an attachment, by SMTP.

Two ways to sign in:

* **password** — any SMTP server: Gmail or Google Workspace (an app password),
  Zoho, Microsoft 365 with SMTP AUTH allowed for the mailbox.
* **m365_oauth** — Microsoft 365 without a password: the app's client secret
  gets a token from Entra ID (client credentials) and SMTP signs in with
  XOAUTH2 as the mailbox. The app needs the Exchange Online permission
  SMTP.SendAsApp with admin consent, and the mailbox has to be granted to the
  app's service principal in Exchange (the same set-up the ProjectSystem uses).
"""
from __future__ import annotations

import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import httpx

XLSX = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
TIMEOUT = 60

PRESETS = {
    "m365": {"smtp_host": "smtp.office365.com", "smtp_port": 587, "security": "starttls"},
    "google": {"smtp_host": "smtp.gmail.com", "smtp_port": 587, "security": "starttls"},
    "zoho_in": {"smtp_host": "smtp.zoho.in", "smtp_port": 587, "security": "starttls"},
}


class MailError(Exception):
    pass


def addresses(text: str | None) -> list[str]:
    """'a@x.com, b@y.com; c@z.com' -> the addresses, each checked."""
    out = []
    for part in re.split(r"[,;\s]+", text or ""):
        part = part.strip()
        if not part:
            continue
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", part):
            raise MailError(f"'{part}' is not an email address.")
        if part.lower() not in (a.lower() for a in out):
            out.append(part)
    return out


def m365_token(tenant: str, client: str, secret: str) -> str:
    """An app token for Exchange Online (client credentials)."""
    if not (tenant and client and secret):
        raise MailError("Microsoft 365 sign-in needs the Tenant ID, Client ID and Client secret.")
    try:
        r = httpx.post(f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token", timeout=30, data={
            "client_id": client, "client_secret": secret, "grant_type": "client_credentials",
            "scope": "https://outlook.office365.com/.default"})
    except httpx.HTTPError as e:
        raise MailError(f"Could not reach Microsoft sign-in: {e}") from e
    if r.status_code != 200:
        try:
            j = r.json()
            why = j.get("error_description") or j.get("error") or r.text
        except ValueError:
            why = r.text
        raise MailError(f"Microsoft sign-in refused the app: {str(why).splitlines()[0][:300]}")
    return r.json()["access_token"]


def build(cfg: dict, to: list[str], cc: list[str], subject: str, text: str, html: str | None,
          attachments: list[tuple[str, bytes]]) -> EmailMessage:
    m = EmailMessage()
    sender = cfg.get("from_address") or cfg.get("username")
    m["From"] = formataddr((cfg.get("from_name") or "", sender))
    m["To"] = ", ".join(to)
    if cc:
        m["Cc"] = ", ".join(cc)
    m["Subject"] = subject
    m["Message-ID"] = make_msgid(domain=(sender or "localhost").split("@")[-1])
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
    for name, data in attachments:
        m.add_attachment(data, maintype=XLSX[0], subtype=XLSX[1], filename=name)
    return m


def _explain(e: Exception) -> str:
    s = str(e)
    if "5.7.139" in s or "SmtpClientAuthentication is disabled" in s:
        return ("Microsoft 365 has SMTP AUTH turned off for this mailbox (5.7.139). Turn on "
                "'Authenticated SMTP' for the mailbox in the Microsoft 365 admin centre, or use "
                "Microsoft 365 (OAuth).")
    if isinstance(e, smtplib.SMTPAuthenticationError):
        hint = (" For Gmail, use an app password (Google account › Security › App passwords)."
                if "gmail" in s.lower() or "google" in s.lower() else "")
        return f"The mail server refused the sign-in: {e.smtp_code} {e.smtp_error.decode(errors='replace')[:300]}.{hint}"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "The mail server refused the address(es): " + ", ".join(e.recipients)
    if isinstance(e, (TimeoutError, ConnectionError, OSError)) and not isinstance(e, smtplib.SMTPException):
        return f"Could not reach the mail server: {s or type(e).__name__}"
    return f"{type(e).__name__}: {s[:400]}"


def send(cfg: dict, msg: EmailMessage) -> str:
    """Send it; the server's last word on success, MailError otherwise."""
    host, port = cfg.get("smtp_host"), int(cfg.get("smtp_port") or 0)
    if not host or not port:
        raise MailError("Fill in the SMTP server and port on Analyzer Email.")
    security, auth = cfg.get("security") or "starttls", cfg.get("auth") or "password"
    user = cfg.get("username") or cfg.get("from_address")
    token = None
    if auth == "m365_oauth":
        token = m365_token(cfg.get("tenant_id"), cfg.get("client_id"), cfg.get("client_secret"))
    try:
        ctx = ssl.create_default_context()
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=TIMEOUT)
        with server:
            server.ehlo()
            if security == "starttls":
                server.starttls(context=ctx)
                server.ehlo()
            if auth == "password":
                if not user or not cfg.get("password"):
                    raise MailError("Fill in the user and password (or choose Microsoft 365 OAuth).")
                server.login(user, cfg["password"])
            elif auth == "m365_oauth":
                server.auth("XOAUTH2", lambda challenge=None: f"user={user}\x01auth=Bearer {token}\x01\x01")
            refused = server.send_message(msg)
            if refused:
                raise MailError("The mail server refused: " + ", ".join(refused))
            code, words = server.noop()
            return f"{code} {words.decode(errors='replace')[:120]}"
    except MailError:
        raise
    except Exception as e:                           # every SMTP / network failure, said plainly
        raise MailError(_explain(e)) from e
