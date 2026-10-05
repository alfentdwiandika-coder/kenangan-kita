import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from database import (
    init_db, create_job, add_photo, get_job,
    update_job, list_templates, get_template,
)
from renderer import render_slideshow, RenderError

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kenangan-kita")

# ─── Konstanta keamanan ───────────────────────────────────────────────────────

ALLOWED_MIME   = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_EXT    = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_BYTES = 10 * 1024 * 1024   # 10 MB per foto
MAX_PHOTOS     = 10                  # maksimum foto per job
MIN_PHOTOS     = 1
MAX_JOBS_PER_IP_PER_MINUTE = 5       # rate limit sederhana

# In-memory rate limit store: {ip: [timestamp, ...]}
_rate_store: dict[str, list[float]] = {}

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# ─── Path setup ──────────────────────────────────────────────────────────────

BASE_DIR     = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR   = BASE_DIR / "storage" / "uploads"
OUTPUT_DIR   = BASE_DIR / "storage" / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Kenangan Kita — Video Generator",
    # Sembunyikan docs di production jika diperlukan
    docs_url="/docs",
    redoc_url=None,
)

# [FIX #5] CORS — hanya izinkan origin yang diketahui.
# Untuk local dev, localhost:8000 sudah cukup.
# Ganti dengan domain production saat deploy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Static files
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")
app.mount("/assets",  StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")


# ─── Startup ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    init_db()


# ─── Middleware: Security Headers [FIX #9] ───────────────────────────────────

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"]  = "nosniff"
    response.headers["X-Frame-Options"]         = "DENY"
    response.headers["X-XSS-Protection"]        = "1; mode=block"
    response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"]      = "camera=(), microphone=(), geolocation=()"
    # CSP: izinkan resource dari origin sendiri + Google Fonts untuk frontend
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' blob: data:; "
        "media-src 'self' blob:; "
        "connect-src 'self';"
    )
    return response


# ─── Helper: validasi UUID [FIX #2] ──────────────────────────────────────────

def _require_valid_uuid(value: str, label: str = "ID") -> str:
    if not UUID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"{label} tidak valid.")
    return value


# ─── Helper: rate limit [FIX #8] ─────────────────────────────────────────────

def _check_rate_limit(request: Request):
    ip  = request.client.host if request.client else "unknown"
    now = time.time()
    window = 60.0

    timestamps = _rate_store.get(ip, [])
    # Buang timestamp lama di luar window
    timestamps = [t for t in timestamps if now - t < window]

    if len(timestamps) >= MAX_JOBS_PER_IP_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail=f"Terlalu banyak permintaan. Tunggu sebentar lalu coba lagi.",
        )

    timestamps.append(now)
    _rate_store[ip] = timestamps


# ─── Helper: validasi & sanitasi file upload [FIX #1] ────────────────────────

async def _validate_photo(photo: UploadFile, index: int) -> bytes:
    # 1. Cek ekstensi
    suffix = Path(photo.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Foto {index + 1}: tipe file tidak didukung ({suffix}). "
                   f"Gunakan JPG, PNG, atau WebP.",
        )

    # 2. Baca konten & cek ukuran
    content = await photo.read()
    if len(content) > MAX_FILE_BYTES:
        mb = len(content) / 1024 / 1024
        raise HTTPException(
            status_code=413,
            detail=f"Foto {index + 1}: ukuran file terlalu besar ({mb:.1f} MB). "
                   f"Maksimum 10 MB.",
        )
    if len(content) < 8:
        raise HTTPException(status_code=400, detail=f"Foto {index + 1}: file rusak atau kosong.")

    # 3. Validasi magic bytes (file signature) — jangan percaya ekstensi saja
    magic = content[:8]
    is_jpeg = magic[:2] == b"\xff\xd8"
    is_png  = magic[:8] == b"\x89PNG\r\n\x1a\n"
    is_webp = magic[:4] == b"RIFF" and content[8:12] == b"WEBP"

    if not (is_jpeg or is_png or is_webp):
        raise HTTPException(
            status_code=400,
            detail=f"Foto {index + 1}: konten file tidak sesuai tipe gambar yang valid.",
        )

    return content


# ─── Frontend ────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


# ─── Templates ───────────────────────────────────────────────────────────────

@app.get("/api/templates")
def api_list_templates():
    return {"templates": list_templates()}


# ─── Jobs ────────────────────────────────────────────────────────────────────

