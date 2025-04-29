# inventory_app.py – Streamlit app for quick inventory & email
"""
Inventory Counter & Emailer
==========================
Streamlit GUI to:
* Add items **with an initial quantity** (item is created *only* when you press **Add**)
* Adjust quantities inline via **number boxes** or ➕/➖ shortcuts
* Delete individual rows or clear the whole list
* Customise subject, intro, outro text
* Send an e-mail report using SMTP credentials stored in **st.secrets**

2025-04-30 ‒ Update
-------------------
* **Fix:** Typing in the *Item* box no longer auto-adds the row; the item is added exactly once when you click **Add**.
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
    """Build plain-text + HTML e-mail and send via SSL SMTP."""
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

# ---------- Add-item row ----------

def add_item_cb() -> None:
    name = st.session_state.get("new_item", "").strip()
    qty = int(st.session_state.get("new_qty", 0))
    if name:
        st.session_state.inventory[name] = max(0, qty)
        st.session_state["new_item"] = ""
        st.session_state["new_qty"] = 0
        st.rerun()

col_name, col_qty, col_btn = st.columns([3, 1, 1])
with col_name:
    st.text_input("Item", key="new_item", placeholder="e.g. Blueberry Muffin")
with col_qty:
    st.number_input("Qty", key="new_qty", min_value=0, value=0, step=1, format="%d")
with col_btn:
    st.button("Add", on_click=add_item_cb, use_container_width=True)

st.divider()

# ---------- Inventory table ----------
if st.session_state.inventory:
    st.subheader("Current Inventory")
    for item in list(st.session_state.inventory.keys()):
        qty = st.session_state.inventory[item]
        plus_col, minus_col, del_col, item_col, qty_col = st.columns([1, 1, 1, 4, 2])

        if plus_col.button("➕", key=f"plus_{item}"):
            st.session_state.inventory[item] += 1
            st.rerun()
        if minus_col.button("➖", key=f"minus_{item}"):
            st.session_state.inventory[item] = max(0, qty - 1)
            st.rerun()
        if del_col.button("🗑️", key=f"del_{item}"):
            st.session_state.inventory.pop(item, None)
            st.rerun()

        if item in st.session_state.inventory:
            item_col.write(item)
            new_val = qty_col.number_input("", min_value=0, step=1, value=qty, key=f"qty_{item}")
            if new_val != qty:
                st.session_state.inventory[item] = new_val

    st.divider()
    if st.button("Clear list 🗑️", type="secondary"):
        st.session_state.inventory.clear()
        st.rerun()
else:
    st.info("Add some items to get started.")

st.divider()

# ---------- E-mail customisation ----------
subject = st.text_input("E-mail subject", value="Inventory Report")
msg_before = st.text_area("Text before table (optional)")
msg_after = st.text_area("Text after table (optional)")

st.divider()

# ---------- Send section ----------
recipient = st.text_input("Recipient e-mail")
ready = recipient.strip() and any(v > 0 for v in st.session_state.inventory.values())
if st.button("Send Inventory Report ✉️", key=f"send_{recipient}_{ready}", disabled=not ready):
    try:
        send_email(
            recipient.strip(),
            st.session_state.inventory,
            subject=subject.strip() or "Inventory Report",
            before=msg_before,
            after=msg_after,
        )
    except Exception as exc:
        st.error(f"Failed to send: {exc}")
    else:
        st.success("Report sent! 🎉")

