# inventory_app.py – Multi‑producer inventory & email app (template editor – **v4.1**)
"""
Fixes – templates & buttons not appearing
----------------------------------------
* **TEMPLATE_DIR** now defaults to *current working directory* (`Path.cwd()/templates`) so you can drop JSON files next to the app without worrying about import paths.
* Template autoload now triggers if the inventory is **missing *or empty***, ensuring built‑in mainstays appear on first load.
* Added a subtle info message if no template is found (so it’s obvious why nothing shows up).
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

# Directory where user‑editable templates live (cwd so users can drop files easily)
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
# 2.  E‑mail composer (unchanged)
# ─────────────────────────────────────────────────────────────
#   … (identical to previous version) …

# ─────────────────────────────────────────────────────────────
# 3.  Streamlit UI (only the loading logic tweaked)
# ─────────────────────────────────────────────────────────────

st.set_page_config(page_title="Inventory Counter", page_icon="📋", layout="wide")

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
        st.session_state.inventory[make_key(itm["name"], itm["tag"])] = {"qty": 0}
    st.session_state.inventory_profile = profile

if (
    "inventory" not in st.session_state
    or st.session_state.get("inventory_profile") != profile
    or not st.session_state.inventory  # inventory empty → reload defaults
):
    load_template_into_inventory()

# Template control buttons (unchanged)
#   …
