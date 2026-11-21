"""ClassPulse AI - Streamlit front end for multimodal attendance and engagement."""
from __future__ import annotations

from datetime import date, datetime, timezone
from html import escape
from io import BytesIO
import importlib
import os
import hashlib
import re
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

# Local .env files are ignored by Git. Streamlit Cloud secrets are copied into
# the process environment so every service module reads one consistent source.
load_dotenv()
for _secret_name in (
    "AUTH_BACKEND",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SYNC_ENABLED",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
):
    if not os.getenv(_secret_name):
        try:
            _secret_value = st.secrets.get(_secret_name)
        except Exception:
            _secret_value = None
        if _secret_value:
            os.environ[_secret_name] = str(_secret_value)

try:
    import auth
except ImportError:  # Services are optional while the UI is being previewed.
    auth = None  # type: ignore[assignment]
try:
    import storage
except ImportError:
    storage = None  # type: ignore[assignment]
try:
    import ai_pipeline
except ImportError:
    ai_pipeline = None  # type: ignore[assignment]

import styles as _styles

_styles = importlib.reload(_styles)
APP_CSS = _styles.APP_CSS
DARK_THEME_CSS = _styles.DARK_THEME_CSS

_CAMERA_COUNTER = components.declare_component(
    "classpulse_visible_face_counter",
    path=os.path.join(os.path.dirname(__file__), "camera_counter"),
)


