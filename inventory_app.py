# inventory_app.py – Multi‑producer inventory & email app (template editor – **v4.2.1 hotfix**)
"""
**Hot‑fix:** Previous commit cut off halfway, causing Streamlit to render only the
header. This restores the **Add‑item row, inventory table, clear/reset buttons,
email section, and send button**. Entire script now runs without syntax errors.
"""

from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
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

# ----- Built‑in defaults (first‑run seed) --------------------
PRODUCERS: Dict[str, Dict[str, Any]] = {
    "Why Not Pie": {
        "categories": ["Cafe", "Market", "Goodies", "Frozen"],
        "default_subject": "Why Not Pie – Daily Inventory",
        "default_recipient": "",
        "mainstays": [
            {"name": "PBJ Muffins", "tag": "Cafe"},
            {"name": "Biscotti", "tag": "Cafe"},
            {"name": "Biscotti", "tag": "Frozen"},
            {"name": "Salami n Cheese Sando", "tag": "Market"},
        ],
    },
    "Sample Bakery": {
        "categories": ["Front", "Back", "Freezer"],
        "default_subject": "Sample Bakery – Inventory",
        "default_recipient": "",
        "mainstays": [
            {"name": "Croissant", "tag": "Front"},
            {"name": "Sourdough", "tag": "Back"},
        ],
    },
}

# Directory where user‑editable templates live (cwd)
TEMPLATE_DIR = Path.cwd() / "templates"
TEMPLATE_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 1.  Utility helpers
# ─────────────────────────────────────────────────────────────
SEP = "~~~"  # internal name‑tag separator

def make_key(name: str, tag: str) -> str:
    return f"{name.strip()}{SEP}{tag}"

def split_key(key: str) -> Tuple[str, str]:
    return key.rsplit(SEP, 1)

def slugify(name: str) -> str:
    return "_".join(name.lower().split())

def template_path(profile: str) -> Path:
    return TEMPLATE_DIR / f"{slugify(profile)}.json"

def load_template(profile: str) -> List[Dict[str, str]]:
    p = template_path(profile)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            st.error(f"⚠️ Failed to read template {p}; using built‑in defaults.")
    else:
        st.info(f"ℹ️ No saved template found for ‘{profile}’. Using built‑in defaults.")
    return PRODUCERS.get(profile, {}).get("mainstays", [])

def save_template(profile: str, items: List[Dict[str, str]]):
    try:
        template_path(profile).write_text(json.dumps(items, indent=2))
    except Exception as e:
        st.error(f"Could not save template: {e}")

def _nl2br(txt: str) -> str:
    return txt.replace("\n", "<br>") if txt else ""

# ─────────────────────────────────────────────────────────────
# 2.  E‑mail composer (grouped)
# ─────────────────────────────────────────────────────────────

def send_email(*, recipient: str, inventory: Dict[str, Dict[str, Any]], categories: List[str], subject: str, before_txt: str, after_txt: str) -> None:
    grouped: Dict[str, List[Tuple[str, int]]] = {cat: [] for cat in categories}
    for k, v in inventory.items():
        name, tag = split_key(k)
        grouped.setdefault(tag, []).append((name, v["qty"]))

    # Plain‑text part
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

    # HTML part
    rows_html: List[str] = []
    for cat in categories + [c for c in grouped if c not in categories]:
        if not grouped.get(cat):
            continue
        rows_html.append(f"<tr style='background:#f3f3f3;font-weight:bold;'><td colspan='2' style='padding:6px 12px'>{cat}</td></tr>")
        for name, qty in sorted(grouped[cat]):
            rows_html.append(f"<tr><td style='padding:4px 12px'>{name}</td><td align='right'>{qty}</td></tr>")
    table_html = (
        "<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse;font-family:sans-serif;'>"
        "<tr><th style='padding:4px 12px'>Item</th><th>Qty</th></tr>" + "".join(rows_html) + "</table>"
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = recipient

    msg.set_content("\n\n".join(filter(None, [before_txt.strip(), table_plain, after_txt.strip()])))
    body_html = "\n".join(filter(None, [f"<p>{_nl2br(before_txt.strip())}</p>" if before_txt.strip() else "", table_html, f"<p>{_nl2br(after_txt.strip())}</p>" if after_txt.strip() else ""]))
    msg.add_alternative(f"<html><body>{body_html}</body></html>", subtype="html")

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

# ---------- Initialize / reset inventory ----------

def load_template_into_inventory():
    st.session_state.inventory = {}
    for itm in load_template(profile):
        if not isinstance(itm, dict):
            st.warning(f"Skipping malformed template entry: {itm}")
            continue
        name, tag = itm.get("name"), itm.get("tag", CATEGORIES[0])
        if name:
            st.session_state.inventory[make_key(name, tag)] = {"qty": 0}
    st.session_state.inventory_profile = profile

if (
    "inventory" not in st.session_state
    or st.session_state.get("inventory_profile") != profile
    or not st.session_state.inventory
):
    load_template_into_inventory()

# ---------- Template buttons ----------
col_reset, col_save = st.columns([1, 1])
with col_reset:
    if st.button("Reset to template items", type="secondary"):
        load_template_into_inventory()
with col_save:
    if st.button("Save current list as template", type="primary"):
        tpl_items = [{"name": split_key(k)[0], "tag": split_key(k)[1]} for k in st.session_state.inventory.keys()]
        save_template(profile, tpl_items)
        st.success("Template saved!")

st.divider()

# ---------- Add item row ----------

def add_item_cb():
    name = st.session_state.get("new_item", "").strip()
    qty = int(st.session_state.get("new_qty", 0))
    tag = st.session_state.get("new_tag", CATEGORIES[0])
    if not name:
        return
    key = make_key(name, tag)
    st.session_state.inventory.setdefault(key, {"qty": 0})["qty"] += qty
    st.session_state["new_item"], st.session_state["new_qty"] = "", 0

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
    for key in sorted(st.session_state.inventory.keys(), key=lambda k
