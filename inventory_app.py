# inventory_app.py – Multi‑producer inventory & email app
# v4.5 – UI now groups items by tag (category) just like the e‑mail does
"""
Major change
------------
* **Inventory table is grouped by tag**: items are shown under bold section
  headers in the same order as `CATEGORIES`, matching the grouping in the
  outgoing e‑mail.
* No behaviour changes elsewhere (template load/save, duplicate handling,
  grouped e‑mail, etc.).
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
# 0.  Configuration  ░ SMTP + producer profiles
# ─────────────────────────────────────────────────────────────
SECRETS = st.secrets.get("smtp", {})
SMTP_HOST = SECRETS.get("host") or os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(SECRETS.get("port") or os.getenv("SMTP_PORT", 465))
SMTP_USER = SECRETS.get("user") or os.getenv("SMTP_USER")
SMTP_PASS = SECRETS.get("pass") or os.getenv("SMTP_PASS")

if not (SMTP_USER and SMTP_PASS):
    st.warning("⚠️  Configure SMTP credentials in Secrets or env vars to enable e‑mail.")

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
    "Arbor Teas": {
        "categories": ["Market", "Cafe", "Freezer"],
        "default_subject": "Arbor Teas – Inventory",
        "default_recipient": "",
       "mainstays": []
    },
}

TEMPLATE_DIR = Path.cwd() / "templates"
TEMPLATE_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 1.  Helpers
# ─────────────────────────────────────────────────────────────
SEP = "~~~"
make_key = lambda n, t: f"{n.strip()}{SEP}{t}"
split_key = lambda k: k.rsplit(SEP, 1)
slugify = lambda s: "_".join(s.lower().split())

def template_path(profile: str) -> Path:
    return TEMPLATE_DIR / f"{slugify(profile)}.json"

def load_template(profile: str) -> List[Dict[str, str]]:
    p = template_path(profile)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            return [d for d in data if isinstance(d, dict) and d.get("name")]
        except Exception as exc:
            st.error(f"⚠️ Could not parse {p}: {exc}")
    return PRODUCERS.get(profile, {}).get("mainstays", [])

def save_template(profile: str, items: List[Dict[str, str]]):
    try:
        template_path(profile).write_text(json.dumps(items, indent=2))
    except Exception as exc:
        st.error(f"Template save failed: {exc}")

_nl2br = lambda s: s.replace("\n", "<br>") if s else ""

# ─────────────────────────────────────────────────────────────
# 2.  E‑mail (unchanged from v4.4)
# ─────────────────────────────────────────────────────────────

def send_email(*, recipient: str, inventory: Dict[str, Dict[str, Any]], categories: List[str], subject: str, before_txt: str, after_txt: str) -> None:
    grouped: Dict[str, List[Tuple[str, int]]] = {cat: [] for cat in categories}
    for k, v in inventory.items():
        name, tag = split_key(k)
        grouped.setdefault(tag, []).append((name, v["qty"]))

    rows_plain: List[str] = []
    for cat in categories + [c for c in grouped if c not in categories]:
        if not grouped[cat]:
            continue
        rows_plain.extend([f"=== {cat} ===", "Item\tQuantity"])
        rows_plain.extend([f"{n}\t{q}" for n, q in sorted(grouped[cat])])
        rows_plain.append("")
    table_plain = "\n".join(rows_plain).strip()

    rows_html: List[str] = []
    for cat in categories + [c for c in grouped if c not in categories]:
        if not grouped[cat]:
            continue
        rows_html.append(f"<tr style='background:#f3f3f3;font-weight:bold;'><td colspan='2' style='padding:6px 12px'>{cat}</td></tr>")
        for n, q in sorted(grouped[cat]):
            rows_html.append(f"<tr><td style='padding:4px 12px'>{n}</td><td align='right'>{q}</td></tr>")
    table_html = (
        "<table border='1' cellspacing='0' cellpadding='4' style='border-collapse:collapse;font-family:sans-serif;'>"
        "<tr><th style='padding:4px 12px'>Item</th><th>Qty</th></tr>" + "".join(rows_html) + "</table>"
    )

    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, SMTP_USER, recipient
    msg.set_content("\n\n".join(filter(None, [before_txt.strip(), table_plain, after_txt.strip()])))
    msg.add_alternative(f"<html><body>{_nl2br(before_txt)}{table_html}{_nl2br(after_txt)}</body></html>", subtype="html")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS); smtp.send_message(msg)

# ─────────────────────────────────────────────────────────────
# 3.  Streamlit UI
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Inventory Counter",
    page_icon="logo.png",          # favicon in the browser tab
    layout="wide",
)




# Profile selector
profile_names = list(PRODUCERS)
profile = st.selectbox("Producer profile", profile_names, index=profile_names.index(st.session_state.get("profile", profile_names[0])))
st.session_state.profile = profile
CFG, CATEGORIES = PRODUCERS[profile], PRODUCERS[profile]["categories"]



# ‼️ Place logo.png in the same folder as inventory_app.py
LOGO_FILE = "logo.png"             # or a full URL

# One narrow column for the logo, one wide for the title
logo_col, title_col = st.columns([1, 8])   # tweak the 1/8 ratio as you like
with logo_col:
    st.image(LOGO_FILE, width=80)          # width≈80-120 px feels right
with title_col:
    st.title(f" Inventory Counter – {profile}")



# Load template into session_state.inventory
if "inventory" not in st.session_state or st.session_state.get("inventory_profile") != profile:
    st.session_state.inventory = {make_key(itm["name"], itm.get("tag", CATEGORIES[0])): {"qty": 0} for itm in load_template(profile)}
    st.session_state.inventory_profile = profile

# Template buttons
col_reset, col_save = st.columns([1, 1])
if col_reset.button("Reset to template items", type="secondary"):
    st.session_state.inventory = {make_key(itm["name"], itm.get("tag", CATEGORIES[0])): {"qty": 0} for itm in load_template(profile)}
if col_save.button("Save current list as template", type="primary"):
    save_template(profile, [{"name": split_key(k)[0], "tag": split_key(k)[1]} for k in st.session_state.inventory])
    st.success("Template saved!")

st.divider()

# Add‑item row

def add_item_cb():
    name, qty = st.session_state.get("new_item", "").strip(), int(st.session_state.get("new_qty", 0))
    tag = st.session_state.get("new_tag", CATEGORIES[0])
    if name:
        st.session_state.inventory.setdefault(make_key(name, tag), {"qty": 0})["qty"] += qty
    st.session_state["new_item"], st.session_state["new_qty"] = "", 0

c1, c2, c3, c4 = st.columns([3, 1, 3, 1])
with c1: st.text_input("Item", key="new_item", placeholder="e.g. Blueberry Muffin")
with c2: st.number_input("Qty", key="new_qty", min_value=0, step=1, format="%d")
with c3: st.selectbox("Tag", key="new_tag", options=CATEGORIES)
with c4: st.button("Add", on_click=add_item_cb, use_container_width=True)

st.divider()

# Grouped inventory table
if st.session_state.inventory:
    st.subheader("Current Inventory")
    for cat in CATEGORIES:
        cat_keys = [k for k in st.session_state.inventory if split_key(k)[1] == cat]
        if not cat_keys:
            continue
        st.markdown(f"### {cat}")
        for key in sorted(cat_keys, key=lambda k: split_key(k)[0].lower()):
            name, tag = split_key(key);
            qty = st.session_state.inventory[key]["qty"]
            p, m, d, nm, qt, tg = st.columns([1, 1, 1, 4, 2, 3])
            if p.button("➕", key=f"plus_{key}"): st.session_state.inventory[key]["qty"] += 1
            if m.button("➖", key=f"minus_{key}"): st.session_state.inventory[key]["qty"] = max(0, qty - 1)
            if d.button("🗑️", key=f"del_{key}"): st.session_state.inventory.pop(key); st.experimental_rerun()
            nm.write(name)
            new_q = qt.number_input(" ", value=qty, min_value=0, step=1, key=f"num_{key}", label_visibility="collapsed")
            st.session_state.inventory[key]["qty"] = int(new_q)
            new_tag = tg.selectbox(" ", options=CATEGORIES, index=CATEGORIES.index(tag), key=f"tag_{key}", label_visibility="collapsed")
            if new_tag != tag:
                new_key = make_key(name, new_tag)
                st.session_state.inventory.setdefault(new_key, {"qty": 0})["qty"] += st.session_state.inventory[key]["qty"]
                st.session_state.inventory.pop(key);
                st.experimental_rerun()
    st.divider()
    if st.button("Clear list 🗑️", type="secondary"): st.session_state.inventory.clear()
else:
    st.info("Add some items to get started.")

st.divider()

# Email config & send
subject = st.text_input("E‑mail subject", value=CFG.get("default_subject", "Inventory Report"))
msg_before = st.text_area("Text before table (optional)")
msg_after = st.text_area("Text after table (optional)")
recipient = st.text_input("Recipient e‑mail", value=CFG.get("default_recipient", ""))

ready = bool(recipient.strip()) and any(v["qty"] > 0 for v in st.session_state.inventory.values())
if st.button("Send Inventory Report ✉️", disabled=not ready):
    try:
        send_email(recipient=recipient.strip(), inventory=st.session_state.inventory, categories=CATEGORIES, subject=subject.strip(), before_txt=msg_before, after_txt=msg_after)
    except Exception as exc:
        st.error(f"Failed to send: {exc}")
    else:
        st.success("Report sent!")
