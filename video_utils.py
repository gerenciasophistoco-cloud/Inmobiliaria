"""
Generación de video con FFmpeg — Formato 4:5 Premium (1080×1350).
Arquitectura indestructible:
  Paso 1: _to_jpeg   → normaliza imagen a JPEG limpio (maneja WebP, AVIF, etc.)
  Paso 2: _make_clip → JPEG → clip MP4 1080×1350 con blurred background + fade
  Paso 3: slideshow  → concat clips + overlay premium → video final

REGLA CRÍTICA de FFmpeg (causa del error -22):
  drawtext  → usa 'w' y 'h'  (NUNCA iw/ih)
  drawbox   → usa 'iw' y 'ih' (válido)
  crop/scale→ usa 'iw' y 'ih' (válido)
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

# ── Formato 4:5 — estándar de lujo para redes sociales ──────────────────────
VW, VH  = 1080, 1350   # 4:5 vertical premium
FPS     = 25
DUR_PER = 3.0          # segundos por foto
_FADE   = 0.8          # fade-in y fade-out por clip


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
    """Convierte cualquier imagen a JPEG limpio (maneja WebP/AVIF con EXIF corrupto)."""
    out = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.jpg")
    # Intento 1: FFmpeg (robusto, ignora EXIF inválido)
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
    return src_path


def _download(src: str, timeout: int = 20) -> str:
    """Descarga URL → JPEG temporal. Ruta local → convierte a JPEG."""
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
    """Retorna ruta a fuente bold disponible en el sistema."""
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
    """Escapa texto para filtros drawtext de FFmpeg."""
    return (str(text)
        .replace("\\", "\\\\").replace("'", "\\'")
        .replace(":", "\\:").replace(",", "\\,")
        .replace("[", "\\[").replace("]", "\\]")
    )


# ── Overlay premium ───────────────────────────────────────────────────────────

def _overlay_vf(nombre: str, telefono: str, specs: dict, dur: float,
                n_photos: int = 1, dur_per: float = DUR_PER) -> str:
    """
    Overlay premium 1080×1350.

    REGLA ABSOLUTA de FFmpeg:
      drawtext  → 'w', 'h', 'tw'  (NUNCA iw/ih → producen 0 → error -22)
      drawbox   → 'iw', 'ih'      (válido)
      Posiciones absolutas (enteros) no usan variables → siempre seguras.

    Datos del inmueble rotan en sincronía con las fotos via enable='between(t,...)'.
    """
    font = _font()
    fp   = f":fontfile='{font}'" if font else ""
    fv   = []

    precio    = _esc(specs.get("precio", ""))
    ciudad    = _esc(specs.get("ciudad", ""))
    direccion = _esc(specs.get("direccion", ""))

    # ── Precio arriba derecha (dorado) — usa 'w' y 'tw', válidos en drawtext ──
    if precio:
        fv.append(
            f"drawtext=text='{precio}':fontsize=30{fp}"
            f":fontcolor=#FFD700:x=w-tw-20:y=24"
            f":box=1:boxcolor=black@0.50:boxborderw=10"
        )

    # ── Franja inferior — drawbox usa iw/ih (correcto) ───────────────────────
    STRIP_H = 150
    SY      = VH - STRIP_H    # 1200 — entero absoluto, sin variable FFmpeg
    fv.append(f"drawbox=y={SY}:color=black@0.65:width=iw:height={STRIP_H}:t=fill")

    # ── Izquierda: ciudad · dirección · agente — posiciones absolutas ─────────
    if ciudad:
        fv.append(
            f"drawtext=text='{ciudad}':fontsize=30{fp}"
            f":fontcolor=white:x=20:y={SY + 15}"
        )
    if direccion:
        fv.append(
            f"drawtext=text='{direccion}':fontsize=20{fp}"
            f":fontcolor=white@0.80:x=20:y={SY + 57}"
        )
    fv.append(
        f"drawtext=text='{_esc(nombre)}':fontsize=18{fp}"
        f":fontcolor=white@0.70:x=20:y={SY + 100}"
    )

    # ── Derecha: specs rotativas (enable sincronizado con las fotos) ───────────
    data_items = []
    if specs.get("metros"):
        data_items.append(f"{specs['metros']}m2")
    if specs.get("habitaciones"):
        data_items.append(f"{specs['habitaciones']} Hab")
    if specs.get("banos"):
        data_items.append(f"{specs['banos']} Banos")
    if specs.get("estacionamientos"):
        data_items.append(f"{specs['estacionamientos']} Parq")

    # Cada spec visible solo durante su foto (enable usa 't' — válido en drawtext)
    for i in range(n_photos):
        if not data_items:
            break
        item = data_items[i % len(data_items)]
        t0, t1 = i * dur_per, (i + 1) * dur_per
        fv.append(
            f"drawtext=text='{_esc(item)}':fontsize=26{fp}"
            f":fontcolor=white:x=w-tw-20:y={SY + 22}"
            f":enable='between(t,{t0:.1f},{t1:.1f})'"
        )

    # Teléfono dorado — fijo, siempre visible
    fv.append(
        f"drawtext=text='{_esc(telefono)}':fontsize=26{fp}"
        f":fontcolor=#FFD700:x=w-tw-20:y={SY + 90}"
    )

    return ",".join(fv)


# ── Generación de clips normalizados ─────────────────────────────────────────

def _make_clip(img_path: str, idx: int, dur: float) -> str:
    """
    JPEG → clip MP4 normalizado (1080×1350, 25fps, yuv420p, bt709).

    Técnica Blurred Background:
      [bg] = imagen escalada para llenar 1080×1350 + recortada + blur fuerte
      [fg] = imagen escalada para encajar (sin recorte) → centrada sobre [bg]
      Ken Burns: composite escala 5% extra y recorta desde esquina diferente por clip.
      Fade: in 0.8s · out 0.8s

    Todo en un solo filter_complex para garantizar dimensiones exactas.
    """
    out       = str(Path(tempfile.mkdtemp()) / f"clip_{idx}.mp4")
    KB_W      = int(VW * 1.05)   # 1134 — oversized para Ken Burns
    KB_H      = int(VH * 1.05)   # 1417
    # Offset de esquina por clip (percepción de zoom/movimiento)
    cx = [0, KB_W - VW, 0,        KB_W - VW][idx % 4]  # [0, 54, 0, 54]
    cy = [0, 0,         KB_H - VH, KB_H - VH][idx % 4]  # [0, 0, 67, 67]

    fade_dur       = min(_FADE, dur / 3.0)
    fade_out_start = round(dur - fade_dur, 2)

    fc = (
        # Fuente única → 2 caminos
        "[0:v]split=2[bg_raw][fg_raw];"

        # Camino bg: rellena + recorta + blur
        f"[bg_raw]"
        f"scale={VW}:{VH}:force_original_aspect_ratio=increase,"
        f"crop={VW}:{VH},"
        f"boxblur=30:5"
        f"[bg];"

        # Camino fg: encaja (sin recorte, sin padding negro visible)
        f"[fg_raw]"
        f"scale={VW}:{VH}:force_original_aspect_ratio=decrease"
        f"[fg];"

        # Composite: fg centrado sobre bg desenfocado
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        f"[comp];"

        # Ken Burns: escala 5% + recorta esquina + fade
        f"[comp]"
        f"scale={KB_W}:{KB_H},"
        f"crop={VW}:{VH}:x={cx}:y={cy},"
        f"fade=t=in:st=0:d={fade_dur:.2f},"
        f"fade=t=out:st={fade_out_start:.2f}:d={fade_dur:.2f}"
        f"[out]"
    )

    cmd = [
        _ffmpeg_bin(), "-y",
        "-loop", "1", "-i", img_path,
        "-filter_complex", fc,
        "-map", "[out]",
        "-map_metadata", "-1",    # strip ICC Profile
        "-t", str(dur),
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-color_range", "tv",     # fuerza TV range: evita pc/bt470bg que causa frame=0
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(
            f"Error clip {idx}:\n{r.stderr.decode('utf-8', errors='replace')[-500:]}"
        )
    log.info("Clip %d OK → %s", idx, out)
    return out


# ── Slideshow principal (Plan B) ──────────────────────────────────────────────

def generate_slideshow(
    photo_sources: List[str],
    nombre: str,
    telefono: str,
    specs: dict,
    dur_per: float = DUR_PER,
    fade: float = _FADE,
) -> str:
    """
    Slideshow 4:5 indestructible:
      1. Descarga y normaliza cada foto a JPEG
      2. Convierte cada JPEG a clip MP4 normalizado (1080×1350, bt709, yuv420p)
      3. Concat clips (probado y estable) + overlay premium
      4. Codifica salida final con +faststart
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

    # Paso 2: normalizar cada imagen a clip MP4
    clips: List[str] = []
    for i, lp in enumerate(locals_):
        clips.append(_make_clip(lp, i, dur_per))

    # ── Paso 3: UN SOLO PASO — normalizar + concat + overlay en un filter_complex ─
    # El 2-pass genera un intermediario con bt470bg que libx264 rechaza en el overlay.
    # ONE-PASS: setparams normaliza bt470bg→bt709 en cada clip ANTES del concat.
    inputs: List[str] = []
    for clip in clips:
        inputs += ["-i", clip]

    ov = _overlay_vf(nombre, telefono, specs,
                     n * dur_per, n_photos=n, dur_per=dur_per)

    # Normalización por clip: setparams fuerza bt709+tv_range, format garantiza yuv420p
    def _norm(i: int) -> str:
        return (
            f"[{i}:v]"
            f"scale={VW}:{VH}:force_original_aspect_ratio=disable,"
            f"setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,"
            f"format=yuv420p"
            f"[n{i}]"
        )

    if n == 1:
        fc = f"{_norm(0)};[n0]{ov}[final]"
    else:
        norm_chain = ";".join(_norm(i) for i in range(n))
        ci         = "".join(f"[n{i}]" for i in range(n))
        fc         = f"{norm_chain};{ci}concat=n={n}:v=1:a=0[vout];[vout]{ov}[final]"

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        _ffmpeg_bin(), "-y",
        *inputs,
        "-filter_complex", fc,
        "-map", "[final]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        output,
    ]
    log.info("Slideshow ONE-PASS: %d fotos → %s", n, output)
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(
            f"FFmpeg slideshow error:\n{r.stderr.decode('utf-8', errors='replace')[-800:]}"
        )
    return output


# ── Overlays sobre video propio (Plan A) ─────────────────────────────────────

def add_overlays(
    video_source: str,
    nombre: str,
    telefono: str,
    specs: dict,
) -> str:
    """Plan A: reencuadra video del usuario a 4:5 con blurred bg + overlay premium."""
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

    ov = _overlay_vf(nombre, telefono, specs, dur)

    # Blurred background para el video del usuario
    fc = (
        "[0:v]split=2[bg_raw][fg_raw];"
        f"[bg_raw]scale={VW}:{VH}:force_original_aspect_ratio=increase,"
        f"crop={VW}:{VH},boxblur=30:5[bg];"
        f"[fg_raw]scale={VW}:{VH}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
        f"{ov}[out]"
    )

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        _ffmpeg_bin(), "-y", "-i", local_in,
        "-filter_complex", fc,
        "-map", "[out]",
        "-map", "0:a?",
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


# ── Subida a Cloudinary ───────────────────────────────────────────────────────

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
