from __future__ import annotations

import os
import re
import datetime as dt
from typing import Dict, List, Optional, Tuple

import streamlit as st

import psycopg2
import psycopg2.extras

# Optional email
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

APP_TITLE = "Inventory App"

st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)


# UI CSS: fixes button wrapping, header button sizing, compact qty input
st.markdown(
    """
    <style>
      /* Prevent button label wrapping (fixes "Delet e") */
      .stButton > button { white-space: nowrap !important; }

      /* Consistent buttons */
      .stButton > button {
        min-height: 44px;
        padding: 0.35rem 0.65rem;
        border-radius: 10px;
      }

      /* Keep qty number input compact */
      div[data-testid="stNumberInput"] { max-width: 180px; }
      div[data-testid="stNumberInput"] input {
        text-align: center;
        font-weight: 700;
      }

      /* Slightly reduce horizontal gap in rows */
      div[data-testid="stHorizontalBlock"] { gap: 0.75rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def page_header(title: str, subtitle: str = "") -> None:
    st.subheader(title)
    if subtitle:
        st.caption(subtitle)


def now_ts() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def get_database_url() -> str:
    # Prefer env var; fallback to Streamlit secrets
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            url = st.secrets.get("DATABASE_URL", "")
        except Exception:
            url = ""
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to Streamlit secrets:\n"
            'DATABASE_URL="postgresql://postgres:<PW>@db.<REF>.supabase.co:5432/postgres"'
        )
    return url


@st.cache_resource(show_spinner=False)
def get_conn():
    conn = psycopg2.connect(get_database_url())
    conn.autocommit = True
    return conn


def init_db() -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
                    CREATE TABLE IF NOT EXISTS producers (
                                                             id BIGSERIAL PRIMARY KEY,
                                                             name TEXT NOT NULL UNIQUE,
                                                             default_recipient TEXT NOT NULL DEFAULT '',
                                                             default_subject_prefix TEXT NOT NULL DEFAULT 'Inventory',
                                                             archived BOOLEAN NOT NULL DEFAULT FALSE,
                                                             created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        );
                    """)

        cur.execute("""
                    CREATE TABLE IF NOT EXISTS sections (
                                                            id BIGSERIAL PRIMARY KEY,
                                                            producer_id BIGINT NOT NULL REFERENCES producers(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        sort_order INT NOT NULL DEFAULT 0,
                        active BOOLEAN NOT NULL DEFAULT TRUE,
                        UNIQUE(producer_id, name)
                        );
                    """)

        cur.execute("""
                    CREATE TABLE IF NOT EXISTS items (
                                                         id BIGSERIAL PRIMARY KEY,
                                                         producer_id BIGINT NOT NULL REFERENCES producers(id) ON DELETE CASCADE,
                        section_id BIGINT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        unit TEXT NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        active BOOLEAN NOT NULL DEFAULT TRUE,
                        sort_order INT NOT NULL DEFAULT 0,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        );
                    """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_items_producer ON items(producer_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_items_section ON items(section_id);")

        cur.execute("""
                    CREATE TABLE IF NOT EXISTS counts (
                                                          id BIGSERIAL PRIMARY KEY,
                                                          producer_id BIGINT NOT NULL REFERENCES producers(id) ON DELETE CASCADE,
                        status TEXT NOT NULL DEFAULT 'in_progress',  -- in_progress, completed
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        note TEXT NOT NULL DEFAULT ''
                        );
                    """)

        cur.execute("""
                    CREATE TABLE IF NOT EXISTS count_lines (
                                                               count_id BIGINT NOT NULL REFERENCES counts(id) ON DELETE CASCADE,
                        item_id BIGINT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                        qty INT NOT NULL DEFAULT 0,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY(count_id, item_id)
                        );
                    """)


init_db()


# ──────────────────────────────────────────────────────────────────────────────
# DB helpers (Postgres)
# ──────────────────────────────────────────────────────────────────────────────

def qfetchall(sql: str, params: Tuple = ()) -> List[Dict]:
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def qfetchone(sql: str, params: Tuple = ()) -> Optional[Dict]:
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def qexecute(sql: str, params: Tuple = ()) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, params)


def qinsert_returning_id(sql: str, params: Tuple = ()) -> int:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rid = cur.fetchone()[0]
        return int(rid)


# Producers
def list_producers(include_archived: bool = False) -> List[Dict]:
    if include_archived:
        return qfetchall("SELECT * FROM producers ORDER BY lower(name)")
    return qfetchall("SELECT * FROM producers WHERE archived=false ORDER BY lower(name)")


def get_producer(producer_id: int) -> Optional[Dict]:
    return qfetchone("SELECT * FROM producers WHERE id=%s", (producer_id,))


def create_producer(name: str, default_recipient: str, default_subject_prefix: str) -> int:
    return qinsert_returning_id(
        """
        INSERT INTO producers(name, default_recipient, default_subject_prefix)
        VALUES (%s,%s,%s)
            RETURNING id
        """,
        (name.strip(), default_recipient.strip(), (default_subject_prefix.strip() or "Inventory")),
    )


def update_producer(producer_id: int, name: str, default_recipient: str, default_subject_prefix: str, archived: bool) -> None:
    qexecute(
        """
        UPDATE producers
        SET name=%s, default_recipient=%s, default_subject_prefix=%s, archived=%s
        WHERE id=%s
        """,
        (name.strip(), default_recipient.strip(), (default_subject_prefix.strip() or "Inventory"), bool(archived), producer_id),
    )


# Sections
def list_sections(producer_id: int, active_only: bool = True) -> List[Dict]:
    if active_only:
        return qfetchall(
            "SELECT * FROM sections WHERE producer_id=%s AND active=true ORDER BY sort_order, lower(name)",
            (producer_id,),
        )
    return qfetchall(
        "SELECT * FROM sections WHERE producer_id=%s ORDER BY sort_order, lower(name)",
        (producer_id,),
    )


def create_section(producer_id: int, name: str, sort_order: int) -> int:
    return qinsert_returning_id(
        """
        INSERT INTO sections(producer_id, name, sort_order, active)
        VALUES (%s,%s,%s,true)
            RETURNING id
        """,
        (producer_id, name.strip(), int(sort_order)),
    )


def update_section(section_id: int, name: str, sort_order: int, active: bool) -> None:
    qexecute(
        "UPDATE sections SET name=%s, sort_order=%s, active=%s WHERE id=%s",
        (name.strip(), int(sort_order), bool(active), section_id),
    )


def section_item_count(section_id: int) -> int:
    row = qfetchone("SELECT COUNT(*)::int AS c FROM items WHERE section_id=%s", (section_id,))
    return int(row["c"]) if row else 0


def delete_section(section_id: int) -> None:
    qexecute("DELETE FROM sections WHERE id=%s", (section_id,))


# Items
def list_items(producer_id: int, include_inactive: bool = False) -> List[Dict]:
    base = """
           SELECT items.*, sections.name AS section_name, sections.sort_order AS section_sort
           FROM items
                    JOIN sections ON sections.id = items.section_id
           WHERE items.producer_id=%s \
           """
    if not include_inactive:
        base += " AND items.active=true AND sections.active=true"
    base += " ORDER BY section_sort, lower(sections.name), items.sort_order, lower(items.name)"
    return qfetchall(base, (producer_id,))


def list_items_by_section(producer_id: int, include_inactive: bool = False) -> Dict[int, List[Dict]]:
    items = list_items(producer_id, include_inactive=include_inactive)
    out: Dict[int, List[Dict]] = {}
    for it in items:
        out.setdefault(int(it["section_id"]), []).append(it)
    return out


def create_item(producer_id: int, section_id: int, name: str, unit: str = "", notes: str = "", sort_order: int = 0) -> int:
    return qinsert_returning_id(
        """
        INSERT INTO items(producer_id, section_id, name, unit, notes, active, sort_order)
        VALUES (%s,%s,%s,%s,%s,true,%s)
            RETURNING id
        """,
        (producer_id, section_id, name.strip(), unit.strip(), notes.strip(), int(sort_order)),
    )


def update_item(item_id: int, section_id: int, name: str, unit: str, notes: str, active: bool, sort_order: int) -> None:
    qexecute(
        """
        UPDATE items
        SET section_id=%s, name=%s, unit=%s, notes=%s, active=%s, sort_order=%s
        WHERE id=%s
        """,
        (section_id, name.strip(), unit.strip(), notes.strip(), bool(active), int(sort_order), item_id),
    )


def delete_item(item_id: int) -> None:
    qexecute("DELETE FROM items WHERE id=%s", (item_id,))


# Counts
def create_new_count(producer_id: int) -> int:
    return qinsert_returning_id(
        "INSERT INTO counts(producer_id, status) VALUES (%s,'in_progress') RETURNING id",
        (producer_id,),
    )


def start_or_resume_count(producer_id: int) -> int:
    row = qfetchone(
        """
        SELECT id FROM counts
        WHERE producer_id=%s AND status='in_progress'
        ORDER BY created_at DESC
            LIMIT 1
        """,
        (producer_id,),
    )
    if row:
        return int(row["id"])
    return create_new_count(producer_id)


def get_count(count_id: int) -> Optional[Dict]:
    return qfetchone("SELECT * FROM counts WHERE id=%s", (count_id,))


def set_count_status(count_id: int, status: str) -> None:
    qexecute("UPDATE counts SET status=%s, updated_at=NOW() WHERE id=%s", (status, count_id))


def list_recent_counts(producer_id: int, limit: int = 50) -> List[Dict]:
    return qfetchall(
        """
        SELECT * FROM counts
        WHERE producer_id=%s
        ORDER BY created_at DESC
            LIMIT %s
        """,
        (producer_id, int(limit)),
    )


def load_count_lines(count_id: int) -> Dict[int, int]:
    rows = qfetchall("SELECT item_id, qty FROM count_lines WHERE count_id=%s", (count_id,))
    return {int(r["item_id"]): int(r["qty"]) for r in rows}


def upsert_count_line(count_id: int, item_id: int, qty: int) -> None:
    qexecute(
        """
        INSERT INTO count_lines(count_id, item_id, qty, updated_at)
        VALUES (%s,%s,%s,NOW())
            ON CONFLICT (count_id, item_id) DO UPDATE SET
            qty=EXCLUDED.qty,
                                                   updated_at=NOW()
        """,
        (count_id, item_id, int(qty)),
    )
    qexecute("UPDATE counts SET updated_at=NOW() WHERE id=%s", (count_id,))


# ──────────────────────────────────────────────────────────────────────────────
# Email + report building
# ──────────────────────────────────────────────────────────────────────────────

def sanitize_subject(s: str) -> str:
    return re.sub(r"[\r\n]+", " ", (s or "").strip())


def build_grouped_report_rows(producer_id: int, count_id: int) -> List[Tuple[str, List[Tuple[str, int]]]]:
    """
    [(section_name, [(item_name, qty), ...]), ...]
    - excludes qty <= 0
    - excludes empty sections
    - sorts sections by sort_order then name
    - sorts items by name
    """
    sections = list_sections(producer_id, active_only=True)
    sec_meta = {int(s["id"]): (int(s["sort_order"]), str(s["name"])) for s in sections}

    qty_map = load_count_lines(count_id)
    items = list_items(producer_id, include_inactive=False)

    grouped: Dict[int, List[Tuple[str, int]]] = {}
    for it in items:
        q = int(qty_map.get(int(it["id"]), 0))
        if q <= 0:
            continue
        grouped.setdefault(int(it["section_id"]), []).append((str(it["name"]), q))

    rows: List[Tuple[str, List[Tuple[str, int]]]] = []
    for sid, pairs in grouped.items():
        _, sec_name = sec_meta.get(sid, (999999, "Other"))
        rows.append((sec_name, sorted(pairs, key=lambda x: x[0].lower())))

    def sec_key(sec_name: str) -> Tuple[int, str]:
        for sid, (order, nm) in sec_meta.items():
            if nm == sec_name:
                return (order, nm.lower())
        return (999999, sec_name.lower())

    rows.sort(key=lambda r: sec_key(r[0]))
    return rows


def send_email_report(
        *,
        recipient: str,
        subject: str,
        before_txt: str,
        after_txt: str,
        grouped_rows: List[Tuple[str, List[Tuple[str, int]]]],
) -> None:
    smtp_host = os.environ.get("SMTP_HOST") or st.secrets.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT") or st.secrets.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER") or st.secrets.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS") or st.secrets.get("SMTP_PASS", "")
    smtp_from = os.environ.get("SMTP_FROM") or st.secrets.get("SMTP_FROM", "") or smtp_user

    if not (smtp_host and smtp_user and smtp_pass and smtp_from):
        raise RuntimeError("Missing SMTP credentials in secrets/env (SMTP_HOST/PORT/USER/PASS[/FROM]).")

    # Plain text (no zeros, no empty sections)
    lines: List[str] = []
    if before_txt.strip():
        lines.append(before_txt.strip())
        lines.append("")

    for section, items in grouped_rows:
        if not items:
            continue
        lines.append(section)
        lines.append("-" * len(section))
        for name, qty in items:
            lines.append(f"{name}: {qty}")
        lines.append("")

    if after_txt.strip():
        lines.append(after_txt.strip())

    body_plain = "\n".join(lines).strip()

    # HTML
    html_parts: List[str] = []
    if before_txt.strip():
        html_parts.append(f"<p>{before_txt.strip().replace('\\n', '<br/>')}</p>")

    html_parts.append("<div style='font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;'>")
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
                f"<td align='right' style='border-bottom:1px solid #f0f0f0; padding:6px 8px; font-weight:700;'>{qty}</td>"
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
# UI helpers
# ──────────────────────────────────────────────────────────────────────────────