@app.post("/api/jobs/photos", status_code=201)
async def api_upload_photos(
    request: Request,
    photos: List[UploadFile] = File(...),
):
    # [FIX #8] Rate limit
    _check_rate_limit(request)

    # [FIX #6] Batasi jumlah foto
    if len(photos) < MIN_PHOTOS:
        raise HTTPException(status_code=400, detail="Minimal satu foto harus diunggah.")
    if len(photos) > MAX_PHOTOS:
        raise HTTPException(
            status_code=400,
            detail=f"Maksimum {MAX_PHOTOS} foto per video.",
        )

    job_id   = str(uuid.uuid4())
    save_dir = UPLOAD_DIR / job_id
    save_dir.mkdir(parents=True, exist_ok=True)

    create_job(job_id)

    for order, photo in enumerate(photos):
        # [FIX #1] Validasi tipe, ukuran, dan magic bytes
        content = await _validate_photo(photo, order)

        suffix   = Path(photo.filename or "").suffix.lower() or ".jpg"
        filename = f"foto_{order + 1}{suffix}"  # nama aman, tidak pakai nama asli user
        file_path = save_dir / filename

        file_path.write_bytes(content)
        add_photo(job_id, order, filename, str(file_path))

    logger.info("Job %s dibuat dengan %d foto dari %s", job_id, len(photos),
                request.client.host if request.client else "unknown")
    return {"job": {"job_id": job_id}}


class TemplateChoice(BaseModel):
    template_id: str

    # [FIX #4] Whitelist karakter preset_id — cegah path traversal
    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9\-]{1,64}$", v):
            raise ValueError("template_id tidak valid.")
        return v


@app.post("/api/jobs/{job_id}/template")
def api_set_template(job_id: str, body: TemplateChoice):
    # [FIX #2] Validasi UUID
    _require_valid_uuid(job_id, "job_id")

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")

    template = get_template(body.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template tidak ditemukan.")

    update_job(job_id, template_id=body.template_id)
    return {"status": "ok"}


def _run_render(job_id: str):
    """Dipanggil di background thread."""
    job = get_job(job_id)
    if not job:
        return

    photo_paths = [
        p["file_path"]
        for p in sorted(job["photos"], key=lambda p: p["sort_order"])
    ]
    output_dir  = OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "video.mp4"

    try:
        update_job(job_id, status="rendering")
        render_slideshow(photo_paths, output_path, job["template_id"])
        update_job(job_id, status="ready", video_path=str(output_path))
        logger.info("Job %s selesai render: %s", job_id, output_path)
    except RenderError as exc:
        # [FIX #7] Log detail error di server, jangan kirim ke client
        logger.error("Job %s render gagal: %s", job_id, exc)
        update_job(job_id, status="failed", error_message="Render gagal. Coba lagi.")
    except Exception as exc:
        logger.exception("Job %s error tak terduga", job_id)
        update_job(job_id, status="failed", error_message="Terjadi kesalahan. Coba lagi.")


@app.post("/api/jobs/{job_id}/render")
def api_start_render(job_id: str, background_tasks: BackgroundTasks):
    # [FIX #2] Validasi UUID
    _require_valid_uuid(job_id, "job_id")

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    if not job.get("template_id"):
        raise HTTPException(status_code=400, detail="Template belum dipilih.")
    if job["status"] == "rendering":
        raise HTTPException(status_code=409, detail="Render sudah berjalan.")

    # [FIX #6] Cegah re-render job yang sudah selesai / gagal berkali-kali
    if job["status"] == "ready":
        raise HTTPException(status_code=409, detail="Video sudah selesai dibuat.")

    background_tasks.add_task(_run_render, job_id)
    return {"status": "rendering"}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str):
    # [FIX #2] Validasi UUID
    _require_valid_uuid(job_id, "job_id")

    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")

    response = {
        "job_id":        job["id"],
        "status":        job["status"],
        "template_id":   job.get("template_id"),
        # [FIX #7] Hanya tampilkan error_message yang sudah disanitasi (bukan stack trace)
        "error_message": job.get("error_message"),
        "created_at":    job.get("created_at"),
    }

    if job["status"] == "ready" and job.get("video_path"):
        response["video_url"]    = f"/outputs/{job_id}/video.mp4"
        response["download_url"] = f"/outputs/{job_id}/video.mp4"

    return response


@app.get("/api/jobs/{job_id}/download")
def api_download_video(job_id: str):
    # [FIX #2] Validasi UUID
    _require_valid_uuid(job_id, "job_id")

    job = get_job(job_id)
    if not job or job["status"] != "ready":
        raise HTTPException(status_code=404, detail="Video belum siap atau tidak ditemukan.")

    video_path = Path(job["video_path"])

    # [FIX #4] Pastikan path video masih di dalam OUTPUT_DIR (cegah path traversal)
    try:
        video_path.resolve().relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        logger.warning("Path traversal attempt pada job %s: %s", job_id, video_path)
        raise HTTPException(status_code=403, detail="Akses ditolak.")

    if not video_path.exists():
        raise HTTPException(status_code=404, detail="File video tidak ditemukan.")

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=f"kenangan-kita-{job_id[:8]}.mp4",
    )
