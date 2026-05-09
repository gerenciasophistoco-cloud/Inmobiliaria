"""
Generación de video con FFmpeg.
Plan A: usuario sube su propio video → agregarle overlays.
Plan B: generar slideshow Ken Burns + crossfade desde las fotos.
En ambos casos sube el resultado a Cloudinary y devuelve la URL.
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

VW, VH = 1920, 1080   # 16:9
FPS = 30

# Patrones Ken Burns (pan rápido con crop — mucho más rápido que zoompan)
# (scale_w, scale_h, x_expr, y_expr)  — crop final siempre 1920×1080
_MOVES = [
    (2120, 1193, "200*t/{d}", "(1193-1080)/2"),       # pan izquierda→derecha
    (2120, 1193, "200*(1-t/{d})", "(1193-1080)/2"),   # pan derecha→izquierda
    (1920, 1302, "(2120-1920)/2", "222*t/{d}"),        # pan arriba→abajo
    (1920, 1302, "(2120-1920)/2", "222*(1-t/{d})"),    # pan abajo→arriba
]


# ─── Utilidades ───────────────────────────────────────────────────────────────

def _download(src: str) -> str:
    """Descarga una URL a un archivo temporal y devuelve la ruta local."""
    if src.startswith("http://") or src.startswith("https://"):
        ext = Path(src.split("?")[0]).suffix or ".jpg"
        dst = Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}{ext}"
        urllib.request.urlretrieve(src, str(dst))
        return str(dst)
    # Ruta local relativa al proyecto
    if src.startswith("/uploads/") or src.startswith("/tmp/"):
        base = Path(__file__).parent
        candidate = base / src.lstrip("/")
        if candidate.exists():
            return str(candidate)
    return src   # ya es ruta absoluta


def _font() -> str:
    for p in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]:
        if os.path.exists(p):
            return p
    return ""


def _esc(text: str) -> str:
    """Escapa caracteres especiales para filtros drawtext de FFmpeg."""
    return (text
        .replace("\\", "\\\\")
        .replace("'",  "\\'")
        .replace(":",  "\\:")
        .replace(",",  "\\,")
        .replace("[",  "\\[")
        .replace("]",  "\\]")
    )


def _overlay_vf(nombre: str, telefono: str, specs: dict, dur: float) -> str:
    """Retorna la cadena de filtros vf para los overlays de texto."""
    fp = f":fontfile='{_font()}'" if _font() else ""

    parts_spec = [s for s in [
        f"{specs.get('metros','')} m²"       if specs.get("metros")       else "",
        f"{specs.get('habitaciones','')} hab." if specs.get("habitaciones") else "",
        f"{specs.get('banos','')} baños"       if specs.get("banos")        else "",
    ] if s]
    spec_str = " · ".join(parts_spec)

    show = min(4.5, dur - 0.5)
    fv = [
        # Franja oscura inferior
        "drawbox=y=ih-80:color=black@0.72:width=iw:height=80:t=fill",
        # Nombre (blanco, centrado)
        f"drawtext=text='{_esc(nombre)}':fontsize=30{fp}:fontcolor=white:x=(w-tw)/2:y=h-62",
        # Teléfono (verde WhatsApp)
        f"drawtext=text='{_esc(telefono)}':fontsize=22{fp}:fontcolor=#25D366:x=(w-tw)/2:y=h-32",
    ]
    if spec_str and dur > 1:
        fv.append(
            f"drawtext=text='{_esc(spec_str)}':fontsize=32{fp}:fontcolor=white"
            f":x=40:y=40:box=1:boxcolor=black@0.55:boxborderw=10"
            f":enable='between(t,0.5,{show:.1f})'"
        )
    return ",".join(fv)


# ─── Generación de slideshow (Plan B) ────────────────────────────────────────

def _kb_segment(i: int, dur: float) -> str:
    """Devuelve el fragmento del filtro Ken Burns para la foto i."""
    sw, sh, cx, cy = _MOVES[i % len(_MOVES)]
    cx_s = cx.format(d=dur)
    cy_s = cy.format(d=dur)
    return (
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},"
        f"crop={VW}:{VH}:x='{cx_s}':y='{cy_s}':eval=frame,"
        f"trim=duration={dur},setpts=PTS-STARTPTS"
    )


def _xfade_graph(n: int, dur: float, fade: float = 0.8) -> str:
    """
    Construye el filter_complex de FFmpeg para n clips ya etiquetados [v0]..[vN-1].
    Devuelve la cadena del filter_complex y el pad de salida.
    """
    if n == 1:
        return "[v0]copy[vout]", "vout"

    parts = []
    for i in range(1, n):
        a   = "v0" if i == 1 else f"xf{i-2}"
        out = "vout" if i == n - 1 else f"xf{i-1}"
        off = i * (dur - fade)
        parts.append(
            f"[{a}][v{i}]xfade=transition=fade:duration={fade}:offset={off:.2f}[{out}]"
        )
    return ";".join(parts), "vout"


def generate_slideshow(
    photo_sources: List[str],
    nombre: str,
    telefono: str,
    specs: dict,
    dur_per: float = 5.0,
    fade:    float = 0.8,
) -> str:
    """
    Crea un MP4 16:9 con Ken Burns + crossfade + overlays.
    Devuelve la ruta del archivo generado.
    """
    locals_: List[str] = []
    for src in photo_sources[:6]:
        try:
            locals_.append(_download(src))
        except Exception as e:
            log.warning("No se pudo obtener foto %s: %s", src, e)

    if not locals_:
        raise ValueError("No hay fotos disponibles para el slideshow")

    n = len(locals_)
    total = n * dur_per - (n - 1) * fade if n > 1 else dur_per

    # Inputs de FFmpeg
    inputs: List[str] = []
    for lp in locals_:
        inputs += ["-loop", "1", "-t", str(dur_per + 1), "-i", lp]

    # Ken Burns por foto
    kb_parts = [f"[{i}:v]{_kb_segment(i, dur_per)}[v{i}]" for i in range(n)]

    # Crossfade chain
    xf_chain, out_pad = _xfade_graph(n, dur_per, fade)

    # Overlay sobre el resultado final
    ov = _overlay_vf(nombre, telefono, specs, total)

    filter_complex = ";".join(kb_parts) + ";" + xf_chain + f";[{out_pad}]{ov}[final]"

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[final]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-t", str(total),
        "-movflags", "+faststart",
        output,
    ]
    log.info("Generando slideshow para %d fotos (%.0fs)...", n, total)
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace")[-800:])

    return output


# ─── Overlays sobre video existente (Plan A) ─────────────────────────────────

def add_overlays(
    video_source: str,
    nombre: str,
    telefono: str,
    specs: dict,
) -> str:
    """Añade overlays a un video del usuario. Devuelve ruta del resultado."""
    local_in = _download(video_source)

    # Detectar duración
    dur = 30.0
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", local_in],
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
    # Escalar a 16:9 y aplicar overlays en un solo paso
    vf = f"scale={VW}:{VH}:force_original_aspect_ratio=decrease,pad={VW}:{VH}:(ow-iw)/2:(oh-ih)/2,{ov}"

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", local_in,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace")[-800:])
    return output


# ─── Upload a Cloudinary ──────────────────────────────────────────────────────

def upload_video(video_path: str) -> Optional[str]:
    """Sube video a Cloudinary. Devuelve URL pública o None."""
    if not os.getenv("CLOUDINARY_URL"):
        return None
    try:
        import cloudinary
        import cloudinary.uploader
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
