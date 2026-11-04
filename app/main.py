from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

APP_ROOT = Path(__file__).resolve().parent
DEFAULT_ROOT = APP_ROOT.parent
DEFAULT_DOWNLOAD_DIR = os.getenv("MONTUBE_DOWNLOAD_DIR", str(DEFAULT_ROOT / "downloads"))
DB_PATH = Path(os.getenv("MONTUBE_DB_PATH", DEFAULT_ROOT / "montube.db"))

SOCKET_PREFIX = "/app/montube"
STATIC_DIR = APP_ROOT / "static"
BUILD_ID = "montube-20261104133723"  # replaced by build-fpk.sh so every package build is distinguishable


def log_config():
    """Record what is actually deployed; this is the first thing to check on a blank page."""
    for marker in ["main.py", "requirements.txt", "static", "assets", "ui", "wheels"]:
        state = "yes" if (APP_ROOT / marker).exists() else "MISSING"
        print(f"[montube] {marker}: {state}", flush=True)
    found = sorted(str(path.relative_to(STATIC_DIR)) for path in STATIC_DIR.rglob("*") if path.is_file()) if STATIC_DIR.is_dir() else []
    print(f"[montube] version={app.version} build={BUILD_ID} root={APP_ROOT}", flush=True)
    print(f"[montube] static files={found}", flush=True)


app = FastAPI(title="Montube", version="0.2.6")


async def serve_app(scope, receive, send):
    """Placeholder replaced by the built middleware stack at startup."""
    await app.router(scope, receive, send)


class GatewayPrefixMiddleware:
    """Serve the app under fnOS gateway paths such as /app/montube/api/health.

    The gateway forwards the prefix as part of the path, while every route and
    static mount is registered at the root. Each such request is therefore
    replayed once with the prefix stripped. The replay keeps the same dict for
    middleware context and returns immediately, so it never re-enters the regex
    router; while it runs the original scope shows root_path=/app/montube so
    generated HTML and health output keep the URLs the browser needs.
    """

    async def __call__(self, scope, receive, send):
        path = scope.get("path") or "/"
        is_prefixed = scope.get("type") == "http" and (path == SOCKET_PREFIX or path.startswith(SOCKET_PREFIX + "/"))
        if not is_prefixed:
            await serve_app(scope, receive, send)
            return
        if path == SOCKET_PREFIX:
            location = SOCKET_PREFIX + "/"
            query = scope.get("query_string") or b""
            if query:
                location += "?" + query.decode("latin-1")
            await send({
                "type": "http.response.start",
                "status": 307,
                "headers": [(b"location", location.encode("latin-1")), (b"content-length", b"0")],
            })
            await send({"type": "http.response.body", "body": b""})
            return
        inner_path = path[len(SOCKET_PREFIX):] or "/"
        replay = dict(scope)
        replay["path"] = inner_path
        replay["raw_path"] = inner_path.encode("utf-8", "replace")
        replay["root_path"] = SOCKET_PREFIX
        await serve_app(replay, receive, send)


async def install_gateway_prefix():
    """Build the middleware stack once and put the gateway layer in front of it."""
    global serve_app
    if app.middleware_stack is None:
        app.middleware_stack = app.build_middleware_stack()
    serve_app = app.middleware_stack
    gateway = GatewayPrefixMiddleware()
    app.middleware_stack = gateway
    app.build_middleware_stack = lambda: gateway


def forwarded_prefix(request: Request) -> str:
    return SOCKET_PREFIX if request.scope.get("root_path") == SOCKET_PREFIX else ""


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT, status TEXT NOT NULL,
            kind TEXT NOT NULL, quality TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
            speed TEXT, eta TEXT, file_name TEXT, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        conn.execute("INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES('download_dir',?,?)", (DEFAULT_DOWNLOAD_DIR, now()))

class CreateJob(BaseModel):
    url: str = Field(min_length=4)
    kind: str = Field(default="video", pattern="^(video|audio)$")
    quality: str = Field(default="best", pattern="^(best|1080|720|480|audio)$")

class SettingsUpdate(BaseModel):
    download_dir: str = Field(min_length=1, max_length=1024)

def now():
    return datetime.now(timezone.utc).isoformat()

def get_download_dir() -> Path:
    init_db()
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='download_dir'").fetchone()
    configured = row["value"] if row else DEFAULT_DOWNLOAD_DIR
    return Path(configured).expanduser()

def update_job(job_id: str, **fields):
    fields["updated_at"] = now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    with db() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", [*fields.values(), job_id])

def parse_progress(line: str):
    percent = re.search(r"(\d+(?:\.\d+)?)%", line)
    speed = re.search(r"at\s+([^ ]+/?s)", line)
    eta = re.search(r"ETA\s+([^ ]+)", line)
    result = {}
    if percent:
        result["progress"] = min(100, float(percent.group(1)))
    if speed:
        result["speed"] = speed.group(1)
    if eta:
        result["eta"] = eta.group(1)
    return result

