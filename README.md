# Kenangan Kita — Video Generator

Aplikasi web untuk membuat video slideshow romantis dari foto-foto kenangan.

## Cara Menjalankan

**Double-click `run-server.bat`**

Atau manual via terminal:

```powershell
cd backend/video-generator-backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Lalu buka browser ke: **http://localhost:8000**

## Instalasi Dependency

```powershell
pip install -r requirements.txt
```

FFmpeg juga harus terinstall dan tersedia di PATH.

## Struktur Project

```
video-generator-backend/
├── main.py              # Entry point FastAPI
├── renderer.py          # FFmpeg render engine
├── presets_lib.py       # Loader & definisi preset
├── database.py          # SQLite job tracking
├── requirements.txt
├── run-server.bat       # Shortcut jalankan server
├── assets/
│   └── BRUSHSCI.TTF     # Font brush untuk teks lirik
├── presets/
│   ├── my-kisah.json    # Preset "My Kisah"
│   └── beam-music.mp3
├── frontend/
│   ├── index.html
│   └── assets/
│       ├── app.js
│       └── styles.css
└── storage/
    ├── app.db
    ├── uploads/         # Foto yang diupload user
    └── outputs/         # Video hasil render
```

## Alur Penggunaan

1. Upload 6 foto kenangan
2. Pilih template **My Kisah**
3. Klik "Buat Video" — tunggu render selesai
4. Download video hasil
