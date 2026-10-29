# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Outthinkx by Luca De Simoni
"""
Email the meeting memo to the configured recipients
"""

import os
import ssl
import smtplib
import mimetypes
from email.message import EmailMessage
from typing import List, Optional

from .config import EmailConfig

# Keep emails deliverable: most mail servers reject messages above ~20-25 MB
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024


def build_memo_email(config: EmailConfig, subject: str, body: str,
                     attachments: Optional[List[str]] = None) -> EmailMessage:
    files, skipped = [], []
    for path in attachments or []:
        if not path or not os.path.exists(path):
            continue
        if os.path.getsize(path) > MAX_ATTACHMENT_BYTES:
            skipped.append(os.path.basename(path))
        else:
            files.append(path)
    if skipped:
        body += "\n\n(Too large to attach: " + ", ".join(skipped) + ")"

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = config.from_email or config.smtp_user
    msg['To'] = ', '.join(config.to_emails)
    msg.set_content(body)

    for path in files:
        ctype, _ = mimetypes.guess_type(path)
        maintype, subtype = (ctype or 'application/octet-stream').split('/', 1)
        with open(path, 'rb') as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(path))
    return msg


def send_email(config: EmailConfig, msg: EmailMessage, timeout: int = 30):
    """Send via SMTP: STARTTLS on 587 (use_tls), implicit SSL on 465"""
    password = config.resolved_password()
    context = ssl.create_default_context()
    if config.smtp_port == 465:
        server = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=timeout,
                                  context=context)
    else:
        server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=timeout)
    with server:
        if config.smtp_port != 465 and config.use_tls:
            server.starttls(context=context)
        if config.smtp_user and password:
            server.login(config.smtp_user, password)
        server.send_message(msg)


def memo_subject(title: str, language: str) -> str:
    prefix = "Protokoll" if (language or '').lower().startswith('de') else "Meeting notes"
    return f"{prefix}: {title}"