def run_download(job_id: str, payload: CreateJob):
    download_dir = get_download_dir()
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        update_job(job_id, status="failed", error=f"下载目录不可用: {exc}")
        return
    output = download_dir / "%(title)s.%(ext)s"
    if payload.kind == "audio":
        args = [sys.executable, "-m", "yt_dlp", "--newline", "--no-playlist", "-x", "--audio-format", "mp3", "-o", str(output), payload.url]
    else:
        fmt = "bestvideo+bestaudio/best" if payload.quality == "best" else f"bestvideo[height<={payload.quality}]+bestaudio/best[height<={payload.quality}]"
        args = [sys.executable, "-m", "yt_dlp", "--newline", "--no-playlist", "-f", fmt, "--merge-output-format", "mp4", "-o", str(output), payload.url]
    update_job(job_id, status="running", progress=0)
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout or []:
            progress = parse_progress(line)
            if progress:
                update_job(job_id, **progress)
            if "[download] Destination:" in line:
                update_job(job_id, file_name=line.split("Destination:", 1)[1].strip())
        code = process.wait()
        if code == 0:
            update_job(job_id, status="completed", progress=100, eta="-")
        else:
            update_job(job_id, status="failed", error=f"yt-dlp exited with code {code}")
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc))

@app.get("/api/jobs")
def list_jobs():
    with db() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100")]


@app.get("/api/settings")
def get_settings():
    return {"download_dir": str(get_download_dir())}


@app.put("/api/settings")
def update_settings(payload: SettingsUpdate):
    path = Path(payload.download_dir).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise OSError("路径不是目录")
    except OSError as exc:
        raise HTTPException(400, f"下载目录不可用: {exc}") from exc
    with db() as conn:
        conn.execute("INSERT INTO settings(key,value,updated_at) VALUES('download_dir',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (str(path), now()))
    return {"download_dir": str(path)}


@app.post("/api/jobs", status_code=202)
def create_job(payload: CreateJob):
    job_id = str(uuid.uuid4())
    timestamp = now()
    with db() as conn:
        conn.execute("INSERT INTO jobs (id,url,status,kind,quality,progress,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)", (job_id, payload.url, "queued", payload.kind, payload.quality, 0, timestamp, timestamp))
    threading.Thread(target=run_download, args=(job_id, payload), daemon=True).start()
    return {"id": job_id}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    with db() as conn:
        deleted = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,)).rowcount
    if not deleted:
        raise HTTPException(404, "Job not found")
    return {"ok": True}


# Installed via lifespan: see install_gateway_prefix().
@app.on_event("startup")
async def startup():
    init_db()
    log_config()
    await install_gateway_prefix()


# Mounted last so the API routes above take precedence over static files.
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def index_html(request: Request) -> str:
    """Serve the built SPA, pointing its relative asset URLs at wherever it is mounted."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    prefix = forwarded_prefix(request)
    if prefix:
        html = re.sub(r'(src|href)="(\.?/)', lambda m: f'{m.group(1)}="{prefix}{m.group(2)[1:]}', html)
    return html


@app.get("/")
def index(request: Request):
    return HTMLResponse(index_html(request))


@app.get("/api/health")
def health(request: Request):
    return {
        "ok": True,
        "version": app.version,
        "build": BUILD_ID,
        "root_path": request.scope.get("root_path", ""),
        "download_dir": str(get_download_dir()),
        "api_base": f"{forwarded_prefix(request)}/api",
        "static_files": sorted(str(path.relative_to(STATIC_DIR)) for path in STATIC_DIR.rglob("*") if path.is_file()),
    }


@app.exception_handler(StarletteHTTPException)
async def not_found_page(request: Request, exc: StarletteHTTPException):
    """Browser navigation to a SPA route (including /app/montube) gets the app, not a bare 404."""
    if exc.status_code == 404 and request.method == "GET":
        accept = request.headers.get("accept", "")
        path = request.scope.get("path", "")
        if "text/html" in accept and not path.startswith("/api/") and not path.startswith("/assets/"):
            return HTMLResponse(index_html(request))
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.get("/api/diagnostics")
def diagnostics(request: Request):
    """Everything a blank page needs: what is deployed, how it was reached, UI links."""
    share_paths = [p for p in (os.getenv("TRIM_DATA_SHARE_PATHS") or "").split(":") if p]
    links = [{"share": share, "ui_link": str(Path(share) / ".ui"), "exists": (Path(share) / ".ui").exists()} for share in share_paths]
    return {
        "build": BUILD_ID,
        "root_path": request.scope.get("root_path", ""),
        "request_path": request.scope.get("path", ""),
        "app_root": str(APP_ROOT),
        "static_files": sorted(str(path.relative_to(STATIC_DIR)) for path in STATIC_DIR.rglob("*") if path.is_file()),
        "ui_package": (APP_ROOT / "ui" / "map").exists(),
        "ui_links": links,
    }
