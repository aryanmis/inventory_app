# inventory_app.py — Multi-producer inventory app (DB-backed, front-end template builder)
# v5.1 — UI-only producer/template creation; add/delete items; refined email output; workflow bug fixes

from __future__ import annotations

import os
import re
import sqlite3
import datetime as dt
from typing import Dict, List, Optional, Tuple

import streamlit as st

# Optional email
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ──────────────────────────────────────────────────────────────────────────────
# App config
# ──────────────────────────────────────────────────────────────────────────────

APP_TITLE = "Inventory App"
DB_PATH = os.environ.get("INVENTORY_DB_PATH", "inventory.db")

st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)

# --- UI CSS fixes (buttons, number inputs, wrapping) ---
st.markdown(
    """
    <style>
      /* Prevent button label wrapping (fixes "Delet e") */
      .stButton > button {
        white-space: nowrap !important;
      }

      /* Make small buttons look consistent (quick +/- buttons) */
      .stButton > button {
        min-height: 44px;
        padding: 0.35rem 0.65rem;
        border-radius: 10px;
      }

      /* Make column-contained buttons actually fill their column cleanly */
      .stButton > button {
        width: 100%;
      }

      /* Tighten number input width so it doesn't look like a giant slider */
      div[data-testid="stNumberInput"] {
        max-width: 180px;
      }
      div[data-testid="stNumberInput"] input {
        text-align: center;
        font-weight: 600;
      }

      /* Reduce vertical whitespace between item rows */
      div[data-testid="stHorizontalBlock"] {
        gap: 0.75rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS producers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                default_recipient TEXT NOT NULL DEFAULT '',
                default_subject_prefix TEXT NOT NULL DEFAULT 'Inventory',
                archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                producer_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(producer_id, name),
                FOREIGN KEY(producer_id) REFERENCES producers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                producer_id INTEGER NOT NULL,
                section_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                unit TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(producer_id) REFERENCES producers(id) ON DELETE CASCADE,
                FOREIGN KEY(section_id) REFERENCES sections(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_items_producer ON items(producer_id);
            CREATE INDEX IF NOT EXISTS idx_items_section ON items(section_id);

            CREATE TABLE IF NOT EXISTS counts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                producer_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress', -- in_progress, completed
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(producer_id) REFERENCES producers(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS count_lines (
                count_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                qty INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(count_id, item_id),
                FOREIGN KEY(count_id) REFERENCES counts(id) ON DELETE CASCADE,
                FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
            );
            """
        )


init_db()


# ──────────────────────────────────────────────────────────────────────────────
# Data access layer
# ──────────────────────────────────────────────────────────────────────────────

def list_producers(include_archived: bool = False) -> List[sqlite3.Row]:
    q = "SELECT * FROM producers"
    if not include_archived:
        q += " WHERE archived=0"
    q += " ORDER BY lower(name)"
    with db() as conn:
        return conn.execute(q).fetchall()


def get_producer(producer_id: int) -> Optional[sqlite3.Row]:
    with db() as conn:
        return conn.execute("SELECT * FROM producers WHERE id=?", (producer_id,)).fetchone()


def create_producer(name: str, default_recipient: str, default_subject_prefix: str) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO producers(name, default_recipient, default_subject_prefix, created_at) VALUES (?,?,?,?)",
            (name.strip(), default_recipient.strip(), (default_subject_prefix.strip() or "Inventory"), now_iso()),
        )
        return int(cur.lastrowid)


