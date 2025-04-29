# inventory_app.py – Streamlit app for quick inventory & email (multi‑category support)
"""
Inventory Counter & Emailer
==========================
Streamlit GUI that lets you
* **Add items with an initial quantity & tag** (item is created only when you press **Add**)
* **Same item name can live in several categories** (e.g. Coffee Cups in *Cafe* **and** *Market*)
* **Edit quantities and tags inline**; tags can be moved between categories and duplicates will auto‑merge
* **Delete rows** or **clear the list**
* Customize **e‑mail subject + intro/outro text** and send the table via SMTP

🔄 **v2.0 – 2025‑04‑29**
• Internal key switched to **name + tag** so duplicates across categories no longer collide.
• Editing a row’s tag moves/merges it behind the scenes.
• Add‑item callback now increments quantity if the same *(name, tag)* already exists.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Dict, Any, Tuple

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
SEP = "~~~"  # internal name‑tag separator (unlikely to appear in input)

def make_key(name: str, tag: str) -> str:  # internal composite key
    return f"{name.strip()}{SEP}{tag}"

def split_key(key: str) -> Tuple[str, str]:
    return key.rsplit(SEP, 1)

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
    rows_plain = ["Item\tTag\tQuantity"]
    for k, v in inventory.items():
        name, tag = split_key(k)
        rows_plain.append(f"{name}\t{tag}\t{v['qty']}")
    table_plain = "\n".join(rows_plain)

    rows_html = "".join(
        f"<tr><td style='padding:4px 12px'>{split_key(k)[0]}</td><td>{split_key(k)[1]}</td><td align='right'>{v['qty']}</td></tr>"
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
    # Dict key = name~~~tag  ; value = {"qty": int}
    st.session_state.inventory: Dict[str, Dict[str, Any]] = {}

# ---------- Add item row ----------

def add_item_cb():
    name = st.session_state.get("new_item", "").strip()
    qty = int(st.session_state.get("new_qty", 0))
    tag = st.session_state.get("new_tag", CATEGORIES[0])
    if not name:
        return
    key = make_key(name, tag)
    if key in st.session_state.inventory:
        st.session_state.inventory[key]["qty"] += qty  # merge duplicate
    else:
        st.session_state.inventory[key] = {"qty": qty}
    # Reset fields for quick next entry
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
    st.selectbox("Tag (click to choose)", key="new_tag", options=CATEGORIES, label_visibility="visible")
with col_add:
    st.button("Add", key="add_btn", on_click=add_item_cb, use_container_width=True)

st.divider()

# ---------- Inventory table ----------
if st.session_state.inventory:
    st.subheader("Current Inventory")
    # Sort by (name, tag) for stable display
    for key in sorted(st.session_state.inventory.keys(), key=lambda k: split_key(k)):
        name, tag = split_key(key)
        qty = st.session_state.inventory[key]["qty"]

        plus_col, minus_col, del_col, item_col, qty_col, tag_col = st.columns([1, 1, 1, 4, 2, 3])

        # Buttons & delete
        if plus_col.button("➕", key=f"plus_{key}"):
            st.session_state.inventory[key]["qty"] += 1
        if minus_col.button("➖", key=f"minus_{key}"):
            st.session_state.inventory[key]["qty"] = max(0, qty - 1)
        if del_col.button("🗑️", key=f"del_{key}"):
            st.session_state.inventory.pop(key, None)
            continue  # Skip rendering deleted row

        # Row content (only if not deleted)
        if key not in st.session_state.inventory:
            continue

        item_col.write(name)
        new_q = qty_col.number_input(
            label=" ",
            min_value=0,
            step=1,
            value=st.session_state.inventory[key]["qty"],
            key=f"num_{key}",
            label_visibility="collapsed",
        )
        st.session_state.inventory[key]["qty"] = int(new_q)

        new_tag = tag_col.selectbox(
            label=" ",
            options=CATEGORIES,
            index=CATEGORIES.index(tag),
            key=f"tag_{key}",
            label_visibility="collapsed",
        )
        if new_tag != tag:
            new_key = make_key(name, new_tag)
            # Merge if target exists
            if new_key in st.session_state.inventory:
                st.session_state.inventory[new_key]["qty"] += st.session_state.inventory[key]["qty"]
            else:
                st.session_state.inventory[new_key] = st.session_state.inventory[key]
            # Remove old key
            st.session_state.inventory.pop(key, None)
            # Trigger immediate UI refresh
            st.experimental_rerun()

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
ready = bool(recipient.strip()) and any(v["qty"] > 0 for v in st.session_state.inventory.values())
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
