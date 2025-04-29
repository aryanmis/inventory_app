# inventory_app.py – Streamlit app for quick inventory & email (with per-item tags)
"""
Inventory Counter & Emailer
==========================
Streamlit GUI that lets you
* **Add items with an initial quantity & tag** (item is created only when you press **Add**)
* **Edit quantities and tags inline** or use ➕/➖ buttons
* **Delete rows** or **clear the list**
* Customize **e‑mail subject + intro/outro text** and send the table via SMTP

🔄 **v1.1 – 2025‑04‑29**
• Switched to **layout="wide"** so narrow screens don’t hide widgets.
• Widened the tag‑selector column and forced the dropdown to show.
• Minor UX tweaks (placeholder text, focus reset).
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Dict, Any

import streamlit as st

# ─────────────────────────────────────────────────────────────
# 0.  Configuration, constants & helpers
# ─────────────────────────────────────────────────────────────
SECRETS = st.secrets.get("smtp", {})  # host, port, user, pass
SMTP_HOST = SECRETS.get("host") or os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(SECRETS.get("port") or os.getenv("SMTP_PORT", 465))
SMTP_USER = SECRETS.get("user") or os.getenv("SMTP_USER")
SMTP_PASS = SECRETS.get("pass") or os.getenv("SMTP_PASS")

if not (SMTP_USER and SMTP_PASS):
    st.warning("⚠️  Configure SMTP credentials in Secrets or env vars to enable e‑mail.")

CATEGORIES = ["Cafe", "Market", "Goodies", "Frozen"]  # Allowed tags


def _nl2br(txt: str) -> str:
    """Convert newlines to <br> for HTML bodies."""
    return txt.replace("\n", "<br>") if txt else ""


def send_email(
    recipient: str,
    inventory: Dict[str, Dict[str, Any]],
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
    rows_plain = ["Item\tTag\tQuantity"] + [
        f"{k}\t{v['tag']}\t{v['qty']}" for k, v in inventory.items()
    ]
    table_plain = "\n".join(rows_plain)

    rows_html = "".join(
        f"<tr><td style='padding:4px 12px'>{k}</td><td>{v['tag']}</td><td align='right'>{v['qty']}</td></tr>"
        for k, v in inventory.items()
    )
    table_html = (
        "<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse;font-family:sans-serif;'>"
        "<tr><th style='padding:4px 12px'>Item</th><th>Tag</th><th>Qty</th></tr>"
        f"{rows_html}</table>"
    )

    # --------- plain-text body ---------
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
# Use a wide layout so the dropdown stays visible even on smaller screens
st.set_page_config(page_title="Inventory Counter", page_icon="📋", layout="wide")

st.title("📋 Inventory Counter (with Tags)")

if "inventory" not in st.session_state:
    # Each entry is a dict: {"qty": int, "tag": str}
    st.session_state.inventory: Dict[str, Dict[str, Any]] = {}

# ---------- Add item row ----------

def add_item_cb():
    name = st.session_state.get("new_item", "").strip()
    qty = int(st.session_state.get("new_qty", 0))
    tag = st.session_state.get("new_tag", CATEGORIES[0])
    if name:
        st.session_state.inventory[name] = {"qty": qty, "tag": tag}
        # Reset the entry fields so users can add the next item quickly
        st.session_state["new_item"] = ""
        st.session_state["new_qty"] = 0
        st.session_state["new_tag"] = CATEGORIES[0]

# Wider tag column so the dropdown isn’t squeezed off‑screen
col_name, col_qty, col_tag, col_add = st.columns([3, 1, 3, 1])
with col_name:
    st.text_input("Item", key="new_item", placeholder="e.g. Blueberry Muffin", label_visibility="visible")
with col_qty:
    st.number_input("Qty", key="new_qty", min_value=0, value=0, step=1, format="%d", label_visibility="visible")
with col_tag:
    st.selectbox(
        "Tag (click to choose)",
        key="new_tag",
        options=CATEGORIES,
        label_visibility="visible",
    )
with col_add:
    st.button("Add", key="add_btn", on_click=add_item_cb, use_container_width=True)

st.divider()

# ---------- Inventory table ----------
if st.session_state.inventory:
    st.subheader("Current Inventory")
    for item in list(st.session_state.inventory.keys()):
        entry = st.session_state.inventory[item]
        qty = entry["qty"]
        tag = entry["tag"]

        plus_col, minus_col, del_col, item_col, qty_col, tag_col = st.columns([1, 1, 1, 4, 2, 3])

        if plus_col.button("➕", key=f"plus_{item}"):
            st.session_state.inventory[item]["qty"] += 1
        if minus_col.button("➖", key=f"minus_{item}"):
            st.session_state.inventory[item]["qty"] = max(0, qty - 1)
        if del_col.button("🗑️", key=f"del_{item}"):
            st.session_state.inventory.pop(item, None)
            continue  # Skip rendering deleted row in this cycle

        # Row content (only if not deleted)
        if item in st.session_state.inventory:
            item_col.write(item)
            new_q = qty_col.number_input(
                label=" ",
                min_value=0,
                step=1,
                value=st.session_state.inventory[item]["qty"],
                key=f"num_{item}",
                label_visibility="collapsed",
            )
            st.session_state.inventory[item]["qty"] = int(new_q)

            new_tag = tag_col.selectbox(
                label=" ",
                options=CATEGORIES,
                index=CATEGORIES.index(tag),
                key=f"tag_{item}",
                label_visibility="collapsed",
            )
            st.session_state.inventory[item]["tag"] = new_tag

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
ready = bool(recipient.strip()) and any(
    entry["qty"] > 0 for entry in st.session_state.inventory.values()
)
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