def update_producer(producer_id: int, name: str, default_recipient: str, default_subject_prefix: str, archived: bool) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE producers
            SET name=?, default_recipient=?, default_subject_prefix=?, archived=?
            WHERE id=?
            """,
            (name.strip(), default_recipient.strip(), (default_subject_prefix.strip() or "Inventory"), 1 if archived else 0, producer_id),
        )


def list_sections(producer_id: int, active_only: bool = True) -> List[sqlite3.Row]:
    q = "SELECT * FROM sections WHERE producer_id=?"
    params = [producer_id]
    if active_only:
        q += " AND active=1"
    q += " ORDER BY sort_order, lower(name)"
    with db() as conn:
        return conn.execute(q, params).fetchall()


def create_section(producer_id: int, name: str, sort_order: int) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO sections(producer_id, name, sort_order, active) VALUES (?,?,?,1)",
            (producer_id, name.strip(), int(sort_order)),
        )
        return int(cur.lastrowid)


def update_section(section_id: int, name: str, sort_order: int, active: bool) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE sections SET name=?, sort_order=?, active=? WHERE id=?",
            (name.strip(), int(sort_order), 1 if active else 0, section_id),
        )


def delete_section(section_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM sections WHERE id=?", (section_id,))


def section_item_count(section_id: int) -> int:
    with db() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM items WHERE section_id=?", (section_id,)).fetchone()
        return int(row["c"])


def list_items(producer_id: int, include_inactive: bool = False) -> List[sqlite3.Row]:
    q = """
        SELECT items.*, sections.name AS section_name, sections.sort_order AS section_sort
        FROM items
                 JOIN sections ON sections.id = items.section_id
        WHERE items.producer_id=? \
        """
    params = [producer_id]
    if not include_inactive:
        q += " AND items.active=1 AND sections.active=1"
    q += " ORDER BY section_sort, lower(sections.name), items.sort_order, lower(items.name)"
    with db() as conn:
        return conn.execute(q, params).fetchall()


def list_items_by_section(producer_id: int, include_inactive: bool = False) -> Dict[int, List[sqlite3.Row]]:
    items = list_items(producer_id, include_inactive=include_inactive)
    out: Dict[int, List[sqlite3.Row]] = {}
    for it in items:
        out.setdefault(int(it["section_id"]), []).append(it)
    return out


def create_item(
        producer_id: int,
        section_id: int,
        name: str,
        unit: str = "",
        notes: str = "",
        sort_order: int = 0,
) -> int:
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO items(producer_id, section_id, name, unit, notes, active, sort_order, created_at)
            VALUES (?,?,?,?,?,1,?,?)
            """,
            (producer_id, section_id, name.strip(), unit.strip(), notes.strip(), int(sort_order), now_iso()),
        )
        return int(cur.lastrowid)


def update_item(item_id: int, section_id: int, name: str, unit: str, notes: str, active: bool, sort_order: int) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE items
            SET section_id=?, name=?, unit=?, notes=?, active=?, sort_order=?
            WHERE id=?
            """,
            (section_id, name.strip(), unit.strip(), notes.strip(), 1 if active else 0, int(sort_order), item_id),
        )


def delete_item(item_id: int) -> None:
    # Cascades to count_lines because of FK constraints
    with db() as conn:
        conn.execute("DELETE FROM items WHERE id=?", (item_id,))


def create_new_count(producer_id: int) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO counts(producer_id, status, created_at, updated_at) VALUES (?,?,?,?)",
            (producer_id, "in_progress", now_iso(), now_iso()),
        )
        return int(cur.lastrowid)


def start_or_resume_count(producer_id: int) -> int:
    """Return the in-progress count id if exists, else create new."""
    with db() as conn:
        row = conn.execute(
            """
            SELECT id FROM counts
            WHERE producer_id=? AND status='in_progress'
            ORDER BY datetime(created_at) DESC
                LIMIT 1
            """,
            (producer_id,),
        ).fetchone()
        if row:
            return int(row["id"])
    return create_new_count(producer_id)


def get_count(count_id: int) -> Optional[sqlite3.Row]:
    with db() as conn:
        return conn.execute("SELECT * FROM counts WHERE id=?", (count_id,)).fetchone()


def list_recent_counts(producer_id: int, limit: int = 30) -> List[sqlite3.Row]:
    with db() as conn:
        return conn.execute(
            """
            SELECT * FROM counts
            WHERE producer_id=?
            ORDER BY datetime(created_at) DESC
                LIMIT ?
            """,
            (producer_id, int(limit)),
        ).fetchall()


def set_count_status(count_id: int, status: str) -> None:
    with db() as conn:
        conn.execute("UPDATE counts SET status=?, updated_at=? WHERE id=?", (status, now_iso(), count_id))


def load_count_lines(count_id: int) -> Dict[int, int]:
    with db() as conn:
        rows = conn.execute("SELECT item_id, qty FROM count_lines WHERE count_id=?", (count_id,)).fetchall()
    return {int(r["item_id"]): int(r["qty"]) for r in rows}


def upsert_count_line(count_id: int, item_id: int, qty: int) -> None:
    qty_i = int(qty)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO count_lines(count_id, item_id, qty, updated_at)
            VALUES (?,?,?,?)
                ON CONFLICT(count_id, item_id) DO UPDATE SET
                qty=excluded.qty,
                                                      updated_at=excluded.updated_at
            """,
            (count_id, item_id, qty_i, now_iso()),
        )
        conn.execute("UPDATE counts SET updated_at=? WHERE id=?", (now_iso(), count_id))


