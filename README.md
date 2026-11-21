# ClassPulse AI

A Python-first, privacy-conscious classroom attendance and engagement prototype. It combines local media analysis with instructor-facing summaries; it is designed as a teaching aid, not an automated decision system.

## Quick start: run the Streamlit app

This repository includes the complete Python app. To run the same Streamlit interface on your computer, install Python 3.12, Git, and a current Chrome, Edge, or Firefox browser, then clone the repository:

```bash
git clone https://github.com/PadamSinghRajpurohit/classpulse-ai.git
cd classpulse-ai
```

Create a virtual environment and install the Streamlit dependencies:

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-streamlit.txt
streamlit run app.py
```

**macOS / Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-streamlit.txt
streamlit run app.py
```

Open the local address printed by Streamlit, usually <http://localhost:8501>. Sign up, then use the sidebar to move between Overview, Attendance, Live session, Insights, and the AI teaching coach. Camera and microphone features request browser permission only when you start them. Allow access on `localhost` to use those features; manual attendance remains available without camera permission. The camera face count and microphone sound sampler are estimates, so review results before saving.

The app starts in **local-only mode**: accounts, roster, attendance, and session data use a SQLite database on the computer running the app (`data/classpulse.db`). No Gemini key, Supabase account, Vercel account, or other personal service is needed to install and use the core app. No data is sent to the repository owner. Leave the optional integrations unconfigured for local-only use.

**For private, local storage, clone the repository and run it on your computer.** A public Streamlit or Vercel URL runs on that hosting provider's servers; it does not store data on the visitor's phone or computer. Treat the public hosted demo as a demo, and do not enter private student information there.

### Run the same entrypoint used by Streamlit Community Cloud

The hosted app uses `streamlit_cloud/app.py` as a small deployment entrypoint and `streamlit_cloud/requirements.txt` for dependencies. Locally, use `streamlit run app.py` from the repository root; it launches the same full app and uses the same dependency list. To mirror the hosted setup exactly, run `python -m pip install -r streamlit_cloud/requirements.txt` from the repository root, then run `streamlit run streamlit_cloud/app.py`.

Streamlit Community Cloud and local mode share the application code, but they do not store data in the same place. When you run `streamlit run app.py` on your computer, SQLite is stored on that computer. When you deploy to Streamlit Community Cloud, the app and SQLite file run on Streamlit's servers, and that local disk can reset during rebuilds; the data is not on your personal computer. For storage that stays on your own computer, use the local run instructions and do not deploy the app to a hosted service.

## Run locally

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-streamlit.txt
streamlit run app.py
```

The local mode uses SQLite and does not require API keys, a Supabase account, or a paid service. Create an account from the app's sign-up page. The local database is created on first run and ignored by Git.

## Follow the data flow

1. Start the app with `streamlit run app.py` and open the local URL printed in the terminal (normally `http://localhost:8501`).
2. Create an account and sign in. With `AUTH_BACKEND=supabase`, account credentials are handled by Supabase Auth; Supabase may require email confirmation before the first sign-in.
3. Local-only accounts store classes, rosters, attendance, and sessions in SQLite. If Supabase Auth and `SUPABASE_SYNC_ENABLED=true` are configured, classes, rosters, attendance, and aggregate session summaries are stored in the deploying owner's Supabase project using the signed-in user's token and owner-only Row Level Security.
4. The Supabase schema is in `supabase/migrations/`. Never put a service-role key in the app or repository; configure only the publishable/anon key in private Streamlit Secrets.

Never push `.env`; it can contain private configuration and is ignored by Git. This repository does not include or require the maintainer's Supabase credentials or project.

## Vercel preview

The local Streamlit interface uses a persistent process and local SQLite, which does not fit Vercel's request-based Python Functions. Vercel therefore uses the lightweight, stateless WSGI app in `vercel_app.py` with the same Supabase Auth and owner-protected aggregate-summary table. The hosted preview records group totals only; it does not store student names, individual attendance rows, or uploaded media. Add `SUPABASE_URL` and the Supabase publishable key as Vercel project environment variables to enable sign-in and persistence. Do not add `GEMINI_API_KEY` unless you explicitly choose to run Gemini in that deployment.

### Streamlit camera attendance and class rosters

