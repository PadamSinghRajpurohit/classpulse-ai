# ClassPulse AI

A Python-first, privacy-conscious classroom attendance and engagement prototype. It combines local media analysis with instructor-facing summaries; it is designed as a teaching aid, not an automated decision system.

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
3. Add a class roster and record attendance in the app. Student names and individual attendance rows are kept in the local SQLite database (`data/classpulse.db`).
4. Save a session summary. For a Supabase Auth user, the app sends only aggregate counts, a group engagement score, class label, and approved summary codes to `classpulse_session_summaries`.
5. Inspect hosted rows in the Supabase project's **Table Editor → public → classpulse_session_summaries**. The table has owner-only Row Level Security; the anon role has no table access.

The current connected project is [PadamSinghRajpurohit's Supabase project](https://supabase.com/dashboard/project/thtohsposkmvvssffrlq). Never push `.env`; it contains private configuration and is ignored by Git.

## Vercel preview

The local Streamlit interface uses a persistent process and local SQLite, which does not fit Vercel's request-based Python Functions. Vercel therefore uses the lightweight, stateless WSGI app in `vercel_app.py` with the same Supabase Auth and owner-protected aggregate-summary table. The hosted preview records group totals only; it does not store student names, individual attendance rows, or uploaded media. Add `SUPABASE_URL` and the Supabase publishable key as Vercel project environment variables to enable sign-in and persistence. Do not add `GEMINI_API_KEY` unless you explicitly choose to run Gemini in that deployment.

The Vercel runtime uses the standard-library-only root `requirements.txt`. Streamlit Community Cloud has an isolated entrypoint and dependency file under `streamlit_cloud/`; this lets its full AI/media dependencies install without burdening the Vercel build.

### Install ClassPulse on a phone

The Vercel site is an installable Progressive Web App (PWA). Share the HTTPS site link with a phone. On Android, use **Add to phone** or the browser menu's **Install app / Add to Home screen**. On iPhone or iPad, open the link in Safari, tap **Share**, then **Add to Home Screen**. This adds a browser-based web app; it does not download an APK or create an App Store package. Do not install APKs advertised as ClassPulse from third-party download sites. After the first visit, the public app shell can open offline, while sign-in and Supabase data still require internet.

After signing in, **Camera attendance estimate** offers optional live camera preview and approximate on-device face counting. The browser requests camera permission only after **Start camera & count**. The free MediaPipe face detector runs in the browser; video frames are not uploaded, recorded, or stored. Only the numeric group estimate is entered into the session form, and the instructor must review/correct it before saving. This detects visible faces, not student identities, and can miss or double-count people; declining camera permission leaves manual entry available. Stop the camera when finished. Counting requires a first-time download of the MediaPipe runtime/model from jsDelivr and Google Storage; the rest of the site continues to work with manual entry if those are unavailable.

The sign-in screen has **Preview sample dashboard** for a clearly marked, non-persistent view with fictional rows. For real data, sign in and save sessions; a new account's dashboard remains empty until it has sessions. The hosted session form also has an optional microphone sound-level sampler. It starts only after an instructor confirms consent and presses **Start sound sampler**. The browser calculates a broad sound-active percentage in memory; it does not record, upload, transcribe, or identify speakers. If the instructor saves the session, only that aggregate percentage is included in the user's RLS-protected summary. It is not speech detection or engagement and is not fused into the attendance/participation index.

The **local Python session analyzer** can additionally match face bounding boxes between sampled video frames to estimate how long a visible face remains in view. Matching state exists only in memory for that analysis; it returns aggregate counts/durations and never returns names, face crops, embeddings, or track IDs. A separate, unchecked-by-default option enables a camera-relative head-angle proxy with MediaPipe Face Landmarker. This is not gaze, attention, emotion, or engagement and is not used to identify people. If the optional runtime or model is unavailable, Haar face-presence and scene-motion estimates continue without head orientation. Only after explicitly enabling that option does the version-pinned official model bundle download from Google's MediaPipe model host and cache under the user's home cache (`.cache/classpulse/models`); downloads are capped at 32 MB and validated as an intact task archive before use. The model is not stored in the repository. MediaPipe may send performance/utilization metrics to Google; the local session screen discloses this before media selection. The local dependency file includes `mediapipe` and `webrtcvad-wheels`; if either cannot be installed, the analyzer falls back to face presence/motion or sound-energy-only audio respectively. WebRTC VAD estimates likely speech only; it does not transcribe or identify speakers.

The browser dashboard includes dark and light themes (dark is the default), a month selector, an attendance and engagement trend chart, local-time session details, and monthly CSV export. Session history is fetched in pages so the dashboard can display older months as well as recent sessions.

## Optional free services

- **Supabase:** Set `AUTH_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SYNC_ENABLED=true` in a local `.env` file or deployment secrets to enable Supabase Auth and hosted session-summary sync. Apply `supabase/schema.sql` in the Supabase SQL editor first. The app uses owner-only Row Level Security. Never add a service-role key to the app or repository. Supabase's free plan has quotas and may pause inactive projects; check the provider's current limits before deployment.
- **Gemini:** Set `GEMINI_API_KEY` only if you choose to use optional summaries. The local rules work without it. Raw audio/video, frames, faces, and student identifiers must not be sent to Gemini. Only de-identified aggregate session metrics may be sent, and only after the user explicitly enables that action.

Copy `.env.example` to `.env` for local configuration. The `supabase` Python package is included in `requirements-streamlit.txt`; local SQLite remains the default until Supabase credentials and sync are enabled. `.env` and Streamlit secrets are excluded from Git. GitHub should contain placeholders and setup instructions only, never live API keys.

## Privacy and security defaults

- Video, audio, and frame processing is opt-in and local by default.
- Temporary media must be discarded after analysis; raw recordings are not part of the database.
- Passwords are stored as salted password hashes, never in plaintext.
- Student names and individual attendance records stay in the app's SQLite database and are not synced to Supabase. In a hosted deployment, that database is on the hosting server, not the instructor's device; use synthetic data until its access and retention have been reviewed.
- Engagement values are heuristic estimates with signal-quality caveats. They are not emotion detection or individual grades.
- Use group-level summaries and instructor review. Do not use the app to determine student eligibility, discipline, grading, or other consequential outcomes.
- Use HTTPS for deployed instances, set a strong Streamlit secrets policy, and review Supabase Row Level Security before enabling a hosted database.

## Project structure

- `app.py` — Streamlit interface
- `vercel_app.py` and `web/` — stateless Vercel web preview
- `auth.py` — sign-up and login
- `storage.py` — local SQLite and optional Supabase data adapter
- `ai_pipeline.py` — local multimodal signal analysis and recommendations
- `streamlit_cloud/` — isolated Streamlit Community Cloud entrypoint and dependencies
- `ai_chatbot.py` / `ai_chatbot_ui.py` — optional Gemini teaching coach and quiz builder
- `.env.example` — configuration names with empty values
- `supabase/schema.sql` — optional database schema and Row Level Security policies
- `pyproject.toml` — Vercel Python entrypoint configuration

## Deployment

### Streamlit Community Cloud

1. Push this repository to GitHub and open [share.streamlit.io](https://share.streamlit.io/).
2. Choose **New app**, select `PadamSinghRajpurohit/classpulse-ai`, branch `main`, and set the main file path to `streamlit_cloud/app.py`.
3. In **Advanced settings**, choose Python 3.12. Streamlit installs `streamlit_cloud/requirements.txt`, which includes the full local media and AI dependency set.
4. Add secrets in the app's **Settings → Secrets** using `streamlit_cloud/secrets.example.toml` as a placeholder template. For hosted, persistent user accounts and session summaries, configure `AUTH_BACKEND`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `SUPABASE_SYNC_ENABLED` using the values for the Supabase project; apply `supabase/schema.sql` first. Never use the Supabase service-role key.
5. Add `GEMINI_API_KEY` in Streamlit Secrets to enable the teaching coach and quiz builder. They use the Gemini 2.5 Flash text API by default (`GEMINI_MODEL` can override it). Keep the key in Streamlit Secrets, never in GitHub. Gemini's free tier has usage limits; Google's pricing page says free-tier submitted content may be used to improve products, so send only non-identifying lesson topics/questions. Review Google's current [Gemini API pricing and data terms](https://ai.google.dev/gemini-api/docs/pricing) before use.

Streamlit Community Cloud's local SQLite filesystem may reset when the app is rebuilt or restarted. Use Supabase Auth and session-summary sync for persistent remote summaries. Roster/individual attendance still use local SQLite and should not be treated as durable in this hosted deployment. Free hosting and API quotas can change; do not upload real student recordings until privacy, retention, access, and consent have been reviewed.
