"""Alert notification dispatch — Slack webhook and email."""
from __future__ import annotations

import json
import logging
import os
import smtplib
from email.mime.text import MIMEText
from urllib.request import Request, urlopen

from bdc_news.alerts.evaluator import Alert

log = logging.getLogger(__name__)


def send_all(alerts: list[Alert]) -> int:
    sent = 0
    for alert in alerts:
        for ch in alert.channels:
            try:
                if ch == "slack":
                    _send_slack(alert)
                    sent += 1
                elif ch == "email":
                    _send_email(alert)
                    sent += 1
            except Exception as exc:
                log.warning("Failed to send %s via %s: %s", alert.rule_id, ch, exc)
    return sent


_SEV_EMOJI = {"high": ":red_circle:", "medium": ":large_orange_circle:", "low": ":white_circle:"}


def _send_slack(alert: Alert) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        log.info("SLACK_WEBHOOK_URL not set — skipping Slack for %s", alert.rule_id)
        return
    payload = {
        "text": f"{_SEV_EMOJI.get(alert.severity, ':bell:')} *[{alert.severity.upper()}]* {alert.ticker}\n{alert.message}",
    }
    data = json.dumps(payload).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=15) as resp:
        if resp.status != 200:
            log.warning("Slack returned %d", resp.status)
    log.info("Slack alert sent: %s / %s", alert.rule_id, alert.ticker)


def _send_email(alert: Alert) -> None:
    host = os.environ.get("SMTP_HOST")
    from_addr = os.environ.get("ALERT_FROM_EMAIL")
    to_addr = os.environ.get("ALERT_TO_EMAIL")
    if not all([host, from_addr, to_addr]):
        log.info("Email env vars not set — skipping email for %s", alert.rule_id)
        return
    port = int(os.environ.get("SMTP_PORT", "587"))
    msg = MIMEText(
        f"BDC Alert [{alert.severity.upper()}]\n\n"
        f"Rule: {alert.rule_id}\n"
        f"Ticker: {alert.ticker}\n"
        f"Value: {alert.value}\n\n"
        f"{alert.message}",
        _charset="utf-8",
    )
    msg["Subject"] = f"[BDC Alert] {alert.severity.upper()}: {alert.ticker} — {alert.description}"
    msg["From"] = from_addr
    msg["To"] = to_addr
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        user = os.environ.get("SMTP_USER", from_addr)
        pw = os.environ.get("SMTP_PASSWORD", "")
        if pw:
            s.login(user, pw)
        s.sendmail(from_addr, [to_addr], msg.as_string())
    log.info("Email alert sent: %s / %s", alert.rule_id, alert.ticker)
