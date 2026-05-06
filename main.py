from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import subprocess, tempfile, os, uuid, re

app = FastAPI(title="Studio Dr. Guzmán — Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

WATERMARK = "Dr. Guzmán · Tijuana"
MAX_MB = 500


def clean_text(text: str, max_chars: int = 60) -> str:
    """Limpia el texto para usarlo en FFmpeg drawtext."""
    text = text[:max_chars]
    text = re.sub(r"['\"\[\]{}\\%]", "", text)
    text = text.replace(":", " ").replace(",", " ").replace("\n", " ")
    return text.strip()


def wrap_text(text: str, max_chars: int = 30) -> str:
    """Parte el texto en líneas para subtítulos."""
    words = text.split()
    lines, line = [], []
    for w in words:
        line.append(w)
        if len(" ".join(line)) >= max_chars:
            lines.append(" ".join(line))
            line = []
    if line:
        lines.append(" ".join(line))
    return r"\n".join(lines[:4])  # máximo 4 líneas


@app.get("/")
def root():
    return {"status": "ok", "mensaje": "Studio Dr. Guzmán Backend activo 🎬"}


@app.get("/health")
def health():
    # Verifica que FFmpeg esté instalado
    result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    ffmpeg_ok = result.returncode == 0
    return {"status": "ok", "ffmpeg": ffmpeg_ok}


@app.post("/process")
async def process_video(
    video: UploadFile = File(...),
    hook: str = Form(""),
    watermark_name: str = Form(WATERMARK),
    platform: str = Form("tiktok"),       # tiktok | instagram | both
    add_subtitles: str = Form("true"),
    add_watermark: str = Form("true"),
):
    # ── Validar tamaño ────────────────────────────────────────────
    content = await video.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_MB:
        raise HTTPException(400, f"El video pesa {size_mb:.0f} MB. Máximo: {MAX_MB} MB.")

    job_id = str(uuid.uuid4())[:8]
    tmp = tempfile.mkdtemp()
    input_path  = os.path.join(tmp, f"in_{job_id}.mp4")
    output_path = os.path.join(tmp, f"out_{job_id}.mp4")

    with open(input_path, "wb") as f:
        f.write(content)

    # ── Dimensiones por plataforma ────────────────────────────────
    W, H = 1080, 1920  # 9:16 vertical (TikTok + Reels)

    # ── Construir filtros de video ────────────────────────────────
    filters = [
        f"scale={W}:{H}:force_original_aspect_ratio=increase",
        f"crop={W}:{H}",
    ]

    if add_subtitles == "true" and hook.strip():
        hook_clean = clean_text(hook, 70)
        hook_wrapped = wrap_text(hook_clean, 28)
        filters.append(
            f"drawtext=text='{hook_wrapped}':"
            f"fontsize=54:fontcolor=white:x=(w-text_w)/2:y=120:"
            f"box=1:boxcolor=black@0.55:boxborderw=14:"
            f"line_spacing=10:shadowcolor=black:shadowx=2:shadowy=2"
        )

    if add_watermark == "true":
        wm = clean_text(watermark_name, 40)
        filters.append(
            f"drawtext=text='{wm}':"
            f"fontsize=34:fontcolor=white:x=(w-text_w)/2:y=h-90:"
            f"box=1:boxcolor=black@0.45:boxborderw=10:"
            f"shadowcolor=black:shadowx=1:shadowy=1"
        )

    vf = ",".join(filters)

    # ── Ejecutar FFmpeg ───────────────────────────────────────────
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-t", "180",          # máximo 3 min
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        # Devuelve el error de FFmpeg para diagnóstico
        raise HTTPException(500, f"Error al procesar el video: {result.stderr[-800:]}")

    if not os.path.exists(output_path):
        raise HTTPException(500, "El video procesado no se generó correctamente.")

    filename = f"studio_{platform}_{job_id}.mp4"
    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename=filename,
        headers={"X-Job-Id": job_id}
    )
