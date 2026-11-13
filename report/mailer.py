"""Email delivery. Same methods as the HCS Safety Scorecard (config.yaml -> email.method):

  onedrive  Default. Writes the PDF and a small message file into a work-OneDrive folder; the existing
            Power Automate flow "HCS Safety Report email" sends it from your mailbox. Works with the
            new Outlook and needs no IT changes. See docs/power-automate-flow.md.
  outlook   Outlook desktop (classic) on this PC through COM (pywin32).
  graph     Microsoft Graph sendMail with an Entra ID app that has Mail.Send (IT must grant it).
  smtp      SMTP AUTH. Usually disabled in Microsoft 365.

Every send also saves <out>/email.html and <out>/email.eml so you can see exactly what went out.
With email.enabled: false nothing is sent.
"""

from __future__ import annotations

import base64
import datetime as dt
import html as htmllib
import json
import os
import re
import shutil
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


def build_message(cfg: dict, subject: str, html: str, attachment: Path | None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    if cfg.get("from"):
        msg["From"] = cfg["from"]
    msg["To"] = ", ".join(cfg.get("to") or [])
    if cfg.get("cc"):
        msg["Cc"] = ", ".join(cfg["cc"])
    msg.set_content("This report is best viewed as HTML. The full report is attached as a PDF.")
    msg.add_alternative(html, subtype="html")
    if attachment:
        msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf",
                           filename=attachment.name)
    return msg


def send(cfg: dict, subject: str, html: str, attachment: Path | None, save_dir: Path) -> str:
    """Send the email using cfg["method"]. Returns a one-line description of what happened."""
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "email.html").write_text(html, encoding="utf-8")
    msg = build_message(cfg, subject, html, attachment)
    (save_dir / "email.eml").write_bytes(bytes(msg))
    if not cfg.get("enabled", True):
        return f"email disabled in config: saved {save_dir / 'email.eml'}"
    if not cfg.get("to"):
        raise RuntimeError("email.enabled is true but email.to is empty")

    method = cfg.get("method") or cfg.get("backend") or "onedrive"
    if method == "onedrive":
        return _send_onedrive(cfg, subject, html, attachment)
    if method == "outlook":
        _send_outlook(cfg, subject, html, attachment)
    elif method == "graph":
        _send_graph(cfg, subject, html, attachment)
    elif method == "smtp":
        _send_smtp(cfg, msg)
    else:
        raise ValueError(f"Unknown email.method: {method}")
    return f"sent via {method} to {', '.join(cfg['to'])}"


# ---- onedrive + Power Automate ------------------------------------------------

def onedrive_folder(cfg: dict) -> Path:
    """<work OneDrive>/<email.onedrive.folder>. Windows sets OneDriveCommercial for the work OneDrive."""
    od = cfg.get("onedrive") or {}
    root = od.get("root") or os.environ.get("OneDriveCommercial") or os.environ.get("OneDrive")
    if not root:
        raise RuntimeError("Work OneDrive folder not found. Set email.onedrive.root in config.yaml "
                           "(e.g. C:\\Users\\you\\OneDrive - Hillwood).")
    return Path(root) / od.get("folder", "HCS Safety Report")


def _send_onedrive(cfg, subject, html, attachment) -> str:
    """Hand the email to the Power Automate flow. The attachment goes to <folder>/Attachments, then a
    message file to <folder>/Outbox. The flow triggers on the message file, waits for the attachment
    to sync, and sends. Message format is shared with the Safety Scorecard, so one flow serves both."""
    base = onedrive_folder(cfg)
    att_dir, outbox = base / "Attachments", base / "Outbox"
    att_dir.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")  # unique per message
    if attachment is None:  # e.g. a failure notice: the flow always attaches a file, so attach a short note
        att_name = f"run-notes ({stamp}).txt"
        (att_dir / att_name).write_text(htmllib.unescape(re.sub(r"<[^>]+>", "", html)), encoding="utf-8")
    else:
        att_name = f"{attachment.stem} ({stamp}){attachment.suffix}"
        shutil.copyfile(attachment, att_dir / att_name)
    message = {"to": "; ".join(cfg["to"]), "cc": "; ".join(cfg.get("cc") or []), "subject": subject,
               "html": html, "attachment": att_name}
    tmp = base / f".message {stamp}.tmp"  # write elsewhere, then move in, so the flow never sees half a file
    tmp.write_text(json.dumps(message), encoding="utf-8")
    final = outbox / f"message {stamp}.json"
    shutil.move(str(tmp), final)
    return f"handed to Power Automate via {final} (sends to {message['to']} once OneDrive syncs)"


# ---- outlook desktop ----------------------------------------------------------

def _send_outlook(cfg, subject, html, attachment):
    import win32com.client  # pip install -r requirements-windows.txt
    mail = win32com.client.Dispatch("Outlook.Application").CreateItem(0)
    mail.To = "; ".join(cfg["to"])
    if cfg.get("cc"):
        mail.CC = "; ".join(cfg["cc"])
    mail.Subject = subject
    mail.HTMLBody = html
    if attachment:
        mail.Attachments.Add(str(attachment.resolve()))
    mail.Send()


# ---- smtp ---------------------------------------------------------------------

def _send_smtp(cfg, msg: EmailMessage):
    s = cfg.get("smtp") or {}
    host = os.environ.get("SMTP_HOST") or s.get("host", "smtp.office365.com")
    port = int(os.environ.get("SMTP_PORT") or s.get("port", 587))
    with smtplib.SMTP(host, port, timeout=60) as smtp:
        if s.get("starttls", True):
            smtp.starttls(context=ssl.create_default_context())
        if os.environ.get("SMTP_USERNAME"):
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


# ---- microsoft graph ----------------------------------------------------------

def _send_graph(cfg, subject, html, attachment):
    import requests
    tenant = os.environ.get("GRAPH_TENANT_ID") or (cfg.get("graph") or {}).get("tenant_id")
    tok = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={"grant_type": "client_credentials", "client_id": os.environ["GRAPH_CLIENT_ID"],
              "client_secret": os.environ["GRAPH_CLIENT_SECRET"],
              "scope": "https://graph.microsoft.com/.default"},
        timeout=60,
    )
    tok.raise_for_status()
    rcpt = lambda xs: [{"emailAddress": {"address": a}} for a in xs or []]
    message = {"subject": subject, "body": {"contentType": "HTML", "content": html},
               "toRecipients": rcpt(cfg["to"]), "ccRecipients": rcpt(cfg.get("cc"))}
    if attachment:
        message["attachments"] = [{
            "@odata.type": "#microsoft.graph.fileAttachment", "name": attachment.name,
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode(attachment.read_bytes()).decode(),
        }]
    resp = requests.post(f"https://graph.microsoft.com/v1.0/users/{cfg['from']}/sendMail",
                         json={"message": message, "saveToSentItems": True},
                         headers={"Authorization": f"Bearer {tok.json()['access_token']}"}, timeout=60)
    resp.raise_for_status()
