"""
Generación de video — Pipeline ultra-simple.
1. Cada imagen → clip 1080x1350 con fondo desenfocado + fade
2. Clips → concat con transición fade
3. Sin overlays de texto (fase 1)
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

VW, VH  = 1080, 1350
FPS     = 25
DUR_PER = 3.0
FADE    = 0.5          # fade in/out por clip (segundos)


# ── Utilidades básicas ────────────────────────────────────────────────────────

def ffmpeg_available() -> bool:
    if shutil.which("ffmpeg"):
        return True
    for p in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg"]:
        if os.path.exists(p):
            return True
    return False


def _ffmpeg_bin() -> str:
    w = shutil.which("ffmpeg")
    if w:
        return w
    for p in ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg"]:
        if os.path.exists(p):
            return p
    return "ffmpeg"


def _to_jpeg(src_path: str) -> str:
    """Convierte cualquier imagen (WebP, AVIF, PNG) a JPEG limpio."""
    out = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.jpg")
    try:
        r = subprocess.run(
            [_ffmpeg_bin(), "-y", "-i", src_path,
             "-frames:v", "1", "-q:v", "2",
             "-map_metadata", "-1",   # elimina ICC Profile del contenedor JPEG
             out],
            capture_output=True, timeout=30
        )
        if r.returncode == 0 and os.path.getsize(out) > 500:
            return out
    except Exception:
        pass
    try:
        from PIL import Image
        Image.open(src_path).convert("RGB").save(out, "JPEG", quality=92)
        if os.path.getsize(out) > 500:
            return out
    except Exception:
        pass
    return src_path


def _download(src: str, timeout: int = 20) -> str:
    if src.startswith(("http://", "https://")):
        ext = Path(src.split("?")[0]).suffix or ".jpg"
        raw = Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}{ext}"
        req = urllib.request.Request(src, headers={"User-Agent": "ListaPro/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with open(str(raw), "wb") as f:
                f.write(resp.read())
        return _to_jpeg(str(raw))
    if src.startswith(("/uploads/", "/tmp/")):
        candidate = Path(__file__).parent / src.lstrip("/")
        if candidate.exists():
            return _to_jpeg(str(candidate))
    return src


def _font() -> str:
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        if os.path.exists(p):
            return p
    return ""


def _esc(text: str) -> str:
    return (str(text)
        .replace("\\", "\\\\").replace("'", "\\'")
        .replace(":", "\\:").replace(",", "\\,")
        .replace("[", "\\[").replace("]", "\\]")
    )


# ── Paso 1: cada imagen → clip MP4 ───────────────────────────────────────────

def _make_clip(jpeg_path: str, idx: int, dur: float = DUR_PER) -> str:
    """
    JPEG → clip MP4 1080x1350 con fondo desenfocado.

    Técnica blurred background:
      [bg] = imagen escalada para LLENAR 1080x1350 + recortada + boxblur
      [fg] = imagen escalada para CABER dentro de 1080x1350 (sin recortar)
      overlay centra [fg] sobre [bg]

    Fade in 0.5s al inicio, fade out 0.5s al final.
    Sin color space flags: -map_metadata -1 elimina ICC Profile.
    """
    out          = str(Path(tempfile.mkdtemp()) / f"clip_{idx}.mp4")
    fade_out_st  = round(dur - FADE, 2)

    fc = (
        # Dividir fuente en dos streams
        "[0:v]split=2[bg_src][fg_src];"

        # Background: llena el frame y desenfoca
        f"[bg_src]"
        f"scale={VW}:{VH}:force_original_aspect_ratio=increase,"
        f"crop={VW}:{VH},"
        f"boxblur=25:4"
        f"[bg];"

        # Foreground: cabe dentro del frame sin recortar (puede tener barras negras)
        f"[fg_src]"
        f"scale={VW}:{VH}:force_original_aspect_ratio=decrease"
        f"[fg];"

        # Composite: fg centrado sobre bg
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"

        # Fade in y fade out
        f"fade=t=in:st=0:d={FADE:.2f},"
        f"fade=t=out:st={fade_out_st:.2f}:d={FADE:.2f}"
        f"[out]"
    )

    cmd = [
        _ffmpeg_bin(), "-y",
        "-loop", "1", "-i", jpeg_path,
        "-filter_complex", fc,
        "-map", "[out]",
        "-t", str(dur),
        "-r", str(FPS),
        "-map_metadata", "-1",
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level:v", "4.2",
        "-preset", "ultrafast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        # filter_units elimina NAL type 6 (SEI) que contiene el ICC Profile
        # del bitstream h264. Sin esto, el concat demuxer falla con frame=0
        # porque h264_mp4toannexb no puede procesar el SEI corrupto.
        "-bsf:v", "filter_units=remove_types=6",
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(
            f"Clip {idx} error:\n{r.stderr.decode('utf-8', errors='replace')[-600:]}"
        )
    log.info("Clip %d generado OK", idx)
    return out


# ── Paso 2: concat clips con fade ────────────────────────────────────────────

def generate_slideshow(
    photo_sources: List[str],
    nombre: str,
    telefono: str,
    specs: dict,
    dur_per: float = DUR_PER,
    fade: float = FADE,
) -> str:
    """
    Pipeline mínimo:
      1. Descarga y convierte fotos a JPEG
      2. Crea un clip por foto (_make_clip)
      3. Une los clips con concat demuxer (sin overlay de texto)
      4. Retorna el MP4 final

    Los fades baked en cada clip crean la transición fade-to-black entre fotos.
    """
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no disponible en este servidor.")

    # 1. Descargar y convertir fotos
    jpegs: List[str] = []
    for src in photo_sources[:6]:
        try:
            jpegs.append(_download(src))
            log.info("Foto %d/%d OK", len(jpegs), min(len(photo_sources), 6))
        except Exception as e:
            log.warning("Foto omitida %s: %s", src, e)

    if not jpegs:
        raise ValueError("No se pudo obtener ninguna foto.")

    n = len(jpegs)

    # 2. Crear un clip por foto
    clips: List[str] = []
    for i, jp in enumerate(jpegs):
        clips.append(_make_clip(jp, i, dur_per))

    # 3. Unir clips con concat demuxer
    concat_txt = str(Path(tempfile.mkdtemp()) / "playlist.txt")
    with open(concat_txt, "w") as f:
        for clip in clips:
            f.write(f"file '{clip}'\n")

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")

    cmd = [
        _ffmpeg_bin(), "-y",
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-map_metadata", "-1",
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level:v", "4.2",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ]

    log.info("Ensamblando %d clips → %s", n, output)
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(
            f"FFmpeg concat error:\n{r.stderr.decode('utf-8', errors='replace')[-800:]}"
        )
    return output


# ── Plan A: overlays sobre video del usuario ─────────────────────────────────

def add_overlays(
    video_source: str,
    nombre: str,
    telefono: str,
    specs: dict,
) -> str:
    """Reencuadra el video del usuario a 1080x1350 con blurred background."""
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no disponible.")

    local_in = _download(video_source)
    dur = 30.0
    try:
        probe = subprocess.run(
            [_ffmpeg_bin().replace("ffmpeg", "ffprobe"),
             "-v", "quiet", "-print_format", "json", "-show_streams", local_in],
            capture_output=True, text=True, timeout=30,
        )
        info = json.loads(probe.stdout)
        for s in info.get("streams", []):
            if s.get("codec_type") == "video":
                dur = float(s.get("duration", 30.0))
                break
    except Exception:
        pass

    fc = (
        "[0:v]split=2[bg_src][fg_src];"
        f"[bg_src]scale={VW}:{VH}:force_original_aspect_ratio=increase,"
        f"crop={VW}:{VH},boxblur=25:4[bg];"
        f"[fg_src]scale={VW}:{VH}:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[out]"
    )

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        _ffmpeg_bin(), "-y", "-i", local_in,
        "-filter_complex", fc,
        "-map", "[out]",
        "-map", "0:a?",
        "-map_metadata", "-1",
        "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2",
        "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(
            f"FFmpeg overlay error:\n{r.stderr.decode('utf-8', errors='replace')[-600:]}"
        )
    return output


# ── Cloudinary ────────────────────────────────────────────────────────────────

def upload_video(video_path: str) -> Optional[str]:
    if not os.getenv("CLOUDINARY_URL"):
        return None
    try:
        import cloudinary, cloudinary.uploader
        cloudinary.config(cloudinary_url=os.getenv("CLOUDINARY_URL"))
        result = cloudinary.uploader.upload(
            video_path, resource_type="video",
            folder="listapro/videos", public_id=str(uuid.uuid4()),
        )
        return result["secure_url"]
    except Exception as e:
        log.error("Error Cloudinary: %s", e)
        return None