def require_producer_selected() -> Tuple[int, Dict]:
    prods = list_producers(include_archived=False)
    if not prods:
        st.info("No producers yet. Go to **Producers** → **Create Producer**.")
        st.stop()

    labels = [p["name"] for p in prods]
    ids = [int(p["id"]) for p in prods]

    if "producer_id" not in st.session_state:
        st.session_state.producer_id = ids[0]

    try:
        idx = ids.index(st.session_state.producer_id)
    except ValueError:
        idx = 0
        st.session_state.producer_id = ids[0]

    chosen = st.sidebar.selectbox("Producer", labels, index=idx)
    chosen_id = ids[labels.index(chosen)]
    st.session_state.producer_id = chosen_id

    p = get_producer(chosen_id)
    if not p:
        st.error("Producer not found.")
        st.stop()
    return chosen_id, p


def confirm_button(key: str, label: str, confirm_label: str = "Delete", cancel_label: str = "Keep") -> bool:
    """
    Two-click confirm pattern. Returns True only when user hits Confirm on second step.
    """
    state_key = f"confirm__{key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = False

    if not st.session_state[state_key]:
        if st.button(label, key=f"{key}__btn"):
            st.session_state[state_key] = True
            st.rerun()
        return False

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
                status = " (archived)" if p["archived"] else ""
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
                except Exception as e:
                    st.error(f"Could not create producer: {e}")
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
            archived = st.checkbox("Archived", value=bool(p["archived"]))
            ok = st.form_submit_button("Save changes")

        if ok:
            try:
                update_producer(pid, new_name, new_recipient, new_prefix, archived)
            except Exception as e:
                st.error(f"Could not save: {e}")
            else:
                st.success("Saved.")
                st.rerun()


