"""Email delivery. Two backends:

  smtp  - any SMTP relay (SendGrid, Mailgun, Gmail/Workspace, Microsoft 365 with
          SMTP AUTH enabled for the sending mailbox).
  graph - Microsoft 365 via Microsoft Graph sendMail, using an Entra ID app
          registration with the Mail.Send application permission. Use this if
          your tenant has SMTP AUTH turned off (Microsoft's default).
"""

from __future__ import annotations

import base64
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

import requests


def send(cfg: dict, subject: str, html: str, attachment: Path) -> None:
    backend = cfg.get("backend", "smtp")
    to, cc = cfg["to"], cfg.get("cc", [])
    if backend == "smtp":
        _send_smtp(cfg, subject, html, attachment, to, cc)
    elif backend == "graph":
        _send_graph(cfg, subject, html, attachment, to, cc)
    else:
        raise ValueError(f"Unknown email backend: {backend}")


def _send_smtp(cfg, subject, html, attachment, to, cc):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content("This report is best viewed as HTML. The full report is attached as a PDF.")
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf",
                       filename=attachment.name)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=60) as s:
        s.starttls(context=ctx)
        if os.environ.get("SMTP_USERNAME"):
            s.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


def _send_graph(cfg, subject, html, attachment, to, cc):
    tenant = os.environ["GRAPH_TENANT_ID"]
    tok = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["GRAPH_CLIENT_ID"],
            "client_secret": os.environ["GRAPH_CLIENT_SECRET"],
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=60,
    )
    tok.raise_for_status()
    addr = lambda a: {"emailAddress": {"address": a}}
    body = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [addr(a) for a in to],
            "ccRecipients": [addr(a) for a in cc],
            "attachments": [{
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": attachment.name,
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(attachment.read_bytes()).decode(),
            }],
        },
        "saveToSentItems": True,
    }
    resp = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{cfg['from']}/sendMail",
        json=body,
        headers={"Authorization": f"Bearer {tok.json()['access_token']}"},
        timeout=60,
    )
    resp.raise_for_status()
