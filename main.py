import os
import shutil
import uuid
import asyncio
from pathlib import Path
from typing import List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from database import init_db, create_job, add_photo, get_job, update_job, list_templates, get_template
from renderer import render_slideshow, RenderError

BASE_DIR   = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR = BASE_DIR / "storage" / "uploads"
OUTPUT_DIR = BASE_DIR / "storage" / "outputs"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Video Generator Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")
app.mount("/assets",  StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")


@app.on_event("startup")
def on_startup():
    init_db()


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
async def api_upload_photos(photos: List[UploadFile] = File(...)):
    if not photos:
        raise HTTPException(status_code=400, detail="Minimal satu foto harus diunggah.")

    job_id   = str(uuid.uuid4())
    save_dir = UPLOAD_DIR / job_id
    save_dir.mkdir(parents=True, exist_ok=True)

    create_job(job_id)

    for order, photo in enumerate(photos):
        # Nama file aman: foto_1.ext, foto_2.ext, dst.
        suffix   = Path(photo.filename).suffix.lower() or ".jpg"
        filename = f"foto_{order + 1}{suffix}"
        file_path = save_dir / filename

        with file_path.open("wb") as buf:
            shutil.copyfileobj(photo.file, buf)

        add_photo(job_id, order, filename, str(file_path))

    return {"job": {"job_id": job_id}}


class TemplateChoice(BaseModel):
    template_id: str


@app.post("/api/jobs/{job_id}/template")
def api_set_template(job_id: str, body: TemplateChoice):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")

    template = get_template(body.template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{body.template_id}' tidak ditemukan.")

    update_job(job_id, template_id=body.template_id)
    return {"status": "ok"}


def _run_render(job_id: str):
    """Dipanggil di background thread."""
    job = get_job(job_id)
    if not job:
        return

    photo_paths = [p["file_path"] for p in sorted(job["photos"], key=lambda p: p["sort_order"])]
    output_dir  = OUTPUT_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "video.mp4"

    try:
        update_job(job_id, status="rendering")
        render_slideshow(photo_paths, output_path, job["template_id"])
        update_job(job_id, status="ready", video_path=str(output_path))
    except RenderError as exc:
        update_job(job_id, status="failed", error_message=str(exc))
    except Exception as exc:
        update_job(job_id, status="failed", error_message=f"Kesalahan tak terduga: {exc}")


@app.post("/api/jobs/{job_id}/render")
def api_start_render(job_id: str, background_tasks: BackgroundTasks):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    if not job.get("template_id"):
        raise HTTPException(status_code=400, detail="Template belum dipilih.")
    if job["status"] == "rendering":
        raise HTTPException(status_code=409, detail="Render sudah berjalan.")

    background_tasks.add_task(_run_render, job_id)
    return {"status": "rendering"}


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")

    response = {
        "job_id":        job["id"],
        "status":        job["status"],
        "template_id":   job.get("template_id"),
        "error_message": job.get("error_message"),
        "created_at":    job.get("created_at"),
    }

    if job["status"] == "ready" and job.get("video_path"):
        video_path = Path(job["video_path"])
        # URL relatif yang bisa diakses frontend
        response["video_url"]    = f"/outputs/{job_id}/video.mp4"
        response["download_url"] = f"/outputs/{job_id}/video.mp4"

    return response


@app.get("/api/jobs/{job_id}/download")
def api_download_video(job_id: str):
    job = get_job(job_id)
    if not job or job["status"] != "ready":
        raise HTTPException(status_code=404, detail="Video belum siap atau tidak ditemukan.")

    video_path = Path(job["video_path"])
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="File video tidak ditemukan di server.")

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=f"kenangan-kita-{job_id[:8]}.mp4",
    )
