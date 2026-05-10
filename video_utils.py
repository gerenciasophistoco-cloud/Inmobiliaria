"""
video_utils.py — Pipeline cinematográfico Premium.

Narrativa secuencial por diapositiva:
  Clip 0 → Intro       (ciudad · dirección · precio)
  Clip 1 → Specs       (tarjetas elegantes: Área | HAB | BAÑOS | GAR)
  Clip 2 → Amenidades  (chips de zonas comunes, si las hay)
  Clip 3+ → ciclo      (rota intro → specs → amenidades)
  Outro   → tarjeta de contacto del agente

Overlay: Pillow → RGBA PNG → FFmpeg overlay filter (sin tocar el codec)
Pipeline: JPEG limpio → clip (blur bg + overlay) → concat -c copy → faststart

Anti-ICC: -bsf:v filter_units=remove_types=6 en cada clip.
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
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

VW, VH   = 1080, 1350
FPS      = 25
DUR_PER  = 3.0
FADE_DUR = 0.5          # fade in/out por clip → 1 s de transición entre clips

_GOLD      = (255, 210,   0, 255)
_WHITE     = (255, 255, 255, 255)
_WHITE_DIM = (205, 205, 205, 185)
_CARD_BG   = (  0,   0,   0,  55)
_CARD_BDR  = (255, 255, 255,  80)


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


# ─── Pillow helpers ───────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False):
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
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _gradient_strip(width: int, height: int, a0: int, a1: int):
    """Banda RGBA negra con degradado suave de alpha a0 → a1."""
    from PIL import Image, ImageDraw
    img  = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = (y / max(height - 1, 1)) ** 1.6
        a = max(0, min(255, int(a0 + (a1 - a0) * t)))
        draw.line([(0, y), (width - 1, y)], fill=(0, 0, 0, a))
    return img


def _stxt(draw, xy, text: str, font, color: tuple, shadow: int = 3):
    """Texto con sombra difusa para legibilidad sobre cualquier foto."""
    x, y = xy
    for dx, dy in ((-shadow, shadow), (shadow, shadow), (0, shadow), (0, 0)):
        alpha = 140 if (dx, dy) != (0, 0) else 0
        if alpha:
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, alpha))
    draw.text((x, y), text, font=font, fill=color)


def _fetch_logo(src: str) -> Optional[str]:
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


def _fetch_image_local(src: str) -> Optional[str]:
    """Como _fetch_logo pero para fotos de agente (misma lógica)."""
    return _fetch_logo(src)


# ─── constructores de overlay ─────────────────────────────────────────────────

def _base_canvas(bot_h: int = 560) -> "Image":
    """Lienzo RGBA 1080×1350 con vignettes superior e inferior."""
    from PIL import Image
    ov = Image.new("RGBA", (VW, VH), (0, 0, 0, 0))
    top = _gradient_strip(VW, 300, 210, 0)
    ov.paste(top, (0, 0), top)
    bot = _gradient_strip(VW, bot_h, 0, 240)
    ov.paste(bot, (0, VH - bot_h), bot)
    return ov


def _draw_header(ov, draw, specs: dict, nombre: str):
    """Cabecera común: logo + inmobiliaria (izq) | tipo · precio (der)."""
    from PIL import Image
    M          = 48
    nombre_inm = str(specs.get("nombre_inmobiliaria") or nombre or "")
    tipo       = str(specs.get("tipo_propiedad") or "")
    operacion  = str(specs.get("operacion") or "")
    precio     = str(specs.get("precio") or "")
    logo_src   = str(specs.get("logo_path") or specs.get("logo_url") or "")

    logo_w = 0
    logo_local = _fetch_logo(logo_src)
    if logo_local:
        try:
            logo_img = Image.open(logo_local).convert("RGBA")
            logo_img.thumbnail((54, 54), Image.LANCZOS)
            ov.paste(logo_img, (M, 40), logo_img)
            logo_w = logo_img.width + 14
        except Exception:
            pass

    if nombre_inm:
        _stxt(draw, (M + logo_w, 54),
              f"INMOBILIARIA {nombre_inm.upper()}", _load_font(21), _WHITE, 2)

    tipo_line = " · ".join(filter(None, [tipo.upper(), operacion.upper()]))
    if tipo_line:
        f = _load_font(20)
        bb = draw.textbbox((0, 0), tipo_line, font=f)
        _stxt(draw, (VW - M - (bb[2] - bb[0]), 42), tipo_line, f, _WHITE, 2)

    if precio:
        f = _load_font(30, bold=True)
        bb = draw.textbbox((0, 0), precio, font=f)
        _stxt(draw, (VW - M - (bb[2] - bb[0]), 70), precio, f, _GOLD, 2)


# ── Slide 0: Intro ────────────────────────────────────────────────────────────
def _overlay_intro(specs: dict, nombre: str) -> str:
    """Ciudad (enorme) · dirección · precio dorado."""
    from PIL import Image, ImageDraw
    ov   = _base_canvas(bot_h=580)
    draw = ImageDraw.Draw(ov)
    _draw_header(ov, draw, specs, nombre)
    M = 48

    ciudad    = (specs.get("ciudad") or "").upper().strip()
    direccion = str(specs.get("direccion") or "")
    precio    = str(specs.get("precio") or "")

    if ciudad:
        _stxt(draw, (M, 938), ciudad, _load_font(108, bold=True), _WHITE, 4)
    if direccion:
        _stxt(draw, (M, 1070), direccion[:46], _load_font(32), (235, 235, 235, 215), 2)
    if precio:
        _stxt(draw, (M, 1140), precio, _load_font(54, bold=True), _GOLD, 3)

    path = str(Path(tempfile.mkdtemp()) / "ov_intro.png")
    ov.save(path, "PNG")
    return path


# ── Slide 1: Specs ────────────────────────────────────────────────────────────
def _overlay_specs(specs: dict, nombre: str) -> str:
    """Tarjetas minimalistas: Área | HAB | BAÑOS | GAR."""
    from PIL import Image, ImageDraw
    ov   = _base_canvas(bot_h=500)
    draw = ImageDraw.Draw(ov)
    _draw_header(ov, draw, specs, nombre)
    M = 48

    items = [(v, l) for v, l in [
        (str(specs.get("metros") or specs.get("metros_construidos") or ""), "M²"),
        (str(specs.get("habitaciones") or ""),   "HAB"),
        (str(specs.get("banos") or ""),          "BAÑOS"),
        (str(specs.get("estacionamientos") or ""), "GAR"),
    ] if v]

    if items:
        n      = len(items)
        gap    = 14
        card_w = (VW - 2 * M - gap * (n - 1)) // n
        card_h = 210
        y_card = VH - 490 + 60

        fv = _load_font(max(44, 70 - (n - 3) * 6), bold=True)
        fl = _load_font(20)

        for i, (val, lbl) in enumerate(items):
            x = M + i * (card_w + gap)
            # Tarjeta: fondo oscuro + borde fino blanco
            draw.rounded_rectangle(
                [x, y_card, x + card_w, y_card + card_h],
                radius=14,
                fill=_CARD_BG,
                outline=_CARD_BDR,
                width=1,
            )
            cx = x + card_w // 2
            # Valor numérico
            vb = draw.textbbox((0, 0), val, font=fv)
            _stxt(draw, (cx - (vb[2] - vb[0]) // 2, y_card + 24), val, fv, _WHITE, 2)
            # Etiqueta
            lb = draw.textbbox((0, 0), lbl, font=fl)
            _stxt(draw, (cx - (lb[2] - lb[0]) // 2, y_card + card_h - 42),
                  lbl, fl, _WHITE_DIM, 1)

    # Precio pequeño centrado abajo
    precio = str(specs.get("precio") or "")
    if precio:
        fp = _load_font(40, bold=True)
        pb = draw.textbbox((0, 0), precio, font=fp)
        _stxt(draw, ((VW - (pb[2] - pb[0])) // 2, VH - 68), precio, fp, _GOLD, 3)

    path = str(Path(tempfile.mkdtemp()) / "ov_specs.png")
    ov.save(path, "PNG")
    return path


# ── Slide 2: Amenidades ───────────────────────────────────────────────────────
def _overlay_amenidades(specs: dict, nombre: str) -> str:
    """Chips de zonas comunes con borde fino."""
    from PIL import Image, ImageDraw
    amenidades = specs.get("amenidades") or []
    if not amenidades:
        return _overlay_intro(specs, nombre)

    ov   = _base_canvas(bot_h=520)
    draw = ImageDraw.Draw(ov)
    _draw_header(ov, draw, specs, nombre)
    M = 48

    # Título con línea dorada
    ft = _load_font(26)
    _stxt(draw, (M, VH - 515 + 28), "ZONAS COMUNES", ft, _GOLD, 2)
    draw.line([(M, VH - 515 + 72), (VW - M, VH - 515 + 72)],
              fill=(255, 210, 0, 70), width=1)

    # Chips
    fc   = _load_font(22)
    px, py = 18, 9
    gap     = 10
    x, y    = M, VH - 515 + 90

    for am in amenidades[:9]:
        bb = draw.textbbox((0, 0), am, font=fc)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        cw, ch = tw + px * 2, th + py * 2

        if x + cw > VW - M:
            x  = M
            y += ch + gap

        draw.rounded_rectangle(
            [x, y, x + cw, y + ch],
            radius=ch // 2,
            fill=(0, 0, 0, 65),
            outline=(255, 255, 255, 100),
            width=1,
        )
        draw.text((x + px, y + py), am, font=fc, fill=_WHITE)
        x += cw + gap

    # Precio debajo
    precio = str(specs.get("precio") or "")
    if precio:
        fp = _load_font(38, bold=True)
        pb = draw.textbbox((0, 0), precio, font=fp)
        _stxt(draw, (M, VH - 64), precio, fp, _GOLD, 3)

    path = str(Path(tempfile.mkdtemp()) / "ov_amenidades.png")
    ov.save(path, "PNG")
    return path


# ── Fábrica por índice de clip ────────────────────────────────────────────────
def _create_slide_overlay(specs: dict, nombre: str, idx: int,
                           cache: Dict[str, Optional[str]]) -> Optional[str]:
    """
    Selecciona el tipo de overlay según el índice y rota el ciclo.
    Usa cache para no regenerar el mismo PNG dos veces.
    """
    has_am    = bool(specs.get("amenidades"))
    has_specs = any(specs.get(k) for k in ("metros", "habitaciones", "banos"))

    if has_am and has_specs:
        cycle = ["intro", "specs", "amenidades"]
    elif has_specs:
        cycle = ["intro", "specs"]
    elif has_am:
        cycle = ["intro", "amenidades"]
    else:
        cycle = ["intro"]

    slide_type = cycle[idx % len(cycle)]

    if slide_type not in cache:
        try:
            if slide_type == "intro":
                cache[slide_type] = _overlay_intro(specs, nombre)
            elif slide_type == "specs":
                cache[slide_type] = _overlay_specs(specs, nombre)
            elif slide_type == "amenidades":
                cache[slide_type] = _overlay_amenidades(specs, nombre)
            log.info("Overlay '%s' generado", slide_type)
        except Exception as e:
            log.warning("Overlay '%s' falló: %s", slide_type, e)
            cache[slide_type] = None

    return cache.get(slide_type)


# ─── Outro (tarjeta de contacto) ──────────────────────────────────────────────

def _create_outro_image(nombre: str, telefono: str, specs: dict) -> str:
    """
    Pantalla de cierre:
      fondo degradado oscuro + logo + foto circular del agente
      + nombre + WhatsApp en dorado + branding LISTAPRO
    """
    from PIL import Image, ImageDraw, ImageFilter

    W, H = VW, VH

    # Fondo: degradado oscuro azul-negro → cálido oscuro
    tiny = Image.new("RGBA", (1, 2))
    tiny.putpixel((0, 0), (10, 10, 16, 255))
    tiny.putpixel((0, 1), (22, 18, 14, 255))
    frame = tiny.resize((W, H), Image.BILINEAR).convert("RGBA")

    # Glow dorado central muy sutil
    try:
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([W // 4, H // 4, 3 * W // 4, 3 * H // 4],
                                     fill=(70, 52, 8, 35))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=200))
        frame = Image.alpha_composite(frame, glow)
    except Exception:
        pass

    draw      = ImageDraw.Draw(frame)
    gold      = (255, 210, 0, 255)
    nombre_inm = str(specs.get("nombre_inmobiliaria") or nombre or "")
    logo_src   = str(specs.get("logo_path") or specs.get("logo_url") or "")
    foto_ag    = str(specs.get("foto_agente") or "")

    cy = 140  # cursor vertical

    # ── Logo ──────────────────────────────────────────────────────────────────
    logo_local = _fetch_logo(logo_src)
    if logo_local:
        try:
            logo_img = Image.open(logo_local).convert("RGBA")
            logo_img.thumbnail((100, 100), Image.LANCZOS)
            lx = (W - logo_img.width) // 2
            frame.paste(logo_img, (lx, cy), logo_img)
            cy += logo_img.height + 28
        except Exception:
            pass

    # Línea dorada
    draw.rectangle([W // 4, cy, 3 * W // 4, cy + 2], fill=gold)
    cy += 46

    # Nombre inmobiliaria
    if nombre_inm:
        fl = _load_font(25)
        label = f"INMOBILIARIA {nombre_inm.upper()}"
        bb = draw.textbbox((0, 0), label, font=fl)
        draw.text(((W - (bb[2] - bb[0])) // 2, cy), label, font=fl,
                  fill=(185, 185, 185, 185))
        cy += 52

    cy = max(cy, 500)

    # ── Foto circular del agente ───────────────────────────────────────────────
    foto_local = _fetch_image_local(foto_ag)
    if foto_local:
        try:
            size = 170
            ag   = Image.open(foto_local).convert("RGBA").resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
            circle = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            circle.paste(ag, (0, 0), mask)

            # Borde dorado
            ring = Image.new("RGBA", (size + 8, size + 8), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse([0, 0, size + 7, size + 7],
                                          outline=(255, 210, 0, 200), width=3)
            ring.paste(circle, (4, 4), circle)

            lx = (W - ring.width) // 2
            frame.paste(ring, (lx, cy), ring)
            cy += ring.height + 28
        except Exception:
            pass

    # ── Nombre del agente ──────────────────────────────────────────────────────
    if nombre:
        fn = _load_font(54, bold=True)
        bb = draw.textbbox((0, 0), nombre, font=fn)
        draw.text(((W - (bb[2] - bb[0])) // 2, cy), nombre, font=fn,
                  fill=(255, 255, 255, 255))
        cy += 80

    # Rol
    fr  = _load_font(23)
    rol = "Asesor Inmobiliario"
    bb  = draw.textbbox((0, 0), rol, font=fr)
    draw.text(((W - (bb[2] - bb[0])) // 2, cy), rol, font=fr,
              fill=(145, 145, 145, 165))
    cy += 64

    # Separador
    draw.rectangle([(W // 2 - 24), cy, (W // 2 + 24), cy + 2], fill=gold)
    cy += 42

    # ── WhatsApp / teléfono ────────────────────────────────────────────────────
    if telefono:
        fl2 = _load_font(22)
        lbl = "WhatsApp · Llama ahora"
        bb  = draw.textbbox((0, 0), lbl, font=fl2)
        draw.text(((W - (bb[2] - bb[0])) // 2, cy), lbl, font=fl2,
                  fill=(160, 160, 160, 165))
        cy += 42

        ft2 = _load_font(46, bold=True)
        bb  = draw.textbbox((0, 0), telefono, font=ft2)
        draw.text(((W - (bb[2] - bb[0])) // 2, cy), telefono, font=ft2, fill=gold)

    # Branding
    fb  = _load_font(16)
    brand = "Creado con LISTAPRO"
    bb    = draw.textbbox((0, 0), brand, font=fb)
    draw.text(((W - (bb[2] - bb[0])) // 2, H - 65), brand, font=fb,
              fill=(65, 65, 65, 155))

    path = str(Path(tempfile.mkdtemp()) / "outro.png")
    frame.save(path, "PNG")
    return path


def _make_outro_clip(outro_png: str, dur: float = 4.0) -> str:
    """PNG de cierre → clip MP4 con fade in/out."""
    out         = str(Path(tempfile.mkdtemp()) / "outro.mp4")
    fade_out_st = max(0.0, dur - FADE_DUR)
    cmd = [
        _ffmpeg_bin(), "-y",
        "-loop", "1", "-i", outro_png,
        "-vf", (f"scale={VW}:{VH}:force_original_aspect_ratio=disable,"
                f"fade=t=in:st=0:d={FADE_DUR},"
                f"fade=t=out:st={fade_out_st:.3f}:d={FADE_DUR}"),
        "-t", str(dur), "-r", str(FPS),
        "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2",
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
    JPEG limpio → clip MP4 1080×1350.
    Si overlay_path existe, lo compuesta sobre el frame (FFmpeg overlay filter).
    Clave anti-ICC: -bsf:v filter_units=remove_types=6
    """
    out         = str(Path(tempfile.mkdtemp()) / f"clip_{idx}.mp4")
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
            "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2",
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
            "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2",
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
    Pipeline cinematográfico:
      1. Fotos → JPEG limpio (sin ICC)
      2. Overlays PNG por slide (Pillow, cacheados por tipo)
      3. Cada JPEG → clip con overlay correspondiente (FFmpeg)
      4. Outro de contacto del agente
      5. Concat -c copy + faststart
    """
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no está instalado en este servidor.")

    specs = specs or {}

    # 1. Fotos → JPEG sin ICC
    jpegs: List[str] = []
    for src in photo_sources[:6]:
        try:
            jpegs.append(_to_jpeg(src))
            log.info("Foto %d/%d OK", len(jpegs), min(len(photo_sources), 6))
        except Exception as e:
            log.warning("Foto omitida (%s): %s", src, e)

    if not jpegs:
        raise ValueError("No se pudo obtener ninguna foto.")

    # 2 + 3. Overlay por slide → clip
    ov_cache: Dict[str, Optional[str]] = {}
    clips: List[str] = []
    for i, jp in enumerate(jpegs):
        ov = _create_slide_overlay(specs, nombre, i, ov_cache)
        clips.append(_make_clip(jp, i, overlay_path=ov, dur=dur_per))

    # 4. Outro
    try:
        outro_png  = _create_outro_image(nombre, telefono, specs)
        outro_clip = _make_outro_clip(outro_png, dur=4.0)
        clips.append(outro_clip)
        log.info("Outro OK")
    except Exception as e:
        log.warning("Outro omitido: %s", e)

    # 5. Concat -c copy
    playlist = str(Path(tempfile.mkdtemp()) / "playlist.txt")
    with open(playlist, "w") as f:
        for clip in clips:
            f.write(f"file '{clip}'\n")

    output = str(Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}.mp4")
    cmd = [
        _ffmpeg_bin(), "-y",
        "-f", "concat", "-safe", "0", "-i", playlist,
        "-c", "copy", "-movflags", "+faststart",
        output,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(
            f"Concat error:\n{r.stderr.decode('utf-8', errors='replace')[-800:]}"
        )
    size = os.path.getsize(output)
    if size < 1000:
        raise RuntimeError(f"Video final vacío ({size} bytes)")
    log.info("Slideshow OK: %d clips, %d bytes", len(clips), size)
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
