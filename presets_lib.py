import json
import logging
import re
from pathlib import Path

PRESET_DIR = Path(__file__).resolve().parent / "presets"

logger = logging.getLogger("kenangan-kita")

# [FIX #4] Whitelist karakter yang boleh ada di preset ID
_PRESET_ID_RE = re.compile(r"^[a-z0-9\-]{1,64}$")

LOOKS = {
    "warm-rose": (
        "eq=contrast=1.06:brightness=0.035:saturation=1.22:"
        "gamma_r=1.10:gamma_g=1.03:gamma_b=0.90,vignette=PI/5"
    ),
    "peach-film": (
        "eq=contrast=1.04:brightness=0.03:saturation=1.10:"
        "gamma_r=1.08:gamma_g=1.04:gamma_b=0.94,vignette=PI/4"
    ),
    "soft-blush": (
        "eq=contrast=1.03:brightness=0.045:saturation=1.16:"
        "gamma_r=1.07:gamma_g=1.02:gamma_b=0.95,vignette=PI/6"
    ),
    "degdegan": (
        "eq=contrast=1.08:brightness=0.02:saturation=1.28:"
        "gamma_r=1.06:gamma_g=1.01:gamma_b=0.92,vignette=PI/7"
    ),
    "beam-aesthetic": (
        "eq=contrast=1.12:brightness=-0.02:saturation=1.35:"
        "gamma_r=1.25:gamma_g=0.95:gamma_b=0.85,vignette=PI/3"
    ),
    # Golden Sepia Analog — TikTok "Setinggi Angkasa" style
    # Warm amber/golden shadows, strong contrast, heavy grain, very dark vignette
    "golden-analog": (
        "eq=contrast=1.22:brightness=-0.04:saturation=0.95:"
        "gamma_r=1.30:gamma_g=1.08:gamma_b=0.68,vignette=PI/2.2"
    ),
    # My Kisah — Kodak Gold / vintage scrapbook
    # Highlights cream-kuning, midtones amber, shadows coklat-hitam kehijauan
    # Referensi: LUT Kodak Gold 200 emulation
    "my-kisah": (
        "eq=contrast=1.18:brightness=-0.03:saturation=1.05:"
        "gamma_r=1.28:gamma_g=1.10:gamma_b=0.72,vignette=PI/2.5"
    ),
}

DEFAULTS = {
    "duration_per_photo": 2.5,
    "fade": 0.6,
    "zoom": 1.1,
    "look": "warm-rose",
    "size": "1080x1920",
    "overlay": None,
    "music": None,
}


def _parse_size(size: str) -> tuple[int, int]:
    width, height = size.lower().split("x")
    return int(width), int(height)


def load_preset(preset_id: str) -> dict:
    # [FIX #4] Validasi preset_id — cegah path traversal seperti "../../../etc/passwd"
    if not _PRESET_ID_RE.match(preset_id):
        raise ValueError(f"Preset ID tidak valid: '{preset_id}'.")

    path = PRESET_DIR / f"{preset_id}.json"

    # Double-check: pastikan path masih di dalam PRESET_DIR setelah resolve
    try:
        path.resolve().relative_to(PRESET_DIR.resolve())
    except ValueError:
        logger.warning("Path traversal attempt pada preset_id: %s", preset_id)
        raise FileNotFoundError(f"Preset '{preset_id}' tidak ditemukan.")

    if not path.exists():
        raise FileNotFoundError(f"Preset '{preset_id}' tidak ditemukan di folder presets.")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    preset = {**DEFAULTS, **data, "id": preset_id}
    width, height = _parse_size(preset["size"])
    if width % 2 or height % 2:
        raise ValueError("Ukuran preset harus genap, contoh 1080x1920.")

    fade = float(preset["fade"])
    duration = float(preset["duration_per_photo"])
    if fade >= duration:
        raise ValueError("Nilai fade harus lebih kecil dari duration_per_photo.")

    preset["width"] = width
    preset["height"] = height
    preset["color_filter"] = LOOKS.get(preset["look"], LOOKS["warm-rose"])

    if preset["overlay"]:
        overlay_path = PRESET_DIR / preset["overlay"]
        preset["overlay_path"] = overlay_path if overlay_path.exists() else None
    else:
        preset["overlay_path"] = None

    if preset["music"]:
        music_path = PRESET_DIR / preset["music"]
        preset["music_path"] = music_path if music_path.exists() else None
    else:
        preset["music_path"] = None

    return preset


def list_preset_summaries() -> list[dict]:
    summaries = []
    for path in sorted(PRESET_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        preset = {**DEFAULTS, **data, "id": path.stem}
        summaries.append(
            {
                "id": preset["id"],
                "name": preset.get("name", path.stem),
                "description": preset.get("description", ""),
                "duration_per_photo": preset["duration_per_photo"],
                "size": preset["size"],
            }
        )
    return summaries