def page_template_builder() -> None:
    producer_id, producer = require_producer_selected()
    page_header("Template Builder", f"Build tabs/sections and items for **{producer['name']}**.")

    st.markdown("## Sections (tabs)")

    sections_all = list_sections(producer_id, active_only=False)
    sections_active = [s for s in sections_all if s["active"]]

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
                except Exception as e:
                    st.error(f"Could not add section: {e}")
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
                title = f"{s['name']}" + ("" if s["active"] else " (inactive)")
                with st.expander(title, expanded=False):
                    with st.form(f"edit_section_{sid}"):
                        new_name = st.text_input("Name", value=s["name"], key=f"sec_name_{sid}")
                        new_order = st.number_input("Sort order", min_value=0, step=1, value=int(s["sort_order"]), key=f"sec_order_{sid}")
                        active = st.checkbox("Active", value=bool(s["active"]), key=f"sec_active_{sid}")
                        ok = st.form_submit_button("Save section")

                    if ok:
                        try:
                            update_section(sid, new_name, int(new_order), bool(active))
                        except Exception as e:
                            st.error(f"Could not save: {e}")
                        else:
                            st.success("Saved.")
                            st.rerun()

                    st.caption(f"Items in this section: {item_ct}")
                    if item_ct == 0:
                        if confirm_button(f"del_section_{sid}", "Delete section 🗑️"):
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

    sections_any = list_sections(producer_id, active_only=False)
    section_ids = [int(s["id"]) for s in sections_any]
    section_labels = [s["name"] + ("" if s["active"] else " (inactive)") for s in sections_any]
    label_to_id = {lab: sid for lab, sid in zip(section_labels, section_ids)}

    search = st.text_input("Search items", placeholder="Type to filter by name…").strip().lower()
    filtered = [it for it in items if search in it["name"].lower()] if search else items

    for it in filtered[:800]:
        item_id = int(it["id"])
        title = f"{it['name']}  —  {it['section_name']}" + ("" if it["active"] else " (inactive)")
        with st.expander(title, expanded=False):
            # current section label
            curr_label = None
            for s in sections_any:
                if int(s["id"]) == int(it["section_id"]):
                    curr_label = s["name"] + ("" if s["active"] else " (inactive)")
                    break
            curr_label = curr_label or section_labels[0]

            with st.form(f"edit_item_{item_id}"):
                new_section_label = st.selectbox("Section", section_labels, index=section_labels.index(curr_label), key=f"it_sec_{item_id}")
                new_section_id = label_to_id[new_section_label]
                new_name = st.text_input("Name", value=it["name"], key=f"it_name_{item_id}")
                new_unit = st.text_input("Unit", value=it["unit"], key=f"it_unit_{item_id}")
                new_notes = st.text_input("Notes", value=it["notes"], key=f"it_notes_{item_id}")
                new_order = st.number_input("Sort order", min_value=0, step=1, value=int(it["sort_order"]), key=f"it_order_{item_id}")
                new_active = st.checkbox("Active", value=bool(it["active"]), key=f"it_active_{item_id}")
                ok = st.form_submit_button("Save item")

            if ok:
                update_item(item_id, new_section_id, new_name, new_unit, new_notes, bool(new_active), int(new_order))
                st.success("Saved.")
                st.rerun()

            st.divider()
            if confirm_button(f"del_item_{item_id}", "Delete item 🗑️"):
                delete_item(item_id)
                st.success("Item deleted.")
                st.rerun()


