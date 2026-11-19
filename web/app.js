"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const view = { config: null, user: null, accessToken: null, mode: "signin", sessions: [] };

  function message(id, text, error = false) {
    const node = $(id);
    node.textContent = text || "";
    node.classList.toggle("error", Boolean(error));
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
      const vision = await import("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.22/vision_bundle.mjs");
      if (!cameraStream) return;
      const files = await vision.FilesetResolver.forVisionTasks(
        "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.22/wasm",
      );
      faceDetector = await vision.FaceDetector.createFromOptions(files, {
        baseOptions: {
          modelAssetPath: "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_full_range/float16/latest/blaze_face_full_range.tflite",
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
    } catch {
      if (cameraStream) cameraStatus("Camera is on · counter unavailable; enter the count manually", true, true);
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
      cameraStream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: $("camera-facing").value },
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
      });
      const video = $("camera-video");
      video.srcObject = cameraStream;
      video.classList.add("active");
      video.classList.toggle("mirrored", $("camera-facing").value === "user");
      await video.play();
      $("camera-placeholder").classList.add("hidden");
      $("camera-stop").disabled = false;
      start.disabled = true;
      $("camera-count-toggle").disabled = true;
      cameraStatus("Camera on · preparing on-device counter…", false, true);
      await startFaceCounting(video);
      cameraStream.getVideoTracks().forEach((track) => {
        track.addEventListener("ended", () => stopCameraPreview("Camera stream ended"), { once: true });
      });
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
    $("dashboard-view").classList.add("hidden");
    $("auth-view").classList.remove("hidden");
    $("logout-button").classList.add("hidden");
    $("auth-form").reset();
    setMode("signin");
  }

  async function loadSessions() {
    const query = new URLSearchParams({
      select: "id,class_name,started_at,enrollment_count,attendance_count,engagement_score,participation_count",
      owner_id: `eq.${view.user.id}`,
      order: "started_at.desc",
      limit: "50",
    });
    try {
      const rows = await request(`/rest/v1/classpulse_session_summaries?${query.toString()}`, {
        headers: { Authorization: `Bearer ${view.accessToken}` },
      });
      view.sessions = Array.isArray(rows) ? rows : [];
      renderSessions();
    } catch (error) {
      message("session-message", `Signed in, but summaries could not be loaded: ${error.message}`, true);
    }
  }

  function renderSessions() {
    const rows = view.sessions;
    $("sessions-count").textContent = String(rows.length);
    $("recent-count").textContent = `${rows.length} saved`;
    const totalEnrolled = rows.reduce((sum, row) => sum + Number(row.enrollment_count || 0), 0);
    const totalPresent = rows.reduce((sum, row) => sum + Number(row.attendance_count || 0), 0);
    const avgAttendance = totalEnrolled ? Math.round((totalPresent / totalEnrolled) * 100) : null;
    const scores = rows.map((row) => Number(row.engagement_score)).filter((score) => Number.isFinite(score));
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
      empty.append(orbit, strong, p); list.append(empty); return;
    }
    for (const row of rows) {
      const item = document.createElement("article"); item.className = "session-row";
      const info = document.createElement("div"); info.className = "session-info";
      const title = document.createElement("strong"); title.textContent = row.class_name || "Class session";
      const details = document.createElement("span");
      const date = row.started_at ? new Date(row.started_at) : new Date();
      const dateText = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
      details.textContent = `${dateText} · ${Number(row.attendance_count || 0)} / ${Number(row.enrollment_count || 0)} present`;
      info.append(title, details);
      const score = document.createElement("div"); score.className = "session-score";
      score.textContent = Number.isFinite(Number(row.engagement_score)) ? String(Math.round(Number(row.engagement_score))) : "—";
      const scoreLabel = document.createElement("small"); scoreLabel.textContent = "pulse / 100"; score.append(scoreLabel);
      item.append(info, score); list.append(item);
    }
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
    const enrollment = Number($("enrollment").value);
    const attendance = Number($("attendance").value);
    const participation = Number($("participation").value || 0);
    if (!className || enrollment < 1 || attendance < 0 || attendance > enrollment || participation < 0) {
      message("session-message", "Check the class label and totals. Present learners cannot exceed enrollment.", true);
      return;
    }
    const score = estimatePulse(enrollment, attendance, participation);
    const recommendationCodes = [];
    if (attendance / enrollment < 0.75) recommendationCodes.push("quick_check_in");
    if (score < 60) recommendationCodes.push("add_visual_example", "repeat_key_point");
    const body = {
      owner_id: view.user.id,
      class_name: className,
      started_at: new Date().toISOString(),
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
      $("session-form").reset(); $("participation").value = "0"; updatePreview();
      message("session-message", "Summary saved. Only group totals were sent to your protected Supabase table.");
      await loadSessions();
    } catch (error) {
      message("session-message", `Could not save the session: ${error.message}`, true);
    } finally {
      button.disabled = false; button.innerHTML = 'Save session summary <span aria-hidden="true">→</span>';
    }
  }

  async function initialize() {
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
