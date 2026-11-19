"""ClassPulse AI - Streamlit front end for multimodal attendance and engagement."""
from __future__ import annotations

from datetime import date
from html import escape
from io import BytesIO
import os
import hashlib
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

from styles import APP_CSS


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
                metrics = {
                    "attendance_rate": data.get("attendance_rate") or 0,
                    "present_count": data.get("attendance_total") or 0,
                    "student_count": data.get("enrollment_total") or 0,
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
                    # The storage API intentionally persists aggregate session summaries only.
                    "attendance": [],
                    "insights": [],
                }
        except Exception:
            pass
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
        page = st.radio("Navigation", ["Overview", "Attendance", "Live session", "Insights"], label_visibility="collapsed")
        st.markdown("<div class='sidebar-spacer'></div>", unsafe_allow_html=True)
        st.markdown('<div class="privacy-chip"><span class="privacy-dot"></span><div><b>Privacy first</b><small>Local analysis · No raw media saved</small></div></div>', unsafe_allow_html=True)
        st.divider()
        st.caption(_safe_user_name(user))
        if st.button("Sign out", use_container_width=True):
            st.session_state.user = None
            st.session_state.analysis_result = None
            st.rerun()
    return page


def _render_overview(data: dict[str, Any]) -> None:
    metrics = data.get("metrics", {})
    st.markdown(f'<div class="page-kicker">{date.today().strftime("%A, %d %b %Y").upper()}</div>', unsafe_allow_html=True)
    st.title("Your classroom, at a glance")
    st.markdown("A clear read on today’s attendance and engagement signals.")
    cols = st.columns(4)
    with cols[0]: _metric_card("ATTENDANCE RATE", f"{metrics.get('attendance_rate', 84)}%", f"{metrics.get('present_count', 126)} of {metrics.get('student_count', 150)} roster entries present")
    with cols[1]: _metric_card("CLASS ENGAGEMENT", f"{metrics.get('engagement_score', 78)}<small>/100</small>", "Group-level estimate · review before acting", "mint")
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
            for item in data.get("classes", []):
                with st.container(border=True):
                    st.markdown(f"**{item.get('name', 'Class session')}**")
                    st.caption(f"{item.get('time', '')} · {item.get('room', '')}")
                    st.markdown(f"<span class='status-pill'>{escape(str(item.get('status', 'Scheduled')))}</span>", unsafe_allow_html=True)
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
            for insight in data.get("insights", [])[:3]:
                st.markdown(f"**{insight.get('title', 'Classroom signal')}**")
                st.caption(insight.get("detail", "Review the session signals."))
                st.markdown("---")


