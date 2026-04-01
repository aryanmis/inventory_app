from __future__ import annotations

import html as html_lib
import io
import os
import re
import datetime as dt
from typing import Dict, List, Optional, Tuple

import streamlit as st

import psycopg2
import psycopg2.extras

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

APP_TITLE = "Inventory"

st.set_page_config(page_title=APP_TITLE, layout="wide", page_icon="📦")


# ── CSS: theme-aware, modern minimalist ──────────────────────────────────────
st.markdown(
    """
    <style>
      /* ── Font ── */
      html, body, [class*="css"], .stApp {
        font-family: 'Inter', 'SF Pro Display', -apple-system, BlinkMacSystemFont,
                     'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
      }

      /* ── Layout ── */
      .main .block-container {
        padding-top: 1.75rem;
        padding-bottom: 3rem;
        max-width: 1100px;
      }

      /* ── Headings (inherit theme colour, don't hard-code) ── */
      h1 {
        font-size: 1.55rem !important;
        font-weight: 700 !important;
        letter-spacing: -0.03em !important;
        padding-bottom: 0.2rem !important;
      }
      h2 {
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        letter-spacing: -0.01em !important;
        margin-top: 1.5rem !important;
      }
      h3 {
        font-size: 0.975rem !important;
        font-weight: 600 !important;
        margin-top: 0.75rem !important;
      }

      /* ── Buttons: neutral, theme-safe ── */
      .stButton > button {
        white-space: nowrap !important;
        min-height: 38px !important;
        padding: 0.25rem 0.85rem !important;
        border-radius: 6px !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        border: 1px solid rgba(127,127,127,0.3) !important;
        background: transparent !important;
        transition: opacity 0.15s ease !important;
      }
      .stButton > button:hover { opacity: 0.75 !important; }

      /* Primary form submit buttons */
      .stFormSubmitButton > button {
        border-radius: 6px !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        min-height: 38px !important;
        padding: 0.25rem 1rem !important;
      }

      /* ── Number inputs ── */
      div[data-testid="stNumberInput"] { max-width: 150px !important; }
      div[data-testid="stNumberInput"] input {
        text-align: center !important;
        font-weight: 700 !important;
        font-size: 1rem !important;
        border-radius: 6px !important;
      }

      /* ── Text inputs / text areas ── */
      .stTextInput input, .stTextArea textarea {
        border-radius: 6px !important;
        font-size: 0.9rem !important;
      }

      /* ── Selectbox ── */
      .stSelectbox > div > div { border-radius: 6px !important; font-size: 0.9rem !important; }

      /* ── Expanders ── */
      .streamlit-expanderHeader {
        font-size: 0.9rem !important;
        font-weight: 500 !important;
        border-radius: 6px !important;
        padding: 0.45rem 0.75rem !important;
      }

      /* ── Tabs ── */
      .stTabs [data-baseweb="tab"] {
        border-radius: 6px 6px 0 0 !important;
        font-size: 0.875rem !important;
        font-weight: 500 !important;
        padding: 0.45rem 1rem !important;
      }

      /* ── Alerts ── */
      .stAlert { border-radius: 6px !important; font-size: 0.875rem !important; }

      /* ── Dividers ── */
      hr { margin: 1.2rem 0 !important; }

      /* ── Column gap ── */
      div[data-testid="stHorizontalBlock"] { gap: 0.75rem; }

      /* ── Count status strip ── */
      .count-strip {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 1rem;
        padding: 0.65rem 0;
        font-size: 0.875rem;
        opacity: 0.85;
      }
      .count-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        font-weight: 600;
        font-size: 0.8rem;
        padding: 0.2rem 0.6rem;
        border-radius: 999px;
        border: 1px solid currentColor;
      }
      .count-badge-progress { color: #d97706; }
      .count-badge-done     { color: #16a34a; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📦 Inventory")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def page_header(title: str, subtitle: str = "") -> None:
    st.subheader(title)
    if subtitle:
        st.caption(subtitle)
    st.divider()


def fmt_ts(ts) -> str:
    if ts is None:
        return "—"
    try:
        if isinstance(ts, str):
            ts = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return ts.strftime("%-m/%-d/%y %-I:%M %p")
    except Exception:
        return str(ts)[:16]


def now_ts() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        try:
            url = st.secrets.get("DATABASE_URL", "")
        except Exception:
            url = ""
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set.\n\n"
            "Add it to your Streamlit secrets (Manage app → Secrets):\n\n"
            '  DATABASE_URL = "postgresql://user:password@host:5432/dbname"'
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
                status TEXT NOT NULL DEFAULT 'in_progress',
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


try:
    init_db()
except Exception as _db_err:
    st.error(
        "**Could not connect to the database.**\n\n"
        "Make sure `DATABASE_URL` is set in your Streamlit Cloud secrets "
        "(Manage app → Secrets):\n\n"
        "```\nDATABASE_URL = \"postgresql://user:password@host:5432/dbname\"\n```\n\n"
        f"Error: `{_db_err}`"
    )
    st.stop()


# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
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
        return int(cur.fetchone()[0])


# ── Producers ──────────────────────────────────────────────────────────────

def list_producers(include_archived: bool = False) -> List[Dict]:
    if include_archived:
        return qfetchall("SELECT * FROM producers ORDER BY lower(name)")
    return qfetchall("SELECT * FROM producers WHERE archived=false ORDER BY lower(name)")


def get_producer(producer_id: int) -> Optional[Dict]:
    return qfetchone("SELECT * FROM producers WHERE id=%s", (producer_id,))


def create_producer(name: str, default_recipient: str, default_subject_prefix: str) -> int:
    return qinsert_returning_id(
        "INSERT INTO producers(name, default_recipient, default_subject_prefix) VALUES (%s,%s,%s) RETURNING id",
        (name.strip(), default_recipient.strip(), (default_subject_prefix.strip() or "Inventory")),
    )


def update_producer(producer_id: int, name: str, default_recipient: str, default_subject_prefix: str, archived: bool) -> None:
    qexecute(
        "UPDATE producers SET name=%s, default_recipient=%s, default_subject_prefix=%s, archived=%s WHERE id=%s",
        (name.strip(), default_recipient.strip(), (default_subject_prefix.strip() or "Inventory"), bool(archived), producer_id),
    )


# ── Sections ───────────────────────────────────────────────────────────────

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
        "INSERT INTO sections(producer_id, name, sort_order, active) VALUES (%s,%s,%s,true) RETURNING id",
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


# ── Items ──────────────────────────────────────────────────────────────────

def list_items(producer_id: int, include_inactive: bool = False) -> List[Dict]:
    base = """
        SELECT items.*, sections.name AS section_name, sections.sort_order AS section_sort
        FROM items JOIN sections ON sections.id = items.section_id
        WHERE items.producer_id=%s
    """
    if not include_inactive:
        base += " AND items.active=true AND sections.active=true"
    base += " ORDER BY section_sort, lower(sections.name), items.sort_order, lower(items.name)"
    return qfetchall(base, (producer_id,))


def list_items_by_section(producer_id: int, include_inactive: bool = False) -> Dict[int, List[Dict]]:
    out: Dict[int, List[Dict]] = {}
    for it in list_items(producer_id, include_inactive=include_inactive):
        out.setdefault(int(it["section_id"]), []).append(it)
    return out


def create_item(producer_id: int, section_id: int, name: str, unit: str = "", notes: str = "", sort_order: int = 0) -> int:
    return qinsert_returning_id(
        "INSERT INTO items(producer_id, section_id, name, unit, notes, active, sort_order) VALUES (%s,%s,%s,%s,%s,true,%s) RETURNING id",
        (producer_id, section_id, name.strip(), unit.strip(), notes.strip(), int(sort_order)),
    )


def update_item(item_id: int, section_id: int, name: str, unit: str, notes: str, active: bool, sort_order: int) -> None:
    qexecute(
        "UPDATE items SET section_id=%s, name=%s, unit=%s, notes=%s, active=%s, sort_order=%s WHERE id=%s",
        (section_id, name.strip(), unit.strip(), notes.strip(), bool(active), int(sort_order), item_id),
    )


def delete_item(item_id: int) -> None:
    qexecute("DELETE FROM items WHERE id=%s", (item_id,))


# ── Counts ─────────────────────────────────────────────────────────────────

def create_new_count(producer_id: int) -> int:
    return qinsert_returning_id(
        "INSERT INTO counts(producer_id, status) VALUES (%s,'in_progress') RETURNING id",
        (producer_id,),
    )


def start_or_resume_count(producer_id: int) -> int:
    row = qfetchone(
        "SELECT id FROM counts WHERE producer_id=%s AND status='in_progress' ORDER BY created_at DESC LIMIT 1",
        (producer_id,),
    )
    return int(row["id"]) if row else create_new_count(producer_id)


def get_count(count_id: int) -> Optional[Dict]:
    return qfetchone("SELECT * FROM counts WHERE id=%s", (count_id,))


def set_count_status(count_id: int, status: str) -> None:
    qexecute("UPDATE counts SET status=%s, updated_at=NOW() WHERE id=%s", (status, count_id))


def update_count_note(count_id: int, note: str) -> None:
    qexecute("UPDATE counts SET note=%s, updated_at=NOW() WHERE id=%s", (note.strip(), count_id))


def delete_count(count_id: int) -> None:
    # count_lines cascade-deletes via FK
    qexecute("DELETE FROM counts WHERE id=%s", (count_id,))


def list_recent_counts(producer_id: int, limit: int = 50) -> List[Dict]:
    return qfetchall(
        "SELECT * FROM counts WHERE producer_id=%s ORDER BY created_at DESC LIMIT %s",
        (producer_id, int(limit)),
    )


def load_count_lines(count_id: int) -> Dict[int, int]:
    rows = qfetchall("SELECT item_id, qty FROM count_lines WHERE count_id=%s", (count_id,))
    return {int(r["item_id"]): int(r["qty"]) for r in rows}


def upsert_count_line(count_id: int, item_id: int, qty: int) -> None:
    qexecute(
        """
        INSERT INTO count_lines(count_id, item_id, qty, updated_at) VALUES (%s,%s,%s,NOW())
        ON CONFLICT (count_id, item_id) DO UPDATE SET qty=EXCLUDED.qty, updated_at=NOW()
        """,
        (count_id, item_id, int(qty)),
    )
    qexecute("UPDATE counts SET updated_at=NOW() WHERE id=%s", (count_id,))


def reset_count_lines(count_id: int) -> None:
    """Delete all qty entries for a count (resets everything to 0)."""
    qexecute("DELETE FROM count_lines WHERE count_id=%s", (count_id,))
    qexecute("UPDATE counts SET updated_at=NOW() WHERE id=%s", (count_id,))


def copy_count_lines(source_count_id: int, dest_count_id: int) -> None:
    """Copy all quantities from one count into another."""
    rows = qfetchall("SELECT item_id, qty FROM count_lines WHERE count_id=%s", (source_count_id,))
    for r in rows:
        upsert_count_line(dest_count_id, int(r["item_id"]), int(r["qty"]))


# ──────────────────────────────────────────────────────────────────────────────
# Email + report building
# ──────────────────────────────────────────────────────────────────────────────

def sanitize_subject(s: str) -> str:
    return re.sub(r"[\r\n]+", " ", (s or "").strip())


def build_grouped_report_rows(producer_id: int, count_id: int) -> List[Tuple[str, List[Tuple[str, int]]]]:
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

    def sec_key(name: str) -> Tuple[int, str]:
        for sid, (order, nm) in sec_meta.items():
            if nm == name:
                return (order, nm.lower())
        return (999999, name.lower())

    rows.sort(key=lambda r: sec_key(r[0]))
    return rows


def build_csv(grouped_rows: List[Tuple[str, List[Tuple[str, int]]]], count_note: str = "") -> str:
    buf = io.StringIO()
    buf.write("Section,Item,Qty\n")
    for section, items in grouped_rows:
        for name, qty in items:
            buf.write(f"{section},{name},{qty}\n")
    return buf.getvalue()


def _smtp_secret(key: str, default: str = "") -> str:
    val = os.environ.get(key, "")
    if not val:
        try:
            val = st.secrets.get(key, default)
        except Exception:
            val = default
    return val


def send_email_report(
        *,
        recipient: str,
        subject: str,
        before_txt: str,
        after_txt: str,
        grouped_rows: List[Tuple[str, List[Tuple[str, int]]]],
) -> None:
    smtp_host = _smtp_secret("SMTP_HOST")
    smtp_port_raw = _smtp_secret("SMTP_PORT", "587")
    smtp_user = _smtp_secret("SMTP_USER")
    smtp_pass = _smtp_secret("SMTP_PASS")
    smtp_from = _smtp_secret("SMTP_FROM") or smtp_user

    if not (smtp_host and smtp_user and smtp_pass and smtp_from):
        raise RuntimeError(
            "Missing SMTP credentials. Add SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS "
            "(and optionally SMTP_FROM) to your Streamlit secrets or environment variables."
        )

    try:
        smtp_port = int(smtp_port_raw)
    except Exception:
        smtp_port = 587

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

    def nl2br(text: str) -> str:
        return html_lib.escape(text).replace("\n", "<br/>")

    html_parts: List[str] = [
        "<div style='font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
        "color:#111827;font-size:15px;line-height:1.6;'>"
    ]
    if before_txt.strip():
        html_parts.append(f"<p style='margin:0 0 16px 0;'>{nl2br(before_txt.strip())}</p>")
    for section, items in grouped_rows:
        if not items:
            continue
        html_parts.append(
            f"<h3 style='margin:20px 0 8px 0;font-size:13px;font-weight:600;"
            f"text-transform:uppercase;letter-spacing:0.05em;color:#6b7280;'>"
            f"{html_lib.escape(section)}</h3>"
        )
        html_parts.append(
            "<table cellspacing='0' cellpadding='0' style='border-collapse:collapse;"
            "width:100%;max-width:600px;margin-bottom:16px;'>"
            "<tr>"
            "<th align='left' style='border-bottom:2px solid #e5e7eb;padding:6px 8px;"
            "font-size:12px;color:#9ca3af;font-weight:500;'>Item</th>"
            "<th align='right' style='border-bottom:2px solid #e5e7eb;padding:6px 8px;"
            "font-size:12px;color:#9ca3af;font-weight:500;'>Qty</th>"
            "</tr>"
        )
        for name, qty in items:
            html_parts.append(
                f"<tr>"
                f"<td style='border-bottom:1px solid #f3f4f6;padding:8px;font-size:14px;'>"
                f"{html_lib.escape(name)}</td>"
                f"<td align='right' style='border-bottom:1px solid #f3f4f6;padding:8px;"
                f"font-size:14px;font-weight:700;'>{qty}</td>"
                f"</tr>"
            )
        html_parts.append("</table>")
    if after_txt.strip():
        html_parts.append(f"<p style='margin:16px 0 0 0;color:#6b7280;'>{nl2br(after_txt.strip())}</p>")
    html_parts.append("</div>")
    body_html = "\n".join(html_parts)

    msg = MIMEMultipart("alternative")
    msg["To"] = recipient.strip()
    msg["From"] = smtp_from
    msg["Subject"] = sanitize_subject(subject)
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    timeout_s = 20
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout_s) as srv:
            srv.ehlo(); srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_from, [recipient.strip()], msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=timeout_s) as srv:
            srv.ehlo(); srv.starttls(); srv.ehlo(); srv.login(smtp_user, smtp_pass)
            srv.sendmail(smtp_from, [recipient.strip()], msg.as_string())


# ──────────────────────────────────────────────────────────────────────────────
# UI helpers
# ──────────────────────────────────────────────────────────────────────────────

def require_producer_selected() -> Tuple[int, Dict]:
    prods = list_producers(include_archived=False)
    if not prods:
        st.info("No producers yet. Go to **Producers** to create your first one.")
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


def confirm_button(key: str, label: str, confirm_label: str = "Yes, delete", cancel_label: str = "Cancel") -> bool:
    """Two-click confirm. Returns True only on confirmation."""
    state_key = f"confirm__{key}"
    if state_key not in st.session_state:
        st.session_state[state_key] = False

    if not st.session_state[state_key]:
        if st.button(label, key=f"{key}__btn"):
            st.session_state[state_key] = True
            st.rerun()
        return False

    cols = st.columns([2.5, 2.5, 8], vertical_alignment="center")
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
    page_header("Producers", "A producer is a location or entity you track inventory for (e.g. a store, kitchen, or warehouse).")

    colA, colB = st.columns([2, 3], vertical_alignment="top")

    with colA:
        st.markdown("### Existing producers")
        prods = list_producers(include_archived=True)
        if not prods:
            st.info("No producers yet — create one on the right.")
        else:
            for p in prods:
                status = " *(archived)*" if p["archived"] else ""
                st.write(f"• **{p['name']}**{status}")

    with colB:
        st.markdown("### Create a new producer")
        with st.form("create_producer_form"):
            name = st.text_input("Producer name *", placeholder="e.g. Main Store, Warehouse A")
            default_recipient = st.text_input(
                "Default recipient email",
                placeholder="reports@example.com",
                help="Email address reports will be sent to by default.",
            )
            default_subject_prefix = st.text_input("Email subject prefix", value="Inventory")
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
                    st.success(f"Producer **{name.strip()}** created.")
                    st.session_state.producer_id = new_id
                    st.rerun()

        st.divider()
        st.markdown("### Edit a producer")
        prods_any = list_producers(include_archived=True)
        if not prods_any:
            return

        labels = [p["name"] for p in prods_any]
        ids = [int(p["id"]) for p in prods_any]
        pick = st.selectbox("Select producer to edit", labels, index=0)
        pid = ids[labels.index(pick)]
        p = get_producer(pid)
        if not p:
            return

        with st.form("edit_producer_form"):
            new_name = st.text_input("Name", value=p["name"])
            new_recipient = st.text_input("Default recipient email", value=p["default_recipient"])
            new_prefix = st.text_input("Email subject prefix", value=p["default_subject_prefix"])
            archived = st.checkbox(
                "Archive this producer",
                value=bool(p["archived"]),
                help="Archived producers are hidden but their data is kept.",
            )
            ok = st.form_submit_button("Save changes")

        if ok:
            try:
                update_producer(pid, new_name, new_recipient, new_prefix, archived)
            except Exception as e:
                st.error(f"Could not save: {e}")
            else:
                st.success("Changes saved.")
                st.rerun()


def page_template_builder() -> None:
    producer_id, producer = require_producer_selected()
    page_header(
        "Items & Sections",
        f"Manage the sections (tabs) and items counted for **{producer['name']}**. Changes apply to all future counts.",
    )

    st.markdown("## Sections")
    st.caption("Sections appear as tabs on the Count page — one per area or category (e.g. Cafe, Freezer, Market).")

    sections_all = list_sections(producer_id, active_only=False)
    sections_active = [s for s in sections_all if s["active"]]

    c1, c2 = st.columns([2, 3], vertical_alignment="top")
    with c1:
        st.markdown("### Add a section")
        with st.form("add_section_form"):
            sec_name = st.text_input("Section name *", placeholder="e.g. Cafe, Market, Freezer")
            sec_order = st.number_input(
                "Sort order", min_value=0, step=10, value=(len(sections_all) * 10),
                help="Lower numbers appear first.",
            )
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
                    st.success(f"Section **{sec_name.strip()}** added.")
                    st.rerun()

        st.divider()
        st.markdown("### Bulk-add items")
        st.caption("Paste a list — fastest way to build your inventory template.")
        if not sections_active:
            st.info("Create at least one active section first.")
        else:
            with st.form("quick_add_items"):
                sec_label = [s["name"] for s in sections_active]
                sec_ids = [int(s["id"]) for s in sections_active]
                chosen = st.selectbox("Add into section", sec_label, index=0)
                chosen_id = sec_ids[sec_label.index(chosen)]
                st.caption("Format: `Item name` or `Item name | unit | notes` — one per line.")
                raw = st.text_area(
                    "Items", height=160,
                    placeholder="Croissant | each | front case\nSourdough boule | each\nOat milk | carton",
                )
                submit_quick = st.form_submit_button("Add items")

            if submit_quick:
                item_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                if not item_lines:
                    st.error("No items entered.")
                else:
                    added = 0
                    for i, ln in enumerate(item_lines):
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
                inactive_badge = " — inactive" if not s["active"] else ""
                with st.expander(f"{s['name']}{inactive_badge}  ({item_ct} items)", expanded=False):
                    with st.form(f"edit_section_{sid}"):
                        new_name = st.text_input("Name", value=s["name"], key=f"sec_name_{sid}")
                        new_order = st.number_input(
                            "Sort order", min_value=0, step=10,
                            value=int(s["sort_order"]), key=f"sec_order_{sid}",
                        )
                        active = st.checkbox(
                            "Active", value=bool(s["active"]), key=f"sec_active_{sid}",
                            help="Inactive sections are hidden from the Count page.",
                        )
                        ok = st.form_submit_button("Save")
                    if ok:
                        try:
                            update_section(sid, new_name, int(new_order), bool(active))
                        except Exception as e:
                            st.error(f"Could not save: {e}")
                        else:
                            st.success("Saved.")
                            st.rerun()

                    if item_ct == 0:
                        if confirm_button(f"del_section_{sid}", "Delete section"):
                            delete_section(sid)
                            st.success("Section deleted.")
                            st.rerun()
                    else:
                        st.caption(f"Move or delete its {item_ct} item(s) first to enable deletion.")

    st.divider()
    st.markdown("## Items")

    if not sections_active:
        st.info("Create at least one active section before adding items.")
        return

    st.markdown("### Add a single item")
    with st.form("add_item_form"):
        col1, col2 = st.columns(2)
        with col1:
            sec_label = [s["name"] for s in sections_active]
            sec_ids = [int(s["id"]) for s in sections_active]
            chosen = st.selectbox("Section", sec_label, index=0)
            chosen_id = sec_ids[sec_label.index(chosen)]
            item_name = st.text_input("Item name *")
        with col2:
            unit = st.text_input("Unit (optional)", placeholder="each / case / lb / tray")
            notes = st.text_input("Notes (optional)", placeholder="Where stored or how to count it")
            sort_order = st.number_input("Sort order", min_value=0, step=10, value=0)
        add_item = st.form_submit_button("Add item")

    if add_item:
        if not item_name.strip():
            st.error("Item name is required.")
        else:
            create_item(producer_id, chosen_id, item_name, unit=unit, notes=notes, sort_order=int(sort_order))
            st.success(f"Item **{item_name.strip()}** added.")
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

    search = st.text_input("Search items", placeholder="Filter by name…").strip().lower()
    filtered = [it for it in items if search in it["name"].lower()] if search else items

    if not filtered:
        st.caption("No items match your search.")
        return

    for it in filtered[:800]:
        item_id = int(it["id"])
        inactive_badge = " — inactive" if not it["active"] else ""
        with st.expander(f"{it['name']}  ·  {it['section_name']}{inactive_badge}", expanded=False):
            curr_label = next(
                (s["name"] + ("" if s["active"] else " (inactive)")
                 for s in sections_any if int(s["id"]) == int(it["section_id"])),
                section_labels[0],
            )

            with st.form(f"edit_item_{item_id}"):
                col1, col2 = st.columns(2)
                with col1:
                    new_section_label = st.selectbox(
                        "Section", section_labels,
                        index=section_labels.index(curr_label),
                        key=f"it_sec_{item_id}",
                    )
                    new_section_id = label_to_id[new_section_label]
                    new_name = st.text_input("Name", value=it["name"], key=f"it_name_{item_id}")
                with col2:
                    new_unit = st.text_input("Unit", value=it["unit"], key=f"it_unit_{item_id}")
                    new_notes = st.text_input("Notes", value=it["notes"], key=f"it_notes_{item_id}")
                    new_order = st.number_input(
                        "Sort order", min_value=0, step=10,
                        value=int(it["sort_order"]), key=f"it_order_{item_id}",
                    )
                new_active = st.checkbox("Active", value=bool(it["active"]), key=f"it_active_{item_id}")
                ok = st.form_submit_button("Save changes")

            if ok:
                update_item(item_id, new_section_id, new_name, new_unit, new_notes, bool(new_active), int(new_order))
                st.success("Saved.")
                st.rerun()

            st.divider()
            if confirm_button(f"del_item_{item_id}", "Delete item"):
                delete_item(item_id)
                st.success("Item deleted.")
                st.rerun()


def page_count() -> None:
    producer_id, producer = require_producer_selected()
    page_header("Count", f"Enter quantities for **{producer['name']}**. Changes save automatically.")

    sections = list_sections(producer_id, active_only=True)
    if not sections:
        st.info("No sections yet. Go to **Items & Sections** to set up your inventory template.")
        st.stop()

    items_by_section = list_items_by_section(producer_id, include_inactive=False)
    all_items = [it for its in items_by_section.values() for it in its]
    if not all_items:
        st.info("No items yet. Go to **Items & Sections** to add items.")
        st.stop()

    count_id = start_or_resume_count(producer_id)
    count_row = get_count(count_id)
    if not count_row:
        st.error("Could not load count. Please refresh the page.")
        st.stop()

    lines = load_count_lines(count_id)

    # ── Status strip ────────────────────────────────────────────────────────
    is_complete = count_row["status"] == "completed"
    status_label = "Completed" if is_complete else "In Progress"
    badge_class = "count-badge-done" if is_complete else "count-badge-progress"

    filled = sum(1 for item_id in [int(it["id"]) for it in all_items] if lines.get(item_id, 0) > 0)
    total = len(all_items)
    note_display = f"  ·  {html_lib.escape(count_row['note'])}" if count_row.get("note", "").strip() else ""

    st.markdown(
        f"""
        <div class="count-strip">
          <span class="count-badge {badge_class}">{status_label}</span>
          <span>Started {fmt_ts(count_row['created_at'])}</span>
          <span>·</span>
          <span>Saved {fmt_ts(count_row['updated_at'])}</span>
          <span>·</span>
          <span><strong>{filled}</strong> / {total} items filled</span>
          {f'<span>·</span><span style="font-style:italic;">{note_display[4:]}</span>' if note_display else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Action row ──────────────────────────────────────────────────────────
    a1, a2, a3, a4, _ = st.columns([2, 2, 2, 2, 4], vertical_alignment="center")
    with a1:
        if not is_complete:
            if st.button("Mark complete", key=f"mc_{count_id}", use_container_width=True):
                set_count_status(count_id, "completed")
                st.success("Count marked as complete.")
                st.rerun()
        else:
            if st.button("Reopen count", key=f"reopen_{count_id}", use_container_width=True):
                set_count_status(count_id, "in_progress")
                st.rerun()
    with a2:
        if st.button("Start new count", key=f"snc_{count_id}", use_container_width=True):
            if not is_complete:
                set_count_status(count_id, "completed")
            new_id = create_new_count(producer_id)
            st.success(f"New count started.")
            st.rerun()
    with a3:
        if confirm_button(f"reset_{count_id}", "Reset to zero"):
            reset_count_lines(count_id)
            st.success("All quantities reset to 0.")
            st.rerun()
    with a4:
        if confirm_button(f"del_count_{count_id}", "Delete count"):
            delete_count(count_id)
            st.success("Count deleted.")
            st.rerun()

    # ── Count note ──────────────────────────────────────────────────────────
    with st.expander("Count note (optional label for this count)", expanded=False):
        note_val = st.text_input(
            "Note",
            value=count_row.get("note", ""),
            placeholder="e.g. Week ending Apr 7 · Holiday stock · Pre-event count",
            key=f"note_input_{count_id}",
            label_visibility="collapsed",
        )
        if st.button("Save note", key=f"save_note_{count_id}"):
            update_count_note(count_id, note_val)
            st.success("Note saved.")
            st.rerun()

    st.divider()

    search = st.text_input(
        "Search items",
        placeholder="Filter item names across all tabs…",
        label_visibility="collapsed",
    ).strip().lower()

    with st.expander("Add a missing item to this count", expanded=False):
        st.caption("This item will be saved and appear in all future counts too.")
        with st.form("inline_add_item"):
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                sec_label = [s["name"] for s in sections]
                sec_ids = [int(s["id"]) for s in sections]
                chosen = st.selectbox("Section", sec_label, index=0)
                chosen_id = sec_ids[sec_label.index(chosen)]
                nm = st.text_input("Item name *", placeholder="New item name")
            with col2:
                unit = st.text_input("Unit (optional)")
            with col3:
                notes = st.text_input("Notes (optional)")
            ok = st.form_submit_button("Add item")
        if ok:
            if not nm.strip():
                st.error("Item name is required.")
            else:
                create_item(producer_id, chosen_id, nm, unit=unit, notes=notes, sort_order=9999)
                st.success(f"Item **{nm.strip()}** added.")
                st.rerun()

    # ── Item tabs ────────────────────────────────────────────────────────────
    tabs = st.tabs([s["name"] for s in sections])

    for tab, section in zip(tabs, sections):
        sid = int(section["id"])
        tab_items = items_by_section.get(sid, [])
        if search:
            tab_items = [it for it in tab_items if search in it["name"].lower()]

        with tab:
            if not tab_items:
                st.caption("No matching items in this section.")
                continue

            for it in tab_items:
                item_id = int(it["id"])
                curr = int(lines.get(item_id, 0))

                cols = st.columns([7, 2, 1], vertical_alignment="center")
                with cols[0]:
                    label = f"**{it['name']}**"
                    if (it.get("unit") or "").strip():
                        label += f"  ·  *{it['unit']}*"
                    st.markdown(label)
                    if (it.get("notes") or "").strip():
                        st.caption(it["notes"])

                with cols[1]:
                    new_qty = st.number_input(
                        "Qty", min_value=0, step=1, value=curr,
                        key=f"qty_{count_id}_{item_id}",
                        label_visibility="collapsed",
                    )
                    if int(new_qty) != curr:
                        upsert_count_line(count_id, item_id, int(new_qty))

                with cols[2]:
                    # Quick-clear button (only shown when qty > 0)
                    if curr > 0:
                        if st.button("✕", key=f"clr_{count_id}_{item_id}", help="Reset to 0"):
                            upsert_count_line(count_id, item_id, 0)
                            st.rerun()

    # ── Send Report ─────────────────────────────────────────────────────────
    st.divider()
    st.markdown("## Send Report")

    grouped_rows = build_grouped_report_rows(producer_id, count_id)

    if not grouped_rows:
        st.info("No items with a quantity above 0. Fill in some quantities above, then return here to send the report.")
        return

    # Download CSV
    csv_data = build_csv(grouped_rows)
    filename = f"inventory_{producer['name'].replace(' ','_')}_{dt.date.today().strftime('%Y-%m-%d')}.csv"
    st.download_button(
        "Download as CSV",
        data=csv_data,
        file_name=filename,
        mime="text/csv",
        help="Download the current count as a spreadsheet.",
    )

    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        default_subject = (
            f"{producer['default_subject_prefix']} {producer['name']} "
            f"{dt.date.today().strftime('%m.%d.%y')}"
        )
        subject = st.text_input("Email subject", value=default_subject)
        recipient = st.text_input(
            "Recipient email",
            value=producer["default_recipient"],
            help="The address to send the report to.",
        )
    with col2:
        before_txt = st.text_area("Opening message (optional)", height=80, placeholder="Hi, please see this week's inventory count.")
        after_txt = st.text_area("Closing message (optional)", height=80, placeholder="Let me know if you have any questions.")

    if not recipient.strip():
        st.caption("Enter a recipient email address to send the report.")
    else:
        if st.button("Send inventory report →"):
            with st.spinner("Sending…"):
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
    page_header("History", f"Past counts for **{producer['name']}**. Items with qty 0 are hidden.")

    rows = list_recent_counts(producer_id, limit=50)
    if not rows:
        st.info("No counts yet. Complete a count on the Count page and it will appear here.")
        return

    sec_map = {int(s["id"]): s["name"] for s in list_sections(producer_id, active_only=False)}
    all_items_map = {int(it["id"]): it for it in list_items(producer_id, include_inactive=True)}

    for r in rows:
        cid = int(r["id"])
        is_complete = r["status"] == "completed"
        status_icon = "✓" if is_complete else "…"
        note_part = f"  ·  {r['note']}" if (r.get("note") or "").strip() else ""
        label = f"{status_icon}  {fmt_ts(r['created_at'])}{note_part}"

        with st.expander(label, expanded=False):
            qty_map = load_count_lines(cid)

            grouped: Dict[str, List[Tuple[str, int]]] = {}
            for it in all_items_map.values():
                q = int(qty_map.get(int(it["id"]), 0))
                if q <= 0:
                    continue
                sec_name = sec_map.get(int(it["section_id"]), "Other")
                grouped.setdefault(sec_name, []).append((it["name"], q))

            if grouped:
                cols = st.columns(min(len(grouped), 3))
                for i, sec_name in enumerate(sorted(grouped.keys(), key=str.lower)):
                    with cols[i % len(cols)]:
                        st.markdown(f"**{sec_name}**")
                        for nm, q in sorted(grouped[sec_name], key=lambda x: x[0].lower()):
                            st.write(f"{nm}: **{q}**")
            else:
                st.caption("No quantities recorded for this count.")

            st.divider()

            # Actions: copy to new count, delete
            act1, act2, _ = st.columns([2, 2, 6], vertical_alignment="center")
            with act1:
                if st.button("Copy to new count", key=f"copy_{cid}",
                             help="Start a new count pre-filled with these quantities as a starting point."):
                    if r["status"] == "in_progress":
                        # close the current in-progress count first
                        set_count_status(cid, "completed")
                    new_id = create_new_count(producer_id)
                    copy_count_lines(cid, new_id)
                    st.success(f"New count started with quantities copied from this one.")
                    st.rerun()
            with act2:
                if confirm_button(f"del_hist_{cid}", "Delete count"):
                    delete_count(cid)
                    st.success("Count deleted.")
                    st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Navigation
# ──────────────────────────────────────────────────────────────────────────────

st.sidebar.header("Navigation")
page = st.sidebar.radio(
    "Go to",
    ["Count", "Items & Sections", "Producers", "History"],
    index=0,
)

if page == "Count":
    page_count()
elif page == "Items & Sections":
    page_template_builder()
elif page == "Producers":
    page_producers()
elif page == "History":
    page_history()