def page_count() -> None:
    producer_id, producer = require_producer_selected()
    page_header("Count", f"Manual weekly count for **{producer['name']}** (tabs generated from template).")

    sections = list_sections(producer_id, active_only=True)
    if not sections:
        st.info("No sections yet. Go to **Template Builder** to create tabs/sections.")
        st.stop()

    items_by_section = list_items_by_section(producer_id, include_inactive=False)
    if not any(items_by_section.values()):
        st.info("No items yet. Go to **Template Builder** to add items.")
        st.stop()

    count_id = start_or_resume_count(producer_id)
    count_row = get_count(count_id)
    if not count_row:
        st.error("Could not load count.")
        st.stop()

    lines = load_count_lines(count_id)

    # header with stable button sizing
    top = st.columns([2.2, 2.2, 2.2, 6.4], vertical_alignment="center")
    with top[0]:
        st.metric("Count status", count_row["status"])
    with top[1]:
        st.caption("Created")
        st.write(str(count_row["created_at"])[:19])
    with top[2]:
        st.caption("Updated")
        st.write(str(count_row["updated_at"])[:19])
    with top[3]:
        b1, b2, _ = st.columns([2.6, 2.6, 7.0], vertical_alignment="center")
        with b1:
            if st.button("Mark complete ✅", key=f"mc_{count_id}", use_container_width=True):
                set_count_status(count_id, "completed")
                st.success("Marked complete.")
                st.rerun()
        with b2:
            if st.button("Start new count 🆕", key=f"snc_{count_id}", use_container_width=True):
                if count_row["status"] != "completed":
                    set_count_status(count_id, "completed")
                new_id = create_new_count(producer_id)
                st.success(f"Started new count (#{new_id}).")
                st.rerun()

    st.divider()

    search = st.text_input("Search items (optional)", placeholder="Type to filter item names across tabs…").strip().lower()

    with st.expander("Add missing item (persists for future counts)", expanded=False):
        with st.form("inline_add_item"):
            sec_label = [s["name"] for s in sections]
            sec_ids = [int(s["id"]) for s in sections]
            chosen = st.selectbox("Section", sec_label, index=0)
            chosen_id = sec_ids[sec_label.index(chosen)]
            nm = st.text_input("Item name *", placeholder="New item name")
            unit = st.text_input("Unit (optional)")
            notes = st.text_input("Notes (optional)")
            ok = st.form_submit_button("Add item")
        if ok:
            if not nm.strip():
                st.error("Item name is required.")
            else:
                create_item(producer_id, chosen_id, nm, unit=unit, notes=notes, sort_order=9999)
                st.success("Item added.")
                st.rerun()

    tabs = st.tabs([s["name"] for s in sections])

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

            for it in items:
                item_id = int(it["id"])
                curr = int(lines.get(item_id, 0))

                cols = st.columns([6, 3, 2, 1], vertical_alignment="center")

                with cols[0]:
                    label = it["name"]
                    if (it.get("unit") or "").strip():
                        label += f"  ·  *{it['unit']}*"
                    st.write(label)
                    if (it.get("notes") or "").strip():
                        st.caption(it["notes"])

                with cols[1]:
                    b1, b2, b3, b4 = st.columns(4)
                    if b1.button("+1", key=f"p1_{count_id}_{item_id}", use_container_width=True):
                        upsert_count_line(count_id, item_id, curr + 1); st.rerun()
                    if b2.button("+5", key=f"p5_{count_id}_{item_id}", use_container_width=True):
                        upsert_count_line(count_id, item_id, curr + 5); st.rerun()
                    if b3.button("-1", key=f"m1_{count_id}_{item_id}", use_container_width=True):
                        upsert_count_line(count_id, item_id, max(0, curr - 1)); st.rerun()
                    if b4.button("0", key=f"z_{count_id}_{item_id}", use_container_width=True):
                        upsert_count_line(count_id, item_id, 0); st.rerun()

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
                    st.caption("")

    st.divider()
    st.markdown("## Send Report (refined)")

    grouped_rows = build_grouped_report_rows(producer_id, count_id)

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
    page_header("History", f"Recent counts for **{producer['name']}** (qty 0 hidden).")

    rows = list_recent_counts(producer_id, limit=50)
    if not rows:
        st.info("No counts yet.")
        return

    sec_map = {int(s["id"]): s["name"] for s in list_sections(producer_id, active_only=False)}

    for r in rows:
        cid = int(r["id"])
        with st.expander(f"Count #{cid} — {r['status']} — {str(r['created_at'])[:19]}", expanded=False):
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
page = st.sidebar.radio("Go to", ["Count", "Template Builder", "Producers", "History"], index=0)

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
