# inventory_app.py – Multi‑producer inventory & email app
"""
Inventory Counter & Emailer (Multi‑Producer Edition)
===================================================
This single Streamlit app can service **multiple producers / brands**.  Each
producer profile defines its own:

* **Category list** (column headers in the UI and grouping in e‑mails)
* (Optional) **Default e‑mail subject / recipient**
* (Optional) **Custom colour** for the page header (coming soon)

Add as many producers as you like by extending the `PRODUCERS` dict.  All other
logic (duplicate handling, grouping, e‑mail) re‑uses the boilerplate we built
for *Why Not Pie*.

🔄 **v3.0 – 2025‑04‑29**
• Introduced `PRODUCERS` config + profile selector.
• Inventory is **profile‑scoped**—switching producer clears the list to avoid
  mixing items.
• Category dropdowns & e‑mail grouping now pull from the active profile.
• Kept multi‑category duplicates + grouped e‑mail from v2.1.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Dict, Any, Tuple, List

import streamlit as st

# ─────────────────────────────────────────────────────────────
# 0.  Global configuration (SMTP + producer profiles)
# ─────────────────────────────────────────────────────────────
SECRETS = st.secrets.get("smtp", {})  # host, port, user, pass
SMTP_HOST = SECRETS.get("host") or os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(SECRETS.get("port") or os.getenv("SMTP_PORT", 465))
SMTP_USER = SECRETS.get("user") or os.getenv("SMTP_USER")
SMTP_PASS = SECRETS.get("pass") or os.getenv("SMTP_PASS")

if not (SMTP_USER and SMTP_PASS):
    st.warning("⚠️  Configure SMTP credentials in Secrets or env vars to enable e‑mail.")

# ----- Producer‑specific defaults -------------------------------------------
PRODUCERS: Dict[str, Dict[str, Any]] = {
    "Why Not Pie": {
        "categories": ["Cafe", "Market", "Goodies", "Frozen"],
        "default_subject": "Why Not Pie – Daily Inventory",
        "default_recipient": "",
    },
    "Sample Bakery": {
        "categories": ["Front", "Back", "Freezer"],
        "default_subject": "Sample Bakery – Inventory",
        "default_recipient": "",
    },
}

# ─────────────────────────────────────────────────────────────
# 1.  Utility helpers
# ─────────────────────────────────────────────────────────────
SEP = "~~~"  # internal name‑tag separator (unlikely in real text)

def make_key(name: str, tag: str) -> str:
    return f"{name.strip()}{SEP}{tag}"

def split_key(key: str) -> Tuple[str, str]:
    return key.rsplit(SEP, 1)

def _nl2br(txt: str) -> str:
    return txt.replace("\n", "<br>") if txt else ""

# ─────────────────────────────────────────────────────────────
# 2.  E‑mail composer (grouped by category from active profile)
# ─────────────────────────────────────────────────────────────

def send_email(
    *,
    recipient: str,
    inventory: Dict[str, Dict[str, Any]],
    categories: List[str],
    subject: str,
    before_txt: str,
    after_txt: str,
) -> None:
    """Compose and send grouped inventory e‑mail."""

    # Group inventory by category
    grouped: Dict[str, List[Tuple[str, int]]] = {cat: [] for cat in categories}
    # Ensure any ad‑hoc tags that slipped in are still shown
    for k, v in inventory.items():
        name, tag = split_key(k)
        grouped.setdefault(tag, []).append((name, v["qty"]))

    # ----- Plain‑text body -----
    rows_plain: List[str] = []
    for cat in categories + [c for c in grouped if c not in categories]:
        if not grouped.get(cat):
            continue
        rows_plain.append(f"=== {cat} ===")
        rows_plain.append("Item\tQuantity")
        for name, qty in sorted(grouped[cat]):
            rows_plain.append(f"{name}\t{qty}")
        rows_plain.append("")
    table_plain = "\n".join(rows_plain).strip()

    # ----- HTML body -----
    rows_html: List[str] = []
    for cat in categories + [c for c in grouped if c not in categories]:
        if not grouped.get(cat):
            continue
        rows_html.append(
            f"<tr style='background:#f3f3f3;font-weight:bold;'><td colspan='2' style='padding:6px 12px'>{cat}</td></tr>"
        )
        for name, qty in sorted(grouped[cat]):
            rows_html.append(
                f"<tr><td style='padding:4px 12px'>{name}</td><td align='right'>{qty}</td></tr>"
            )
    table_html = (
        "<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse;font-family:sans-serif;'>"
        "<tr><th style='padding:4px 12px'>Item</th><th>Qty</th></tr>"
        + "".join(rows_html)
        + "</table>"
    )

    # ----- Build EmailMessage -----
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient

    parts_plain: List[str] = []
    if before_txt.strip():
        parts_plain.append(before_txt.strip())
    parts_plain.append(table_plain)
    if after_txt.strip():
        parts_plain.append(after_txt.strip())
    msg.set_content("\n\n".join(parts_plain))

    parts_html: List[str] = []
    if before_txt.strip():
        parts_html.append(f"<p>{_nl2br(before_txt.strip())}</p>")
    parts_html.append(table_html)
    if after_txt.strip():
        parts_html.append(f"<p>{_nl2br(after_txt.strip())}</p>")
    msg.add_alternative("<html><body>" + "\n".join(parts_html) + "</body></html>", subtype="html")

    # ----- Send -----
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)

# ─────────────────────────────────────────────────────────────
# 3.  Streamlit UI
# ─────────────────────────────────────────────────────────────

st.set_page_config(page_title="Inventory Counter", page_icon="📋", layout="wide")

# ----- Profile selector -----
profile_names = list(PRODUCERS.keys())
sel_index = profile_names.index(st.session_state.get("profile", profile_names[0]))
profile = st.selectbox("Producer profile", profile_names, index=sel_index)
st.session_state.profile = profile
CFG = PRODUCERS[profile]
CATEGORIES: List[str] = CFG["categories"]

st.title(f"📋 Inventory Counter – {profile}")

# Clearing inventory when switching profiles keeps data separate
if "inventory" not in st.session_state or st.session_state.get("inventory_profile") != profile:
    st.session_state.inventory = {}
    st.session_state.inventory_profile = profile

# ---------- Add item row ----------

def add_item_cb():
    name = st.session_state.get("new_item", "").strip()
    qty = int(st.session_state.get("new_qty", 0))
    tag = st.session_state.get("new_tag", CATEGORIES[0])
    if not name:
        return
    key = make_key(name, tag)
    if key in st.session_state.inventory:
        st.session_state.inventory[key]["qty"] += qty
    else:
        st.session_state.inventory[key] = {"qty": qty}
    # Reset for next entry
    st.session_state["new_item"] = ""
    st.session_state["new_qty"] = 0
    st.session_state["new_tag"] = CATEGORIES[0]

col_name, col_qty, col_tag, col_add = st.columns([3, 1, 3, 1])
with col_name:
    st.text_input("Item", key="new_item", placeholder="e.g. Blueberry Muffin")
with col_qty:
    st.number_input("Qty", key="new_qty", min_value=0, value=0, step=1, format="%d")
with col_tag:
    st.selectbox("Tag", key="new_tag", options=CATEGORIES)
with col_add:
    st.button("Add", key="add_btn", on_click=add_item_cb, use_container_width=True)

st.divider()

# ---------- Inventory table ----------
if st.session_state.inventory:
    st.subheader("Current Inventory")
    for key in sorted(st.session_state.inventory.keys(), key=lambda k: split_key(k)):
        name, tag = split_key(key)
        qty = st.session_state.inventory[key]["qty"]

        plus_col, minus_col, del_col, item_col, qty_col, tag_col = st.columns([1, 1, 1, 4, 2, 3])
        if plus_col.button("➕", key=f"plus_{key}"):
            st.session_state.inventory[key]["qty"] += 1
        if minus_col.button("➖", key=f"minus_{key}"):
            st.session_state.inventory[key]["qty"] = max(0, qty - 1)
        if del_col.button("🗑️", key=f"del_{key}"):
            st.session_state.inventory.pop(key, None)
            continue

        if key not in st.session_state.inventory:
            continue

        item_col.write(name)
        new_q = qty_col.number_input(" ", min_value=0, step=1, value=qty, key=f"num_{key}", label_visibility="collapsed")
        st.session_state.inventory[key]["qty"] = int(new_q)

        new_tag = tag_col.selectbox(" ", options=CATEGORIES, index=CATEGORIES.index(tag) if tag in CATEGORIES else 0, key=f"tag_{key}", label_visibility="collapsed")
        if new_tag != tag:
            new_key = make_key(name, new_tag)
            if new_key in st.session_state.inventory:
                st.session_state.inventory[new_key]["qty"] += st.session_state.inventory[key]["qty"]
            else:
                st.session_state.inventory[new_key] = st.session_state.inventory[key]
            st.session_state.inventory.pop(key, None)
            st.experimental_rerun()

    st.divider()
    if st.button("Clear list 🗑️", type="secondary"):
        st.session_state.inventory.clear()
else:
    st.info("Add some items to get started.")

st.divider()

# ---------- E‑mail customisation ----------
subject_default = CFG.get("default_subject", "Inventory Report")
recipient_default = CFG.get("default_recipient", "")

subject = st.text_input("E‑mail subject", value=subject_default)
msg_before = st.text_area("Text before table (optional)")
msg_after = st.text_area("Text after table (optional)")

st.divider()

# ---------- Send section ----------
recipient = st.text_input("Recipient e‑mail", value=recipient_default)
ready = bool(recipient.strip()) and any(v["qty"] > 0 for v in st.session_state.inventory.values())
if st.button("Send Inventory Report ✉️", key=f"send_{ready}", disabled=not ready):
    try:
        send_email(
            recipient=recipient.strip(),
            inventory=st.session_state.inventory,
            categories=CATEGORIES,
            subject=subject.strip() or subject_default,
            before_txt=msg_before,
            after_txt=msg_after,
        )
    except Exception as exc:
        st.error(f"Failed to send:
