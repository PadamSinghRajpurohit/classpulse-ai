"""Small, stateless WSGI entrypoint for the Vercel-hosted ClassPulse preview.

The richer Streamlit app remains available locally. Vercel runs request-scoped
Python functions, so this entrypoint serves the lightweight web dashboard and
uses Supabase Auth + the owner-RLS table directly from the browser.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from wsgiref.types import StartResponse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def _send(start_response: StartResponse, status: str, body: bytes, content_type: str, *, cache: str = "no-store") -> list[bytes]:
    start_response(status, [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", cache),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("X-Frame-Options", "DENY"),
        ("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()"),
    ])
    return [body]


def application(environ: dict, start_response: StartResponse) -> list[bytes]:
    """Vercel WSGI handler. No credentials or user data are logged or persisted."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    if method not in {"GET", "HEAD"}:
        return _send(start_response, "405 Method Not Allowed", b"Method not allowed", "text/plain; charset=utf-8")

    path = environ.get("PATH_INFO", "/")
    if path == "/api/config":
        base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        publishable_key = (os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()
        configured = bool(base_url and publishable_key)
        payload = json.dumps({
            "configured": configured,
            "supabaseUrl": base_url if configured else "",
            # Supabase publishable/anon keys are designed for browser use; RLS
            # is the security boundary. Never return a service-role/secret key.
            "publishableKey": publishable_key if configured else "",
        }).encode("utf-8")
        return _send(start_response, "200 OK", payload, "application/json; charset=utf-8")

    if path == "/api/health":
        configured = bool(os.getenv("SUPABASE_URL", "").strip() and (os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")))
        payload = json.dumps({"status": "ok", "supabase_configured": configured}).encode("utf-8")
        return _send(start_response, "200 OK", payload, "application/json; charset=utf-8")

    asset_map = {
        "/": (WEB / "index.html", "text/html; charset=utf-8"),
        "/index.html": (WEB / "index.html", "text/html; charset=utf-8"),
        "/manifest.webmanifest": (WEB / "manifest.webmanifest", "application/manifest+json; charset=utf-8"),
        "/service-worker.js": (WEB / "service-worker.js", "application/javascript; charset=utf-8"),
        "/assets/styles.css": (WEB / "styles.css", "text/css; charset=utf-8"),
        "/assets/app.js": (WEB / "app.js", "text/javascript; charset=utf-8"),
        "/assets/pwa.js": (WEB / "assets" / "pwa.js", "text/javascript; charset=utf-8"),
        "/assets/pwa.css": (WEB / "assets" / "pwa.css", "text/css; charset=utf-8"),
        "/assets/icon-192.png": (WEB / "assets" / "icon-192.png", "image/png"),
        "/assets/icon-512.png": (WEB / "assets" / "icon-512.png", "image/png"),
        "/assets/icon-maskable-512.png": (WEB / "assets" / "icon-maskable-512.png", "image/png"),
    }
    asset = asset_map.get(path)
    if asset is None:
        return _send(start_response, "404 Not Found", b"Not found", "text/plain; charset=utf-8")
    file_path, content_type = asset
    try:
        body = file_path.read_bytes()
    except OSError:
        return _send(start_response, "503 Service Unavailable", b"ClassPulse assets are unavailable", "text/plain; charset=utf-8")

    if path in {"/", "/index.html"}:
        markup = body.decode("utf-8")
        pwa_head = (
            '<link rel="manifest" href="/manifest.webmanifest">\n'
            '<link rel="apple-touch-icon" href="/assets/icon-192.png">\n'
            '<meta name="apple-mobile-web-app-capable" content="yes">\n'
            '<link rel="stylesheet" href="/assets/pwa.css">\n'
        )
        markup = markup.replace("</head>", pwa_head + "</head>", 1)
        markup = markup.replace("</body>", '<script src="/assets/pwa.js" defer></script>\n</body>', 1)
        body = markup.encode("utf-8")

    origin = "'self'"
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    if supabase_url:
        parsed = urlsplit(supabase_url)
        if parsed.scheme == "https" and parsed.hostname and parsed.hostname.endswith(".supabase.co"):
            origin = f"https://{parsed.hostname}"
    csp = (
        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval' https://cdn.jsdelivr.net; style-src 'self'; "
        "worker-src 'self' blob:; img-src 'self' data:; "
        f"connect-src 'self' {origin} https://cdn.jsdelivr.net https://storage.googleapis.com; "
        "base-uri 'self'; form-action 'self'; object-src 'none'; frame-ancestors 'none'"
    )
    response_headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-cache" if path in {"/", "/index.html", "/service-worker.js", "/manifest.webmanifest"} else "public, max-age=300"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("X-Frame-Options", "DENY"),
        ("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()"),
        ("Content-Security-Policy", csp),
    ]
    if path == "/service-worker.js":
        response_headers.append(("Service-Worker-Allowed", "/"))
    start_response("200 OK", response_headers)
    return [body if method == "GET" else b""]
