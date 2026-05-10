"""
Generación de video con FFmpeg.
Plan A: usuario sube video propio → agregarle overlays.
Plan B: generar slideshow Ken Burns + crossfade desde las fotos.
Sube el resultado a Cloudinary y devuelve la URL.
"""
import json
import logging
import os
import shutil
import subprocess
import tempfile
import urllib.request
import uuid
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

# 720p — óptimo para web: carga rápida, buena calidad
VW, VH = 1280, 720
FPS     = 30
DUR_PER = 3.0   # segundos por foto (el usuario pidió 3s)
FADE    = 0.6   # duración del crossfade entre fotos

# Patrones Ken Burns (crop+pan, mucho más rápido que zoompan)
# (scale_w, scale_h, x_expr, y_expr) — crop final siempre VW×VH
_MOVES = [
    (VW + 160, VH + 90,  "160*t/{d}",        "(90)/2"),            # ← →
    (VW + 160, VH + 90,  "160*(1-t/{d})",     "(90)/2"),            # → ←
    (VW,       VH + 90,  "0",                 "90*t/{d}"),           # ↓
    (VW,       VH + 90,  "0",                 "90*(1-t/{d})"),       # ↑
]


# ─── Utilidades ───────────────────────────────────────────────────────────────

def ffmpeg_available() -> bool:
    """True si ffmpeg está instalado y accesible."""
    # Primero buscar en PATH
    if shutil.which("ffmpeg"):
        return True
    # Rutas absolutas comunes en Linux (Railway/Docker)
    for p in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg"]:
        if os.path.exists(p):
            return True
    return False


def _ffmpeg_bin() -> str:
    """Retorna la ruta al binario de FFmpeg."""
    w = shutil.which("ffmpeg")
    if w:
        return w
    for p in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg"]:
        if os.path.exists(p):
            return p
    return "ffmpeg"


def _to_jpeg(src_path: str) -> str:
    """
    Convierte cualquier imagen a JPEG limpio usando FFmpeg como primer intento.
    FFmpeg lee WebP correctamente (ignora EXIF inválido) y produce JPEG sin problemas.
    Pillow como fallback por si acaso.
    """
    out = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.jpg")

    # Intento 1: FFmpeg (más robusto con WebP/EXIF inválido de Cloudinary)
    try:
        r = subprocess.run(
            [_ffmpeg_bin(), "-y", "-i", src_path,
             "-frames:v", "1", "-q:v", "2", out],
            capture_output=True, timeout=30
        )
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 500:
            return out
    except Exception:
        pass

    # Intento 2: Pillow
    try:
        from PIL import Image
        Image.open(src_path).convert("RGB").save(out, "JPEG", quality=92)
        if os.path.exists(out) and os.path.getsize(out) > 500:
            return out
    except Exception:
        pass

    return src_path  # último recurso: original


