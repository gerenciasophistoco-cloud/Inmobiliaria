"""
Generación de video con FFmpeg — Formato 4:5 Premium (1080×1350).
Pipeline probado con FFmpeg 7.x (Railway):
  Paso 1: _to_jpeg   → JPEG limpio (maneja WebP con EXIF corrupto)
  Paso 2: _make_clip → JPEG → clip MP4 1080×1350 con color space bt709/tv
  Paso 3: slideshow  → concat demuxer + -vf overlay (sin filter_complex)

REGLAS ABSOLUTAS de FFmpeg (causan frame=0 si se violan):
  drawtext  → usa 'w', 'h', 'tw'  (NUNCA iw/ih)
  drawbox   → usa 'iw', 'ih'      (válido)
  filter_complex con bt470bg/pc → rechazado en FFmpeg 7.x → usar concat demuxer
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

VW, VH  = 1080, 1350   # 4:5 vertical premium
FPS     = 25
DUR_PER = 3.0
_FADE   = 0.8


# ── Utilidades ────────────────────────────────────────────────────────────────

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
    """Convierte cualquier imagen a JPEG limpio (maneja WebP/AVIF con EXIF corrupto)."""
    out = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.jpg")
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
    try:
        from PIL import Image
        Image.open(src_path).convert("RGB").save(out, "JPEG", quality=92)
        if os.path.exists(out) and os.path.getsize(out) > 500:
            return out
    except Exception:
        pass
    return src_path


def _download(src: str, timeout: int = 20) -> str:
    if src.startswith("http://") or src.startswith("https://"):
        ext = Path(src.split("?")[0]).suffix or ".jpg"
        raw = Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}{ext}"
        req = urllib.request.Request(src, headers={"User-Agent": "ListaPro/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with open(str(raw), "wb") as f:
                f.write(resp.read())
        return _to_jpeg(str(raw))
    if src.startswith("/uploads/") or src.startswith("/tmp/"):
        candidate = Path(__file__).parent / src.lstrip("/")
        if candidate.exists():
            return _to_jpeg(str(candidate))
    return src


def _font() -> str:
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        if os.path.exists(p):
            return p
    try:
        lines = subprocess.run(
            ["fc-list", ":style=Bold", "--format=%{file}\n"],
            capture_output=True, text=True, timeout=3
        ).stdout.strip().splitlines()
        for line in lines:
            if line.strip() and os.path.exists(line.strip()):
                return line.strip()
    except Exception:
        pass
    return ""


def _esc(text: str) -> str:
    return (str(text)
        .replace("\\", "\\\\").replace("'", "\\'")
        .replace(":", "\\:").replace(",", "\\,")
        .replace("[", "\\[").replace("]", "\\]")
    )


# ── Overlay ───────────────────────────────────────────────────────────────────

def _overlay_vf(nombre: str, telefono: str, specs: dict, dur: float,
                n_photos: int = 1, dur_per: float = DUR_PER) -> str:
    """
    Overlay mínimo y probado para -vf (no filter_complex).
    Usa solo los filtros y parámetros que funcionaron antes.
    drawtext: w/h/tw (NUNCA iw/ih).  drawbox: iw/ih (válido).
    """
    font = _font()
    fp   = f":fontfile='{font}'" if font else ""
    fv   = []

    precio    = _esc(specs.get("precio", ""))
    ciudad    = _esc(specs.get("ciudad", ""))

    # Precio arriba derecha (fontcolor=white, sin hex que puede causar parsing issues)
    if precio:
        fv.append(
            f"drawtext=text='{precio}':fontsize=28{fp}"
            f":fontcolor=white:x=w-tw-20:y=24"
            f":box=1:boxcolor=black@0.55:boxborderw=8"
        )

    # Franja inferior (drawbox: iw/ih válidos aquí)
    STRIP_H = 130
    SY = VH - STRIP_H    # 1220 — entero absoluto

    fv.append(f"drawbox=y={SY}:color=black@0.72:width=iw:height={STRIP_H}:t=fill")

    # Nombre y teléfono centrados (misma fórmula que funcionó con 1280×720)
    fv.append(
        f"drawtext=text='{_esc(nombre)}':fontsize=26{fp}"
        f":fontcolor=white:x=(w-tw)/2:y=h-85"
    )
    fv.append(
        f"drawtext=text='{_esc(telefono)}':fontsize=22{fp}"
        f":fontcolor=white:x=(w-tw)/2:y=h-52"
    )

    # Ciudad izquierda
    if ciudad:
        fv.append(
            f"drawtext=text='{ciudad}':fontsize=22{fp}"
            f":fontcolor=white:x=20:y={SY + 15}"
        )

    # Specs rotativas (enable — probado que funciona en drawtext)
    data_items = []
    if specs.get("metros"):
        data_items.append(f"{specs['metros']}m2")
    if specs.get("habitaciones"):
        data_items.append(f"{specs['habitaciones']} Hab")
    if specs.get("banos"):
        data_items.append(f"{specs['banos']} Ban")
    if specs.get("estacionamientos"):
        data_items.append(f"{specs['estacionamientos']} Parq")

    for i in range(n_photos):
        if not data_items:
            break
        item = data_items[i % len(data_items)]
        t0, t1 = i * dur_per, (i + 1) * dur_per
        fv.append(
            f"drawtext=text='{_esc(item)}':fontsize=22{fp}"
            f":fontcolor=white:x=20:y={SY + 48}"
            f":enable='between(t,{t0:.1f},{t1:.1f})'"
        )

    return ",".join(fv)


# ── Creación de clips ─────────────────────────────────────────────────────────

def _make_clip(img_path: str, idx: int, dur: float) -> str:
    """
    JPEG → clip MP4 1080×1350 con color space bt709/tv.

    La clave: 'colorspace=all=bt709:range=tv' en el -vf convierte bt470bg/pc
    (color space de las imágenes de Cloudinary) a bt709/tv que libx264 acepta
    en FFmpeg 7.x sin producir frame=0.

    Ken Burns: escala 10% y recorta desde esquina diferente por clip.
    Fade in/out de 0.8s para transiciones suaves al concatenar.
    """
    out = str(Path(tempfile.mkdtemp()) / f"clip_{idx}.mp4")

    SW, SH = int(VW * 1.10), int(VH * 1.10)   # 1188 × 1485
    xs = [0, SW - VW, 0,       SW - VW]
    ys = [0, 0,       SH - VH, SH - VH]
    x, y = xs[idx % 4], ys[idx % 4]

    fade_dur       = min(_FADE, dur / 3.0)
    fade_out_start = round(dur - fade_dur, 2)

    # colorspace convierte bt470bg/pc → bt709/tv ANTES de codificar
    # Esto elimina el 'yuv420p(pc, bt470bg)' que causa frame=0 en FFmpeg 7.x
    vf = (
        f"scale={SW}:{SH}:force_original_aspect_ratio=increase,"
        f"crop={SW}:{SH},"
        f"crop={VW}:{VH}:x={x}:y={y},"
        f"colorspace=all=bt709:range=tv,"
        f"fade=t=in:st=0:d={fade_dur:.2f},"
        f"fade=t=out:st={fade_out_start:.2f}:d={fade_dur:.2f}"
    )

    cmd = [
        _ffmpeg_bin(), "-y",
        "-loop", "1", "-i", img_path,
        "-vf", vf,
        "-t", str(dur),
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(
            f"Error clip {idx}:\n{r.stderr.decode('utf-8', errors='replace')[-500:]}"
        )
    log.info("Clip %d OK → %s", idx, out)
    return out


# ── Slideshow principal ───────────────────────────────────────────────────────

def generate_slideshow(
    photo_sources: List[str],
    nombre: str,
    telefono: str,
    specs: dict,
    dur_per: float = DUR_PER,
    fade: float = _FADE,
) -> str:
    """
    Slideshow 4:5 con concat DEMUXER (no filter_complex).

    El concat DEMUXER es más robusto que el concat FILTER en FFmpeg 7.x:
    evita el frame=0 causado por bt470bg frames en filter_complex.
    El overlay se aplica con -vf sobre el stream concatenado.
    """
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no está instalado en este servidor.")

    locals_: List[str] = []
    for src in photo_sources[:6]:
        try:
            locals_.append(_download(src))
            log.info("Foto %d/%d OK", len(locals_), min(len(photo_sources), 6))
        except Exception as e:
            log.warning("Foto omitida %s: %s", src, e)

    if not locals_:
        raise ValueError("No se pudo descargar ninguna foto.")

    n = len(locals_)

    # Paso 1: cada imagen → clip MP4 bt709/tv (color space limpio)
    clips: List[str] = []
    for i, lp in enumerate(locals_):
        clips.append(_make_clip(lp, i, dur_per))

    ov     = _overlay_vf(nombre, telefono, specs,
                         n * dur_per, n_photos=n, dur_per=dur_per)
    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")

    if n == 1:
        # Un clip: entrada directa → -vf overlay → salida
        cmd = [
            _ffmpeg_bin(), "-y", "-i", clips[0],
            "-vf", ov,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output,
        ]
    else:
        # Múltiples clips: concat DEMUXER (evita filter_complex con bt470bg)
        concat_txt = str(Path(tempfile.mkdtemp()) / "concat.txt")
        with open(concat_txt, "w") as f:
            for clip in clips:
                f.write(f"file '{clip}'\n")

        cmd = [
            _ffmpeg_bin(), "-y",
            "-f", "concat", "-safe", "0", "-i", concat_txt,
            "-vf", ov,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output,
        ]

    log.info("Slideshow %d fotos → %s", n, output)
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(
            f"FFmpeg error:\n{r.stderr.decode('utf-8', errors='replace')[-800:]}"
        )
    return output


# ── Plan A: overlays sobre video del usuario ─────────────────────────────────

def add_overlays(
    video_source: str,
    nombre: str,
    telefono: str,
    specs: dict,
) -> str:
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no está instalado.")

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

    ov = _overlay_vf(nombre, telefono, specs, dur)

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    vf_full = (
        f"scale={VW}:{VH}:force_original_aspect_ratio=decrease,"
        f"pad={VW}:{VH}:(ow-iw)/2:(oh-ih)/2,"
        f"colorspace=all=bt709:range=tv,"
        f"{ov}"
    )
    cmd = [
        _ffmpeg_bin(), "-y", "-i", local_in,
        "-vf", vf_full,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
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
            video_path,
            resource_type="video",
            folder="listapro/videos",
            public_id=str(uuid.uuid4()),
        )
        return result["secure_url"]
    except Exception as e:
        log.error("Error subiendo video a Cloudinary: %s", e)
        return None