The Attendance page has a live camera counter. Choose or create a class, then explicitly press **Start camera & count** and allow browser camera access. A free MediaPipe face detector estimates the number of visible faces in the browser and returns only that numeric estimate to Streamlit. Frames are not uploaded or stored. The estimate is not a count of verified students: the teacher must compare the selected class roster, confirm each student as present or absent, and save attendance manually. It cannot identify who is in the room. If camera access is declined or the detector cannot load, manual attendance remains available.

Each local class has its own roster. Students can be enrolled in more than one class; removing a student from a class does not delete them from other classes. Existing local rosters and attendance history are migrated into the class model when the app starts. Session analysis also lets the instructor choose a stored class so confirmed attendance is associated with the right class.

The Vercel runtime uses the standard-library-only root `requirements.txt`. Streamlit Community Cloud has an isolated entrypoint and dependency file under `streamlit_cloud/`; this lets its full AI/media dependencies install without burdening the Vercel build.

### Install ClassPulse on a phone

The Vercel site is an installable Progressive Web App (PWA). Share the HTTPS site link with a phone. On Android, use **Add to phone** or the browser menu's **Install app / Add to Home screen**. On iPhone or iPad, open the link in Safari, tap **Share**, then **Add to Home Screen**. This adds a browser-based web app; it does not download an APK or create an App Store package. Do not install APKs advertised as ClassPulse from third-party download sites. After the first visit, the public app shell can open offline, while sign-in and Supabase data still require internet.

After signing in, **Camera attendance estimate** offers optional live camera preview and approximate on-device face counting. The browser requests camera permission only after **Start camera & count**. The free MediaPipe face detector runs in the browser; video frames are not uploaded, recorded, or stored. Only the numeric group estimate is entered into the session form, and the instructor must review/correct it before saving. This detects visible faces, not student identities, and can miss or double-count people; declining camera permission leaves manual entry available. Stop the camera when finished. Counting requires a first-time download of the MediaPipe runtime/model from jsDelivr and Google Storage; the rest of the site continues to work with manual entry if those are unavailable.

The sign-in screen has **Preview sample dashboard** for a clearly marked, non-persistent view with fictional rows. For real data, sign in and save sessions; a new account's dashboard remains empty until it has sessions. The hosted session form also has an optional microphone sound-level sampler. It starts only after an instructor confirms consent and presses **Start sound sampler**. The browser calculates a broad sound-active percentage in memory; it does not record, upload, transcribe, or identify speakers. If the instructor saves the session, only that aggregate percentage is included in the user's RLS-protected summary. It is not speech detection or engagement and is not fused into the attendance/participation index.

The **local Python session analyzer** can additionally match face bounding boxes between sampled video frames to estimate how long a visible face remains in view. Matching state exists only in memory for that analysis; it returns aggregate counts/durations and never returns names, face crops, embeddings, or track IDs. A separate, unchecked-by-default option enables a camera-relative head-angle proxy with MediaPipe Face Landmarker. This is not gaze, attention, emotion, or engagement and is not used to identify people. If the optional runtime or model is unavailable, Haar face-presence and scene-motion estimates continue without head orientation. Only after explicitly enabling that option does the version-pinned official model bundle download from Google's MediaPipe model host and cache under the user's home cache (`.cache/classpulse/models`); downloads are capped at 32 MB and validated as an intact task archive before use. The model is not stored in the repository. MediaPipe may send performance/utilization metrics to Google; the local session screen discloses this before media selection. The local dependency file includes `mediapipe` and `webrtcvad-wheels`; if either cannot be installed, the analyzer falls back to face presence/motion or sound-energy-only audio respectively. WebRTC VAD estimates likely speech only; it does not transcribe or identify speakers.

The browser dashboard includes dark and light themes (dark is the default), a month selector, an attendance and engagement trend chart, local-time session details, and monthly CSV export. Session history is fetched in pages so the dashboard can display older months as well as recent sessions.

## Optional integrations (not required for local-only use)