# ──────────────────────────────────────────────────────────────────────────────
# Email
# ──────────────────────────────────────────────────────────────────────────────

def sanitize_subject(s: str) -> str:
    return re.sub(r"[\r\n]+", " ", (s or "").strip())


def build_grouped_report_rows(
        *,
        producer_id: int,
        count_id: int
) -> List[Tuple[str, List[Tuple[str, int]]]]:
    """
    Returns rows grouped by section name:
        [(section_name, [(item_name, qty), ...]), ...]
    Excludes qty <= 0, excludes empty sections, sorts by section sort_order then name.
    """
    sections = list_sections(producer_id, active_only=True)
    section_meta = {int(s["id"]): (int(s["sort_order"]), str(s["name"])) for s in sections}

    qty_map = load_count_lines(count_id)
    items = list_items(producer_id, include_inactive=False)

    grouped: Dict[int, List[Tuple[str, int]]] = {}
    for it in items:
        item_id = int(it["id"])
        qty = int(qty_map.get(item_id, 0))
        if qty <= 0:
            continue
        grouped.setdefault(int(it["section_id"]), []).append((str(it["name"]), qty))

    # Convert to ordered list; drop empty sections automatically
    rows: List[Tuple[str, List[Tuple[str, int]]]] = []
    for sid, item_pairs in grouped.items():
        _, sec_name = section_meta.get(sid, (999999, "Other"))
        item_pairs_sorted = sorted(item_pairs, key=lambda x: x[0].lower())
        rows.append((sec_name, item_pairs_sorted))

    # Sort sections by sort_order then name
    def sec_sort_key(section_name: str) -> Tuple[int, str]:
        # Find matching section id by name (unique per producer by constraint)
        for sid, (order, nm) in section_meta.items():
            if nm == section_name:
                return (order, nm.lower())
        return (999999, section_name.lower())

    rows.sort(key=lambda r: sec_sort_key(r[0]))
    return rows


def send_email_report(
        *,
        recipient: str,
        subject: str,
        before_txt: str,
        after_txt: str,
        grouped_rows: List[Tuple[str, List[Tuple[str, int]]]],
) -> None:
    """
    Uses SMTP credentials from environment variables:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM (optional, defaults SMTP_USER)
    """
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_from = os.environ.get("SMTP_FROM", "") or smtp_user

    if not (smtp_host and smtp_user and smtp_pass and smtp_from):
        raise RuntimeError(
            "Missing SMTP credentials. Set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS (and optionally SMTP_FROM)."
        )

    # Plain text (refined: no empty sections; no qty 0; clean formatting)
    lines: List[str] = []
    if before_txt.strip():
        lines.append(before_txt.strip())
        lines.append("")

    for section, items in grouped_rows:
        if not items:
            continue
        lines.append(f"{section}")
        lines.append("-" * len(section))
        for name, qty in items:
            lines.append(f"{name}: {qty}")
        lines.append("")

    if after_txt.strip():
        lines.append(after_txt.strip())

    body_plain = "\n".join(lines).strip()

    # HTML (refined)
    html_parts: List[str] = []
    if before_txt.strip():
        html_parts.append(f"<p>{before_txt.strip().replace('\\n', '<br/>')}</p>")

    html_parts.append(
        "<div style='font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;'>"
    )

    for section, items in grouped_rows:
        if not items:
            continue
        html_parts.append(f"<h3 style='margin:14px 0 8px 0;'>{section}</h3>")
        html_parts.append(
            "<table cellspacing='0' cellpadding='0' style='border-collapse:collapse; width:100%; max-width:700px;'>"
            "<tr>"
            "<th align='left' style='border-bottom:1px solid #ddd; padding:6px 8px;'>Item</th>"
            "<th align='right' style='border-bottom:1px solid #ddd; padding:6px 8px;'>Qty</th>"
            "</tr>"
        )
        for name, qty in items:
            html_parts.append(
                "<tr>"
                f"<td style='border-bottom:1px solid #f0f0f0; padding:6px 8px;'>{name}</td>"
                f"<td align='right' style='border-bottom:1px solid #f0f0f0; padding:6px 8px; font-weight:600;'>{qty}</td>"
                "</tr>"
            )
        html_parts.append("</table>")

    html_parts.append("</div>")

    if after_txt.strip():
        html_parts.append(f"<p>{after_txt.strip().replace('\\n', '<br/>')}</p>")

    body_html = "\n".join(html_parts)

    msg = MIMEMultipart("alternative")
    msg["To"] = recipient.strip()
    msg["From"] = smtp_from
    msg["Subject"] = sanitize_subject(subject)
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_from, [recipient.strip()], msg.as_string())


