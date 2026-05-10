"""
video_utils.py — Pipeline mínimo y estable.
Sin textos, sin transiciones. Solo fotos → 4:5 con fondo desenfocado.

Causa raíz del frame=0 (resuelto aquí):
  Las fotos de Cloudinary vienen en WebP con ICC Profile corrupto.
  Ese ICC Profile sobrevive a -map_metadata y se incrusta en el
  bitstream h264 como SEI (NAL type 6), corrompiendo el concat.
  Fix: -bsf:v filter_units=remove_types=6 en cada clip.
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

VW, VH  = 1080, 1350   # 4:5
FPS     = 25
DUR_PER = 3.0


# ─── utilidades ───────────────────────────────────────────────────────────────

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


def _to_jpeg(src: str) -> str:
    """
    Descarga o lee src y lo convierte a JPEG sin ICC Profile.
    -map_metadata -1 elimina el ICC Profile del CONTENEDOR del JPEG.
    El JPEG resultante no tendrá APP2 marker, así que los frames
    decodificados no tendrán ICC Profile como side-data.
    """
    out = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.jpg")

    # si es URL, descarga primero
    raw = src
    if src.startswith(("http://", "https://")):
        raw = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.img")
        req = urllib.request.Request(src, headers={"User-Agent": "ListaPro/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            with open(raw, "wb") as f:
                f.write(r.read())
    elif src.startswith(("/uploads/", "/tmp/")):
        candidate = Path(__file__).parent / src.lstrip("/")
        if candidate.exists():
            raw = str(candidate)

    # convierte a JPEG limpio (sin ICC Profile)
    r = subprocess.run(
        [_ffmpeg_bin(), "-y", "-i", raw,
         "-frames:v", "1", "-q:v", "2",
         "-map_metadata", "-1",   # ← elimina ICC Profile del JPEG
         out],
        capture_output=True, timeout=30
    )
    if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
        return out

    # fallback: Pillow
    try:
        from PIL import Image
        Image.open(raw).convert("RGB").save(out, "JPEG", quality=90)
        return out
    except Exception:
        pass

    return raw   # último recurso


def _make_clip(jpeg: str, idx: int, dur: float = DUR_PER) -> str:
    """
    JPEG limpio → clip MP4 1080×1350.

    Técnica Blurred Background:
      [bg]  = imagen escalada para LLENAR el canvas + boxblur
      [fg]  = imagen escalada para CABER (sin recortar)
      overlay centra [fg] sobre [bg] desenfocado

    Clave anti-ICC: -bsf:v filter_units=remove_types=6
      Elimina los NAL units tipo 6 (SEI) del bitstream h264.
      El ICC Profile vive en el SEI; sin él, el concat funciona.
    """
    out = str(Path(tempfile.mkdtemp()) / f"clip_{idx}.mp4")

    # Blurred background filter_complex
    fc = (
        "[0:v]split=2[bg_src][fg_src];"
        f"[bg_src]scale={VW}:{VH}:force_original_aspect_ratio=increase,"
        f"crop={VW}:{VH},boxblur=20:2[bg];"
        f"[fg_src]scale={VW}:{VH}:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[out]"
    )

    cmd = [
        _ffmpeg_bin(), "-y",
        "-loop", "1", "-i", jpeg,
        "-filter_complex", fc,
        "-map", "[out]",
        "-t", str(dur),
        "-r", str(FPS),
        "-map_metadata", "-1",
        "-c:v", "libx264",
        "-profile:v", "high", "-level:v", "4.2",
        "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-bsf:v", "filter_units=remove_types=6",  # ← elimina SEI/ICC del h264
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        msg = r.stderr.decode("utf-8", errors="replace")[-600:]
        raise RuntimeError(f"Error clip {idx}:\n{msg}")

    # verificar que el clip no esté vacío
    size = os.path.getsize(out)
    if size < 1000:
        raise RuntimeError(f"Clip {idx} vacío ({size} bytes)")

    log.info("Clip %d OK (%d bytes)", idx, size)
    return out


def generate_slideshow(
    photo_sources: List[str],
    nombre: str = "",
    telefono: str = "",
    specs: dict = None,
    dur_per: float = DUR_PER,
    fade: float = 0,
) -> str:
    """
    Pipeline:
      1. Cada foto → JPEG limpio (sin ICC Profile)
      2. Cada JPEG  → clip MP4 con fondo desenfocado (sin ICC en bitstream)
      3. Clips      → concat con -c copy (+faststart)

    -c copy evita re-encodear, elimina posibles errores de codec,
    y no necesita h264_mp4toannexb porque es MP4→MP4.
    """
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no está instalado en este servidor.")

    specs = specs or {}

    # 1. Fotos → JPEG sin ICC Profile
    jpegs: List[str] = []
    for src in photo_sources[:6]:
        try:
            jpegs.append(_to_jpeg(src))
            log.info("Foto %d/%d convertida", len(jpegs), min(len(photo_sources), 6))
        except Exception as e:
            log.warning("Foto omitida (%s): %s", src, e)

    if not jpegs:
        raise ValueError("No se pudo obtener ninguna foto.")

    # 2. JPEG → clips
    clips: List[str] = []
    for i, jp in enumerate(jpegs):
        clips.append(_make_clip(jp, i, dur_per))

    # 3. Clips → video final con concat -c copy
    playlist = str(Path(tempfile.mkdtemp()) / "playlist.txt")
    with open(playlist, "w") as f:
        for clip in clips:
            f.write(f"file '{clip}'\n")

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        _ffmpeg_bin(), "-y",
        "-f", "concat", "-safe", "0", "-i", playlist,
        "-c", "copy",               # sin re-encodear
        "-movflags", "+faststart",  # carga instantánea en browser
        output,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        msg = r.stderr.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"Concat error:\n{msg}")

    size = os.path.getsize(output)
    if size < 1000:
        raise RuntimeError(f"Video final vacío ({size} bytes)")

    log.info("Slideshow OK: %d fotos, %d bytes → %s", len(clips), size, output)
    return output


# ─── Plan A: video del usuario ────────────────────────────────────────────────

def add_overlays(video_source: str, nombre: str, telefono: str, specs: dict) -> str:
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no disponible.")

    local_in = _to_jpeg(video_source) if video_source.endswith((".jpg", ".jpeg", ".png", ".webp")) else video_source

    # Si no es imagen, descargar como video
    if video_source.startswith(("http://", "https://")):
        raw = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
        req = urllib.request.Request(video_source, headers={"User-Agent": "ListaPro/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            with open(raw, "wb") as f:
                f.write(resp.read())
        local_in = raw

    dur = 30.0
    try:
        probe = subprocess.run(
            [_ffmpeg_bin().replace("ffmpeg", "ffprobe"), "-v", "quiet",
             "-print_format", "json", "-show_streams", local_in],
            capture_output=True, text=True, timeout=30,
        )
        for s in json.loads(probe.stdout).get("streams", []):
            if s.get("codec_type") == "video":
                dur = float(s.get("duration", 30.0))
                break
    except Exception:
        pass

    fc = (
        "[0:v]split=2[bg_src][fg_src];"
        f"[bg_src]scale={VW}:{VH}:force_original_aspect_ratio=increase,"
        f"crop={VW}:{VH},boxblur=20:2[bg];"
        f"[fg_src]scale={VW}:{VH}:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[out]"
    )

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    r = subprocess.run(
        [_ffmpeg_bin(), "-y", "-i", local_in,
         "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
         "-map_metadata", "-1",
         "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2",
         "-preset", "fast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k",
         "-pix_fmt", "yuv420p",
         "-bsf:v", "filter_units=remove_types=6",
         "-movflags", "+faststart", output],
        capture_output=True, timeout=300
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace")[-600:])
    return output


# ─── Cloudinary ───────────────────────────────────────────────────────────────

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
        log.error("Cloudinary: %s", e)
        return None
