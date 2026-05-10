"""
video_utils.py — Pipeline estable + overlay premium (Pillow).

Flujo:
  foto → JPEG limpio (sin ICC) → clip MP4 (blur bg + overlay PNG via Pillow)
  → concat -c copy → video final + outro

Causa raíz del frame=0 (resuelto):
  ICC Profile de Cloudinary WebP queda en SEI h264 NAL type 6.
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

VW, VH   = 1080, 1350   # 4:5
FPS      = 25
DUR_PER  = 3.0
FADE_DUR = 0.4           # fade in / fade out por clip

# Paleta premium
_GOLD      = (255, 210,   0, 255)
_WHITE     = (255, 255, 255, 255)
_WHITE_DIM = (210, 210, 210, 190)
_SHADOW    = (  0,   0,   0, 160)


# ─── utilidades FFmpeg ────────────────────────────────────────────────────────

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
    """Descarga / lee src y lo convierte a JPEG sin ICC Profile."""
    out = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.jpg")
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

    r = subprocess.run(
        [_ffmpeg_bin(), "-y", "-i", raw,
         "-frames:v", "1", "-q:v", "2", "-map_metadata", "-1", out],
        capture_output=True, timeout=30,
    )
    if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    try:
        from PIL import Image
        Image.open(raw).convert("RGB").save(out, "JPEG", quality=90)
        return out
    except Exception:
        pass
    return raw


# ─── overlay premium (Pillow) ─────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False):
    """Mejor fuente disponible en el sistema para el tamaño dado."""
    from PIL import ImageFont
    paths = (
        [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
            "/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
            "/Library/Fonts/Arial Bold.ttf",
        ]
        if bold else
        [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf",
            "C:\\Windows\\Fonts\\arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ]
    )
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)   # Pillow ≥ 10
    except Exception:
        return ImageFont.load_default()


def _gradient_strip(width: int, height: int, alpha_start: int, alpha_end: int):
    """Banda RGBA negra con degradado vertical de alpha_start a alpha_end."""
    from PIL import Image, ImageDraw
    img  = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = (y / max(height - 1, 1)) ** 1.5   # curva exponencial suave
        a = int(alpha_start + (alpha_end - alpha_start) * t)
        draw.line([(0, y), (width - 1, y)], fill=(0, 0, 0, max(0, min(255, a))))
    return img


def _stxt(draw, xy, text: str, font, color: tuple, shadow: int = 3):
    """Texto con sombra suave para máxima legibilidad sobre foto."""
    x, y = xy
    for dx, dy in ((-shadow, shadow), (shadow, shadow), (0, shadow)):
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 150))
    draw.text((x, y), text, font=font, fill=color)


def _fetch_logo(src: str) -> Optional[str]:
    """Descarga el logo si es URL; retorna ruta local o None."""
    if not src:
        return None
    if src.startswith(("http://", "https://")):
        dest = str(Path(tempfile.mkdtemp()) / f"logo_{uuid.uuid4()}.img")
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "ListaPro/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                with open(dest, "wb") as f:
                    f.write(r.read())
            return dest
        except Exception:
            return None
    return src if os.path.exists(src) else None


def _create_overlay(specs: dict, nombre: str) -> str:
    """
    Genera overlay.png RGBA 1080×1350 con la estética premium inmobiliaria:
      · Vignette superior e inferior
      · Cabecera: logo + inmobiliaria (izq) | tipo·operación + precio (der)
      · Bloque inferior: specs row, ciudad gigante, dirección, precio dorado
    """
    from PIL import Image, ImageDraw

    W, H = VW, VH
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Vignettes
    top_strip = _gradient_strip(W, 290, 210, 0)
    ov.paste(top_strip, (0, 0), top_strip)
    bot_h = 570
    bot_strip = _gradient_strip(W, bot_h, 0, 235)
    ov.paste(bot_strip, (0, H - bot_h), bot_strip)

    draw = ImageDraw.Draw(ov)
    M = 48   # margen lateral

    # ── extraer datos ──────────────────────────────────────────────────────────
    precio     = str(specs.get("precio") or "")
    ciudad     = (specs.get("ciudad") or "").upper().strip()
    direccion  = str(specs.get("direccion") or "")
    tipo       = str(specs.get("tipo_propiedad") or "")
    operacion  = str(specs.get("operacion") or "")
    nombre_inm = str(specs.get("nombre_inmobiliaria") or nombre or "")
    metros     = str(specs.get("metros") or specs.get("metros_construidos") or "")
    hab        = str(specs.get("habitaciones") or "")
    banos      = str(specs.get("banos") or "")
    garaje     = str(specs.get("estacionamientos") or "")
    logo_src   = str(specs.get("logo_path") or specs.get("logo_url") or "")

    # ── cabecera izquierda: logo + nombre inmobiliaria ─────────────────────────
    logo_w = 0
    logo_local = _fetch_logo(logo_src)
    if logo_local:
        try:
            logo_img = Image.open(logo_local).convert("RGBA")
            logo_img.thumbnail((54, 54), Image.LANCZOS)
            ov.paste(logo_img, (M, 42), logo_img)
            logo_w = logo_img.width + 14
        except Exception:
            pass

    if nombre_inm:
        font_inm = _load_font(21)
        label = f"INMOBILIARIA {nombre_inm.upper()}"
        _stxt(draw, (M + logo_w, 56), label, font_inm, _WHITE, shadow=2)

    # ── cabecera derecha: tipo · operación | precio ────────────────────────────
    tipo_line = " · ".join(filter(None, [tipo.upper(), operacion.upper()]))
    font_tipo = _load_font(20)
    font_precio_hdr = _load_font(30, bold=True)

    if tipo_line:
        bb = draw.textbbox((0, 0), tipo_line, font=font_tipo)
        tw = bb[2] - bb[0]
        _stxt(draw, (W - M - tw, 44), tipo_line, font_tipo, _WHITE, shadow=2)

    if precio:
        bb = draw.textbbox((0, 0), precio, font=font_precio_hdr)
        pw = bb[2] - bb[0]
        _stxt(draw, (W - M - pw, 72), precio, font_precio_hdr, _GOLD, shadow=2)

    # ── fila de specs ──────────────────────────────────────────────────────────
    spec_items = [(v, l) for v, l in [
        (metros, "M²"), (hab, "HAB"), (banos, "BAÑOS"), (garaje, "GAR"),
    ] if v]

    if spec_items:
        font_sv = _load_font(50, bold=True)
        font_sl = _load_font(19)
        n = len(spec_items)
        col_w = W // n
        for i, (val, lbl) in enumerate(spec_items):
            cx = col_w * i + col_w // 2
            nb = draw.textbbox((0, 0), val, font=font_sv)
            nw = nb[2] - nb[0]
            _stxt(draw, (cx - nw // 2, 828), val, font_sv, _WHITE)
            lb = draw.textbbox((0, 0), lbl, font=font_sl)
            lw = lb[2] - lb[0]
            _stxt(draw, (cx - lw // 2, 892), lbl, font_sl, _WHITE_DIM, shadow=1)

    # ── ciudad (enorme) ────────────────────────────────────────────────────────
    if ciudad:
        font_city = _load_font(108, bold=True)
        _stxt(draw, (M, 940), ciudad, font_city, _WHITE, shadow=4)

    # ── dirección ─────────────────────────────────────────────────────────────
    if direccion:
        font_dir = _load_font(32)
        _stxt(draw, (M, 1072), direccion[:45], font_dir, (235, 235, 235, 220), shadow=2)

    # ── precio grande dorado ───────────────────────────────────────────────────
    if precio:
        font_precio_bot = _load_font(54, bold=True)
        _stxt(draw, (M, 1142), precio, font_precio_bot, _GOLD, shadow=3)

    out_path = str(Path(tempfile.mkdtemp()) / "overlay.png")
    ov.save(out_path, "PNG")
    return out_path


def _create_outro_image(nombre: str, telefono: str, specs: dict) -> str:
    """
    Frame de cierre del video: fondo oscuro degradado + logo + agente + WhatsApp en dorado.
    """
    from PIL import Image, ImageDraw

    W, H = VW, VH

    # Fondo: degradado oscuro azul-negro → negro cálido
    frame = Image.new("RGBA", (1, 2))
    frame.putpixel((0, 0), (10, 10, 16, 255))
    frame.putpixel((0, 1), (24, 20, 16, 255))
    frame = frame.resize((W, H), Image.BILINEAR).convert("RGBA")

    # Glow dorado central muy sutil
    try:
        from PIL import ImageFilter
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(
            [W // 4, H // 3, 3 * W // 4, 2 * H // 3],
            fill=(80, 60, 10, 40),
        )
        glow = glow.filter(ImageFilter.GaussianBlur(radius=180))
        frame = Image.alpha_composite(frame, glow)
    except Exception:
        pass

    draw = ImageDraw.Draw(frame)
    nombre_inm = str(specs.get("nombre_inmobiliaria") or nombre or "")
    logo_src   = str(specs.get("logo_path") or specs.get("logo_url") or "")
    gold_rgb   = (255, 210, 0, 255)

    cy = 180  # cursor vertical

    # Logo centrado
    logo_local = _fetch_logo(logo_src)
    if logo_local:
        try:
            logo_img = Image.open(logo_local).convert("RGBA")
            logo_img.thumbnail((110, 110), Image.LANCZOS)
            lx = (W - logo_img.width) // 2
            frame.paste(logo_img, (lx, cy), logo_img)
            cy += logo_img.height + 36
        except Exception:
            pass

    # Línea dorada
    draw.rectangle([W // 4, cy, 3 * W // 4, cy + 3], fill=gold_rgb)
    cy += 48

    # Nombre inmobiliaria
    if nombre_inm:
        font_inm = _load_font(26)
        label = f"INMOBILIARIA {nombre_inm.upper()}"
        bb = draw.textbbox((0, 0), label, font=font_inm)
        tw = bb[2] - bb[0]
        draw.text(((W - tw) // 2, cy), label, font=font_inm,
                  fill=(190, 190, 190, 190))
        cy += 58

    # Empujar hacia abajo si hay poco contenido arriba
    cy = max(cy, 560)

    # Nombre del agente
    if nombre:
        font_ag = _load_font(56, bold=True)
        bb = draw.textbbox((0, 0), nombre, font=font_ag)
        tw = bb[2] - bb[0]
        draw.text(((W - tw) // 2, cy), nombre, font=font_ag,
                  fill=(255, 255, 255, 255))
        cy += 84

    # Rol
    font_rol = _load_font(24)
    rol = "Asesor Inmobiliario"
    bb = draw.textbbox((0, 0), rol, font=font_rol)
    tw = bb[2] - bb[0]
    draw.text(((W - tw) // 2, cy), rol, font=font_rol,
              fill=(150, 150, 150, 170))
    cy += 68

    # Separador dorado pequeño
    draw.rectangle([(W // 2 - 28), cy, (W // 2 + 28), cy + 2], fill=gold_rgb)
    cy += 44

    # WhatsApp / Teléfono
    if telefono:
        font_tel_lbl = _load_font(22)
        lbl = "WhatsApp · Llama ahora"
        bb = draw.textbbox((0, 0), lbl, font=font_tel_lbl)
        tw = bb[2] - bb[0]
        draw.text(((W - tw) // 2, cy), lbl, font=font_tel_lbl,
                  fill=(170, 170, 170, 170))
        cy += 44

        font_tel = _load_font(48, bold=True)
        bb = draw.textbbox((0, 0), telefono, font=font_tel)
        tw = bb[2] - bb[0]
        draw.text(((W - tw) // 2, cy), telefono, font=font_tel,
                  fill=gold_rgb)

    # Branding
    font_brand = _load_font(17)
    brand = "Creado con LISTAPRO"
    bb = draw.textbbox((0, 0), brand, font=font_brand)
    tw = bb[2] - bb[0]
    draw.text(((W - tw) // 2, H - 70), brand, font=font_brand,
              fill=(70, 70, 70, 160))

    out_path = str(Path(tempfile.mkdtemp()) / "outro.png")
    frame.save(out_path, "PNG")
    return out_path


def _make_outro_clip(outro_png: str, dur: float = 4.0) -> str:
    """PNG de cierre → clip MP4 con fade in/out."""
    out = str(Path(tempfile.mkdtemp()) / "outro.mp4")
    fade_out_st = max(0.0, dur - FADE_DUR)
    cmd = [
        _ffmpeg_bin(), "-y",
        "-loop", "1", "-i", outro_png,
        "-vf", (f"scale={VW}:{VH}:force_original_aspect_ratio=disable,"
                f"fade=t=in:st=0:d={FADE_DUR},"
                f"fade=t=out:st={fade_out_st:.3f}:d={FADE_DUR}"),
        "-t", str(dur),
        "-r", str(FPS),
        "-c:v", "libx264",
        "-profile:v", "high", "-level:v", "4.2",
        "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-bsf:v", "filter_units=remove_types=6",
        out,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace")[-400:])
    if os.path.getsize(out) < 1000:
        raise RuntimeError("Outro clip vacío")
    log.info("Outro OK (%d bytes)", os.path.getsize(out))
    return out


# ─── pipeline de clips ────────────────────────────────────────────────────────

def _make_clip(jpeg: str, idx: int, overlay_path: Optional[str] = None,
               dur: float = DUR_PER) -> str:
    """
    JPEG limpio → clip MP4 1080×1350 con fondo desenfocado + overlay premium.

    Clave anti-ICC: -bsf:v filter_units=remove_types=6
    """
    out = str(Path(tempfile.mkdtemp()) / f"clip_{idx}.mp4")
    fade_out_st = max(0.0, dur - FADE_DUR)

    if overlay_path:
        fc = (
            "[0:v]split=2[bg_src][fg_src];"
            f"[bg_src]scale={VW}:{VH}:force_original_aspect_ratio=increase,"
            f"crop={VW}:{VH},boxblur=20:2[bg];"
            f"[fg_src]scale={VW}:{VH}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[main];"
            f"[main][1:v]overlay=0:0,"
            f"fade=t=in:st=0:d={FADE_DUR},"
            f"fade=t=out:st={fade_out_st:.3f}:d={FADE_DUR}[out]"
        )
        cmd = [
            _ffmpeg_bin(), "-y",
            "-loop", "1", "-i", jpeg,
            "-loop", "1", "-i", overlay_path,
            "-filter_complex", fc,
            "-map", "[out]",
            "-t", str(dur), "-r", str(FPS),
            "-map_metadata", "-1",
            "-c:v", "libx264",
            "-profile:v", "high", "-level:v", "4.2",
            "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-bsf:v", "filter_units=remove_types=6",
            out,
        ]
    else:
        fc = (
            "[0:v]split=2[bg_src][fg_src];"
            f"[bg_src]scale={VW}:{VH}:force_original_aspect_ratio=increase,"
            f"crop={VW}:{VH},boxblur=20:2[bg];"
            f"[fg_src]scale={VW}:{VH}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
            f"fade=t=in:st=0:d={FADE_DUR},"
            f"fade=t=out:st={fade_out_st:.3f}:d={FADE_DUR}[out]"
        )
        cmd = [
            _ffmpeg_bin(), "-y",
            "-loop", "1", "-i", jpeg,
            "-filter_complex", fc,
            "-map", "[out]",
            "-t", str(dur), "-r", str(FPS),
            "-map_metadata", "-1",
            "-c:v", "libx264",
            "-profile:v", "high", "-level:v", "4.2",
            "-preset", "ultrafast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-bsf:v", "filter_units=remove_types=6",
            out,
        ]

    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace")[-600:])
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
      1. Cada foto  → JPEG limpio (sin ICC Profile)
      2. Overlay    → PNG RGBA (Pillow) con vignettes, datos y estética premium
      3. Cada JPEG  → clip MP4 (blur bg + overlay via FFmpeg overlay filter)
      4. Outro      → clip de cierre con agente y WhatsApp
      5. Clips      → concat -c copy (+faststart)
    """
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no está instalado en este servidor.")

    specs = specs or {}

    # 1. Fotos → JPEG sin ICC
    jpegs: List[str] = []
    for src in photo_sources[:6]:
        try:
            jpegs.append(_to_jpeg(src))
            log.info("Foto %d/%d convertida", len(jpegs), min(len(photo_sources), 6))
        except Exception as e:
            log.warning("Foto omitida (%s): %s", src, e)

    if not jpegs:
        raise ValueError("No se pudo obtener ninguna foto.")

    # 2. Overlay PNG (Pillow) — generado una sola vez
    overlay_path: Optional[str] = None
    try:
        overlay_path = _create_overlay(specs, nombre)
        log.info("Overlay premium generado OK")
    except Exception as e:
        log.warning("Overlay omitido (%s) — video sin texto", e)

    # 3. JPEG → clips con overlay
    clips: List[str] = []
    for i, jp in enumerate(jpegs):
        clips.append(_make_clip(jp, i, overlay_path=overlay_path, dur=dur_per))

    # 4. Outro clip
    try:
        outro_png  = _create_outro_image(nombre, telefono, specs)
        outro_clip = _make_outro_clip(outro_png, dur=4.0)
        clips.append(outro_clip)
        log.info("Outro clip OK")
    except Exception as e:
        log.warning("Outro omitido (%s)", e)

    # 5. Concat -c copy
    playlist = str(Path(tempfile.mkdtemp()) / "playlist.txt")
    with open(playlist, "w") as f:
        for clip in clips:
            f.write(f"file '{clip}'\n")

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        _ffmpeg_bin(), "-y",
        "-f", "concat", "-safe", "0", "-i", playlist,
        "-c", "copy",
        "-movflags", "+faststart",
        output,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"Concat error:\n{r.stderr.decode('utf-8', errors='replace')[-800:]}")

    size = os.path.getsize(output)
    if size < 1000:
        raise RuntimeError(f"Video final vacío ({size} bytes)")
    log.info("Slideshow OK: %d clips, %d bytes → %s", len(clips), size, output)
    return output


# ─── Plan A: video del usuario ────────────────────────────────────────────────

def add_overlays(video_source: str, nombre: str, telefono: str, specs: dict) -> str:
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no disponible.")

    local_in = (_to_jpeg(video_source)
                if video_source.endswith((".jpg", ".jpeg", ".png", ".webp"))
                else video_source)

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
        capture_output=True, timeout=300,
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
