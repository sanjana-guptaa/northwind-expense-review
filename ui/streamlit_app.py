"""
Northwind Logistics — Expense Review
"""
import json
import os
import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Northwind · Expense Review",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif !important; }

/* sidebar */
section[data-testid="stSidebar"] { background: #0f172a !important; }
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p { color: #94a3b8 !important; }
section[data-testid="stSidebar"] .stRadio > div > label { font-size: 0.875rem !important; }

/* main padding */
.block-container { padding-top: 1.25rem !important; max-width: 1080px; }

/* verdict pills */
.pill {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 9px; border-radius: 20px;
    font-size: 0.7rem; font-weight: 600;
    letter-spacing: 0.05em; text-transform: uppercase;
    font-family: 'DM Mono', monospace;
    white-space: nowrap;
}
.p-compliant { background:#dcfce7; color:#15803d; border:1px solid #bbf7d0; }
.p-flagged   { background:#fef3c7; color:#b45309; border:1px solid #fde68a; }
.p-rejected  { background:#fee2e2; color:#b91c1c; border:1px solid #fecaca; }
.p-pending   { background:#f1f5f9; color:#475569; border:1px solid #e2e8f0; }
.p-ingested  { background:#ede9fe; color:#6d28d9; border:1px solid #ddd6fe; }
.p-analyzed  { background:#dbeafe; color:#1d4ed8; border:1px solid #bfdbfe; }

/* stat cards */
.stat-row { display:flex; gap:10px; margin-bottom:18px; flex-wrap:wrap; }
.stat-card {
    flex:1; min-width:90px;
    background:#fff; border:1px solid #e8ecf0; border-radius:10px; padding:14px 16px;
}
.stat-lbl { font-size:0.68rem; color:#94a3b8; text-transform:uppercase; letter-spacing:0.07em; }
.stat-val { font-size:1.7rem; font-weight:600; line-height:1.1; font-family:'DM Mono',monospace; }

/* submission rows */
.sub-row {
    border:1px solid #e8ecf0; border-radius:10px;
    padding:12px 16px; margin-bottom:8px; background:#fff;
}
.sub-name { font-weight:600; font-size:0.9rem; color:#0f172a; }
.sub-meta { font-size:0.78rem; color:#64748b; margin-top:2px; }

/* confidence bar */
.cbar-wrap { display:inline-flex; align-items:center; gap:8px; }
.cbar-track { width:80px; height:4px; background:#f1f5f9; border-radius:3px; overflow:hidden; display:inline-block; vertical-align:middle; }
.cbar-fill  { height:100%; border-radius:3px; display:block; }
.cbar-pct   { font-size:0.75rem; color:#64748b; font-family:'DM Mono',monospace; }

/* verdict banner */
.v-banner {
    border-radius:10px; padding:16px 20px; margin-bottom:16px;
    display:flex; justify-content:space-between; align-items:center;
}
.v-banner-compliant { background:#f0fdf4; border:1px solid #bbf7d0; }
.v-banner-flagged   { background:#fffbeb; border:1px solid #fde68a; }
.v-banner-rejected  { background:#fef2f2; border:1px solid #fecaca; }
.v-label { font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em; color:#6b7280; margin-bottom:3px; }
.v-value { font-size:1.4rem; font-weight:700; font-family:'DM Mono',monospace; }
.v-value-compliant { color:#15803d; }
.v-value-flagged   { color:#b45309; }
.v-value-rejected  { color:#b91c1c; }

/* citation boxes */
.cit {
    border-left:3px solid #3b82f6; background:#eff6ff;
    padding:7px 12px; margin:5px 0; border-radius:0 6px 6px 0;
    font-size:0.8rem; line-height:1.45;
}
.cit-green { border-left-color:#10b981; background:#f0fdf4; }
.cit-src  { font-weight:600; font-size:0.7rem; font-family:'DM Mono',monospace; color:#1e40af; margin-bottom:2px; }
.cit-green .cit-src { color:#065f46; }
.cit-q    { color:#374151; font-style:italic; }

/* override entry */
.ov-entry {
    background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px;
    padding:9px 13px; margin:5px 0; font-size:0.83rem;
}
.ov-meta { font-size:0.72rem; color:#94a3b8; margin-top:3px; font-family:'DM Mono',monospace; }

/* warnings */
.low-conf { background:#fffbeb; border:1px solid #fcd34d; border-radius:6px; padding:9px 13px; color:#78350f; font-size:0.82rem; }
.oos-msg  { background:#fef2f2; border:1px solid #fecaca; border-radius:6px; padding:9px 13px; color:#991b1b; font-size:0.875rem; }

/* empty state */
.empty-state {
    background:#f8fafc; border:1px dashed #cbd5e1; border-radius:10px;
    padding:32px; text-align:center; color:#94a3b8; font-size:0.9rem;
}

/* form tweaks */
.stButton > button { border-radius:6px !important; font-family:'DM Sans',sans-serif; }
.stTextInput input, .stTextArea textarea, .stSelectbox > div > div { border-radius:6px !important; }
.stTabs [data-baseweb="tab"] { font-size:0.875rem; }
hr { border-color:#f1f5f9 !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def pill(verdict: str) -> str:
    cls = f"p-{verdict.lower()}"
    icons = {"compliant": "✓", "flagged": "!", "rejected": "✗",
             "pending": "–", "ingested": "◑", "analyzed": "●"}
    icon = icons.get(verdict.lower(), "•")
    return f'<span class="pill {cls}">{icon}&nbsp;{verdict}</span>'


def conf_bar(conf: float) -> str:
    pct = int(conf * 100)
    color = "#22c55e" if conf >= 0.75 else "#f59e0b" if conf >= 0.55 else "#ef4444"
    return (
        f'<span class="cbar-wrap">'
        f'<span class="cbar-track"><span class="cbar-fill" style="width:{pct}%;background:{color}"></span></span>'
        f'<span class="cbar-pct">{pct}%</span>'
        f'</span>'
    )


def citation_html(c: dict, green: bool = False) -> str:
    cls = "cit cit-green" if green else "cit"
    return (
        f'<div class="{cls}">'
        f'<div class="cit-src">{c["doc_id"]} · {c["section"]} · p.{c["page"]}</div>'
        f'<div class="cit-q">"{c["exact_quote"]}"</div>'
        f'</div>'
    )


def verdict_banner(overall: str, total: float, approved: float, confidence: float) -> str:
    cls = f"v-value v-value-{overall}"
    icons = {"compliant": "✓", "flagged": "!", "rejected": "✗"}
    icon = icons.get(overall, "•")
    return f"""
<div class="v-banner v-banner-{overall}">
  <div>
    <div class="v-label">Overall verdict</div>
    <div class="{cls}">{icon} {overall.upper()}</div>
  </div>
  <div style="text-align:right">
    <div class="v-label">Total · Approved</div>
    <div style="font-size:1rem;font-weight:600;font-family:'DM Mono',monospace;color:#374151">
      ${total:.2f} · ${approved:.2f}
    </div>
    <div style="margin-top:4px">{conf_bar(confidence)}</div>
  </div>
</div>
"""


def fix_enc(s: str) -> str:
    """Repair UTF-8 mojibake stored as cp1252 (e.g. â€" → —)."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def emp_card(emp: dict) -> str:
    """Render employee info as HTML — no Streamlit metric truncation."""
    def v(key: str) -> str:
        return fix_enc(str(emp.get(key, "—")))

    purpose = fix_enc(emp.get("trip_purpose", "—"))
    return f"""
<div style="background:#fff;border:1px solid #e8ecf0;border-radius:10px;padding:14px 18px;margin-bottom:12px">
  <div style="display:grid;grid-template-columns:2fr 1fr 2fr 2fr;gap:16px">
    <div>
      <div class="stat-lbl">Name</div>
      <div style="font-weight:600;color:#0f172a;font-size:0.95rem">{v("name")}</div>
    </div>
    <div>
      <div class="stat-lbl">Grade</div>
      <div style="font-weight:600;color:#0f172a;font-size:0.95rem">{v("grade")}</div>
    </div>
    <div>
      <div class="stat-lbl">Trip dates</div>
      <div style="font-weight:600;color:#0f172a;font-size:0.85rem;font-family:'DM Mono',monospace">{v("trip_dates")}</div>
    </div>
    <div>
      <div class="stat-lbl">Title</div>
      <div style="font-weight:600;color:#0f172a;font-size:0.85rem">{v("title")}</div>
    </div>
  </div>
  <div style="margin-top:8px;font-size:0.78rem;color:#64748b;border-top:1px solid #f1f5f9;padding-top:8px">
    Purpose: {purpose}
  </div>
</div>
"""


def api(method: str, path: str, **kwargs):
    try:
        r = httpx.request(method, f"{API_URL}{path}", timeout=180, **kwargs)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = str(e)
        st.error(f"API error: {detail}")
        return None
    except httpx.HTTPError as e:
        st.error(f"Connection error: {e}")
        return None


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("""
<div style="padding:1rem 0 1.25rem;border-bottom:1px solid #1e293b;margin-bottom:1rem">
  <div style="font-size:1.05rem;font-weight:700;color:#f1f5f9;letter-spacing:-0.01em">Northwind</div>
  <div style="font-size:0.72rem;color:#475569;margin-top:2px">Expense Review System</div>
</div>
""", unsafe_allow_html=True)

PAGES = ["Dashboard", "New Submission", "Submission Detail", "Override Panel", "Policy Q&A", "Evaluation"]
if "current_page" not in st.session_state:
    st.session_state["current_page"] = "Dashboard"

page = st.sidebar.radio("", PAGES, index=PAGES.index(st.session_state["current_page"]))
st.session_state["current_page"] = page

st.sidebar.markdown("<div style='height:1px;background:#1e293b;margin:1rem 0'></div>", unsafe_allow_html=True)
st.sidebar.caption("API: " + API_URL)


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────
if page == "Dashboard":
    hcol, _ = st.columns([5, 1])
    with hcol:
        st.markdown("## Submissions")

    # Load data
    params = {}
    filter_col1, filter_col2, filter_col3 = st.columns([3, 2, 1])
    with filter_col1:
        q_emp = st.text_input("", placeholder="Search by employee name…", label_visibility="collapsed")
        if q_emp.strip():
            params["employee_name"] = q_emp.strip()
    with filter_col2:
        q_status = st.selectbox("", ["All statuses", "pending", "ingested", "analyzed"],
                                 label_visibility="collapsed")
        if q_status != "All statuses":
            params["status"] = q_status
    with filter_col3:
        st.write("")
        if st.button("Refresh", use_container_width=True):
            st.rerun()

    query_str = "&".join(f"{k}={v}" for k, v in params.items())
    path = f"/api/submissions?{query_str}" if query_str else "/api/submissions"
    submissions = api("GET", path) or []

    # Stats row
    total = len(submissions)
    n_compliant = sum(1 for s in submissions if s.get("effective_verdict") == "compliant")
    n_flagged   = sum(1 for s in submissions if s.get("effective_verdict") == "flagged")
    n_rejected  = sum(1 for s in submissions if s.get("effective_verdict") == "rejected")
    n_pending   = sum(1 for s in submissions if not s.get("effective_verdict"))
    st.markdown(f"""
<div class="stat-row">
  <div class="stat-card"><div class="stat-lbl">Submissions</div><div class="stat-val">{total}</div></div>
  <div class="stat-card"><div class="stat-lbl">Compliant</div><div class="stat-val" style="color:#15803d">{n_compliant}</div></div>
  <div class="stat-card"><div class="stat-lbl">Flagged</div><div class="stat-val" style="color:#b45309">{n_flagged}</div></div>
  <div class="stat-card"><div class="stat-lbl">Rejected</div><div class="stat-val" style="color:#b91c1c">{n_rejected}</div></div>
  <div class="stat-card"><div class="stat-lbl">Pending</div><div class="stat-val" style="color:#64748b">{n_pending}</div></div>
</div>
""", unsafe_allow_html=True)

    if not submissions:
        st.markdown('<div class="empty-state">No submissions found. Use <strong>New Submission</strong> to upload receipts, or ingest a test folder below.</div>', unsafe_allow_html=True)
    else:
        # Column headers
        h1, h2, h3, h4 = st.columns([4, 2.5, 1.8, 1.5])
        h1.markdown('<div style="font-size:0.72rem;color:#94a3b8;text-transform:uppercase;letter-spacing:0.07em;padding:0 0 6px 4px">Submission</div>', unsafe_allow_html=True)
        h2.markdown('<div style="font-size:0.72rem;color:#94a3b8;text-transform:uppercase;letter-spacing:0.07em;padding:0 0 6px 0">Employee</div>', unsafe_allow_html=True)
        h3.markdown('<div style="font-size:0.72rem;color:#94a3b8;text-transform:uppercase;letter-spacing:0.07em;padding:0 0 6px 0">Confidence</div>', unsafe_allow_html=True)

        for sub in submissions:
            verdict = sub.get("effective_verdict") or sub["status"]
            conf = sub.get("confidence")
            c1, c2, c3, c4 = st.columns([4, 2.5, 1.8, 1.5])
            with c1:
                st.markdown(
                    f'<div style="padding:6px 4px">'
                    f'<span class="sub-name">{sub["folder_name"]}</span>&nbsp;'
                    f'{pill(verdict)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with c2:
                st.markdown(
                    f'<div style="padding:6px 0;font-size:0.82rem;color:#64748b">'
                    f'{sub.get("employee_name","—")}'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with c3:
                if conf:
                    st.markdown(f'<div style="padding:6px 0">{conf_bar(conf)}</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div style="padding:6px 0;font-size:0.78rem;color:#cbd5e1">—</div>', unsafe_allow_html=True)
            with c4:
                if sub["status"] == "ingested":
                    if st.button("Analyze", key=f"an_{sub['id']}", use_container_width=True):
                        with st.spinner(""):
                            r = api("POST", f"/api/submissions/{sub['id']}/analyze")
                        if r:
                            st.rerun()
                elif sub["status"] == "analyzed":
                    if st.button("View →", key=f"vw_{sub['id']}", use_container_width=True, type="primary"):
                        st.session_state["selected_submission"] = sub["folder_name"]
                        st.session_state["current_page"] = "Submission Detail"
                        st.rerun()

    # Ingest test folders
    available = api("GET", "/api/submissions/available") or []
    not_ingested = [f["folder"] for f in available if not f["ingested"]]
    if not_ingested:
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        with st.expander(f"📂 Ingest test folders ({len(not_ingested)} available)"):
            ci1, ci2, ci3 = st.columns([3, 1, 1])
            with ci1:
                folder_pick = st.selectbox("Folder", not_ingested, label_visibility="collapsed")
            with ci2:
                if st.button("Ingest", use_container_width=True):
                    api("POST", f"/api/submissions/ingest?folder_name={folder_pick}")
                    st.rerun()
            with ci3:
                if st.button("Ingest all", use_container_width=True):
                    for f in not_ingested:
                        api("POST", f"/api/submissions/ingest?folder_name={f}")
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# New Submission
# ─────────────────────────────────────────────────────────────────────────────
elif page == "New Submission":
    st.markdown("## New Submission")
    st.caption("Select an employee, upload receipts, then analyze.")

    employees = api("GET", "/api/employees") or []

    # ── Step 1: Employee ──────────────────────────────────────────────────────
    st.markdown("#### 1 · Employee")
    tab_pick, tab_new_emp = st.tabs(["Select existing", "Create new"])

    selected_employee = st.session_state.get("ns_employee")

    with tab_pick:
        if not employees:
            st.info("No employees found yet.")
        else:
            emp_map = {f"{e['name']}  ({e['employee_id']}) — {e['title']}": e for e in employees}
            # Preselect if returning from tab_new
            pick_default = 0
            if selected_employee:
                for i, k in enumerate(emp_map):
                    if emp_map[k].get("employee_id") == selected_employee.get("employee_id"):
                        pick_default = i
                        break
            chosen = st.selectbox("Employee", list(emp_map.keys()), index=pick_default,
                                  label_visibility="collapsed")
            selected_employee = emp_map[chosen]
            st.session_state["ns_employee"] = selected_employee
            st.markdown(f"""
<div style="background:#f8fafc;border:1px solid #e8ecf0;border-radius:8px;padding:10px 14px;
            display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:4px">
  <div><div class="stat-lbl">Grade</div><div style="font-weight:600;color:#0f172a">{selected_employee["grade"]}</div></div>
  <div><div class="stat-lbl">Department</div><div style="font-weight:600;color:#0f172a;font-size:0.85rem">{selected_employee["department"]}</div></div>
  <div><div class="stat-lbl">Home base</div><div style="font-weight:600;color:#0f172a;font-size:0.85rem">{selected_employee.get("home_base","—")}</div></div>
  <div><div class="stat-lbl">ID</div><div style="font-weight:600;color:#0f172a;font-family:'DM Mono',monospace;font-size:0.82rem">{selected_employee["employee_id"]}</div></div>
</div>
""", unsafe_allow_html=True)

    with tab_new_emp:
        with st.form("new_emp_form"):
            fc1, fc2 = st.columns(2)
            n_id    = fc1.text_input("Employee ID *", placeholder="NW-00001")
            n_name  = fc2.text_input("Full Name *", placeholder="Jane Smith")
            fc3, fc4 = st.columns(2)
            n_grade = fc3.number_input("Grade *", 1, 10, 5)
            n_title = fc4.text_input("Title *", placeholder="Senior Manager")
            fc5, fc6 = st.columns(2)
            n_dept  = fc5.text_input("Department *", placeholder="Logistics Ops")
            n_home  = fc6.text_input("Home Base", placeholder="Irvine, CA")
            n_mgr   = st.text_input("Manager ID (optional)", placeholder="NW-00000")
            if st.form_submit_button("Create employee", type="primary"):
                if not n_id or not n_name or not n_title or not n_dept:
                    st.error("Employee ID, Name, Title and Department are required.")
                else:
                    res = api("POST", "/api/employees", json={
                        "employee_id": n_id, "name": n_name, "grade": int(n_grade),
                        "title": n_title, "department": n_dept,
                        "home_base": n_home or None, "manager_id": n_mgr or None,
                    })
                    if res:
                        st.success(f"Created {n_name} — switch to 'Select existing' to use them.")
                        st.rerun()

    st.divider()

    # ── Step 2: Receipts ──────────────────────────────────────────────────────
    st.markdown("#### 2 · Upload Receipts")
    st.caption("PDF, JPEG, PNG, or plain-text files — mix any formats freely.")

    if st.session_state.get("ns_uploaded"):
        info = st.session_state["ns_uploaded"]
        st.success(f"✓ Submission created — {info['file_count']} receipt(s) uploaded")
        ac1, ac2, ac3 = st.columns([2, 2, 3])
        with ac1:
            if st.button("Analyze now", type="primary", use_container_width=True):
                with st.spinner("Analyzing receipts…"):
                    vr = api("POST", f"/api/submissions/{info['id']}/analyze")
                if vr:
                    st.session_state["selected_submission"] = info["folder_name"]
                    st.session_state["current_page"] = "Submission Detail"
                    st.session_state.pop("ns_uploaded", None)
                    st.rerun()
        with ac2:
            if st.button("Go to Dashboard", use_container_width=True):
                st.session_state.pop("ns_uploaded", None)
                st.session_state["current_page"] = "Dashboard"
                st.rerun()
    else:
        with st.form("upload_form"):
            uc1, uc2 = st.columns(2)
            trip_purpose = uc1.text_input("Trip purpose", placeholder="Client meeting in Denver")
            trip_dates   = uc2.text_input("Trip dates", placeholder="2025-04-14 to 2025-04-16")
            files_up = st.file_uploader(
                "Receipt files",
                accept_multiple_files=True,
                type=["pdf", "jpg", "jpeg", "png", "txt"],
                label_visibility="visible",
            )
            if st.form_submit_button("Upload & create submission", type="primary"):
                if not selected_employee:
                    st.error("Select or create an employee first (Step 1).")
                elif not files_up:
                    st.error("Upload at least one receipt file.")
                else:
                    emp_json = dict(selected_employee)
                    emp_json["trip_purpose"] = trip_purpose or "Business travel"
                    emp_json["trip_dates"]   = trip_dates or "—"
                    files_payload = [
                        ("files", (f.name, f.getvalue(), f.type or "application/octet-stream"))
                        for f in files_up
                    ]
                    with st.spinner("Uploading…"):
                        try:
                            r = httpx.post(
                                f"{API_URL}/api/submissions/upload",
                                data={"employee_json": json.dumps(emp_json)},
                                files=files_payload, timeout=120,
                            )
                            r.raise_for_status()
                            res = r.json()
                        except httpx.HTTPStatusError as e:
                            try:
                                detail = e.response.json().get("detail", str(e))
                            except Exception:
                                detail = str(e)
                            st.error(f"Upload failed: {detail}")
                            res = None
                        except Exception as e:
                            st.error(f"Upload failed: {e}")
                            res = None
                    if res:
                        st.session_state["ns_uploaded"] = res
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Submission Detail
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Submission Detail":
    st.markdown("## Submission Detail")

    submissions = api("GET", "/api/submissions") or []
    names = [s["folder_name"] for s in submissions]
    if not names:
        st.markdown('<div class="empty-state">No submissions yet.</div>', unsafe_allow_html=True)
        st.stop()

    preselect = st.session_state.get("selected_submission")
    default_idx = names.index(preselect) if preselect in names else 0
    selected = st.selectbox("Submission", names, index=default_idx, label_visibility="collapsed")
    sub_id = next(s["id"] for s in submissions if s["folder_name"] == selected)

    detail = api("GET", f"/api/submissions/{sub_id}")
    if not detail:
        st.stop()

    emp = detail.get("employee", {})

    # Employee card
    st.markdown("##### Employee")
    st.markdown(emp_card(emp), unsafe_allow_html=True)

    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

    verdict = detail.get("verdict")
    if not verdict:
        st.warning("Not yet analyzed.")
        if st.button("Analyze now", type="primary"):
            with st.spinner("Analyzing…"):
                r = api("POST", f"/api/submissions/{sub_id}/analyze")
            if r:
                st.rerun()
        st.stop()

    overall    = detail.get("effective_verdict") or verdict["overall"]
    confidence = verdict["confidence"]
    total      = verdict.get("total_amount", 0)
    approved   = verdict.get("approved_amount", 0)

    # Verdict banner
    st.markdown(verdict_banner(overall, total, approved, confidence), unsafe_allow_html=True)

    if confidence < 0.6:
        st.markdown('<div class="low-conf">⚠️ <strong>Low confidence</strong> — human review required before approving.</div>', unsafe_allow_html=True)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if verdict.get("summary"):
        st.caption(verdict["summary"])

    # Line items
    st.markdown("##### Line Items")
    for item in verdict.get("line_items", []):
        iv = item["verdict"]
        with st.expander(
            f"{item['receipt_file']}  ·  ${item['amount']:.2f}  ·  {item['category']}"
            f"  —  {iv.upper()}  ({int(item['confidence']*100)}%)"
        ):
            cols = st.columns([1, 1])
            with cols[0]:
                st.markdown(f"**Verdict:** {pill(iv)}", unsafe_allow_html=True)
                st.markdown(f"<div style='font-size:0.85rem;margin-top:8px'>{item['reasoning']}</div>",
                            unsafe_allow_html=True)
            with cols[1]:
                citations = item.get("policy_citations", [])
                if citations:
                    st.markdown("**Policy citations:**")
                    for c in citations:
                        st.markdown(citation_html(c), unsafe_allow_html=True)
                else:
                    st.caption("No citations.")

    # Override history
    overrides = detail.get("overrides", [])
    if overrides:
        st.markdown("##### Override History")
        for o in overrides:
            st.markdown(
                f'<div class="ov-entry">'
                f'<strong>{o["reviewer_id"]}</strong> &nbsp;'
                f'{pill(o["original_verdict"])} → {pill(o["new_verdict"])}'
                f'<div class="ov-meta">{o["justification"]}  ·  {o["created_at"][:19]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Override Panel
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Override Panel":
    st.markdown("## Override Panel")

    submissions = api("GET", "/api/submissions") or []
    analyzed = [s for s in submissions if s.get("effective_verdict")]
    if not analyzed:
        st.markdown('<div class="empty-state">No analyzed submissions yet.</div>', unsafe_allow_html=True)
        st.stop()

    ov_sel = st.selectbox(
        "Submission",
        [s["folder_name"] for s in analyzed],
        label_visibility="collapsed",
    )
    sub = next(s for s in analyzed if s["folder_name"] == ov_sel)
    detail = api("GET", f"/api/submissions/{sub['id']}")
    if not detail or not detail.get("verdict"):
        st.warning("No verdict found.")
        st.stop()

    verdict    = detail["verdict"]
    verdict_id = detail.get("verdict_id")
    current    = detail.get("effective_verdict") or verdict["overall"]

    # Current state
    st.markdown(verdict_banner(current, verdict.get("total_amount", 0),
                               verdict.get("approved_amount", 0), verdict["confidence"]),
                unsafe_allow_html=True)
    if verdict.get("summary"):
        st.caption(verdict["summary"])

    # Line items summary
    st.markdown("##### Line Items")
    li_cols = st.columns([3, 2, 1.5])
    li_cols[0].markdown('<span style="font-size:0.72rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.07em">File</span>', unsafe_allow_html=True)
    li_cols[1].markdown('<span style="font-size:0.72rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.07em">Verdict</span>', unsafe_allow_html=True)
    li_cols[2].markdown('<span style="font-size:0.72rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.07em">Amount</span>', unsafe_allow_html=True)
    for item in verdict.get("line_items", []):
        r1, r2, r3 = st.columns([3, 2, 1.5])
        r1.markdown(f'<div style="font-size:0.82rem;padding:3px 0">{item["receipt_file"]}</div>', unsafe_allow_html=True)
        r2.markdown(pill(item["verdict"]), unsafe_allow_html=True)
        r3.markdown(f'<div style="font-size:0.82rem;font-family:DM Mono,monospace;padding:3px 0">${item["amount"]:.2f}</div>', unsafe_allow_html=True)

    st.divider()
    st.markdown("##### Submit Override")
    with st.form("override_form"):
        ov1, ov2 = st.columns(2)
        reviewer_id = ov1.text_input("Reviewer ID", placeholder="reviewer@northwind.com")
        new_verdict_sel = ov2.selectbox("New verdict", ["compliant", "flagged", "rejected"])
        justification = st.text_area("Justification (min 10 characters)")
        if st.form_submit_button("Submit override", type="primary"):
            if not reviewer_id.strip():
                st.error("Reviewer ID is required.")
            elif len(justification.strip()) < 10:
                st.error("Justification must be at least 10 characters.")
            elif not verdict_id:
                st.error("Verdict ID missing — try re-analyzing the submission.")
            else:
                res = api("POST", "/api/overrides", json={
                    "verdict_id": verdict_id,
                    "reviewer_id": reviewer_id.strip(),
                    "new_verdict": new_verdict_sel,
                    "justification": justification.strip(),
                })
                if res:
                    st.success(f"Override recorded → {new_verdict_sel.upper()}")
                    st.rerun()

    overrides = detail.get("overrides", [])
    if overrides:
        st.markdown("##### Override History")
        for o in overrides:
            st.markdown(
                f'<div class="ov-entry">'
                f'<strong>{o["reviewer_id"]}</strong> &nbsp;'
                f'{pill(o["original_verdict"])} → {pill(o["new_verdict"])}'
                f'<div class="ov-meta">{o["justification"]}  ·  {o["created_at"][:19]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Policy Q&A
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Policy Q&A":
    st.markdown("## Policy Q&A")
    st.caption(
        "Ask anything about Northwind expense and travel policy. "
        "Answers are grounded in indexed policy documents with verbatim citations. "
        "Out-of-scope questions are declined."
    )

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    # Render history
    for turn in st.session_state["chat_history"]:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            if turn.get("is_out_of_scope"):
                st.markdown('<div class="oos-msg">🚫 <strong>Out of scope</strong> — This question is outside the expense and travel policy scope.</div>', unsafe_allow_html=True)
            else:
                st.write(turn["answer"])
                for c in turn.get("citations", []):
                    st.markdown(citation_html(c, green=True), unsafe_allow_html=True)

    # Input
    question = st.chat_input("Ask a policy question…")
    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("Searching policy library…"):
                try:
                    r = httpx.get(f"{API_URL}/api/chat", params={"question": question}, timeout=60)
                    r.raise_for_status()
                    result = r.json()
                except Exception as e:
                    st.error(f"Error: {e}")
                    result = None
            if result:
                if result.get("is_out_of_scope"):
                    st.markdown('<div class="oos-msg">🚫 <strong>Out of scope</strong> — This question is outside the expense and travel policy scope.</div>', unsafe_allow_html=True)
                else:
                    st.write(result["answer"])
                    for c in result.get("citations", []):
                        st.markdown(citation_html(c, green=True), unsafe_allow_html=True)
                st.session_state["chat_history"].append({
                    "question": question,
                    "answer": result.get("answer", ""),
                    "is_out_of_scope": result.get("is_out_of_scope", False),
                    "citations": result.get("citations", []),
                })

    if st.session_state["chat_history"]:
        if st.button("Clear conversation", use_container_width=False):
            st.session_state["chat_history"] = []
            st.rerun()

    # Policy chunk debug search
    with st.expander("🔎 Search raw policy chunks"):
        st.caption("Inspect indexed content and verify retrieval quality.")
        q_chunk = st.text_input("Query", placeholder="meal allowance per diem cap", key="chunk_q")
        if q_chunk:
            chunks = api("GET", f"/api/policies/search?q={q_chunk}") or []
            for ch in chunks:
                with st.expander(
                    f"{ch['doc_id']} · {ch['section']} · p.{ch['page']}  (score {ch['score']:.4f})"
                ):
                    st.text(ch["text"])


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────────────────
elif page == "Evaluation":
    st.markdown("## Evaluation Harness")
    st.caption("Upload `expected_outcomes.json` to measure verdict accuracy, citation quality, retrieval hit@5, and calibration (ECE).")

    ev_col1, ev_col2 = st.columns([3, 1])
    with ev_col1:
        uploaded = st.file_uploader("expected_outcomes.json", type="json", label_visibility="collapsed")
    with ev_col2:
        st.write("")
        run_btn = st.button("Run evaluation", type="primary", use_container_width=True,
                            disabled=uploaded is None)

    if uploaded and run_btn:
        with st.spinner("Running evaluation…"):
            try:
                r = httpx.post(f"{API_URL}/api/eval",
                               files={"file": ("expected_outcomes.json", uploaded.read(), "application/json")},
                               timeout=300)
                r.raise_for_status()
                result = r.json()
            except Exception as e:
                st.error(str(e))
                result = None

        if result:
            st.success("Evaluation complete")
            st.markdown(f"""
<div class="stat-row">
  <div class="stat-card"><div class="stat-lbl">Overall accuracy</div><div class="stat-val">{result['verdict_accuracy_overall']:.0%}</div></div>
  <div class="stat-card"><div class="stat-lbl">Line item accuracy</div><div class="stat-val">{result['verdict_accuracy_line_items']:.0%}</div></div>
  <div class="stat-card"><div class="stat-lbl">Citation precision</div><div class="stat-val">{result['citation_precision']:.0%}</div></div>
  <div class="stat-card"><div class="stat-lbl">Citation recall</div><div class="stat-val">{result['citation_recall']:.0%}</div></div>
  <div class="stat-card"><div class="stat-lbl">Retrieval hit@5</div><div class="stat-val">{result['retrieval_hit_at_5']:.0%}</div></div>
  <div class="stat-card"><div class="stat-lbl">ECE</div><div class="stat-val">{result['ece']:.3f}</div></div>
</div>
""", unsafe_allow_html=True)

            st.markdown("##### Confidence Calibration")
            buckets = result.get("bucketed_accuracy", [])
            if buckets:
                import pandas as pd
                df = pd.DataFrame(buckets)
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.bar_chart(df.set_index("bucket")[["mean_confidence", "accuracy"]],
                             use_container_width=True)

            st.markdown("##### Per Submission")
            st.dataframe(result.get("per_submission", []), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("##### Past Runs")
    past = api("GET", "/api/eval/results") or []
    if not past:
        st.caption("No evaluation runs yet.")
    for p in past:
        ece_str = f"{p['ece']:.4f}" if p.get("ece") else "—"
        run_str = (p.get("run_at") or "")[:19]
        st.markdown(
            f'<div class="ov-entry"><strong>{p["filename"]}</strong>'
            f'<div class="ov-meta">ECE: {ece_str}  ·  {run_str}</div></div>',
            unsafe_allow_html=True,
        )
