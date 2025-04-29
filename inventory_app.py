# inventory_app.py – Streamlit app for quick inventory & email
"""
Inventory Counter & Emailer
==========================
Streamlit GUI that lets you
* **Add items with an initial quantity** (item is created only when you press **Add**)
* **Edit quantities inline** (type any number) or use ➕/➖ buttons
* **Delete rows** or **clear the list**
* Customize **e‑mail subject + intro/outro text** and send the table via SMTP

This revision removes all explicit `st.rerun()` calls (Streamlit auto‑reruns on
widget interaction) and restores the full UI that disappeared after the last
edit.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Dict

import streamlit as st

# ─────────────────────────────────────────────────────────────
# 0.  Configuration & helpers
# ─────────────────────────────────────────────────────────────
SECRETS = st.secrets.get("smtp", {})  # host, port, user, pass
SMTP_HOST = SECRETS.get("host") or os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(SECRETS.get("port") or os.getenv("SMTP_PORT", 465))
SMTP_USER = SECRETS.get("user") or os.getenv("SMTP_USER")
SMTP_PASS = SECRETS.get("pass") or os.getenv("SMTP_PASS")

if not (SMTP_USER and SMTP_PASS):
    st.warning("⚠️  Configure SMTP credentials in Secrets or env vars to enable e‑mail.")


def _nl2br(txt: str) -> str:
    """Convert newlines to <br> for HTML bodies."""
    return txt.replace("\n", "<br>") if txt else ""


def send_email(
    recipient: str,
    inventory: Dict[str, int],
    *,
    subject: str,
    before_txt: str,
    after_txt: str,
) -> None:
    """Compose and send an inventory e‑mail (plain + HTML)."""
    msg = EmailMessage()
    msg["Subject"] = subject or "Inventory Report"
    msg["From"] = SMTP_USER
    msg["To"] = recipient

    # --------- render table ---------
    rows_plain = ["Item\tQuantity"] + [f"{k}\t{v}" for k, v in inventory.items()]
    table_plain = "\n".join(rows_plain)

    rows_html = "".join(
        f"<tr><td style='padding:4px 12px'>{k}</td><td align='right'>{v}</td></tr>" for k, v in inventory.items()
    )
    table_html = (
        "<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse;font-family:sans-serif;'>"
        "<tr><th style='padding:4px 12px'>Item</th><th>Qty</th></tr>"
        f"{rows_html}</table>"
    )

    # --------- plain‑text body ---------
    parts_plain = []
    if before_txt.strip():
        parts_plain.append(before_txt.strip())
    parts_plain.append(table_plain)
    if after_txt.strip():
        parts_plain.append(after_txt.strip())
    msg.set_content("\n\n".join(parts_plain))

    # --------- HTML body ---------
    parts_html = []
    if before_txt.strip():
        parts_html.append(f"<p>{_nl2br(before_txt.strip())}</p>")
    parts_html.append(table_html)
    if after_txt.strip():
        parts_html.append(f"<p>{_nl2br(after_txt.strip())}</p>")
    msg.add_alternative("<html><body>" + "\n".join(parts_html) + "</body></html>", subtype="html")

    # --------- send ---------
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)


# ─────────────────────────────────────────────────────────────
# 1.  Streamlit UI
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Inventory Counter", page_icon="📋", layout="centered")

st.title("📋 Inventory Counter")

if "inventory" not in st.session_state:
    st.session_state.inventory: Dict[str, int] = {}

# ---------- Add item row ----------
col_name, col_qty, col_add = st.columns([3, 1, 1])
with col_name:
    new_item = st.text_input("Item", key="new_item", placeholder="e.g. Blueberry Muffin")
with col_qty:
    new_qty = st.number_input("Qty", key="new_qty", min_value=0, value=0, step=1, format="%d")
with col_add:
    if st.button("Add", use_container_width=True):
        name = new_item.strip()
        if name:
            st.session_state.inventory[name] = int(new_qty)
            st.session_state.new_item = ""
            st.session_state.new_qty = 0

st.divider()

# ---------- Inventory table ----------
if st.session_state.inventory:
    st.subheader("Current Inventory")
    for item in list(st.session_state.inventory.keys()):
        qty = st.session_state.inventory[item]
        plus_col, minus_col, del_col, item_col, qty_col = st.columns([1, 1, 1, 4, 2])

        if plus_col.button("➕", key=f"plus_{item}"):
            st.session_state.inventory[item] += 1
        if minus_col.button("➖", key=f"minus_{item}"):
            st.session_state.inventory[item] = max(0, qty - 1)
        if del_col.button("🗑️", key=f"del_{item}"):
            st.session_state.inventory.pop(item, None)
            continue  # Skip rendering deleted row in this cycle

        # Row content
        if item in st.session_state.inventory:
            item_col.write(item)
            new_q = qty_col.number_input("", min_value=0, step=1, value=st.session_state.inventory[item], key=f"num_{item}")
            st.session_state.inventory[item] = int(new_q)

    st.divider()
    if st.button("Clear list 🗑️", type="secondary"):
        st.session_state.inventory.clear()
else:
    st.info("Add some items to get started.")

st.divider()

# ---------- E‑mail customisation ----------
subject = st.text_input("E‑mail subject", value="Inventory Report")
msg_before = st.text_area("Text before table (optional)")
msg_after = st.text_area("Text after table (optional)")

st.divider()

# ---------- Send section ----------
recipient = st.text_input("Recipient e‑mail")
ready = bool(recipient.strip()) and any(qty > 0 for qty in st.session_state.inventory.values())
if st.button("Send Inventory Report ✉️", key=f"send_{ready}", disabled=not ready):
    try:
        send_email(
            recipient.strip(),
            st.session_state.inventory,
            subject=subject.strip() or "Inventory Report",
            before_txt=msg_before,
            after_txt=msg_after,
        )
    except Exception as exc:
        st.error(f"Failed to send: {exc}")
    else:
        st.success("Report sent! 🎉")