# ──────────────────────────────────────────────────────────────────────────────
# UI utilities
# ──────────────────────────────────────────────────────────────────────────────

def page_header(title: str, subtitle: str = "") -> None:
    st.subheader(title)
    if subtitle:
        st.caption(subtitle)


def require_producer_selected() -> Tuple[int, sqlite3.Row]:
    prods = list_producers(include_archived=False)
    if not prods:
        st.info("No producers yet. Go to **Producers** → **Create Producer** to set one up.")
        st.stop()

    producer_labels = [p["name"] for p in prods]
    producer_ids = [int(p["id"]) for p in prods]

    if "producer_id" not in st.session_state:
        st.session_state.producer_id = producer_ids[0]

    try:
        default_idx = producer_ids.index(st.session_state.producer_id)
    except ValueError:
        default_idx = 0
        st.session_state.producer_id = producer_ids[0]

    chosen = st.sidebar.selectbox("Producer", producer_labels, index=default_idx)
    chosen_id = producer_ids[producer_labels.index(chosen)]
    st.session_state.producer_id = chosen_id

    p = get_producer(chosen_id)
    if not p:
        st.error("Producer not found.")
        st.stop()
    return chosen_id, p


def confirm_button(key: str, label: str, confirm_label: str = "Confirm", cancel_label: str = "Cancel") -> bool:
    """
    Two-click confirm pattern to avoid accidental deletes.
    Returns True only when user hits Confirm on second step.
    """
    state_key = f"confirm__{key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = False

    if not st.session_state[state_key]:
        # Give the first button enough room
        if st.button(label, key=f"{key}__btn", use_container_width=False):
            st.session_state[state_key] = True
            st.rerun()
        return False

    # Wider, fixed layout so "Delete" never wraps
    cols = st.columns([2.2, 2.2, 10], vertical_alignment="center")
    did_confirm = False

    with cols[0]:
        if st.button(confirm_label, key=f"{key}__confirm", use_container_width=True):
            did_confirm = True
    with cols[1]:
        if st.button(cancel_label, key=f"{key}__cancel", use_container_width=True):
            st.session_state[state_key] = False
            st.rerun()

    if did_confirm:
        st.session_state[state_key] = False
        return True

    return False



# ──────────────────────────────────────────────────────────────────────────────
# Pages
# ──────────────────────────────────────────────────────────────────────────────

