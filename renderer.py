import shutil
import subprocess
from pathlib import Path

from presets_lib import load_preset


class RenderError(Exception):
    pass


def _prepare_clip(index: int, width: int, height: int, frames: int, zoom: float) -> str:
    # Zoom lebih smooth
    zoom_step = max((zoom - 1.0) / max(frames - 1, 1), 0.0002)
    # trim=end_frame memastikan zoompan tidak melebihi jumlah frame yang diinginkan
    # (bug umum FFmpeg: zoompan bisa generate lebih dari d frame jika input fps berbeda)
    return (
        f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps=30,"
        f"zoompan=z='min(zoom+{zoom_step:.6f},{zoom})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps=30,"
        f"trim=end_frame={frames},setpts=PTS-STARTPTS,"
        f"format=yuv420p[v{index}]"
    )


def render_slideshow(photo_paths: list[str], output_path: Path, preset_id: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RenderError(
            "FFmpeg belum terpasang. Install FFmpeg lalu jalankan ulang backend."
        )
    if not photo_paths:
        raise RenderError("Tidak ada foto untuk dirender.")

    try:
        preset = load_preset(preset_id)
    except (OSError, ValueError, FileNotFoundError) as exc:
        raise RenderError(str(exc)) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    width = preset["width"]
    height = preset["height"]
    duration = float(preset["duration_per_photo"])
    fade = float(preset["fade"])
    frames = max(int(duration * 30), 15)
    n = len(photo_paths)

    command = [ffmpeg, "-y"]
    for photo_path in photo_paths:
        command.extend(["-loop", "1", "-t", str(duration), "-i", str(photo_path)])

    audio_index = None
    if preset.get("music_path"):
        audio_index = n
        command.extend(["-i", str(preset["music_path"])])

    overlay_index = None
    if preset.get("overlay_path"):
        overlay_index = n if audio_index is None else n + 1
        command.extend(["-loop", "1", "-i", str(preset["overlay_path"])])

    filters = [
        _prepare_clip(index, width, height, frames, float(preset["zoom"]))
        for index in range(n)
    ]

    if n == 1 or fade <= 0:
        current = "v0"
        if n > 1:
            concat_inputs = "".join(f"[v{index}]" for index in range(n))
            filters.append(f"{concat_inputs}concat=n={n}:v=1:a=0[joined]")
            current = "joined"
    else:
        current = "v0"
        offset = duration - fade
        # Pilih jenis transisi berdasarkan preset
        xfade_transition = preset.get("transition", "fade")
        for index in range(1, n):
            nxt = f"x{index}"
            filters.append(
                f"[{current}][v{index}]xfade=transition={xfade_transition}:duration={fade}:offset={offset:.3f}[{nxt}]"
            )
            current = nxt
            offset += duration - fade

    # Color Grading & Aesthetic Effects
    # Tambahkan grain dan light leak sintetis jika look adalah beam-aesthetic
    if preset["look"] == "beam-aesthetic":
        # Efek Grain + Warm Glow + Color Correction
        filters.append(
            f"[{current}]noise=alls=12:allf=t+p,"
            f"eq=contrast=1.15:brightness=-0.02:saturation=1.4:gamma_r=1.2:gamma_g=0.9:gamma_b=0.8,"
            f"vignette=PI/3[graded]"
        )
    elif preset["look"] == "golden-analog":
        # Efek Golden Sepia Analog: grain kuat + color grading warm amber
        # Grain sintetis film lama (strength 18, temporal+perlin)
        filters.append(
            f"[{current}]noise=alls=18:allf=t+p,"
            f"eq=contrast=1.22:brightness=-0.04:saturation=0.95:"
            f"gamma_r=1.30:gamma_g=1.08:gamma_b=0.68,"
            f"vignette=PI/2.2[graded]"
        )
    elif preset["look"] == "my-kisah":
        # Kodak Gold vintage scrapbook: grain sedang + letterbox hitam + warm color
        bar_h = int(height * 0.075)   # ~7.5% tinggi frame untuk cinematic bar
        filters.append(
            f"[{current}]noise=alls=14:allf=t+p,"
            f"eq=contrast=1.18:brightness=-0.03:saturation=1.05:"
            f"gamma_r=1.28:gamma_g=1.10:gamma_b=0.72,"
            f"vignette=PI/2.5,"
            # Letterbox hitam atas-bawah (cinematic bars)
            f"drawbox=x=0:y=0:w=iw:h={bar_h}:color=black@1.0:t=fill,"
            f"drawbox=x=0:y=ih-{bar_h}:w=iw:h={bar_h}:color=black@1.0:t=fill"
            f"[graded]"
        )
    else:
        filters.append(f"[{current}]{preset['color_filter']}[graded]")
    
    current = "graded"

    # Typography / Lyrics Overlay
    if preset.get("lyrics"):
        # Menggunakan path relatif tanpa colon (:) agar aman dari parser FFmpeg di Windows
        font_path = "assets/BRUSHSCI.TTF"
        # Warna teks disesuaikan dengan look preset
        if preset["look"] == "golden-analog":
            # Merah tua / maroon seperti di video asli
            default_color = "0x8B1A1A"
            default_shadow = "black@0.5"
            default_fontsize = 72
            default_y_offset = -80
        elif preset["look"] == "my-kisah":
            # Default untuk my-kisah: brush bold, warna oranye-merah
            default_color = "0xCC4400"
            default_shadow = "black@0.4"
            default_fontsize = 80
            default_y_offset = 0
        else:
            default_color = "white"
            default_shadow = "black@0.6"
            default_fontsize = 90
            default_y_offset = -120

        for i, lyric in enumerate(preset["lyrics"]):
            # Escaping sederhana untuk FFmpeg drawtext
            text = lyric["text"].replace("'", "\\'").replace(":", "\\:")
            start = lyric["start"]
            end = lyric["end"]
            # Animasi fade in/out untuk teks (durasi fade 0.5s)
            fade_in  = lyric.get("fade_in", 0.5)
            fade_out = lyric.get("fade_out", 0.5)
            fade_expr = (
                f"if(between(t,{start},{end}),"
                f"min(min(t-{start},{fade_in})/{fade_in},"
                f"min({end}-t,{fade_out})/{fade_out}),0)"
            )

            # Override per-lyric jika ada (my-kisah mendukung ini)
            color     = lyric.get("color",    default_color)
            shadow    = lyric.get("shadow",   default_shadow)
            fontsize  = lyric.get("fontsize", default_fontsize)
            # x/y bisa berupa ekspresi FFmpeg string atau offset integer
            lx = lyric.get("x", "(w-text_w)/2")
            # y: jika integer/float → offset dari tengah, jika string → ekspresi langsung
            raw_y = lyric.get("y", default_y_offset)
            if isinstance(raw_y, str):
                ly = raw_y
            else:
                ly = f"(h-text_h)/2{raw_y:+d}"

            filters.append(
                f"[{current}]drawtext=fontfile={font_path}:text='{text}':"
                f"fontsize={fontsize}:fontcolor={color}:x={lx}:y={ly}:"
                f"alpha='{fade_expr}':shadowcolor={shadow}:shadowx=2:shadowy=2[txt{i}]"
            )
            current = f"txt{i}"

    mapped_video = current

    if overlay_index is not None:
        filters.append(
            f"[{overlay_index}:v]scale={width}:{height},format=rgba,colorchannelmixer=aa=0.45[ov];"
            f"[{current}][ov]overlay=0:0:shortest=1[overlaid]"
        )
        mapped_video = "overlaid"


    command.extend(["-filter_complex", ";".join(filters), "-map", f"[{mapped_video}]"])
    if audio_index is not None:
        command.extend(["-map", f"{audio_index}:a", "-shortest", "-c:a", "aac"])
    else:
        command.extend(["-an"])

    command.extend(
        [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )

    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg gagal").strip()
        raise RenderError(detail[-800:])
    if not output_path.exists():
        raise RenderError("Render selesai tapi file video tidak ditemukan.")