st.set_page_config(
    page_title="ClassPulse AI | Classroom intelligence",
    page_icon="CP",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _initialise() -> None:
    if "user" not in st.session_state:
        st.session_state.user = None
    if "analysis_result" not in st.session_state:
        st.session_state.analysis_result = None
    if "dark_mode" not in st.session_state:
        st.session_state.dark_mode = True
    if storage is not None:
        try:
            storage.init_db()
        except Exception:
            # Keep the demo front end available even if an optional backend is not configured.
            pass


def _safe_user_name(user: Any) -> str:
    if isinstance(user, dict):
        return str(user.get("name") or user.get("email") or "Instructor")
    return "Instructor"


def _uses_persistent_supabase_storage(user: Any) -> bool:
    return bool(
        isinstance(user, dict)
        and user.get("backend") == "supabase"
        and getattr(user, "access_token", None)
        and os.getenv("SUPABASE_SYNC_ENABLED", "").strip().casefold() in {"1", "true", "yes"}
        and os.getenv("SUPABASE_URL", "").strip()
        and os.getenv("SUPABASE_ANON_KEY", "").strip()
    )


def _safe_storage_error(exc: Exception) -> str:
    """Return a short diagnostic without leaking credentials or request headers."""
    message = str(exc).replace("\n", " ").strip()
    for secret_name in ("SUPABASE_ANON_KEY", "GEMINI_API_KEY"):
        secret = os.getenv(secret_name, "").strip()
        if secret:
            message = message.replace(secret, "[redacted]")
    token = getattr(st.session_state.get("user"), "access_token", None)
    if token:
        message = message.replace(token, "[redacted]")
    message = re.sub(r"https://[a-z0-9-]+\.supabase\.co", "[Supabase project URL]", message, flags=re.I)
    return f"{type(exc).__name__}: {message[:240]}" if message else type(exc).__name__


def _fallback_data() -> dict[str, Any]:
    """Sample content makes the application explorable before setup is complete."""
    return {
        "metrics": {
            "attendance_rate": 84,
            "present_count": 126,
            "student_count": 150,
            "engagement_score": 78,
            "participation_count": 32,
            "sessions_this_week": 12,
        },
        "engagement_trend": [62, 58, 64, 61, 76, 70, 72, 64, 77, 80, 74, 83, 79, 88, 81],
        "classes": [
            {"name": "Biology · Cell division", "time": "09:00–09:50", "room": "Room B204", "status": "Live now"},
            {"name": "Physics · Wave motion", "time": "11:00–11:50", "room": "Room B204", "status": "Up next"},
            {"name": "Mathematics · Integrals", "time": "13:00–13:50", "room": "Room A108", "status": "Scheduled"},
        ],
        "attendance": [
            {"student": "Aarav Sharma", "student_id": "STU-1042", "status": "Present", "confidence": "High"},
            {"student": "Diya Patel", "student_id": "STU-1078", "status": "Present", "confidence": "High"},
            {"student": "Kabir Rao", "student_id": "STU-1103", "status": "Review", "confidence": "Low light"},
            {"student": "Meera Nair", "student_id": "STU-1144", "status": "Present", "confidence": "High"},
            {"student": "Ishaan Gupta", "student_id": "STU-1168", "status": "Absent", "confidence": "—"},
        ],
        "insights": [
            {"title": "Try a quick check-in", "detail": "Engagement dipped during the last explanation. A short retrieval question may help refocus."},
            {"title": "Build on the visual example", "detail": "The group engagement estimate rose after the cell-cycle diagram."},
            {"title": "Review signal quality", "detail": "A few faces were occluded. Confirm attendance manually before saving."},
        ],
    }


def _dashboard_data(user: Any) -> dict[str, Any]:
    # Demo fixtures must never appear in a real user's workspace.
    if isinstance(user, dict) and user.get("demo"):
        return _fallback_data()
    if storage is not None:
        try:
            user_id = user.get("id") if isinstance(user, dict) else None
            token = getattr(user, "access_token", None) if isinstance(user, dict) else None
            data = storage.get_dashboard_data(owner_id=user_id, access_token=token)
            if isinstance(data, dict) and data:
                recent = data.get("recent_sessions") or []
                engagement = data.get("engagement_average")
                trend = [s.get("engagement_score") for s in reversed(recent) if s.get("engagement_score") is not None]
                try:
                    roster = storage.list_students(user_id, access_token=token) if user_id is not None else []
                    today_records = storage.list_attendance(
                        user_id, date.today().isoformat(), access_token=token
                    ) if user_id is not None else []
                except Exception:
                    roster, today_records = [], []
                today_present = sum(1 for row in today_records if row.get("present"))
                metrics = {
                    "attendance_rate": round(100 * today_present / len(today_records)) if today_records else data.get("attendance_rate") or 0,
                    "present_count": today_present if today_records else data.get("attendance_total") or 0,
                    "student_count": len(roster) if roster else data.get("enrollment_total") or 0,
                    "engagement_score": engagement if engagement is not None else "—",
                    "participation_count": data.get("participation_total") or 0,
                    "sessions_this_week": data.get("sessions_this_week") or 0,
                }
                return {
                    "metrics": metrics,
                    "engagement_trend": trend,
                    "classes": [
                        {"name": s.get("class_name", "Class session"), "time": str(s.get("started_at", ""))[:16], "room": "Saved session", "status": "Complete"}
                        for s in recent
                    ],
                    # Roster rows are returned only for this authenticated owner.
                    "attendance": [
                        {"student": row.get("student_name", "Student"),
                         "student_id": row.get("student_code", ""),
                         "status": str(row.get("status", "unmarked")).title(),
                         "confidence": "Manually confirmed"}
                        for row in today_records
                    ],
                    "insights": [],
                }
        except Exception:
            st.warning("Your saved dashboard data could not be loaded. Check the signed-in account's storage configuration and refresh.")
    return {
        "metrics": {"attendance_rate": 0, "present_count": 0, "student_count": 0,
                    "engagement_score": "—", "participation_count": 0, "sessions_this_week": 0},
        "engagement_trend": [], "classes": [], "attendance": [], "insights": [],
    }


def _metric_card(label: str, value: str, note: str, accent: str = "violet") -> None:
    st.markdown(
        f'<div class="metric-card {escape(accent)}"><div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value">{escape(str(value))}</div><div class="metric-note">{escape(note)}</div></div>',
        unsafe_allow_html=True,
    )


def _login_screen() -> None:
    st.markdown('<div class="brand-lockup"><span class="brand-mark">CP</span><span>ClassPulse <b>AI</b></span></div>', unsafe_allow_html=True)
    left, center, right = st.columns([1.05, 1.2, 1.05])
    with center:
        st.markdown(
            '<div class="auth-eyebrow">MULTIMODAL CLASSROOM INTELLIGENCE</div>'
            '<h1 class="auth-title">Every class,<br><span>understood.</span></h1>'
            '<p class="auth-copy">Bring attendance, participation, and session signals into one calm, useful workspace.</p>',
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            login_tab, signup_tab = st.tabs(["Sign in", "Create account"])
            with login_tab:
                with st.form("login_form", clear_on_submit=False):
                    email = st.text_input("Email address", placeholder="you@school.edu", autocomplete="email")
                    password = st.text_input("Password", type="password", placeholder="Enter your password", autocomplete="current-password")
                    submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
                    if submitted:
                        if not email.strip() or not password:
                            st.error("Enter your email and password to continue.")
                        elif auth is None:
                            st.error("Authentication is not configured yet. Use the demo workspace below.")
                        else:
                            try:
                                user = auth.authenticate(email.strip(), password)
                                if user:
                                    st.session_state.user = user
                                    st.rerun()
                                st.error("We couldn't sign you in. Check your details and try again.")
                            except Exception:
                                st.error("Sign in is temporarily unavailable. Check your configuration and try again.")
            with signup_tab:
                with st.form("signup_form", clear_on_submit=True):
                    name = st.text_input("Full name", placeholder="Your name", autocomplete="name")
                    email_new = st.text_input("School email", placeholder="you@school.edu", autocomplete="email")
                    password_new = st.text_input("Create password", type="password", placeholder="At least 10 characters", autocomplete="new-password")
                    submitted_new = st.form_submit_button("Create account", type="primary", use_container_width=True)
                    if submitted_new:
                        if not name.strip() or not email_new.strip() or len(password_new) < 10:
                            st.error("Add your name and email, and choose a password with at least 10 characters.")
                        elif auth is None:
                            st.error("Account creation is not configured yet. Use the demo workspace below.")
                        else:
                            try:
                                user = auth.register(email_new.strip(), password_new, name.strip())
                                if user:
                                    if user.get("pending_verification"):
                                        st.success("Account created. Check your email to verify it before signing in.")
                                    else:
                                        st.session_state.user = user
                                        st.success("Your account is ready.")
                                        st.rerun()
                                st.error("We couldn't create that account. The email may already be registered.")
                            except Exception:
                                st.error("Account creation is temporarily unavailable. Check your configuration and try again.")
        st.markdown('<div class="auth-divider"><span>OR EXPLORE FIRST</span></div>', unsafe_allow_html=True)
        if st.button("Open the demo workspace", use_container_width=True, key="demo_login"):
            st.session_state.user = {"id": "demo", "name": "Demo Instructor", "email": "demo@classpulse.local", "demo": True}
            st.rerun()
        st.caption("Demo mode uses sample classroom records. No camera or microphone is accessed unless you choose an input.")
        st.markdown('<div class="auth-footer">Privacy-aware by design · Built for educators</div>', unsafe_allow_html=True)


def _sidebar(user: Any) -> str:
    with st.sidebar:
        st.markdown('<div class="sidebar-brand"><span class="brand-mark">CP</span><span>ClassPulse <b>AI</b></span></div>', unsafe_allow_html=True)
        st.caption("INSTRUCTOR WORKSPACE")
        if os.getenv("CLASSPULSE_DEPLOYMENT") == "streamlit_community_cloud":
            if user.get("demo"):
                st.info("Demo mode uses example data only. Sign in to save your own class records.")
            elif _uses_persistent_supabase_storage(user):
                st.success("Your class roster, attendance, and session summaries use your Supabase account.")
            else:
                st.warning("This account is using hosted SQLite. Streamlit may reset it after a restart. Configure Supabase Auth and sync in private App Secrets for durable class data.")
        page = st.radio("Navigation", ["Overview", "Attendance", "Live session", "Insights", "AI teaching coach"], label_visibility="collapsed")
        st.markdown("<div class='sidebar-spacer'></div>", unsafe_allow_html=True)
        st.toggle("Dark mode", key="dark_mode", help="Switch between dark and light appearance.")
        st.markdown('<div class="privacy-chip"><span class="privacy-dot"></span><div><b>Privacy first</b><small>Local analysis · No raw media saved</small></div></div>', unsafe_allow_html=True)
        st.divider()
        st.caption(_safe_user_name(user))
        if st.button("Sign out", use_container_width=True):
            st.session_state.user = None
            st.session_state.analysis_result = None
            st.session_state.pop("teaching_chat_history", None)
            st.session_state.pop("quiz_chat_history", None)
            st.rerun()
    return page


def _render_overview(data: dict[str, Any]) -> None:
    metrics = data.get("metrics", {})
    st.markdown(f'<div class="page-kicker">{date.today().strftime("%A, %d %b %Y").upper()}</div>', unsafe_allow_html=True)
    st.title("Your classroom, at a glance")
    st.markdown("A clear read on today’s attendance and engagement signals.")
    metrics_empty = not data.get("classes") and not any((
        metrics.get("present_count"), metrics.get("student_count"),
        metrics.get("participation_count"), metrics.get("sessions_this_week"),
    ))
    if metrics_empty:
        st.info("Your account is ready. Create a class and roster in Attendance, then analyze and save a session to build your personal dashboard. Demo sample data is kept separate from your account.")
    cols = st.columns(4)
    with cols[0]: _metric_card("ATTENDANCE RATE", f"{metrics.get('attendance_rate', 84)}%", f"{metrics.get('present_count', 126)} of {metrics.get('student_count', 150)} roster entries present")
    with cols[1]: _metric_card("CLASS ENGAGEMENT", f"{metrics.get('engagement_score', 78)} /100", "Group-level estimate · review before acting", "mint")
    with cols[2]: _metric_card("PARTICIPATION", str(metrics.get("participation_count", 32)), "Contributions across recent sessions", "amber")
    with cols[3]: _metric_card("SESSIONS THIS WEEK", str(metrics.get("sessions_this_week", 12)), "Across your active classes", "blue")

    left, right = st.columns([1.65, 1])
    with left:
        with st.container(border=True):
            st.subheader("Engagement over time")
            st.caption("Multimodal signal estimates, aggregated across the class")
            trend = data.get("engagement_trend", _fallback_data()["engagement_trend"])
            if trend:
                st.area_chart(pd.DataFrame({"Engagement estimate": trend}), color="#7357F5", height=245)
            else:
                st.info("Engagement trends will appear after you save session summaries.")
    with right:
        with st.container(border=True):
            st.subheader("Recent sessions")
            recent_sessions = data.get("classes", [])
            for item in recent_sessions:
                with st.container(border=True):
                    st.markdown(f"**{item.get('name', 'Class session')}**")
                    st.caption(f"{item.get('time', '')} · {item.get('room', '')}")
                    st.markdown(f"<span class='status-pill'>{escape(str(item.get('status', 'Scheduled')))}</span>", unsafe_allow_html=True)
            if not recent_sessions:
                st.info("No saved sessions yet. Analyze a class session to start your history.")
    below_left, below_right = st.columns([1.15, 1])
    with below_left:
        with st.container(border=True):
            st.subheader("Recent attendance")
            attendance = data.get("attendance", [])
            if attendance:
                st.dataframe(pd.DataFrame(attendance), use_container_width=True, hide_index=True)
            else:
                st.info("No attendance records yet. Start a session to capture one.")
    with below_right:
        with st.container(border=True):
            st.subheader("Instructor suggestions")
            insights = data.get("insights", [])[:3]
            for insight in insights:
                st.markdown(f"**{insight.get('title', 'Classroom signal')}**")
                st.caption(insight.get("detail", "Review the session signals."))
                st.markdown("---")
            if not insights:
                st.info("Teaching suggestions appear here after you analyze a session. The AI coach and quiz builder are ready in the sidebar.")


def _render_attendance(data: dict[str, Any]) -> None:
    st.markdown('<div class="page-kicker">CLASS ROSTER</div>', unsafe_allow_html=True)
    st.title("Attendance review")
    st.markdown("Add a local class roster, then confirm each student’s attendance yourself. Face counts can prompt a review, but never identify or mark a student automatically.")
    user = st.session_state.get("user") or {}
    owner_id = user.get("id") if isinstance(user, dict) else None
    access_token = getattr(user, "access_token", None) if isinstance(user, dict) else None
    is_demo = isinstance(user, dict) and user.get("demo")
    class_id = None
    if is_demo:
        class_name = st.selectbox(
            "Class",
            [c.get("name", "Class 1") for c in data.get("classes", [])] or ["Class 1"],
            key="attendance_demo_class",
        )
    else:
        try:
            local_classes = storage.list_classes(owner_id, access_token=access_token) if storage is not None and owner_id is not None else []
        except Exception as exc:
            local_classes = []
            if access_token and os.getenv("SUPABASE_SYNC_ENABLED", "").strip().casefold() in {"1", "true", "yes"}:
                st.error("Supabase could not load this account’s classes. Apply the latest class-roster migration and check the project URL, anon key, and RLS permissions.")
                st.caption(_safe_storage_error(exc))
            else:
                st.error("Local classes could not be loaded. Check database setup and refresh.")
                st.caption(_safe_storage_error(exc))
        if not local_classes:
            st.info("Create a class first. Each class keeps its own roster and attendance history.")
            with st.form("create_local_class_form", clear_on_submit=True):
                new_class = st.text_input("Class name", max_chars=100, placeholder="e.g. Grade 8 · Science")
                create = st.form_submit_button("Create class", type="primary")
                if create:
                    try:
                        storage.create_class(owner_id, new_class, access_token=access_token)
                        st.success("Class created. Add its students below.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
                    except RuntimeError as exc:
                        st.error(str(exc))
                    except Exception:
                        st.error("Class could not be saved. Check the database configuration and try again.")
            class_name = ""
        else:
            selected = st.selectbox(
                "Class",
                local_classes,
                format_func=lambda row: row["name"],
                key="attendance_class_select",
            )
            class_id = int(selected["id"])
            class_name = selected["name"]
    controls = st.columns([1, 1.6])
    with controls[0]:
        session_date = st.date_input("Session date", value=date.today(), key="attendance_session_date")
    with controls[1]:
        st.markdown("<div class='privacy-note'>Camera frames are analyzed in your browser; only an approximate count returns to this app. Supabase-authenticated accounts use their own Supabase project when sync is enabled; local accounts use SQLite.</div>", unsafe_allow_html=True)

    if is_demo:
        st.info("Demo roster · example names and statuses only. Changes stay in this browser session and are not saved to the database.")
        sample = data.get("attendance", [])
        demo_saved = st.session_state.get("demo_attendance")
        if demo_saved:
            saved_by_code = {str(row.get("roster_code")): row for row in demo_saved}
            sample = [
                {**row, "status": saved_by_code.get(str(row.get("student_id")), {}).get("status", row.get("status"))}
                for row in sample
            ]
        roster = [
            {"id": row.get("student_id", f"demo-{i}"), "name": row.get("student", "Sample student"),
             "student_code": row.get("student_id", ""), "status": row.get("status", "Unmarked")}
            for i, row in enumerate(sample)
        ]
        if not roster:
            roster = st.session_state.get("demo_roster", [])
    else:
        try:
            roster = storage.list_students(owner_id, class_id, access_token=access_token) if storage is not None and owner_id is not None and class_id is not None else []
        except Exception:
            roster = []
            st.error("The local roster could not be loaded. Check the database setup and refresh.")

    if not is_demo and class_id is not None:
        with st.expander("Manage this class roster", expanded=not bool(roster)):
            with st.form("add_student_form", clear_on_submit=True):
                new_name = st.text_input("Student name", max_chars=100)
                new_code = st.text_input("Roster code (optional)", max_chars=32, help="Leave blank to create a local roster code.")
                add_student = st.form_submit_button("Add student", type="primary")
                if add_student:
                    if storage is None or owner_id is None:
                        st.error("Local storage is unavailable; this roster was not saved.")
                    elif not new_name.strip():
                        st.error("Enter a student name.")
                    else:
                        try:
                            storage.add_student(owner_id, new_name.strip(), new_code.strip(), class_id=class_id, access_token=access_token)
                            st.success("Student added to this class roster.")
                            st.rerun()
                        except Exception as exc:
                            st.error("Student could not be saved. Check for a duplicate roster code and confirm the database migration is active.")
                            st.caption(_safe_storage_error(exc))
            if class_id is not None:
                try:
                    unenrolled = storage.list_unenrolled_students(owner_id, class_id, access_token=access_token)
                except Exception:
                    unenrolled = []
                    st.warning("Existing students could not be loaded. You can still add a new student to this class.")
                if unenrolled:
                    with st.form("enroll_existing_student_form", clear_on_submit=True):
                        existing_id = st.selectbox("Add an existing local student", unenrolled, format_func=lambda row: f"{row['name']} · {row['student_code']}")
                        if st.form_submit_button("Enroll in this class"):
                            storage.enroll_student(owner_id, class_id, int(existing_id["id"]), access_token=access_token)
                            st.success("Student enrolled in this class.")
                            st.rerun()

    if roster:
        prior_status = {}
        if not is_demo and storage is not None:
            try:
                saved = storage.list_attendance(owner_id, session_date.isoformat(), class_name.strip(), access_token=access_token)
                prior_status = {str(row.get("student_id")): ("Present" if row.get("present") else "Absent") for row in saved}
            except Exception:
                st.warning("Could not load saved attendance for this date and class.")
        attendance_rows = []
        selection_key = f"attendance_present_selection_{owner_id}_{class_id or class_name}_{session_date.isoformat()}"
        applied_selection_key = f"attendance_selection_applied_{owner_id}_{class_id or class_name}_{session_date.isoformat()}"
        selected_present_ids = st.session_state.get(selection_key)
        applied_selection = bool(st.session_state.get(applied_selection_key))
        for row in roster:
            student_id = row.get("id")
            status = prior_status.get(str(student_id), row.get("status", "Unmarked") if is_demo else "Unmarked")
            if applied_selection and selected_present_ids is not None:
                status = "Present" if str(student_id) in selected_present_ids else "Absent"
            if status == "Review":
                status = "Unmarked"
            attendance_rows.append({
                "student_id": student_id,
                "student": row.get("name", "Student"),
                "roster_code": row.get("student_code", ""),
                "status": status if status in {"Present", "Absent", "Unmarked"} else "Unmarked",
            })
        selection_names = {str(row.get("id")): row.get("name", "Student") for row in roster}
        initially_present = [
            str(row["student_id"]) for row in attendance_rows if row["status"] == "Present"
        ]
        with st.container(border=True):
            st.subheader("Choose students present")
            st.caption("Select names directly, apply the selection, then review each student’s status below before saving.")
            st.multiselect(
                "Present students",
                options=[str(row.get("id")) for row in roster],
                default=initially_present,
                format_func=lambda value: selection_names.get(str(value), "Student"),
                key=selection_key,
            )
            if st.button("Apply selected names", key=f"apply_attendance_selection_{owner_id}_{class_id or class_name}_{session_date.isoformat()}"):
                st.session_state[applied_selection_key] = True
                st.rerun()
        editor_id = hashlib.sha256(f"{owner_id}:{class_name}:{session_date.isoformat()}".encode()).hexdigest()[:12]
        edited = st.data_editor(
            pd.DataFrame(attendance_rows),
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key=f"attendance_editor_{editor_id}",
            column_config={
                "student_id": None,
                "student": st.column_config.TextColumn("Student", disabled=True),
                "roster_code": st.column_config.TextColumn("Local roster code", disabled=True),
                "status": st.column_config.SelectboxColumn("Attendance", options=["Unmarked", "Present", "Absent"], required=True),
            },
        )
        marked = bool(len(edited)) and all(value in {"Present", "Absent"} for value in edited["status"].tolist())
        c1, c2, c3 = st.columns([1.1, 1.1, 2.1])
        with c1:
            if is_demo:
                save_demo = st.button("Save demo attendance", type="primary", disabled=not marked, key="save_demo_attendance")
                if save_demo:
                    st.session_state.demo_attendance = edited[["student", "roster_code", "status"]].to_dict("records")
                    st.success("Saved in this session only. Demo data was not written to local storage.")
            else:
                save = st.button("Save confirmed attendance", type="primary", disabled=not marked, key="save_confirmed_attendance")
                if save:
                    try:
                        records = [
                            {"student_id": int(row.student_id), "present": row.status == "Present"}
                            for row in edited.itertuples(index=False)
                        ]
                        storage.save_attendance(owner_id, session_date.isoformat(), class_name.strip(), records, access_token=access_token)
                        st.success("Attendance saved for this class and date.")
                        st.rerun()
                    except Exception as exc:
                        st.error("Attendance could not be saved. Confirm every status and check the account’s database configuration.")
                        st.caption(_safe_storage_error(exc))
        with c2:
            if not is_demo:
                remove_id = st.selectbox("Remove student", [None] + [r.get("id") for r in roster], format_func=lambda value: "Choose…" if value is None else next((r.get("name", "Student") for r in roster if r.get("id") == value), "Student"), key="remove_student_id")
                confirm_remove = st.checkbox("Confirm local removal", key="confirm_remove_student")
                if st.button("Remove", disabled=remove_id is None or not confirm_remove, key="remove_student_button"):
                    try:
                        storage.remove_student_from_class(owner_id, class_id, int(remove_id), access_token=access_token)
                        st.success("Student removed from this class. Their other classes and history remain.")
                        st.rerun()
                    except Exception:
                        st.error("Student could not be removed.")
        with c3:
            if not marked:
                st.caption("Mark every student Present or Absent before saving the attendance list.")
        csv_rows = edited[["student", "roster_code", "status"]]
        st.download_button("Download confirmed attendance CSV", csv_rows.to_csv(index=False), file_name=f"attendance-{session_date.isoformat()}.csv", mime="text/csv", disabled=not marked)
    else:
        st.info("Your local roster is empty. Add students above to start manual attendance.")
    with st.expander("Live camera attendance estimate", expanded=True):
        st.caption("Select the class above, then start the camera. The browser estimates how many faces are visible and never identifies people or marks names present. Confirm each student in the roster before saving.")
        if class_id is None and not is_demo:
            st.caption("You can preview a face count before creating a class; attendance requires a selected class and roster.")
        camera_state = _CAMERA_COUNTER(key=f"attendance_camera_{owner_id}_{class_id or class_name or 'unassigned'}", default={"active": False, "count": None})
        if isinstance(camera_state, dict) and camera_state.get("active") and isinstance(camera_state.get("count"), int):
            visible_estimate = max(0, min(1000, camera_state["count"]))
            st.metric("Approx. visible faces · estimate", visible_estimate)
            st.caption("This is a view count, not a named-student attendance record. Confirm the roster manually.")
    with st.expander("Optional: analyze a classroom image"):
        st.caption("This is opt-in and uses a still image only. Local vision estimates visible faces; it does not recognize identities or mark attendance automatically.")
        image = st.file_uploader("Choose an image", type=["jpg", "jpeg", "png", "webp"], key="attendance_image")
        if image:
            st.image(image, caption="Selected image · processed locally when you submit", use_container_width=True)
        if st.button("Analyze visible-face estimate", disabled=not image, key="analyze_attendance_image"):
            if ai_pipeline is None:
                st.error("The local vision pipeline is not installed yet.")
            else:
                try:
                    from PIL import Image
                    frame = Image.open(BytesIO(image.getvalue())).convert("RGB")
                    result = ai_pipeline.analyze_session(frames=frame, session_label="Attendance image")
                    video = result.get("video_signals", {})
                    if video.get("available"):
                        st.metric("Peak visible faces · estimate", video.get("peak_visible_faces", "—"))
                        st.caption(video.get("note", "Confirm attendance manually."))
                    else:
                        st.info(video.get("note", "No visual estimate was available."))
                except Exception:
                    st.error("Image analysis failed. Choose a supported image and try again.")


def _render_session() -> None:
    st.markdown('<div class="page-kicker">MULTIMODAL ANALYSIS</div>', unsafe_allow_html=True)
    st.title("Session analysis")
    st.markdown("Choose an existing recording or explicitly record a short audio clip. Nothing is captured automatically.")
    with st.container(border=True):
        st.subheader("Choose session media")
        st.caption("The Python pipeline estimates group-level visual cues and broad audio activity; it does not identify people. Media is processed temporarily by this app server and is not retained in project storage or the database. A hosted deployment processes media on its host; run this app locally if recordings must stay on the instructor’s device.")
        session_user = st.session_state.get("user") or {}
        session_owner = session_user.get("id") if isinstance(session_user, dict) else None
        session_token = getattr(session_user, "access_token", None) if isinstance(session_user, dict) else None
        session_classes = []
        if not (isinstance(session_user, dict) and session_user.get("demo")) and storage is not None and session_owner is not None:
            try:
                session_classes = storage.list_classes(session_owner, access_token=session_token)
            except Exception:
                session_classes = []
        if session_classes:
            chosen_class = st.selectbox(
                "Class / session name",
                session_classes,
                format_func=lambda row: row["name"],
                key="analysis_class_select",
                help="Choose the class whose confirmed attendance you want to attach to this analysis.",
            )
            session_label = chosen_class["name"]
        else:
            session_label = st.text_input(
                "Class / session name",
                value="Class session",
                max_chars=100,
                help="Use the same class name shown on Attendance if you want to attach its manual present/absent counts.",
            )
        session_date = st.date_input("Session date", value=date.today(), key="analysis_session_date")
        local_now = datetime.now().astimezone()
        session_start_time = st.time_input(
            "Session start time (local app timezone)",
            value=local_now.time().replace(second=0, microsecond=0, tzinfo=None),
            key="analysis_session_start_time",
        )
        st.caption(
            f"The selected date and time are assumed to use this app’s local timezone ({local_now.tzname() or 'local time'}). "
            "On a hosted deployment, that is the server’s timezone. Saved timestamps are converted to UTC."
        )
        st.caption(
            "Optional head-orientation proxy: if enabled, the first video analysis may download the pinned MediaPipe model "
            "(up to 32 MiB) from Google's official model host; after caching, inference runs locally on this app server. "
            "MediaPipe may send performance and utilization metrics to Google, but video/audio content stays on this server "
            "and is not sent to Google. If the model is unavailable, head orientation is omitted and other estimates continue."
        )
        media_consent = st.checkbox(
            "I am authorized to analyze this media and have consent from everyone represented.",
            key="session_media_consent",
            help="Media is processed temporarily for non-identifying, group-level estimates. Raw media is not saved to the database.",
        )
        video = None
        audio = None
        include_head_orientation = False
        if media_consent:
            video = st.file_uploader(
                "Video recording (optional)",
                type=["mp4", "mov", "avi", "mkv"],
                key="session_video",
            )
            if video:
                include_head_orientation = st.checkbox(
                    "Enable optional MediaPipe head-orientation proxy",
                    value=False,
                    key="session_head_orientation_opt_in",
                    help="Off by default. Provides a camera-relative head-angle proxy, not gaze or attention. See the model and Google metrics notice above.",
                )
        else:
            st.caption("Video upload is available after you confirm authorization and participant consent above.")

        # Keep audio inputs discoverable before consent, while preventing file
        # selection or microphone access until the instructor confirms it.
        audio_source = st.radio(
            "Audio input (optional)",
            ["No audio", "Upload an audio file", "Record with microphone"],
            horizontal=True,
            key="session_audio_source",
            help="Audio is analyzed only after you select a source and explicitly start analysis.",
        )
        if audio_source == "Upload an audio file":
            audio = st.file_uploader(
                "Choose an audio file",
                type=["wav", "mp3", "m4a", "ogg", "flac"],
                key="session_audio_upload",
                disabled=not media_consent,
                help="Confirm authorization and participant consent to enable audio file selection.",
            )
        elif audio_source == "Record with microphone":
            if callable(getattr(st, "audio_input", None)):
                st.caption("Microphone access starts only after consent and when you press Record. The clip is temporarily processed by this app server; raw audio is not stored or sent to Gemini.")
                audio = st.audio_input(
                    "Record a short audio clip",
                    sample_rate=16000,
                    key="session_microphone_audio",
                    disabled=not media_consent,
                    help="Confirm authorization and participant consent, then press Record to grant microphone access.",
                )
            else:
                st.error("Microphone recording needs Streamlit 1.40 or newer. Update Streamlit, or choose the upload option instead.")
        if not media_consent:
            st.info("Audio source choices are shown for clarity. Confirm authorization and participant consent above to enable audio upload or microphone recording.")
        if video or audio:
            st.info("Media selected. Press Analyze to process it. Analysis is disabled until you confirm authorization and participant consent. Only aggregate session metrics can be saved; raw media is not retained.")
        gemini_available = bool(os.getenv("GEMINI_API_KEY"))
        use_gemini = st.checkbox(
            "Use Gemini for an optional session summary",
            value=False,
            disabled=not gemini_available,
            help="Only enabled when GEMINI_API_KEY is set in your local environment. This sends the analysis summary to Google's API.",
        )
        if not gemini_available:
            st.caption("Local analysis works without an API key. Configure GEMINI_API_KEY privately to enable optional Gemini summaries.")
        analyze = st.button("Analyze session", type="primary", disabled=not media_consent or not (video or audio), use_container_width=False)
        if analyze:
            if ai_pipeline is None:
                st.error("The AI pipeline is not installed yet. Add its local dependencies to enable analysis.")
            else:
                try:
                    local_timezone = datetime.now().astimezone().tzinfo
                    session_started_at = datetime.combine(session_date, session_start_time).replace(tzinfo=local_timezone)
                    session_started_at_utc = session_started_at.astimezone(timezone.utc).isoformat(timespec="seconds")
                    result = ai_pipeline.analyze_session(
                        video_file=video,
                        audio_file=audio,
                        session_label=session_label.strip() or "Class session",
                        use_gemini=use_gemini,
                        include_head_orientation=include_head_orientation,
                    )
                    st.session_state.analysis_result = result
                    st.session_state.analysis_saved = False
                    st.session_state.analysis_context = {
                        "class_name": session_label.strip() or "Class session",
                        "session_date": session_date.isoformat(),
                        "started_at": session_started_at_utc,
                    }
                except Exception:
                    st.error("Analysis failed. Check that the optional local AI dependencies are installed and the media format is supported.")
    result = st.session_state.get("analysis_result")
    if result:
        st.subheader("Session summary")
        if isinstance(result, dict):
            score = result.get("engagement_score")
            audio_signals = result.get("audio_signals", {}) or {}
            video_signals = result.get("video_signals", {}) or {}

            def metric_value(value: Any, suffix: str = "", precision: int = 0) -> str:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return "Unavailable"
                number = f"{value:.{precision}f}" if precision else f"{int(round(value))}"
                return f"{number}{suffix}"

            confidence = str(result.get("engagement_confidence") or "unavailable").replace("_", " ")
            score_text = f"{int(round(score))}/100" if isinstance(score, (int, float)) and not isinstance(score, bool) else "Unavailable"
            sound_activity = audio_signals.get("sound_activity_pct")
            if sound_activity is None:
                sound_activity = result.get("audio_activity_pct")
            likely_speech = audio_signals.get("likely_speech_activity_pct")
            if likely_speech is None:
                likely_speech = result.get("likely_speech_activity_pct")
            summary_columns = st.columns(4)
            with summary_columns[0]:
                _metric_card("FUSED GROUP ACTIVITY ESTIMATE", score_text, f"Unvalidated, low-confidence heuristic · {confidence}; not attention or performance", "violet")
            with summary_columns[1]:
                _metric_card("SOUND ACTIVITY", metric_value(sound_activity, "%"), "Broad sound-energy proxy; not a speech detector", "mint")
            with summary_columns[2]:
                speech_method = str(audio_signals.get("speech_activity_method") or "unavailable").replace("_", " ")
                _metric_card("LIKELY-SPEECH ACTIVITY", metric_value(likely_speech, "%"), f"Optional local VAD estimate · {speech_method}; no transcript or speaker ID", "amber")
            with summary_columns[3]:
                _metric_card("SIGNAL QUALITY", str(result.get("signal_quality", "unavailable")).title(), "Interpret group proxies cautiously", "blue")
            st.caption(result.get("fused_score_method", "This unvalidated group activity estimate is advisory and should be checked against classroom context."))
            if result.get("ai_summary"):
                st.markdown(f"**Optional AI summary:** {result['ai_summary']}")
            st.caption(result.get("privacy_note", "Analysis complete. Review the observations below."))

            st.markdown("### Visual group proxies")
            visual_columns = st.columns(4)
            with visual_columns[0]:
                _metric_card(
                    "PEAK VISIBLE-FACE ESTIMATE",
                    metric_value(video_signals.get("peak_visible_faces")),
                    "Sampled-frame count only; it does not identify or verify students",
                    "violet",
                )
            with visual_columns[1]:
                tracking_available = bool(video_signals.get("anonymous_face_tracker_available"))
                track_count = video_signals.get("sustained_visible_face_track_count")
                track_value = f"{metric_value(track_count)} tracks" if tracking_available and isinstance(track_count, (int, float)) and not isinstance(track_count, bool) else "Unavailable"
                track_details = []
                if tracking_available:
                    longest = video_signals.get("longest_visible_face_track_seconds")
                    coverage = video_signals.get("tracked_face_presence_pct")
                    if longest is not None:
                        track_details.append(f"longest {metric_value(longest, ' s', 1)}")
                    if coverage is not None:
                        track_details.append(f"clip coverage {metric_value(coverage, '%')}")
                    track_details.append("ephemeral box matches, not face IDs")
                else:
                    track_details.append(video_signals.get("face_tracking_note", "Reliable sustained tracking was unavailable."))
                _metric_card("SUSTAINED VISIBLE-FACE TRACK ESTIMATE", track_value, " · ".join(track_details), "mint")
            with visual_columns[2]:
                orientation_available = bool(video_signals.get("head_orientation_available"))
                orientation_value = metric_value(video_signals.get("head_orientation_proxy_pct"), "% camera-relative centered") if orientation_available else "Unavailable"
                orientation_note = video_signals.get("head_orientation_note", "Optional model output was unavailable.")
                _metric_card("HEAD-ORIENTATION PROXY", orientation_value, f"{orientation_note} Not gaze or attention.", "amber")
            with visual_columns[3]:
                motion = video_signals.get("group_motion_activity_pct", result.get("group_motion_activity_pct"))
                _metric_card("GROUP SCENE-MOTION PROXY", metric_value(motion, "%"), "Frame changes may reflect camera shake, lighting, or lesson content; not inactivity", "blue")
            if video_signals.get("note"):
                st.caption(video_signals["note"])
            if audio_signals.get("note"):
                st.caption(audio_signals["note"])

            st.markdown("### Multimodal signals across clip progress")
            st.caption("Signals are aligned by relative progress through each clip, not verified clock-time synchronization. Each line is a coarse group proxy, not individual behavior.")
            windows = result.get("multimodal_time_windows") or []
            chart_rows = []
            chart_series = (
                ("Visible-face presence proxy", "visible_presence_pct"),
                ("Group scene-motion proxy", "frame_motion_level_pct"),
                ("Sound activity", "sound_activity_pct"),
                ("Likely-speech activity", "likely_speech_activity_pct"),
                ("Camera-relative head-orientation proxy", "head_orientation_camera_relative_centered_pct"),
            )
            if isinstance(windows, list):
                for window in windows:
                    if not isinstance(window, dict):
                        continue
                    start_pct = window.get("relative_start_pct")
                    end_pct = window.get("relative_end_pct")
                    if not isinstance(start_pct, (int, float)) or not isinstance(end_pct, (int, float)):
                        continue
                    row = {"Clip progress": f"{start_pct:g}–{end_pct:g}%"}
                    for label, key in chart_series:
                        value = window.get(key)
                        row[label] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
                    if any(row[label] is not None for label, _ in chart_series):
                        chart_rows.append(row)
            if chart_rows:
                chart_data = pd.DataFrame(chart_rows).set_index("Clip progress")
                available_series = [label for label, _ in chart_series if chart_data[label].notna().any()]
                if available_series:
                    st.line_chart(chart_data[available_series], height=270)
                else:
                    st.info("No numeric multimodal signals were available for this clip.")
            else:
                st.info("Relative-progress multimodal windows are unavailable for this session.")

            agent = result.get("suggestion_agent") if isinstance(result.get("suggestion_agent"), dict) else {}
            with st.container(border=True):
                st.markdown("### Instructor prompts · bounded-rule agent")
                if agent.get("mode") == "offline_bounded_rule_agent":
                    st.caption("This offline, bounded-rule agent checks aggregate signal quality, selects from fixed instructor prompts, and applies a safety review. It does not identify learners or take action; suggestions are optional and require instructor judgment.")
                else:
                    st.caption("The bounded-rule agent was unavailable; these local fallback prompts remain advisory and require instructor judgment. No learner is identified and no action is taken automatically.")
                tools_used = agent.get("tools_used") or []
                if tools_used:
                    st.caption("Tools used: " + " → ".join(str(tool) for tool in tools_used))
                if agent.get("review_note"):
                    st.caption(agent["review_note"])
                structured_suggestions = agent.get("suggestions") or []
                if structured_suggestions:
                    for item in structured_suggestions:
                        if isinstance(item, dict):
                            title = str(item.get("title") or "Teaching prompt")
                            detail = str(item.get("detail") or "Review this group signal in context.")
                            st.markdown(f"- **{title}:** {detail}")
                else:
                    fallback_suggestions = result.get("suggestions") or []
                    if fallback_suggestions:
                        for item in fallback_suggestions:
                            st.markdown(f"- {item}")
                    else:
                        st.info("No instructor prompts were available for this session.")
            errors = result.get("errors", [])
            if errors:
                for issue in errors:
                    st.warning(issue)
            user = st.session_state.get("user")
            save_disabled = storage is None or not isinstance(user, dict) or user.get("demo") or st.session_state.get("analysis_saved", False)
            context = st.session_state.get("analysis_context", {})
            manual_records = []
            if storage is not None and isinstance(user, dict) and not user.get("demo"):
                try:
                    manual_records = storage.list_attendance(
                        user.get("id"), context.get("session_date", date.today().isoformat()),
                        context.get("class_name", result.get("session_label") or "Class session"),
                        access_token=getattr(user, "access_token", None),
                    )
                    present_count = sum(1 for row in manual_records if row.get("present"))
                    st.caption(
                        f"Manually confirmed attendance for {context.get('class_name', 'this class')} on "
                        f"{context.get('session_date', date.today().isoformat())}: {present_count} present "
                        f"out of {len(manual_records)} students. Only these aggregate counts are saved with the session."
                    )
                except Exception:
                    st.caption("Manual attendance is unavailable for this session; saved attendance counts will remain zero.")
            if st.button("Save aggregate session summary", disabled=save_disabled, key="save_session_summary"):
                try:
                    owner_id = user.get("id")
                    engagement_value = result.get("engagement_score")
                    # Read only aggregate manual attendance. The roster itself remains in local storage.
                    manual_records = storage.list_attendance(
                        owner_id,
                        context.get("session_date", date.today().isoformat()),
                        context.get("class_name", result.get("session_label") or "Class session"),
                        access_token=getattr(user, "access_token", None),
                    )
                    present_count = sum(1 for row in manual_records if row.get("present"))
                    summary = {
                        key: result.get(key)
                        for key in ("engagement_confidence", "signal_quality", "presence_consistency_pct", "audio_activity_pct", "attendance_count_estimate")
                        if isinstance(result.get(key), (str, int, float, bool)) or result.get(key) is None
                    }
                    summary["attendance_source"] = "manual_confirmed" if manual_records else "none"
                    storage.create_session(
                        owner_id=owner_id,
                        class_name=str(context.get("class_name") or result.get("session_label") or "Class session")[:100],
                        enrollment_count=len(manual_records),
                        attendance_count=present_count,
                        engagement_score=float(engagement_value) if isinstance(engagement_value, (int, float)) else None,
                        participation_count=0,
                        summary=summary,
                        started_at=context.get("started_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        access_token=getattr(user, "access_token", None),
                    )
                    st.session_state.analysis_saved = True
                    st.success("Aggregate summary saved. Raw media and student names were not stored.")
                except Exception:
                    st.error("The summary could not be saved. Your analysis remains available in this session.")
            if isinstance(user, dict) and user.get("demo"):
                st.caption("Sign in to save session summaries to your workspace.")
        else:
            st.json(result)
    with st.expander("Privacy and interpretation"):
        st.markdown("Engagement signals are estimates, not measurements of student ability or intent. Use them to guide reflection, never as a standalone student score. Face and voice inputs can be affected by lighting, camera angle, background noise, accessibility needs, and classroom context.")


def _render_insights(data: dict[str, Any]) -> None:
    st.markdown('<div class="page-kicker">SESSION REFLECTION</div>', unsafe_allow_html=True)
    st.title("Teaching insights")
    st.markdown("Practical prompts to help you decide what to try next.")
    for idx, insight in enumerate(data.get("insights", [])):
        with st.container(border=True):
            st.markdown(f"<div class='insight-index'>0{idx + 1}</div>", unsafe_allow_html=True)
            st.subheader(insight.get("title", "Classroom signal"))
            st.write(insight.get("detail", "Review the session signals."))
    if not data.get("insights"):
        st.info("Your account has no saved session suggestions yet. Use Live session to analyze an authorized class recording or audio sample, then save its aggregate summary. No demo suggestions are mixed into your account.")
    st.info("Suggestions are generated from noisy signals and should be reviewed in the context of your class.")


def main() -> None:
    _initialise()
    st.markdown(APP_CSS, unsafe_allow_html=True)
    user = st.session_state.user
    if not user:
        _, theme_col = st.columns([8, 1])
        with theme_col:
            st.toggle("Dark mode", key="dark_mode", help="Switch between dark and light appearance.")
        if st.session_state.dark_mode:
            st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)
        if os.getenv("CLASSPULSE_DEPLOYMENT") == "streamlit_community_cloud" and not (
            os.getenv("AUTH_BACKEND", "local").strip().casefold() == "supabase"
            and os.getenv("SUPABASE_SYNC_ENABLED", "").strip().casefold() in {"1", "true", "yes"}
            and os.getenv("SUPABASE_URL", "").strip()
            and os.getenv("SUPABASE_ANON_KEY", "").strip()
        ):
            st.warning("Hosted accounts and class data may reset while SQLite mode is selected. Configure your own Supabase Auth and sync in private App Secrets for durable data.")
        _login_screen()
        return
    page = _sidebar(user)
    if st.session_state.dark_mode:
        st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)
    data = _dashboard_data(user)
    if isinstance(user, dict) and user.get("demo"):
        st.info("Demo workspace · sample data only", icon=None)
    if page == "Overview":
        _render_overview(data)
    elif page == "Attendance":
        _render_attendance(data)
    elif page == "Live session":
        _render_session()
    elif page == "AI teaching coach":
        import ai_chatbot
        from ai_chatbot_ui import render_teaching_chatbot

        if not os.getenv("GEMINI_API_KEY", "").strip():
            st.warning("Gemini is not configured. Add GEMINI_API_KEY in Streamlit Cloud → Settings → Secrets, or in your private local environment, to use the coach and quiz builder.")
        render_teaching_chatbot(st, ai_chatbot)
    else:
        _render_insights(data)


if __name__ == "__main__":
    main()