def page_producers() -> None:
    page_header("Producers", "Create and manage producers entirely in the app (no JSON/CSV).")

    colA, colB = st.columns([2, 3], vertical_alignment="top")

    with colA:
        st.markdown("### Existing producers")
        prods = list_producers(include_archived=True)
        if not prods:
            st.info("No producers yet.")
        else:
            for p in prods:
                status = " (archived)" if int(p["archived"]) == 1 else ""
                st.write(f"• **{p['name']}**{status}")

    with colB:
        st.markdown("### Create producer")
        with st.form("create_producer_form"):
            name = st.text_input("Producer name *")
            default_recipient = st.text_input("Default recipient email (optional)")
            default_subject_prefix = st.text_input("Default subject prefix", value="Inventory")
            submitted = st.form_submit_button("Create producer")

        if submitted:
            if not name.strip():
                st.error("Producer name is required.")
            else:
                try:
                    new_id = create_producer(name, default_recipient, default_subject_prefix)
                except sqlite3.IntegrityError:
                    st.error("That producer name already exists.")
                else:
                    st.success("Producer created.")
                    st.session_state.producer_id = new_id
                    st.rerun()

        st.divider()

        st.markdown("### Edit producer")
        prods_any = list_producers(include_archived=True)
        if not prods_any:
            st.stop()

        labels = [p["name"] for p in prods_any]
        ids = [int(p["id"]) for p in prods_any]
        pick = st.selectbox("Select producer to edit", labels, index=0)
        pid = ids[labels.index(pick)]
        p = get_producer(pid)
        if not p:
            st.stop()

        with st.form("edit_producer_form"):
            new_name = st.text_input("Name", value=p["name"])
            new_recipient = st.text_input("Default recipient", value=p["default_recipient"])
            new_prefix = st.text_input("Default subject prefix", value=p["default_subject_prefix"])
            archived = st.checkbox("Archived", value=(int(p["archived"]) == 1))
            ok = st.form_submit_button("Save changes")

        if ok:
            try:
                update_producer(pid, new_name, new_recipient, new_prefix, archived)
            except sqlite3.IntegrityError:
                st.error("Another producer already has that name.")
            else:
                st.success("Saved.")
                st.rerun()


