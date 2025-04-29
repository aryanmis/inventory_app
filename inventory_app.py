# inventory_app.py – Streamlit app for quick inventory & email
"""
Inventory Counter & Emailer
==========================
Lightweight Streamlit GUI to tally item counts with ➕ / ➖ buttons, delete items,
reset the whole list, and e‑mail customisable reports.

Changelog (2025‑04‑29 g)
------------------------
* **Bug‑fix:** Delete now works in a *single* click. When you press 🗑️ the page
  immediately reruns so the row disappears without needing a second click.
* **Improvement:** `Clear list` likewise performs an instant rerun.

Quick start
-----------
```bash
streamlit run inventory_app.py
```
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

import streamlit as st
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────
# 0.  Configuration & helpers
# ─────────────────────────────────────────────────────────────
load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")


def _nl2br(text: str) -> str:
    """Convert newlines to <br> for HTML."""
    return text.replace("\n", "<br>") if text else ""


def send_email(
    recipient: str,
    inventory: dict[str, int],
    subject: str = "Inventory Report",
    after_txt: str = "",
) -> None:
    """Compose and send an inventory report via SSL SMTP."""
    msg = EmailMessage()
    msg["Subject"] = subject or "Inventory Report"
    msg["From"] = SMTP_USER
    msg["To"] = recipient

    # ---------- Build table ----------
    rows_plain = ["Item\tQuantity"] + [f"{k}\t{v}" for k, v in inventory.items()]
    table_plain = "\n".join(rows_plain)

    rows_html = "".join(
        f"<tr><td style='padding:4px 12px'>{k}</td><td align='right'>{v}</td></tr>"
        for k, v in inventory.items()
    )
    table_html = (
        "<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse;font-family:sans-serif;'>"
        "<tr><th style='padding:4px 12px'>Item</th><th>Quantity</th></tr>"
        f"{rows_html}</table>"
    )

    # ---------- Plain‑text body ----------
    plain_parts = [table_plain]
    if after_txt:
        plain_parts.append(after_txt.strip())
    msg.set_content("\n\n".join(plain_parts))

    # ---------- HTML body ----------
    html_parts = [table_html]
    if after_txt:
        html_parts.append(f"<p>{_nl2br(after_txt.strip())}</p>")
    msg.add_alternative("<html><body>" + "\n".join(html_parts) + "</body></html>", subtype="html")

    # ---------- Send ----------
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)


# ─────────────────────────────────────────────────────────────
# 1.  Streamlit UI
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Inventory Counter", page_icon="📋", layout="centered")

st.title("📋 Inventory Counter")

# Initialise state on first run
if "inventory" not in st.session_state:
    st.session_state.inventory: dict[str, int] = {}

# ---------- Callbacks ----------

def add_item_cb() -> None:
    """Add textbox value to inventory (if non‑blank) and clear box."""
    item = st.session_state.get("new_item", "").strip()
    if item:
        st.session_state.inventory.setdefault(item, 1)  # start at 0
        st.session_state["new_item"] = ""  # clear textbox

# ---------- Item creation row ----------
col_item, col_add = st.columns([3, 1])
with col_item:
    st.text_input(
        "Add new item",
        key="new_item",
        placeholder="e.g. Blueberry Muffin",
        on_change=add_item_cb,
    )
with col_add:
    st.button("Add", on_click=add_item_cb, use_container_width=True)

st.divider()

# ---------- Inventory table ----------
if st.session_state.inventory:
    st.subheader("Current Inventory")

    for item in list(st.session_state.inventory.keys()):
        qty = st.session_state.inventory[item]
        plus_col, minus_col, del_col, item_col, qty_col = st.columns([1, 1, 1, 5, 2])

        if plus_col.button("➕", key=f"plus_{item}"):
            st.session_state.inventory[item] += 1
            st.rerun()
        if minus_col.button("➖", key=f"minus_{item}"):
            st.session_state.inventory[item] = max(0, qty - 1)
            st.rerun()
        if del_col.button("🗑️", key=f"del_{item}"):
            st.session_state.inventory.pop(item, None)
            st.rerun()  # instant refresh so row disappears immediately

        # Only render if item still exists (prevents flash on delete)
        if item in st.session_state.inventory:
            item_col.write(item)
            qty_col.write(st.session_state.inventory[item])

    st.divider()
    # Clear‑all button
    if st.button("Clear list 🗑️", key="clear_all", type="secondary"):
        st.session_state.inventory.clear()
        st.rerun()
else:
    st.info("Add some items to get started.")

st.divider()

# ---------- E‑mail customisation ----------
subject_input = st.text_input("E‑mail subject", key="email_subject", placeholder="Inventory Report")
msg_after = st.text_area("Text after table (optional)", key="msg_after", height=100)

st.divider()

# ---------- E‑mail section ----------
recipient = st.text_input("Recipient e‑mail", key="recipient", placeholder="manager@example.com")

non_zero_inventory = any(qty > 0 for qty in st.session_state.inventory.values())
can_send = bool(recipient.strip()) and non_zero_inventory
send_key = f"send_btn_{can_send}"

if st.button("Send Inventory Report ✉️", key=send_key, disabled=not can_send):
    try:
        send_email(
            recipient.strip(),
            st.session_state.inventory,
            subject=subject_input.strip() or "Inventory Report",
            after_txt=msg_after,
        )
    except Exception as exc:
        st.error(f"Failed to send e‑mail: {exc}")
    else:
        st.success("Report sent! 🎉")