def _download(src: str, timeout: int = 20) -> str:
    """Descarga URL → JPEG temporal. Ruta local → convierte a JPEG si es necesario."""
    if src.startswith("http://") or src.startswith("https://"):
        ext = Path(src.split("?")[0]).suffix or ".jpg"
        raw = Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}{ext}"
        req = urllib.request.Request(src, headers={"User-Agent": "ListaPro/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with open(str(raw), "wb") as f:
                f.write(resp.read())
        # Convertir a JPEG puro: evita problemas de FFmpeg con WebP/EXIF de Cloudinary
        return _to_jpeg(str(raw))
    if src.startswith("/uploads/") or src.startswith("/tmp/"):
        candidate = Path(__file__).parent / src.lstrip("/")
        if candidate.exists():
            return _to_jpeg(str(candidate))
    return src


def _font() -> str:
    """Retorna una fuente disponible en el sistema."""
    candidates = [
        # Linux (Railway/Docker con fonts-dejavu-core)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        # Windows (desarrollo local)
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # Intentar con fc-list (Linux)
    try:
        out = subprocess.run(
            ["fc-list", ":style=Bold", "--format=%{file}\n"],
            capture_output=True, text=True, timeout=3
        ).stdout.strip().splitlines()
        for line in out:
            if line.strip() and os.path.exists(line.strip()):
                return line.strip()
    except Exception:
        pass
    return ""


def _esc(text: str) -> str:
    """Escapa caracteres especiales para filtros drawtext de FFmpeg."""
    return (text
        .replace("\\", "\\\\").replace("'", "\\'")
        .replace(":", "\\:").replace(",", "\\,")
        .replace("[", "\\[").replace("]", "\\]")
    )


def _overlay_vf(nombre: str, telefono: str, specs: dict, dur: float) -> str:
    """Retorna la cadena de filtros vf para overlays de texto."""
    font = _font()
    fp   = f":fontfile='{font}'" if font else ""

    parts_spec = [s for s in [
        f"{specs.get('metros','')} m²"        if specs.get("metros")       else "",
        f"{specs.get('habitaciones','')} hab." if specs.get("habitaciones") else "",
        f"{specs.get('banos','')} baños"       if specs.get("banos")        else "",
    ] if s]
    spec_str = " · ".join(parts_spec)
    show     = min(4.0, dur - 0.5)

    fv = [
        "drawbox=y=ih-70:color=black@0.72:width=iw:height=70:t=fill",
        f"drawtext=text='{_esc(nombre)}':fontsize=26{fp}:fontcolor=white:x=(w-tw)/2:y=h-55",
        f"drawtext=text='{_esc(telefono)}':fontsize=19{fp}:fontcolor=#25D366:x=(w-tw)/2:y=h-28",
    ]
    if spec_str and dur > 1:
        fv.append(
            f"drawtext=text='{_esc(spec_str)}':fontsize=26{fp}:fontcolor=white"
            f":x=30:y=30:box=1:boxcolor=black@0.55:boxborderw=8"
            f":enable='between(t,0.3,{show:.1f})'"
        )
    return ",".join(fv)


# ─── Slideshow (Plan B) ───────────────────────────────────────────────────────

def _make_clip(img_path: str, idx: int, dur: float) -> str:
    """
    Convierte una imagen JPEG a un clip MP4 de duración exacta con efecto Ken Burns.
    Usar clips MP4 como entrada del xfade es mucho más estable que -loop 1 en filter_complex.
    """
    out = str(Path(tempfile.mkdtemp()) / f"clip_{idx}.mp4")
    SW, SH = int(VW * 1.10), int(VH * 1.10)
    x = [0, SW - VW, 0, SW - VW][idx % 4]
    y = [0, 0, SH - VH, SH - VH][idx % 4]
    vf = (
        f"scale={SW}:{SH}:force_original_aspect_ratio=increase,"
        f"crop={SW}:{SH},"
        f"crop={VW}:{VH}:x={x}:y={y}"
    )
    cmd = [
        _ffmpeg_bin(), "-y",
        "-loop", "1", "-i", img_path,
        "-vf", vf,
        "-t", str(dur),
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-color_range", "tv",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(
            f"Error clip {idx}:\n{r.stderr.decode('utf-8', errors='replace')[-400:]}"
        )
    return out


def generate_slideshow(
    photo_sources: List[str],
    nombre: str,
    telefono: str,
    specs: dict,
    dur_per: float = DUR_PER,
    fade: float = FADE,
) -> str:
    """Crea slideshow 720p Ken Burns + crossfade + overlays. Devuelve ruta MP4."""
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no está instalado en este servidor.")

    locals_: List[str] = []
    for src in photo_sources[:6]:
        try:
            locals_.append(_download(src))
            log.info("Foto %d/%d descargada", len(locals_), min(len(photo_sources), 6))
        except Exception as e:
            log.warning("Foto no disponible %s: %s", src, e)

    if not locals_:
        raise ValueError("No se pudo descargar ninguna foto.")

    n     = len(locals_)
    total = n * dur_per  # concat: sin overlap entre clips

    # Paso 1: Cada imagen → clip MP4 individual (Ken Burns, PTS limpio)
    clips = []
    for i, lp in enumerate(locals_):
        clip = _make_clip(lp, i, dur_per)
        clips.append(clip)
        log.info("Clip %d/%d generado", i + 1, n)

    # Paso 2: Inputs
    inputs = []
    for clip in clips:
        inputs += ["-i", clip]

    # Paso 3: filter_complex con concat (robusto, sin bugs de PTS que tiene xfade)
    ov = _overlay_vf(nombre, telefono, specs, total)

    if n == 1:
        filter_complex = f"[0:v]{ov}[final]"
    else:
        concat_in = "".join(f"[{i}:v]" for i in range(n))
        filter_complex = f"{concat_in}concat=n={n}:v=1:a=0[vout];[vout]{ov}[final]"

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        _ffmpeg_bin(), "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[final]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ]
    log.info("Generando slideshow %dp para %d fotos (%.0fs)...", VH, n, total)
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(
            f"FFmpeg slideshow error:\n{r.stderr.decode('utf-8', errors='replace')[-800:]}"
        )
    return output


# ─── Overlays sobre video existente (Plan A) ─────────────────────────────────

def add_overlays(
    video_source: str,
    nombre: str,
    telefono: str,
    specs: dict,
) -> str:
    """Añade overlays a video del usuario. Devuelve ruta MP4 resultante."""
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no está instalado en este servidor.")

    local_in = _download(video_source)
    dur = 30.0
    try:
        probe = subprocess.run(
            [_ffmpeg_bin().replace("ffmpeg", "ffprobe"), "-v", "quiet",
             "-print_format", "json", "-show_streams", local_in],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(probe.stdout)
        for s in info.get("streams", []):
            if s.get("codec_type") == "video":
                dur = float(s.get("duration", 30.0))
                break
    except Exception:
        pass

    ov  = _overlay_vf(nombre, telefono, specs, dur)
    vf  = (f"scale={VW}:{VH}:force_original_aspect_ratio=decrease,"
           f"pad={VW}:{VH}:(ow-iw)/2:(oh-ih)/2,{ov}")

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        _ffmpeg_bin(), "-y", "-i", local_in,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(
            f"FFmpeg overlay error:\n{r.stderr.decode('utf-8', errors='replace')[-600:]}"
        )
    return output


# ─── Upload a Cloudinary ──────────────────────────────────────────────────────

def upload_video(video_path: str) -> Optional[str]:
    """Sube video a Cloudinary. Devuelve URL pública o None si no hay Cloudinary."""
    if not os.getenv("CLOUDINARY_URL"):
        return None
    try:
        import cloudinary, cloudinary.uploader
        cloudinary.config(cloudinary_url=os.getenv("CLOUDINARY_URL"))
        result = cloudinary.uploader.upload(
            video_path,
            resource_type="video",
            folder="listapro/videos",
            public_id=str(uuid.uuid4()),
        )
        return result["secure_url"]
    except Exception as e:
        log.error("Error subiendo video a Cloudinary: %s", e)
        return None