def page_template_builder() -> None:
    producer_id, producer = require_producer_selected()
    page_header("Template Builder", f"Build tabs/sections and items for **{producer['name']}**.")

    st.markdown("## Sections (tabs)")

    sections_all = list_sections(producer_id, active_only=False)
    sections_active = [s for s in sections_all if int(s["active"]) == 1]

    c1, c2 = st.columns([2, 3], vertical_alignment="top")
    with c1:
        st.markdown("### Add section")
        with st.form("add_section_form"):
            sec_name = st.text_input("Section name *", placeholder="e.g., Cafe, Market, Freezer")
            sec_order = st.number_input("Sort order", min_value=0, step=1, value=(len(sections_all) * 10))
            add = st.form_submit_button("Add section")

        if add:
            if not sec_name.strip():
                st.error("Section name is required.")
            else:
                try:
                    create_section(producer_id, sec_name, int(sec_order))
                except sqlite3.IntegrityError:
                    st.error("That section already exists for this producer.")
                else:
                    st.success("Section added.")
                    st.rerun()

        st.divider()
        st.markdown("### Quick-add items (no CSV)")
        if not sections_active:
            st.info("Create at least one active section to quick-add items.")
        else:
            with st.form("quick_add_items"):
                sec_label = [s["name"] for s in sections_active]
                sec_ids = [int(s["id"]) for s in sections_active]
                chosen = st.selectbox("Add into section", sec_label, index=0)
                chosen_id = sec_ids[sec_label.index(chosen)]

                st.caption("One item per line. Optional: `Item name | unit | notes`")
                raw = st.text_area("Items", height=160, placeholder="Croissant | each | front case\nSourdough boule | each | bread rack")
                submit_quick = st.form_submit_button("Add items")

            if submit_quick:
                lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                if not lines:
                    st.error("No items entered.")
                else:
                    added = 0
                    for i, ln in enumerate(lines):
                        parts = [p.strip() for p in ln.split("|")]
                        nm = parts[0] if parts else ""
                        unit = parts[1] if len(parts) > 1 else ""
                        notes = parts[2] if len(parts) > 2 else ""
                        if nm:
                            create_item(producer_id, chosen_id, nm, unit=unit, notes=notes, sort_order=i * 10)
                            added += 1
                    st.success(f"Added {added} item(s).")
                    st.rerun()

    with c2:
        st.markdown("### Edit / delete sections")
        if not sections_all:
            st.info("No sections yet.")
        else:
            for s in sections_all:
                sid = int(s["id"])
                item_ct = section_item_count(sid)
                title = f"{s['name']}" + ("" if int(s["active"]) == 1 else " (inactive)")
                with st.expander(title, expanded=False):
                    with st.form(f"edit_section_{sid}"):
                        new_name = st.text_input("Name", value=s["name"], key=f"sec_name_{sid}")
                        new_order = st.number_input("Sort order", min_value=0, step=1, value=int(s["sort_order"]), key=f"sec_order_{sid}")
                        active = st.checkbox("Active", value=(int(s["active"]) == 1), key=f"sec_active_{sid}")
                        ok = st.form_submit_button("Save section")
                    if ok:
                        try:
                            update_section(sid, new_name, int(new_order), bool(active))
                        except sqlite3.IntegrityError:
                            st.error("A section with that name already exists for this producer.")
                        else:
                            st.success("Saved.")
                            st.rerun()

                    st.caption(f"Items in this section: {item_ct}")
                    if item_ct == 0:
                        if confirm_button(f"del_section_{sid}", "Delete section 🗑️", "Delete", "Keep"):
                            delete_section(sid)
                            st.success("Section deleted.")
                            st.rerun()
                    else:
                        st.caption("To delete this section, move or delete its items first (section must be empty).")

    st.divider()
    st.markdown("## Items")

    if not sections_active:
        st.info("Create at least one active section to add items.")
        return

    st.markdown("### Add item")
    with st.form("add_item_form"):
        sec_label = [s["name"] for s in sections_active]
        sec_ids = [int(s["id"]) for s in sections_active]
        chosen = st.selectbox("Section", sec_label, index=0)
        chosen_id = sec_ids[sec_label.index(chosen)]
        item_name = st.text_input("Item name *")
        unit = st.text_input("Unit (optional)", placeholder="each / case / lb / tray")
        notes = st.text_input("Notes (optional)", placeholder="Where stored / how to count")
        sort_order = st.number_input("Sort order", min_value=0, step=1, value=0)
        add_item = st.form_submit_button("Add item")

    if add_item:
        if not item_name.strip():
            st.error("Item name is required.")
        else:
            create_item(producer_id, chosen_id, item_name, unit=unit, notes=notes, sort_order=int(sort_order))
            st.success("Item added.")
            st.rerun()

    st.markdown("### Edit / delete items")
    items = list_items(producer_id, include_inactive=True)
    if not items:
        st.info("No items yet.")
        return

    # Section dropdown map (include inactive sections for editing/moving)
    sections_any = list_sections(producer_id, active_only=False)
    section_ids = [int(s["id"]) for s in sections_any]
    section_names = [str(s["name"]) + ("" if int(s["active"]) == 1 else " (inactive)") for s in sections_any]
    name_to_id = {nm: sid for nm, sid in zip(section_names, section_ids)}

    search = st.text_input("Search items", placeholder="Type to filter by name…").strip().lower()
    filtered = [it for it in items if search in it["name"].lower()] if search else items

    for it in filtered[:800]:
        item_id = int(it["id"])
        title = f"{it['name']}  —  {it['section_name']}" + ("" if int(it["active"]) == 1 else " (inactive)")
        with st.expander(title, expanded=False):
            with st.form(f"edit_item_{item_id}"):
                curr_section_id = int(it["section_id"])
                # Build a clean selected label
                curr_label = None
                for s in sections_any:
                    if int(s["id"]) == curr_section_id:
                        curr_label = str(s["name"]) + ("" if int(s["active"]) == 1 else " (inactive)")
                        break
                if curr_label is None:
                    curr_label = section_names[0]

                new_section_label = st.selectbox("Section", section_names, index=section_names.index(curr_label), key=f"it_sec_{item_id}")
                new_section_id = name_to_id[new_section_label]

                new_name = st.text_input("Name", value=it["name"], key=f"it_name_{item_id}")
                new_unit = st.text_input("Unit", value=it["unit"], key=f"it_unit_{item_id}")
                new_notes = st.text_input("Notes", value=it["notes"], key=f"it_notes_{item_id}")
                new_order = st.number_input("Sort order", min_value=0, step=1, value=int(it["sort_order"]), key=f"it_order_{item_id}")
                new_active = st.checkbox("Active", value=(int(it["active"]) == 1), key=f"it_active_{item_id}")
                ok = st.form_submit_button("Save item")

            if ok:
                update_item(item_id, new_section_id, new_name, new_unit, new_notes, bool(new_active), int(new_order))
                st.success("Saved.")
                st.rerun()

            st.divider()
            if confirm_button(f"del_item_{item_id}", "Delete item 🗑️", "Delete", "Keep"):
                delete_item(item_id)
                st.success("Item deleted.")
                st.rerun()