- **Supabase (optional):** Supabase is not used in the default local setup. To enable hosted persistence, configure your own project's Auth URL and publishable/anon key in private Streamlit Secrets, set `AUTH_BACKEND="supabase"` and `SUPABASE_SYNC_ENABLED="true"`, and apply the versioned migrations under `supabase/migrations/`. Supabase Auth users' classes, rosters, attendance, and aggregate session summaries are stored in owner-scoped tables protected by Row Level Security. Never use a service-role key in the app or repository.
- **Gemini (optional):** The teaching coach and quiz builder require a Gemini API key supplied by the person running the app. Without it, local attendance, analysis, dashboards, and manual workflows remain available. Do not send student names, contact details, grades, recordings, frames, or other identifying information to an AI service. Only submit non-identifying lesson topics/questions. API use is subject to Google's own terms and limits.

You do not need to create a `.env` file for local-only use. If you later choose an integration, copy `.env.example` to `.env` and enter only your own credentials. `.env` and Streamlit secrets are excluded from Git. The repository contains no live API keys or Supabase credentials.

## Privacy and security defaults

- Video, audio, and frame processing is opt-in and local by default.
- Temporary media must be discarded after analysis; raw recordings are not part of the database.
- Passwords are stored as salted password hashes, never in plaintext.
- Student names and individual attendance records are stored in SQLite for local-only installs. When Supabase Auth and sync are enabled, they are stored in the instructor's own Supabase project and isolated by Row Level Security. In a hosted SQLite-only deployment, the database is on the hosting server and may reset; configure Supabase before using real class records.
- Engagement values are heuristic estimates with signal-quality caveats. They are not emotion detection or individual grades.
- Use group-level summaries and instructor review. Do not use the app to determine student eligibility, discipline, grading, or other consequential outcomes.
- Use HTTPS for deployed instances, set a strong Streamlit secrets policy, and review Supabase Row Level Security before enabling a hosted database.

## Project structure

- `app.py` — Streamlit interface
- `vercel_app.py` and `web/` — stateless Vercel web preview
- `auth.py` — sign-up and login
- `classpulse_storage.py` — local SQLite and optional Supabase data adapter; uniquely named to avoid package collisions\n- `storage.py` — compatibility import for older local scripts
- `ai_pipeline.py` — local multimodal signal analysis and recommendations
- `streamlit_cloud/` — isolated Streamlit Community Cloud entrypoint and dependencies
- `ai_chatbot.py` / `ai_chatbot_ui.py` — optional Gemini teaching coach and quiz builder
- `.env.example` — configuration names with empty values
- `supabase/schema.sql` — optional database schema and Row Level Security policies
- `pyproject.toml` — Vercel Python entrypoint configuration

## Deployment

### Streamlit Community Cloud (optional hosted deployment)

1. Push this repository to GitHub and open [share.streamlit.io](https://share.streamlit.io/).
2. Choose **New app**, select `PadamSinghRajpurohit/classpulse-ai`, branch `main`, and set the main file path to `streamlit_cloud/app.py`.
3. In **Advanced settings**, choose Python 3.12. Streamlit installs `streamlit_cloud/requirements.txt`, which includes the full local media and AI dependency set.
4. You can leave **Settings → Secrets** empty for local-mode authentication and SQLite inside the hosted app. Hosted SQLite is on Streamlit's servers and may be cleared; it is not storage on your computer. To keep all data on your own computer, run the app locally instead of deploying it.
5. The AI coach and quiz builder are optional and need your own `GEMINI_API_KEY` in Streamlit Secrets. Do not copy someone else's key. The app uses `gemini-3.5-flash-lite` by default (`GEMINI_MODEL` can override it); model availability and free usage limits may change. Send only non-identifying lesson topics/questions. Review Google's current [Gemini API pricing and data terms](https://ai.google.dev/gemini-api/docs/pricing) before use.

Streamlit Community Cloud runs the app on a hosted server. Local SQLite files may reset when the app is rebuilt or restarted. To keep signed-in class and attendance data across those restarts, configure `AUTH_BACKEND="supabase"`, your own `SUPABASE_URL`, your publishable/anon `SUPABASE_ANON_KEY`, and `SUPABASE_SYNC_ENABLED="true"` in Streamlit Secrets. The Supabase GitHub integration applies the project-prefixed migrations in `supabase/migrations/`; without that integration, apply the migration using your own Supabase project before using remote storage. The repository never connects to the maintainer's Supabase project. Review your provider's privacy, retention, access, and consent terms before using real student records.