def _render_attendance(data: dict[str, Any]) -> None:
    st.markdown('<div class="page-kicker">CLASS ROSTER</div>', unsafe_allow_html=True)
    st.title("Attendance review")
    st.markdown("Add a local class roster, then confirm each student’s attendance yourself. Face counts can prompt a review, but never identify or mark a student automatically.")
    user = st.session_state.get("user") or {}
    owner_id = user.get("id") if isinstance(user, dict) else None
    is_demo = isinstance(user, dict) and user.get("demo")
    existing_classes = [c.get("name", "") for c in data.get("classes", []) if c.get("name")]
    controls = st.columns([1.4, 1, 1.6])
    with controls[0]:
        class_name = st.text_input("Class name", value=existing_classes[0] if existing_classes else "Class 1", max_chars=100, key="attendance_class_name")
    with controls[1]: session_date = st.date_input("Session date", value=date.today(), key="attendance_session_date")
    with controls[2]:
        st.markdown("<div class='privacy-note'>Student names and attendance are stored in this app’s SQLite database, separate from Supabase and Gemini. A hosted app stores this file on its server.</div>", unsafe_allow_html=True)

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
            roster = storage.list_students(owner_id) if storage is not None and owner_id is not None else []
        except Exception:
            roster = []
            st.error("The local roster could not be loaded. Check the database setup and refresh.")

    if not is_demo:
        with st.expander("Add a student to this local roster", expanded=not bool(roster)):
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
                            storage.add_student(owner_id, new_name.strip(), new_code.strip())
                            st.success("Student added to your local roster.")
                            st.rerun()
                        except Exception:
                            st.error("Student could not be added. Check for a duplicate roster code and try again.")

    if roster:
        prior_status = {}
        if not is_demo and storage is not None:
            try:
                saved = storage.list_attendance(owner_id, session_date.isoformat(), class_name.strip())
                prior_status = {str(row.get("student_id")): ("Present" if row.get("present") else "Absent") for row in saved}
            except Exception:
                st.warning("Could not load saved attendance for this date and class.")
        attendance_rows = []
        for row in roster:
            student_id = row.get("id")
            status = prior_status.get(str(student_id), row.get("status", "Unmarked") if is_demo else "Unmarked")
            if status == "Review":
                status = "Unmarked"
            attendance_rows.append({
                "student_id": student_id,
                "student": row.get("name", "Student"),
                "roster_code": row.get("student_code", ""),
                "status": status if status in {"Present", "Absent", "Unmarked"} else "Unmarked",
            })
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
                        storage.save_attendance(owner_id, session_date.isoformat(), class_name.strip(), records)
                        st.success("Attendance saved locally for this class and date.")
                        st.rerun()
                    except Exception:
                        st.error("Attendance could not be saved. Confirm every status and try again.")
        with c2:
            if not is_demo:
                remove_id = st.selectbox("Remove student", [None] + [r.get("id") for r in roster], format_func=lambda value: "Choose…" if value is None else next((r.get("name", "Student") for r in roster if r.get("id") == value), "Student"), key="remove_student_id")
                confirm_remove = st.checkbox("Confirm local removal", key="confirm_remove_student")
                if st.button("Remove", disabled=remove_id is None or not confirm_remove, key="remove_student_button"):
                    try:
                        storage.delete_student(owner_id, int(remove_id))
                        st.success("Student removed from the local roster.")
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
    with st.expander("Optional webcam preview · no capture or upload"):
        st.caption("Preview only. Camera access starts after you press Start, and the stream is stopped when you stop the preview or close the page.")
        components.html(
            r"""
            <!doctype html>
            <html><head><meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
              *{box-sizing:border-box} body{margin:0;background:#fff;color:#20243a;font:14px system-ui,-apple-system,"Segoe UI",sans-serif}
              .wrap{border:1px solid #e9eaf2;border-radius:14px;padding:16px;background:linear-gradient(140deg,#fbfaff,#f5f6fb)}
              .toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}
              select,button{font:600 13px system-ui,-apple-system,"Segoe UI",sans-serif;border-radius:9px;padding:10px 12px}
              select{background:#fff;border:1px solid #dfe1eb;color:#353950;min-width:150px}
              button{cursor:pointer;border:1px solid transparent}
              #start{background:linear-gradient(115deg,#785ff6,#5b45df);color:white;box-shadow:0 5px 14px #7357f52b}
              #stop{background:#fff;border-color:#daddea;color:#535970}
              button:disabled{cursor:default;opacity:.48}
              .status{margin-left:auto;color:#7c8297;font-size:12px;min-width:160px;text-align:right}
              .status.on{color:#158669}.status.error{color:#bd4453}
              .stage{position:relative;overflow:hidden;border-radius:11px;background:#171a2c;aspect-ratio:16/9;max-height:390px;display:flex;align-items:center;justify-content:center}
              video{display:none;width:100%;height:100%;object-fit:cover;transform:scaleX(-1)}
              .placeholder{padding:18px;text-align:center;color:#bfc4d7;font-size:13px;line-height:1.6}
              .lens{width:36px;height:36px;border-radius:12px;background:#332b61;color:#b3a7ff;display:flex;align-items:center;justify-content:center;margin:0 auto 11px;font-size:18px}
              .foot{margin:10px 2px 0;color:#858ba1;font-size:11px}
              @media(max-width:520px){.wrap{padding:12px}.status{width:100%;text-align:left;margin:0}.stage{aspect-ratio:4/3;max-height:330px}.toolbar{gap:8px}select,button{flex:1}}
            </style></head><body>
              <div class="wrap">
                <div class="toolbar">
                  <select id="facing" aria-label="Choose camera">
                    <option value="user">Front camera</option>
                    <option value="environment">Rear camera</option>
                  </select>
                  <button id="start" type="button">Start preview</button>
                  <button id="stop" type="button" disabled>Stop</button>
                  <span id="status" class="status" role="status" aria-live="polite">Camera is off</span>
                </div>
                <div class="stage">
                  <video id="preview" autoplay playsinline muted></video>
                  <div id="placeholder" class="placeholder"><div class="lens">◎</div>Camera preview is off.<br>Press Start when you’re ready to view it.</div>
                </div>
                <div class="foot">Live preview stays in this browser. No frames are recorded, saved, or sent to the app.</div>
              </div>
              <script>
                (() => {
                  const video = document.getElementById('preview');
                  const startButton = document.getElementById('start');
                  const stopButton = document.getElementById('stop');
                  const status = document.getElementById('status');
                  const placeholder = document.getElementById('placeholder');
                  const facing = document.getElementById('facing');
                  let stream = null;
                  function setStatus(message, state='') {
                    status.textContent = message;
                    status.className = `status ${state}`.trim();
                  }
                  function stopPreview(message='Camera is off') {
                    if (stream) {
                      stream.getTracks().forEach(track => track.stop());
                      stream = null;
                    }
                    video.pause();
                    video.srcObject = null;
                    video.style.display = 'none';
                    placeholder.style.display = 'block';
                    startButton.disabled = false;
                    stopButton.disabled = true;
                    setStatus(message);
                  }
                  async function startPreview() {
                    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
                      setStatus('Use localhost or HTTPS to preview camera', 'error');
                      return;
                    }
                    startButton.disabled = true;
                    setStatus('Waiting for camera permission…');
                    try {
                      // This is the only getUserMedia call, and it runs only from this click handler.
                      stream = await navigator.mediaDevices.getUserMedia({
                        audio: false,
                        video: {
                          facingMode: { ideal: facing.value },
                          width: { ideal: 1280 },
                          height: { ideal: 720 }
                        }
                      });
                      video.srcObject = stream;
                      video.style.transform = facing.value === 'user' ? 'scaleX(-1)' : 'none';
                      await video.play();
                      placeholder.style.display = 'none';
                      video.style.display = 'block';
                      stopButton.disabled = false;
                      startButton.disabled = false;
                      setStatus('Live preview · camera on', 'on');
                    } catch (error) {
                      stopPreview(error?.name === 'NotAllowedError'
                        ? 'Camera permission was not granted'
                        : 'Camera unavailable · check device and browser settings');
                      status.className = 'status error';
                    }
                  }
                  startButton.addEventListener('click', startPreview);
                  stopButton.addEventListener('click', () => stopPreview());
                  window.addEventListener('pagehide', () => stopPreview());
                  window.addEventListener('beforeunload', () => stopPreview());
                  document.addEventListener('visibilitychange', () => {
                    if (document.hidden && stream) stopPreview('Preview stopped while page was hidden');
                  });
                })();
              </script>
            </body></html>
            """,
            height=500,
            scrolling=False,
        )
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
    st.markdown("Upload an existing recording when you’re ready. Nothing is captured automatically.")
    with st.container(border=True):
        st.subheader("Choose session media")
        st.caption("The local pipeline can combine visual cues and audio features. Use consented classroom recordings only.")
        session_label = st.text_input(
            "Class / session name",
            value="Class session",
            max_chars=100,
            help="Use the same class name shown on Attendance if you want to attach its manual present/absent counts.",
        )
        session_date = st.date_input("Session date", value=date.today(), key="analysis_session_date")
        video = st.file_uploader("Video recording (optional)", type=["mp4", "mov", "avi", "mkv"], key="session_video")
        audio = st.file_uploader("Audio recording (optional)", type=["wav", "mp3", "m4a", "ogg", "flac"], key="session_audio")
        if video or audio:
            st.info("Media selected. Press Analyze to process it. Raw media should remain local and be removed after analysis.")
        gemini_available = bool(os.getenv("GEMINI_API_KEY"))
        use_gemini = st.checkbox(
            "Use Gemini for an optional session summary",
            value=False,
            disabled=not gemini_available,
            help="Only enabled when GEMINI_API_KEY is set in your local environment. This sends the analysis summary to Google's API.",
        )
        if not gemini_available:
            st.caption("Local analysis works without an API key. Configure GEMINI_API_KEY privately to enable optional Gemini summaries.")
        analyze = st.button("Analyze session", type="primary", disabled=not (video or audio), use_container_width=False)
        if analyze:
            if ai_pipeline is None:
                st.error("The AI pipeline is not installed yet. Add its local dependencies to enable analysis.")
            else:
                try:
                    result = ai_pipeline.analyze_session(
                        video_file=video,
                        audio_file=audio,
                        session_label=session_label.strip() or "Class session",
                        use_gemini=use_gemini,
                    )
                    st.session_state.analysis_result = result
                    st.session_state.analysis_saved = False
                    st.session_state.analysis_context = {
                        "class_name": session_label.strip() or "Class session",
                        "session_date": session_date.isoformat(),
                    }
                except Exception:
                    st.error("Analysis failed. Check that the optional local AI dependencies are installed and the media format is supported.")
    result = st.session_state.get("analysis_result")
    if result:
        st.subheader("Session summary")
        if isinstance(result, dict):
            m1, m2, m3 = st.columns(3)
            score = result.get("engagement_score")
            audio_signals = result.get("audio_signals", {}) or {}
            with m1: _metric_card("ENGAGEMENT ESTIMATE", str(score if score is not None else "—"), str(result.get("engagement_confidence", "Group-level signal")))
            with m2: _metric_card("AUDIO ACTIVITY", f"{audio_signals.get('speech_activity_pct')}%" if audio_signals.get("speech_activity_pct") is not None else "—", "Broad sound activity only", "mint")
            with m3: _metric_card("SIGNAL QUALITY", str(result.get("signal_quality", "unavailable")).title(), "Interpret with care", "blue")
            if result.get("ai_summary"):
                st.markdown(f"**Optional AI summary:** {result['ai_summary']}")
            st.caption(result.get("privacy_note", "Analysis complete. Review the observations below."))
            left, right = st.columns(2)
            with left:
                video_signals = result.get("video_signals", {}) or {}
                st.markdown("**Visual signal**")
                st.write(video_signals.get("note", "No video analysis was available."))
                if video_signals.get("peak_visible_faces") is not None:
                    st.caption(f"Peak visible-face estimate: {video_signals['peak_visible_faces']} · not an identity count")
            with right:
                st.markdown("**Audio signal**")
                st.write(audio_signals.get("note", "No audio analysis was available."))
            st.markdown("**Suggestions for review**")
            for item in result.get("suggestions", []):
                st.markdown(f"- {item}")
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
                        started_at=f"{context.get('session_date', date.today().isoformat())}T00:00:00+00:00",
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
    st.info("Suggestions are generated from noisy signals and should be reviewed in the context of your class.")


def main() -> None:
    _initialise()
    st.markdown(APP_CSS, unsafe_allow_html=True)
    user = st.session_state.user
    if not user:
        _login_screen()
        return
    page = _sidebar(user)
    data = _dashboard_data(user)
    if isinstance(user, dict) and user.get("demo"):
        st.info("Demo workspace · sample data only", icon=None)
    if page == "Overview":
        _render_overview(data)
    elif page == "Attendance":
        _render_attendance(data)
    elif page == "Live session":
        _render_session()
    else:
        _render_insights(data)


if __name__ == "__main__":
    main()
