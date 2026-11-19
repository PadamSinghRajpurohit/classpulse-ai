"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const view = { config: null, user: null, accessToken: null, mode: "signin", sessions: [], monthChosen: false };
  const MEDIAPIPE_VERSION = "1.2.3";
  const MEDIAPIPE_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VERSION}`;
  const FACE_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/latest/blaze_face_full_range.tflite";

  function message(id, text, error = false) {
    const node = $(id);
    node.textContent = text || "";
    node.classList.toggle("error", Boolean(error));
  }

  function applyTheme(theme) {
    const selected = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = selected;
    const themeColor = document.querySelector('meta[name="theme-color"]');
    if (themeColor) themeColor.content = selected === "dark" ? "#0c1021" : "#f3f5fb";
    const button = $("theme-toggle");
    if (button) {
      const dark = selected === "dark";
      button.textContent = dark ? "☼ Light mode" : "◐ Dark mode";
      button.setAttribute("aria-pressed", String(dark));
      button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
    }
    try { localStorage.setItem("classpulse-theme", selected); } catch { /* Theme still applies for this page. */ }
  }

  function errorText(payload, fallback) {
    if (!payload || typeof payload !== "object") return fallback;
    const raw = payload.msg || payload.message || payload.error_description || payload.error;
    return typeof raw === "string" && raw.length < 220 ? raw : fallback;
  }

  async function request(path, options = {}) {
    const response = await fetch(`${view.config.supabaseUrl}${path}`, {
      ...options,
      headers: {
        apikey: view.config.publishableKey,
        ...(options.headers || {}),
      },
    });
    const body = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) throw new Error(errorText(body, `Request failed (${response.status}).`));
    return body;
  }

  function setMode(mode) {
    view.mode = mode;
    const signin = mode === "signin";
    $("signin-tab").classList.toggle("active", signin);
    $("signup-tab").classList.toggle("active", !signin);
    $("signin-tab").setAttribute("aria-selected", String(signin));
    $("signup-tab").setAttribute("aria-selected", String(!signin));
    $("auth-title").textContent = signin ? "Welcome back" : "Your next class starts here";
    $("auth-subtitle").textContent = signin ? "Sign in to pick up where your class left off." : "Create a secure account for your teaching space.";
    $("auth-submit").innerHTML = signin ? 'Sign in <span aria-hidden="true">→</span>' : 'Create account <span aria-hidden="true">→</span>';
    $("password").autocomplete = signin ? "current-password" : "new-password";
    message("auth-message", "");
  }

  function setBusy(button, busy, label) {
    button.disabled = busy;
    if (busy) button.textContent = label;
  }

  let cameraStream = null;
  let faceDetector = null;
  let faceCountTimer = null;
  let faceCounts = [];
  let lastVideoTime = -1;
  let autoFaceCount = true;

  function cameraStatus(text, error = false, live = false) {
    const status = $("camera-status");
    const indicator = $("camera-live-indicator");
    if (!status || !indicator) return;
    status.textContent = text;
    status.classList.toggle("error", error);
    status.classList.toggle("live", live);
    indicator.classList.toggle("live", live);
  }

  function stopCameraPreview(text = "Camera is off · manual entry available", error = false) {
    if (faceCountTimer !== null) window.clearTimeout(faceCountTimer);
    faceCountTimer = null;
    if (faceDetector) {
      try { faceDetector.close(); } catch { /* Detector may already be closed. */ }
      faceDetector = null;
    }
    faceCounts = [];
    lastVideoTime = -1;
    autoFaceCount = true;
    if (cameraStream) {
      cameraStream.getTracks().forEach((track) => {
        try { track.stop(); } catch { /* Track may already have ended. */ }
      });
      cameraStream = null;
    }
    const video = $("camera-video");
    if (video) {
      video.pause();
      video.srcObject = null;
      video.classList.remove("active");
    }
    $("camera-placeholder")?.classList.remove("hidden");
    if ($("camera-start")) $("camera-start").disabled = false;
    if ($("camera-stop")) $("camera-stop").disabled = true;
    if ($("camera-count-toggle")) {
      $("camera-count-toggle").disabled = true;
      $("camera-count-toggle").textContent = "Pause auto count";
    }
    cameraStatus(text, error, false);
  }

  async function startFaceCounting(video) {
    cameraStatus("Loading on-device face counter…", false, true);
    try {
      // Load the free MediaPipe runtime only after the user explicitly starts the camera.
      const vision = await import(`${MEDIAPIPE_BASE}/vision_bundle.mjs`);
      if (!cameraStream) return;
      const files = await vision.FilesetResolver.forVisionTasks(
        `${MEDIAPIPE_BASE}/wasm`,
      );
      faceDetector = await vision.FaceDetector.createFromOptions(files, {
        baseOptions: {
          modelAssetPath: FACE_MODEL_URL,
        },
        runningMode: "VIDEO",
        minDetectionConfidence: 0.55,
        minSuppressionThreshold: 0.3,
      });
      if (!cameraStream) {
        faceDetector.close();
        faceDetector = null;
        return;
      }
      $("camera-count-toggle").disabled = false;
      cameraStatus("Counting visible faces on this device…", false, true);
      countVisibleFaces(video);
    } catch (error) {
      if (cameraStream) {
        cameraStatus("Camera is on · face counter failed to load", true, true);
        const details = typeof error?.message === "string" ? error.message.slice(0, 160) : "unknown loading error";
        $("face-count-readout").textContent = `On-device face counting could not start (${details}). Enter the present total manually.`;
      }
      if (faceDetector) {
        try { faceDetector.close(); } catch { /* Ignore cleanup errors. */ }
        faceDetector = null;
      }
    }
  }

  function countVisibleFaces(video) {
    if (!cameraStream || !faceDetector || !autoFaceCount) return;
    try {
      if (video.readyState >= 2 && video.currentTime !== lastVideoTime) {
        lastVideoTime = video.currentTime;
        const detections = faceDetector.detectForVideo(video, performance.now()).detections || [];
        faceCounts.push(detections.length);
        if (faceCounts.length > 5) faceCounts.shift();
        const sorted = [...faceCounts].sort((a, b) => a - b);
        const estimate = sorted[Math.floor(sorted.length / 2)];
        const attendance = $("attendance");
        attendance.value = String(estimate);
        $("face-count-readout").textContent = `Approx. ${estimate} visible face${estimate === 1 ? "" : "s"} · adjust Present today if needed.`;
        updatePreview();
      }
    } catch {
      cameraStatus("Camera is on · count paused; enter the count manually", true, true);
      return;
    }
    faceCountTimer = window.setTimeout(() => countVisibleFaces(video), 700);
  }

  async function startCameraPreview() {
    if (cameraStream) return;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      cameraStatus("Use localhost or HTTPS to preview camera", true);
      return;
    }
    const start = $("camera-start");
    start.disabled = true;
    cameraStatus("Waiting for camera permission…");
    try {
      // Request video only, and only in response to the user's Start click.
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: $("camera-facing").value },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
      cameraStream = stream;
      const video = $("camera-video");
      video.srcObject = stream;
      video.classList.add("active");
      video.classList.toggle("mirrored", $("camera-facing").value === "user");
      await video.play();
      $("camera-placeholder").classList.add("hidden");
      $("camera-stop").disabled = false;
      start.disabled = true;
      $("camera-count-toggle").disabled = true;
      cameraStatus("Camera on · preparing on-device counter…", false, true);
      stream.getVideoTracks().forEach((track) => {
        track.addEventListener("ended", () => {
          if (cameraStream === stream) stopCameraPreview("Camera stream ended · enter the count manually");
        }, { once: true });
      });
      await startFaceCounting(video);
    } catch (error) {
      stopCameraPreview(
        error?.name === "NotAllowedError"
          ? "Camera permission was not granted"
          : "Camera unavailable · check device and browser settings",
        true,
      );
    }
  }

  async function authenticate(event) {
    event.preventDefault();
    message("auth-message", "");
    const button = $("auth-submit");
    const original = view.mode === "signin" ? "Sign in →" : "Create account →";
    setBusy(button, true, view.mode === "signin" ? "Signing in…" : "Creating account…");
    const email = $("email").value.trim().toLowerCase();
    const password = $("password").value;
    try {
      const result = await request(view.mode === "signin" ? "/auth/v1/token?grant_type=password" : "/auth/v1/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!result?.access_token || !result?.user?.id) {
        message("auth-message", "Account created. Check your email to confirm it, then sign in.");
        return;
      }
      view.user = result.user;
      view.accessToken = result.access_token;
      showDashboard();
      await loadSessions();
    } catch (error) {
      message("auth-message", error.message || "Sign-in could not be completed.", true);
    } finally {
      button.disabled = false;
      button.innerHTML = original.replace("→", '<span aria-hidden="true">→</span>');
    }
  }

  function showDashboard() {
    $("auth-view").classList.add("hidden");
    $("dashboard-view").classList.remove("hidden");
    $("logout-button").classList.remove("hidden");
    const label = new Intl.DateTimeFormat(undefined, { weekday: "long", month: "short", day: "numeric" }).format(new Date());
    $("today-label").textContent = label;
  }

  function signOut() {
    stopCameraPreview();
    // The token is memory-only: reloads and sign-out discard it from this page.
    const token = view.accessToken;
    if (token) {
      fetch(`${view.config.supabaseUrl}/auth/v1/logout?scope=local`, {
        method: "POST",
        headers: { apikey: view.config.publishableKey, Authorization: `Bearer ${token}` },
      }).catch(() => {});
    }
    view.user = null;
    view.accessToken = null;
    view.sessions = [];
    view.monthChosen = false;
    $("dashboard-view").classList.add("hidden");
    $("auth-view").classList.remove("hidden");
    $("logout-button").classList.add("hidden");
    $("auth-form").reset();
    setMode("signin");
  }

  async function loadSessions() {
    const loadNote = $("analytics-load-note");
    loadNote.classList.remove("error");
    loadNote.textContent = "Loading your secure session history…";
    try {
      const pageSize = 500;
      const rows = [];
      for (let offset = 0; ; offset += pageSize) {
        const query = new URLSearchParams({
          select: "id,class_name,started_at,enrollment_count,attendance_count,engagement_score,participation_count",
          owner_id: `eq.${view.user.id}`,
          order: "started_at.desc",
          limit: String(pageSize),
          offset: String(offset),
        });
        const page = await request(`/rest/v1/classpulse_session_summaries?${query.toString()}`, {
          headers: { Authorization: `Bearer ${view.accessToken}` },
        });
        if (!Array.isArray(page)) throw new Error("The session list returned an unexpected response.");
        rows.push(...page);
        if (page.length < pageSize) break;
      }
      view.sessions = rows;
      const monthInput = $("analytics-month");
      const selectedMonthHasData = rows.some((row) => {
        const date = new Date(row.started_at || "");
        return Number.isFinite(date.getTime()) && localMonthKey(date) === monthInput.value;
      });
      if (!view.monthChosen && rows.length && !selectedMonthHasData) {
        const newestDate = new Date(rows[0].started_at || "");
        if (Number.isFinite(newestDate.getTime())) monthInput.value = localMonthKey(newestDate);
      }
      renderSessions();
      loadNote.textContent = rows.length
        ? `${rows.length} saved session${rows.length === 1 ? "" : "s"} · times shown in your local timezone`
        : "No sessions saved for this account yet. Save a session to build your monthly analytics.";
    } catch (error) {
      view.sessions = [];
      renderSessions();
      loadNote.textContent = `Saved data could not load: ${error.message || "check your connection and Supabase access"}`;
      loadNote.classList.add("error");
      message("session-message", "The dashboard could not load your saved summaries. See the analytics panel for details.", true);
    }
  }

  function renderSessions() {
    const rows = view.sessions;
    $("sessions-count").textContent = String(rows.length);
    $("recent-count").textContent = `${rows.length} saved`;
    const totalEnrolled = rows.reduce((sum, row) => sum + Number(row.enrollment_count || 0), 0);
    const totalPresent = rows.reduce((sum, row) => sum + Number(row.attendance_count || 0), 0);
    const avgAttendance = totalEnrolled ? Math.round((totalPresent / totalEnrolled) * 100) : null;
    const scores = rows.map((row) => row.engagement_score).filter((score) => score !== null && score !== undefined && score !== "").map(Number).filter(Number.isFinite);
    const avgScore = scores.length ? Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length) : null;
    $("attendance-rate").textContent = avgAttendance === null ? "—" : String(avgAttendance);
    $("engagement-rate").textContent = avgScore === null ? "—" : String(avgScore);

    const list = $("session-list");
    list.replaceChildren();
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      const orbit = document.createElement("span"); orbit.className = "empty-orbit"; orbit.textContent = "◌";
      const strong = document.createElement("strong"); strong.textContent = "Your first session starts here";
      const p = document.createElement("p"); p.textContent = "Save a session summary and it will show up in this list.";
      empty.append(orbit, strong, p); list.append(empty);
      renderMonthlyAnalytics();
      return;
    }
    for (const row of rows.slice(0, 5)) {
      const item = document.createElement("article"); item.className = "session-row";
      const info = document.createElement("div"); info.className = "session-info";
      const title = document.createElement("strong"); title.textContent = row.class_name || "Class session";
      const details = document.createElement("span");
      const date = row.started_at ? new Date(row.started_at) : new Date();
      const dateText = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
      details.textContent = `${dateText} · ${Number(row.attendance_count || 0)} / ${Number(row.enrollment_count || 0)} present`;
      info.append(title, details);
      const score = document.createElement("div"); score.className = "session-score";
      score.textContent = row.engagement_score !== null && row.engagement_score !== undefined && row.engagement_score !== "" && Number.isFinite(Number(row.engagement_score)) ? String(Math.round(Number(row.engagement_score))) : "—";
      const scoreLabel = document.createElement("small"); scoreLabel.textContent = "pulse / 100"; score.append(scoreLabel);
      item.append(info, score); list.append(item);
    }
    renderMonthlyAnalytics();
  }

  const svgElement = (name, attrs = {}, text = "") => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    if (text) node.textContent = text;
    return node;
  };

  function localMonthKey(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  }

  function localDateTimeValue(date = new Date()) {
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }

  function selectedMonthRows() {
    const month = $("analytics-month").value || localMonthKey(new Date());
    return view.sessions.filter((row) => {
      const timestamp = new Date(row.started_at || "");
      return Number.isFinite(timestamp.getTime()) && localMonthKey(timestamp) === month;
    }).sort((a, b) => new Date(a.started_at) - new Date(b.started_at));
  }

  function renderMonthlyAnalytics() {
    const monthInput = $("analytics-month");
    if (!monthInput.value) monthInput.value = localMonthKey(new Date());
    const rows = selectedMonthRows();
    const selectedDate = new Date(`${monthInput.value}-01T12:00:00`);
    const monthLabel = Number.isFinite(selectedDate.getTime())
      ? new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(selectedDate)
      : "Selected month";
    $("analytics-month-label").textContent = `${monthLabel} · ${rows.length} saved session${rows.length === 1 ? "" : "s"}`;
    $("monthly-table-caption").textContent = `${monthLabel} session details · local date and time`;
    $("month-sessions").textContent = String(rows.length);
    const enrolled = rows.reduce((total, row) => total + Number(row.enrollment_count || 0), 0);
    const present = rows.reduce((total, row) => total + Number(row.attendance_count || 0), 0);
    $("month-attendance").textContent = enrolled ? `${Math.round((present / enrolled) * 100)}%` : "—";
    const scores = rows.map((row) => row.engagement_score).filter((score) => score !== null && score !== undefined && score !== "").map(Number).filter(Number.isFinite);
    $("month-pulse").textContent = scores.length ? String(Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length)) : "—";
    $("month-contributions").textContent = String(rows.reduce((sum, row) => sum + Number(row.participation_count || 0), 0));
    renderAnalyticsChart(rows, monthLabel);
    renderMonthlyTable(rows);
    $("export-month").disabled = rows.length === 0;
  }

  function renderAnalyticsChart(rows, monthLabel) {
    const frame = $("analytics-chart");
    frame.replaceChildren();
    const chartRows = rows.filter((row) => Number(row.enrollment_count) > 0 || (row.engagement_score !== null && row.engagement_score !== undefined && row.engagement_score !== "" && Number.isFinite(Number(row.engagement_score))));
    if (!chartRows.length) {
      const empty = document.createElement("div");
      empty.className = "chart-empty";
      empty.textContent = `No session data for ${monthLabel}. Save a session summary to start the trend.`;
      frame.append(empty);
      return;
    }
    const svg = svgElement("svg", { viewBox: "0 0 680 250", role: "img", "aria-label": `Attendance rate and engagement pulse for ${monthLabel}, across ${chartRows.length} saved sessions` });
    const left = 40, right = 666, top = 20, bottom = 210;
    for (const tick of [0, 25, 50, 75, 100]) {
      const y = bottom - (tick / 100) * (bottom - top);
      svg.append(svgElement("line", { x1: left, x2: right, y1: y, y2: y, class: "chart-grid-line" }));
      svg.append(svgElement("text", { x: left - 9, y: y + 4, "text-anchor": "end", class: "chart-axis-label" }, String(tick)));
    }
    const xAt = (index) => chartRows.length === 1 ? (left + right) / 2 : left + (index / (chartRows.length - 1)) * (right - left);
    const yAt = (value) => bottom - (Math.max(0, Math.min(100, value)) / 100) * (bottom - top);
    const attendancePoints = [];
    const pulsePoints = [];
    chartRows.forEach((row, index) => {
      const enrolledCount = Number(row.enrollment_count);
      const attendanceCount = Number(row.attendance_count);
      const attendanceRate = enrolledCount > 0 ? (attendanceCount / enrolledCount) * 100 : NaN;
      const pulse = Number(row.engagement_score);
      const x = xAt(index);
      if (Number.isFinite(attendanceRate)) attendancePoints.push({ x, y: yAt(attendanceRate), row, value: Math.round(attendanceRate), kind: "attendance" });
      if (row.engagement_score !== null && row.engagement_score !== undefined && row.engagement_score !== "" && Number.isFinite(pulse)) pulsePoints.push({ x, y: yAt(pulse), row, value: Math.round(pulse), kind: "pulse" });
    });
    for (const [points, pathClass, pointClass, label] of [[attendancePoints, "chart-attendance-line", "chart-point-attendance", "Attendance"], [pulsePoints, "chart-pulse-line", "chart-point-pulse", "Pulse"]]) {
      if (!points.length) continue;
      const path = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
      svg.append(svgElement("path", { d: path, class: pathClass }));
      for (const point of points) {
        const time = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(point.row.started_at));
        const circle = svgElement("circle", { cx: point.x, cy: point.y, r: 5, class: pointClass });
        circle.append(svgElement("title", {}, `${label}: ${point.value}${label === "Attendance" ? "%" : "/100"} · ${time} · ${point.row.class_name || "Class session"}`));
        svg.append(circle);
      }
    }
    const labelCount = Math.min(5, chartRows.length);
    for (let tick = 0; tick < labelCount; tick += 1) {
      const index = labelCount === 1 ? 0 : Math.round((tick / (labelCount - 1)) * (chartRows.length - 1));
      const date = new Date(chartRows[index].started_at);
      const text = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
      svg.append(svgElement("text", { x: xAt(index), y: 235, "text-anchor": "middle", class: "chart-axis-label" }, text));
    }
    frame.append(svg);
  }

  function renderMonthlyTable(rows) {
    const tbody = $("monthly-session-rows");
    tbody.replaceChildren();
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td"); td.colSpan = 6; td.className = "table-empty"; td.textContent = "No sessions in this month yet.";
      tr.append(td); tbody.append(tr); return;
    }
    for (const row of [...rows].reverse()) {
      const tr = document.createElement("tr");
      const date = new Date(row.started_at);
      const cells = [
        new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }).format(date),
        row.class_name || "Class session",
        `${Number(row.attendance_count || 0)} / ${Number(row.enrollment_count || 0)}`,
        Number(row.enrollment_count) > 0 ? `${Math.round((Number(row.attendance_count || 0) / Number(row.enrollment_count)) * 100)}%` : "—",
        row.engagement_score !== null && row.engagement_score !== undefined && row.engagement_score !== "" && Number.isFinite(Number(row.engagement_score)) ? String(Math.round(Number(row.engagement_score))) : "—",
        String(Number(row.participation_count || 0)),
      ];
      for (const text of cells) { const td = document.createElement("td"); td.textContent = text; tr.append(td); }
      tbody.append(tr);
    }
  }

  function exportMonthlyCsv() {
    const rows = [...selectedMonthRows()].reverse();
    if (!rows.length) return;
    const headers = ["Date and time (local)", "Class", "Enrolled", "Present", "Attendance rate (%)", "Engagement pulse", "Participation contributions"];
    const values = rows.map((row) => {
      const enrollment = Number(row.enrollment_count || 0);
      const present = Number(row.attendance_count || 0);
      const score = row.engagement_score === null || row.engagement_score === undefined ? "" : row.engagement_score;
      return [new Date(row.started_at).toLocaleString(), row.class_name || "Class session", enrollment, present, enrollment ? Math.round((present / enrollment) * 100) : "", score, Number(row.participation_count || 0)];
    });
    const csv = [headers, ...values].map((line) => line.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `classpulse-${$("analytics-month").value}.csv`;
    document.body.append(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function estimatePulse(enrollment, attendance, participation) {
    if (!enrollment || attendance > enrollment) return null;
    const attendanceRate = attendance / enrollment;
    const participationRate = attendance ? Math.min(1, participation / attendance) : 0;
    return Math.round(55 * attendanceRate + 45 * participationRate);
  }

  function updatePreview() {
    const enrollment = Number($("enrollment").value);
    const attendance = Number($("attendance").value);
    const participation = Number($("participation").value || 0);
    const score = estimatePulse(enrollment, attendance, participation);
    const preview = $("insight-preview");
    const spark = document.createElement("span"); spark.className = "insight-spark"; spark.textContent = "✳";
    const copy = document.createElement("span");
    if (score === null) copy.textContent = "Enter valid enrollment and attendance totals to estimate the group pulse.";
    else if (score >= 75) copy.textContent = `Group pulse estimate: ${score}/100. Attendance and participation are both showing up.`;
    else if (score >= 50) copy.textContent = `Group pulse estimate: ${score}/100. Consider a short check-in to invite more voices.`;
    else copy.textContent = `Group pulse estimate: ${score}/100. A low signal is a prompt to ask, not a conclusion.`;
    preview.replaceChildren(spark, copy);
  }

  async function saveSession(event) {
    event.preventDefault();
    message("session-message", "");
    const className = $("class-name").value.trim();
    const sessionDate = new Date($("session-datetime").value);
    const enrollment = Number($("enrollment").value);
    const attendance = Number($("attendance").value);
    const participation = Number($("participation").value || 0);
    if (!className || !Number.isFinite(sessionDate.getTime()) || enrollment < 1 || attendance < 0 || attendance > enrollment || participation < 0) {
      message("session-message", "Check the class label, date, and totals. Present learners cannot exceed enrollment.", true);
      return;
    }
    const score = estimatePulse(enrollment, attendance, participation);
    const recommendationCodes = [];
    if (attendance / enrollment < 0.75) recommendationCodes.push("quick_check_in");
    if (score < 60) recommendationCodes.push("add_visual_example", "repeat_key_point");
    const body = {
      owner_id: view.user.id,
      class_name: className,
      started_at: sessionDate.toISOString(),
      enrollment_count: enrollment,
      attendance_count: attendance,
      engagement_score: score,
      participation_count: participation,
      summary: { recommendation_codes: recommendationCodes },
    };
    const button = $("save-session");
    button.disabled = true; button.textContent = "Saving securely…";
    try {
      await request("/rest/v1/classpulse_session_summaries", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${view.accessToken}`,
          "Content-Type": "application/json",
          Prefer: "return=minimal",
        },
        body: JSON.stringify(body),
      });
      $("session-form").reset(); $("session-datetime").value = localDateTimeValue(); $("participation").value = "0"; updatePreview();
      message("session-message", "Summary saved. Only group totals were sent to your protected Supabase table.");
      await loadSessions();
    } catch (error) {
      message("session-message", `Could not save the session: ${error.message}`, true);
    } finally {
      button.disabled = false; button.innerHTML = 'Save session summary <span aria-hidden="true">→</span>';
    }
  }

  async function initialize() {
    let savedTheme = "dark";
    try { savedTheme = localStorage.getItem("classpulse-theme") || "dark"; } catch { /* Use the dark reference theme. */ }
    applyTheme(savedTheme);
    $("theme-toggle").addEventListener("click", () => {
      applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    });
    $("analytics-month").value = localMonthKey(new Date());
    $("analytics-month").addEventListener("change", () => {
      view.monthChosen = true;
      renderMonthlyAnalytics();
    });
    $("export-month").addEventListener("click", exportMonthlyCsv);
    $("session-datetime").value = localDateTimeValue();
    $("signin-tab").addEventListener("click", () => setMode("signin"));
    $("signup-tab").addEventListener("click", () => setMode("signup"));
    $("auth-form").addEventListener("submit", authenticate);
    $("logout-button").addEventListener("click", signOut);
    $("camera-start").addEventListener("click", startCameraPreview);
    $("camera-count-toggle").addEventListener("click", () => {
      autoFaceCount = !autoFaceCount;
      $("camera-count-toggle").textContent = autoFaceCount ? "Pause auto count" : "Resume auto count";
      if (faceCountTimer !== null) window.clearTimeout(faceCountTimer);
      faceCountTimer = null;
      if (autoFaceCount && cameraStream && faceDetector) {
        cameraStatus("Counting visible faces on this device…", false, true);
        countVisibleFaces($("camera-video"));
      } else if (cameraStream) {
        cameraStatus("Auto count paused · edit the total manually", false, true);
      }
    });
    $("camera-stop").addEventListener("click", () => stopCameraPreview());
    $("camera-facing").addEventListener("change", () => {
      if (cameraStream) stopCameraPreview("Preview stopped · press Start to switch cameras");
    });
    window.addEventListener("pagehide", () => stopCameraPreview());
    window.addEventListener("beforeunload", () => stopCameraPreview());
    document.addEventListener("visibilitychange", () => {
      if (document.hidden && cameraStream) stopCameraPreview("Preview stopped while page was hidden");
    });
    $("session-form").addEventListener("submit", saveSession);
    ["enrollment", "attendance", "participation"].forEach((id) => $(id).addEventListener("input", updatePreview));
    try {
      const response = await fetch("/api/config", { cache: "no-store" });
      view.config = await response.json();
      if (!view.config.configured) {
        message("auth-message", "Deployment setup is incomplete. Add SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY to the Vercel project settings.", true);
      }
    } catch {
      message("auth-message", "Could not load app configuration. Refresh and try again.", true);
    }
  }

  initialize();
})();
