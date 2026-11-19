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

The Vercel runtime uses the standard-library-only `requirements.txt`; install the richer local Streamlit dependencies from `requirements-streamlit.txt`.

### Install ClassPulse on a phone

The Vercel site is an installable Progressive Web App (PWA). Share the HTTPS site link with a phone. On Android, use **Install app** (or the browser menu's **Install app / Add to Home screen**). On iPhone or iPad, open the link in Safari, tap **Share**, then **Add to Home Screen**. This installs a home-screen web app; it does not create an APK or an App Store package. After the first visit, the public app shell can open offline, while sign-in and Supabase data still require internet.

After signing in, **Check your camera framing** offers an optional video-only preview. The browser requests camera permission only after **Start preview**. The preview stays in the browser and is stopped when the user stops it, signs out, switches away, or leaves the page. It does not record, upload, analyze, or store video. The hosted dashboard does not run computer vision on the live camera; the separate local Python media pipeline can analyze a user-selected still image or video file.

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
- `.env.example` — configuration names with empty values
- `supabase/schema.sql` — optional database schema and Row Level Security policies
- `pyproject.toml` — Vercel Python entrypoint configuration

## Deployment

Streamlit Community Cloud offers a free deployment option connected to GitHub. Add optional credentials through the deployment's secrets interface; the app reads those values without placing them in source. Hosted free plans have limits and are not a zero-cost production guarantee. Do not upload real student recordings until the deployment's privacy, retention, access, and consent requirements have been reviewed.