def page_count() -> None:
    producer_id, producer = require_producer_selected()
    page_header("Count", f"Manual weekly count for **{producer['name']}** (tabs generated from template).")

    # --- CSS just for this page (safe to include even if you also added global CSS) ---
    st.markdown(
        """
        <style>
          /* Prevent button text wrapping (fixes "Delet e") */
          .stButton > button { white-space: nowrap !important; }

          /* Make small buttons consistent and not too tall */
          .stButton > button {
            min-height: 44px;
            padding: 0.35rem 0.65rem;
            border-radius: 10px;
            width: 100%;
          }

          /* Keep qty number input compact */
          div[data-testid="stNumberInput"] { max-width: 180px; }
          div[data-testid="stNumberInput"] input {
            text-align: center;
            font-weight: 700;
          }

          /* Slightly reduce row whitespace */
          div[data-testid="stHorizontalBlock"] { gap: 0.75rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    sections = list_sections(producer_id, active_only=True)
    if not sections:
        st.info("No sections yet. Go to **Template Builder** to create tabs/sections.")
        st.stop()

    items_by_section = list_items_by_section(producer_id, include_inactive=False)
    if not any(items_by_section.values()):
        st.info("No items yet. Go to **Template Builder** to add items.")
        st.stop()

    # Count session
    count_id = start_or_resume_count(producer_id)
    count_row = get_count(count_id)
    if not count_row:
        st.error("Could not load count.")
        st.stop()

    lines = load_count_lines(count_id)

    # --- Header actions (no cramped buttons) ---
    top = st.columns([2.2, 2.2, 2.2, 5.4], vertical_alignment="center")
    with top[0]:
        st.metric("Count status", count_row["status"])
    with top[1]:
        st.caption("Created")
        st.write(count_row["created_at"])
    with top[2]:
        st.caption("Updated")
        st.write(count_row["updated_at"])
    with top[3]:
        a, b, c = st.columns([1.4, 1.6, 7], vertical_alignment="center")
        with a:
            if st.button("Mark complete ✅", use_container_width=True):
                set_count_status(count_id, "completed")
                st.success("Marked complete.")
                st.rerun()
        with b:
            if st.button("Start new count 🆕", use_container_width=True):
                # Complete current (if not already), then create a fresh count immediately
                if count_row["status"] != "completed":
                    set_count_status(count_id, "completed")
                new_id = create_new_count(producer_id)
                st.success(f"Started new count (#{new_id}).")
                st.rerun()

    st.divider()

    # --- Search ---
    search = st.text_input(
        "Search items (optional)",
        placeholder="Type to filter item names across tabs…",
    ).strip().lower()

    # --- Inline add missing item (persists) ---
    with st.expander("Add missing item (persists for future counts)", expanded=False):
        with st.form("inline_add_item"):
            sec_label = [s["name"] for s in sections]
            sec_ids = [int(s["id"]) for s in sections]
            chosen = st.selectbox("Section", sec_label, index=0)
            chosen_id = sec_ids[sec_label.index(chosen)]
            nm = st.text_input("Item name *", placeholder="New item name")
            unit = st.text_input("Unit (optional)", placeholder="each / case / lb / tray")
            notes = st.text_input("Notes (optional)", placeholder="Where stored / how to count")
            ok = st.form_submit_button("Add item")
        if ok:
            if not nm.strip():
                st.error("Item name is required.")
            else:
                create_item(producer_id, chosen_id, nm, unit=unit, notes=notes, sort_order=9999)
                st.success("Item added.")
                st.rerun()

    # --- Tabs ---
    tab_names = [s["name"] for s in sections]
    tabs = st.tabs(tab_names)

    for tab, section in zip(tabs, sections):
        sid = int(section["id"])
        items = items_by_section.get(sid, [])

        if search:
            items = [it for it in items if search in it["name"].lower()]

        with tab:
            st.markdown(f"### {section['name']}")
            if not items:
                st.caption("No matching items in this tab.")
                continue

            # Render each item row
            for it in items:
                item_id = int(it["id"])
                curr = int(lines.get(item_id, 0))

                # Better proportions: name | quick buttons | qty | spacer
                cols = st.columns([6, 3, 2, 1], vertical_alignment="center")

                with cols[0]:
                    label = it["name"]
                    if it["unit"].strip():
                        label += f"  ·  *{it['unit']}*"
                    st.write(label)
                    if it["notes"].strip():
                        st.caption(it["notes"])

                with cols[1]:
                    # Four equal square-ish quick buttons
                    b1, b2, b3, b4 = st.columns([1, 1, 1, 1])
                    if b1.button("+1", key=f"p1_{count_id}_{item_id}", use_container_width=True):
                        upsert_count_line(count_id, item_id, curr + 1)
                        st.rerun()
                    if b2.button("+5", key=f"p5_{count_id}_{item_id}", use_container_width=True):
                        upsert_count_line(count_id, item_id, curr + 5)
                        st.rerun()
                    if b3.button("-1", key=f"m1_{count_id}_{item_id}", use_container_width=True):
                        upsert_count_line(count_id, item_id, max(0, curr - 1))
                        st.rerun()
                    if b4.button("0", key=f"z_{count_id}_{item_id}", use_container_width=True):
                        upsert_count_line(count_id, item_id, 0)
                        st.rerun()

                with cols[2]:
                    new_qty = st.number_input(
                        "Qty",
                        min_value=0,
                        step=1,
                        value=curr,
                        key=f"qty_{count_id}_{item_id}",
                        label_visibility="collapsed",
                    )
                    if int(new_qty) != curr:
                        upsert_count_line(count_id, item_id, int(new_qty))

                with cols[3]:
                    st.caption("")  # spacer

    st.divider()
    st.markdown("## Send Report")

    grouped_rows = build_grouped_report_rows(producer_id=producer_id, count_id=count_id)

    default_subject = f"{producer['default_subject_prefix']} {producer['name']} {dt.date.today().strftime('%m.%d.%y')}"
    subject = st.text_input("Email subject", value=default_subject)
    recipient = st.text_input("Recipient email", value=producer["default_recipient"])
    before_txt = st.text_area("Text before report (optional)", height=80)
    after_txt = st.text_area("Text after report (optional)", height=80)

    if not grouped_rows:
        st.info("No nonzero quantities yet — items with qty 0 are automatically hidden from the email.")
        return

    if st.button("Send inventory report ✉️", disabled=not bool(recipient.strip())):
        try:
            send_email_report(
                recipient=recipient.strip(),
                subject=subject.strip(),
                before_txt=before_txt,
                after_txt=after_txt,
                grouped_rows=grouped_rows,
            )
        except Exception as exc:
            st.error(f"Failed to send: {exc}")
        else:
            st.success("Report sent!")



def page_history() -> None:
    producer_id, producer = require_producer_selected()
    page_header("History", f"Recent counts for **{producer['name']}**.")

    rows = list_recent_counts(producer_id, limit=50)
    if not rows:
        st.info("No counts yet.")
        return

    sections_any = list_sections(producer_id, active_only=False)
    sec_map = {int(s["id"]): str(s["name"]) for s in sections_any}

    for r in rows:
        cid = int(r["id"])
        with st.expander(f"Count #{cid} — {r['status']} — {r['created_at']}", expanded=False):
            qty_map = load_count_lines(cid)
            items_all = list_items(producer_id, include_inactive=True)

            grouped: Dict[str, List[Tuple[str, int]]] = {}
            for it in items_all:
                q = int(qty_map.get(int(it["id"]), 0))
                if q <= 0:
                    continue
                grouped.setdefault(sec_map.get(int(it["section_id"]), "Other"), []).append((it["name"], q))

            if not grouped:
                st.caption("No nonzero quantities recorded.")
                continue

            for sec_name in sorted(grouped.keys(), key=lambda x: x.lower()):
                st.markdown(f"#### {sec_name}")
                for nm, q in sorted(grouped[sec_name], key=lambda x: x[0].lower()):
                    st.write(f"- {nm}: **{q}**")


# ──────────────────────────────────────────────────────────────────────────────
# Navigation
# ──────────────────────────────────────────────────────────────────────────────

st.sidebar.header("Navigation")
page = st.sidebar.radio(
    "Go to",
    ["Count", "Template Builder", "Producers", "History"],
    index=0,
)

if page == "Count":
    page_count()
elif page == "Template Builder":
    page_template_builder()
elif page == "Producers":
    page_producers()
elif page == "History":
    page_history()
else:
    st.error("Unknown page.")
