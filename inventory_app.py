# inventory_app.py – Streamlit app for quick inventory & email
"""
Inventory Counter & Emailer
==========================
Streamlit GUI to:
* Add items **with an initial quantity** (item is created *only* when you press **Add**)
* Adjust quantities inline via **number boxes** or ➕/➖ shortcuts
* Delete individual rows or clear the whole list
* Customise subject, intro, outro text
* Send an e‑mail report using SMTP credentials stored in **st.secrets**

2025‑04‑30 ‒ Update
-------------------
* **Fix:** Typing in the *Item* box no longer auto‑adds the row; the item is added exactly once when you click **Add**.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

import streamlit as st

# ─────────────────────────────────────────────────────────────
# 0.  Configuration & helpers
# ─────────────────────────────────────────────────────────────
secrets_cfg = st.secrets.get("smtp", {})
SMTP_HOST = secrets_cfg.get("host") or os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(secrets_cfg.get("port") or os.getenv("SMTP_PORT", 465))
SMTP_USER = secrets_cfg.get("user") or os.getenv("SMTP_USER")
SMTP_PASS = secrets_cfg.get("pass") or os.getenv("SMTP_PASS")

if not all([SMTP_USER, SMTP_PASS]):
    st.warning("⚠️  SMTP credentials missing. Set them in Secrets or env vars.")


def _nl2br(text: str) -> str:
    return text.replace("\n", "<br>") if text else ""


def send_email(recipient: str, inventory: dict[str, int], *, subject: str, before: str, after: str) -> None:
    """Build plain‑text + HTML e‑mail and send via SSL SMTP."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient

    # ---- render table ----
    rows_plain = ["Item\tQuantity"] + [f"{k}\t{v}" for k, v in inventory.items()]
    table_plain = "\n".join(rows_plain)

    rows_html = "".join(
        f"<tr><td style='padding:4px 12px'>{k}</td><td align='right'>{v}</td></tr>"
        for k, v in inventory.items()
    )
    table_html = (
            "<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse;font-family:sans-serif;'>"
            "<tr><th style='padding:4px 12px'>Item</th><th>Qty</th></tr>" + rows_html + "</table>"
    )

    # ---- plain text body ----
    parts_plain = [p.strip() for p in (before, table_plain, after) if p.strip()]
    msg.set_content("\n\n".join(parts_plain))

    # ---- HTML body ----
    parts_html = []
    if before.strip():
        parts_html.append(f"<p>{_nl2br(before.strip())}</p>")
    parts_html.append(table_html)
    if after.strip():
        parts_html.append(f"<p>{_nl2br(after.strip())}</p>")
    msg.add_alternative("<html><body>" + "\n".join(parts_html) + "</body></html>", subtype="html")

    # ---- send ----
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)


# ─────────────────────────────────────────────────────────────
# 1.  Streamlit UI
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Inventory Counter", page_icon="📋", layout="centered")

st.title("📋 Inventory Counter")

if "inventory" not in st.session_state:
    st.session_state.inventory: dict[str, int] = {}


# ---------- Add‑item row ----------

def add_item_cb() -> None:
    name = st.session_state.get("new_item", "").strip()
    qty = int(st.session_state.get("new_qty", 0))
    if name:
        st.session_state.inventory[name] = max(0, qty)
        st.session_state["new_item"] = ""
        st.session_state["new_qty"] = 0

st.caption("© 2025 Inventory Tool")