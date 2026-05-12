"""
video_utils.py — Pipeline cinematográfico. Menos es más.

Narrativa secuencial: cada clip muestra UN solo dato.
  Clip 0 → Intro:        ciudad grande + dirección + precio
  Clip 1 → Área:         un solo dato, tarjeta minimalista esquina
  Clip 2 → Habitaciones: ídem
  Clip 3 → Baños / GAR:  ídem
  Clip 4 → Amenidades:   chips refinados (si existen)
  Clip 5 → Cierre:       precio + ciudad breve
  Outro  → tarjeta del agente con foto circular

Ken Burns: zoom-in / zoom-out alterno (5 % sobre 3 s) para dinamismo.
Overlay:   Pillow → PNG RGBA → FFmpeg overlay (pipeline codec intacto).
Anti-ICC:  -bsf:v filter_units=remove_types=6 en cada clip.
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
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

VW, VH       = 1080, 1350
FPS          = 25
DUR_PER      = 3.5          # más tiempo por slide para leer los datos
FADE_DUR     = 0.5          # fade clip in/out
TEXT_FADE_IN = 0.6          # el texto aparece después de que la foto ya está visible

_GOLD      = (255, 210,   0, 255)   # oro vibrante
_CHAMPAGNE = (255, 224, 130, 255)   # oro suave para subtítulos
_WHITE     = (255, 255, 255, 255)
_WHITE_DIM = (210, 210, 210, 175)


# ─── FFmpeg ───────────────────────────────────────────────────────────────────

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
        ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
         "/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf",
         "C:\\Windows\\Fonts\\arialbd.ttf", "/Library/Fonts/Arial Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
         "/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf",
         "C:\\Windows\\Fonts\\arial.ttf", "/Library/Fonts/Arial.ttf"]
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


def _vignette(width: int, height: int, a0: int, a1: int, exp: float = 2.0):
    """Banda RGBA negra con degradado exponencial cinematográfico a0→a1."""
    from PIL import Image, ImageDraw
    img  = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = (y / max(height - 1, 1)) ** exp
        a = max(0, min(255, int(a0 + (a1 - a0) * t)))
        draw.line([(0, y), (width - 1, y)], fill=(0, 0, 0, a))
    return img


def _txt(draw, xy: Tuple[int, int], text: str, font, color: tuple, sh: int = 2):
    """Texto con sombra ligera (sh=0 → sin sombra)."""
    if sh:
        for dx, dy in ((-sh, sh), (sh, sh), (0, sh)):
            draw.text((xy[0] + dx, xy[1] + dy), text, font=font,
                      fill=(0, 0, 0, 130))
    draw.text(xy, text, font=font, fill=color)


def _txt_center(draw, y: int, text: str, font, color: tuple, sh: int = 2):
    """Texto centrado horizontalmente."""
    bb = draw.textbbox((0, 0), text, font=font)
    x  = (VW - (bb[2] - bb[0])) // 2
    _txt(draw, (x, y), text, font, color, sh)


def _txt_right(draw, y: int, text: str, font, color: tuple, margin: int = 46, sh: int = 2):
    """Texto alineado a la derecha."""
    bb = draw.textbbox((0, 0), text, font=font)
    x  = VW - margin - (bb[2] - bb[0])
    _txt(draw, (x, y), text, font, color, sh)


def _sep(draw, x: int, y: int, w: int = 220):
    """Línea dorada horizontal separadora, delgada y elegante."""
    draw.line([(x, y), (x + w, y)], fill=(255, 210, 0, 200), width=2)


def _add_zone(base_path: str, zone: str) -> str:
    """
    Clona el overlay base y añade el nombre de zona (ej: SALA, COCINA) como
    un tag/pill en la esquina inferior-derecha: fondo oscuro + texto blanco.
    """
    if not base_path or not zone or not zone.strip():
        return base_path
    from PIL import Image, ImageDraw
    try:
        ov   = Image.open(base_path).convert("RGBA")
        draw = ImageDraw.Draw(ov)

        zt  = zone.upper().strip()[:14]   # máx 14 caracteres
        f   = _load_font(20)
        bb  = draw.textbbox((0, 0), zt, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]

        # Pill: fondo oscuro semitransparente + borde blanco fino
        M    = 44
        px, py   = 16, 8
        tag_w    = tw + px * 2
        tag_h    = th + py * 2
        x        = VW - M - tag_w
        y        = VH - M - tag_h

        draw.rounded_rectangle(
            [x, y, x + tag_w, y + tag_h],
            radius=tag_h // 2,
            fill=(0, 0, 0, 170),           # fondo oscuro (67% opacidad)
            outline=(255, 255, 255, 90),   # borde blanco sutil
            width=1,
        )
        draw.text((x + px, y + py), zt, font=f, fill=(255, 255, 255, 235))

        out = str(Path(tempfile.mkdtemp()) / f"ov_z_{zt[:6].lower()}.png")
        ov.save(out, "PNG")
        log.info("Zona '%s' añadida al overlay", zt)
        return out
    except Exception as e:
        log.warning("_add_zone falló ('%s'): %s", zone, e)
        return base_path


def _fetch_img(src: str) -> Optional[str]:
    """Descarga imagen si es URL; retorna ruta local o None."""
    if not src:
        return None
    if src.startswith(("http://", "https://")):
        dest = str(Path(tempfile.mkdtemp()) / f"img_{uuid.uuid4()}.img")
        try:
            req = urllib.request.Request(src, headers={"User-Agent": "ListaPro/1.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                with open(dest, "wb") as f:
                    f.write(r.read())
            return dest
        except Exception:
            return None
    return src if os.path.exists(src) else None


# ─── bloques de overlay ───────────────────────────────────────────────────────

def _canvas() -> "Image.Image":
    """Lienzo RGBA 1080×1350 vacío."""
    from PIL import Image
    return Image.new("RGBA", (VW, VH), (0, 0, 0, 0))


def _header(ov, draw, specs: dict, nombre: str):
    """
    Cabecera limpia: logo + nombre inmobiliaria (izq) | tipo · operacion (der).
    SIN precio — el precio solo aparece en slides específicos.
    """
    from PIL import Image
    M          = 46
    nombre_inm = str(specs.get("nombre_inmobiliaria") or nombre or "")
    tipo       = str(specs.get("tipo_propiedad") or "")
    operacion  = str(specs.get("operacion") or "")
    logo_src   = str(specs.get("logo_path") or specs.get("logo_url") or "")

    logo_w = 0
    logo_local = _fetch_img(logo_src)
    if logo_local:
        try:
            logo_img = Image.open(logo_local).convert("RGBA")
            logo_img.thumbnail((50, 50), Image.LANCZOS)
            ov.paste(logo_img, (M, 40), logo_img)
            logo_w = logo_img.width + 12
        except Exception:
            pass

    if nombre_inm:
        _txt(draw, (M + logo_w, 52),
             nombre_inm.upper(), _load_font(19), _WHITE, sh=2)

    tipo_line = " · ".join(filter(None, [tipo.upper(), operacion.upper()]))
    if tipo_line:
        _txt_right(draw, 46, tipo_line, _load_font(18), _WHITE, sh=1)


# ── Slide 0: Intro ────────────────────────────────────────────────────────────
def _slide_intro(specs: dict, nombre: str) -> str:
    """Ciudad grande + dirección + precio. Vignette cinematográfica profunda."""
    from PIL import Image, ImageDraw
    ov = _canvas()

    top = _vignette(VW, 320, 200, 0, exp=2.2)
    ov.paste(top, (0, 0), top)
    bot = _vignette(VW, 650, 0, 255, exp=1.8)   # negro sólido en los últimos 100px
    ov.paste(bot, (0, VH - 650), bot)

    draw = ImageDraw.Draw(ov)
    _header(ov, draw, specs, nombre)
    M = 48

    ciudad    = (specs.get("ciudad") or "").upper().strip()
    direccion = str(specs.get("direccion") or "")

    # Ciudad: tipografía extra bold, enorme — baja para dejar respiro visual
    if ciudad:
        _txt(draw, (M, 960), ciudad, _load_font(110, bold=True), _WHITE, sh=4)

    # Línea oro ultra-fina bajo la ciudad
    if ciudad:
        _sep(draw, M, 1096, w=200)

    # Dirección: tipografía regular, discreta
    if direccion:
        _txt(draw, (M, 1112), direccion[:46], _load_font(28), _WHITE_DIM, sh=2)

    # El precio NO aparece aquí — solo en el slide de cierre (gran revelación final)

    path = str(Path(tempfile.mkdtemp()) / "s_intro.png")
    ov.save(path, "PNG")
    return path


# ── Slide N: Dato único ────────────────────────────────────────────────────────
def _slide_dato(value: str, label: str, specs: dict, nombre: str) -> str:
    """
    Layout de referencia: UN dato por slide, esquina inferior-izquierda.

    Estructura de abajo hacia arriba:
      VH-82 : precio (gold, regular)
      VH-130: línea dorada (2px)
      VH-165: label (champagne, 22px)  ← "HABITACIONES", "M² · ÁREA"…
      VH-275: valor (blanco bold, 88px) ← "2", "200"…

    La vignette cubre el 48% inferior del frame → el texto flota con
    máximo contraste sobre cualquier foto de fondo.
    """
    from PIL import Image, ImageDraw
    ov   = _canvas()
    top  = _vignette(VW, 300, 190, 0, exp=2.2)
    ov.paste(top, (0, 0), top)
    bot  = _vignette(VW, 650, 0, 255, exp=1.6)
    ov.paste(bot, (0, VH - 650), bot)

    draw = ImageDraw.Draw(ov)
    _header(ov, draw, specs, nombre)

    M   = 48
    fv  = _load_font(88, bold=True)
    fl  = _load_font(22)

    # Anclas sin precio — todo baja para llenar el espacio liberado
    y_sep   = VH - 92    # línea dorada cerca del borde
    y_label = VH - 130   # label champagne
    y_val   = VH - 240   # número grande blanco

    # El precio NO aparece en slides intermedios — solo en el cierre final
    _sep(draw, M, y_sep)
    _txt(draw, (M, y_label), label, fl, _CHAMPAGNE, sh=1)
    _txt(draw, (M, y_val),   value, fv, _WHITE,     sh=3)

    path = str(Path(tempfile.mkdtemp()) / f"s_{label[:6].lower()}.png")
    ov.save(path, "PNG")
    return path


# ── Slide: Amenidad individual ────────────────────────────────────────────────
_AMENIDAD_ICONS = {
    "Piscina": "◉", "Jardín": "◉", "Seguridad 24h": "◉",
    "Gimnasio": "◉", "Zonas comunes": "◉", "BBQ / Asador": "◉",
    "Cuarto de servicio": "◉", "Parque infantil": "◉",
    "Salón comunal": "◉", "Ascensor": "◉", "Terraza": "◉", "Bodega": "◉",
}

def _slide_amenidad_single(amenidad: str, specs: dict, nombre: str) -> str:
    """
    Una amenidad por slide — texto flotante elegante sobre vignette profunda.
    Label 'INCLUYE' en champagne · Nombre en bold blanco grande · línea dorada.
    """
    from PIL import Image, ImageDraw
    ov = _canvas()

    top = _vignette(VW, 300, 190, 0, exp=2.2)
    ov.paste(top, (0, 0), top)
    bot = _vignette(VW, 600, 0, 255, exp=1.7)
    ov.paste(bot, (0, VH - 600), bot)

    draw = ImageDraw.Draw(ov)
    _header(ov, draw, specs, nombre)

    M = 48

    f_label = _load_font(20)
    f_name  = _load_font(72, bold=True)

    # Sin precio — todo baja hacia el borde inferior
    y_sep   = VH - 92
    y_name  = VH - 210
    y_label = y_name - 36

    # El precio NO aparece aquí — solo en el slide de cierre
    _sep(draw, M, y_sep)
    _txt(draw, (M, y_name),  amenidad.upper(), f_name,  _WHITE,     sh=4)
    _txt(draw, (M, y_label), "INCLUYE",        f_label, _CHAMPAGNE, sh=1)

    path = str(Path(tempfile.mkdtemp()) / f"ov_am_{amenidad[:10].lower().replace(' ','_')}.png")
    ov.save(path, "PNG")
    return path


# ── Slide: Amenidades (chips, fallback si hay muchas) ─────────────────────────
def _slide_amenidades(specs: dict, nombre: str) -> str:
    """Chips minimalistas de zonas comunes. Si no hay, cae al intro."""
    from PIL import Image, ImageDraw
    amenidades = specs.get("amenidades") or []
    if not amenidades:
        return _slide_intro(specs, nombre)

    ov = _canvas()
    top = _vignette(VW, 250, 155, 0)
    ov.paste(top, (0, 0), top)
    bot = _vignette(VW, 440, 0, 220)
    ov.paste(bot, (0, VH - 440), bot)

    draw = ImageDraw.Draw(ov)
    _header(ov, draw, specs, nombre)
    M = 46

    # Título sección
    ft = _load_font(22)
    _txt(draw, (M, VH - 430), "ZONAS COMUNES", ft, _GOLD, sh=1)
    # Línea dorada sutil
    draw.line([(M, VH - 400), (VW - M, VH - 400)],
              fill=(255, 210, 0, 55), width=1)

    # Chips
    fc = _load_font(21)
    px, py = 16, 8
    gap = 10
    x, y = M, VH - 388

    for am in amenidades[:8]:
        bb = draw.textbbox((0, 0), am, font=fc)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        cw, ch = tw + px * 2, th + py * 2

        if x + cw > VW - M:
            x  = M
            y += ch + gap

        draw.rounded_rectangle(
            [x, y, x + cw, y + ch],
            radius=ch // 2,
            fill=(0, 0, 0, 35),
            outline=(255, 255, 255, 75),
            width=1,
        )
        draw.text((x + px, y + py), am, font=fc, fill=_WHITE)
        x += cw + gap

    path = str(Path(tempfile.mkdtemp()) / "s_amen.png")
    ov.save(path, "PNG")
    return path


# ── Slide: Cierre (precio + ciudad pequeña) ───────────────────────────────────
def _slide_cierre(specs: dict, nombre: str) -> str:
    """Diapositiva de cierre elegante: precio centrado + ciudad discreta."""
    from PIL import Image, ImageDraw
    ov = _canvas()

    top = _vignette(VW, 250, 155, 0)
    ov.paste(top, (0, 0), top)
    bot = _vignette(VW, 480, 0, 235)
    ov.paste(bot, (0, VH - 480), bot)

    draw = ImageDraw.Draw(ov)
    _header(ov, draw, specs, nombre)

    precio = str(specs.get("precio") or "")
    ciudad = (specs.get("ciudad") or "").upper().strip()

    if ciudad:
        _txt_center(draw, VH - 440, ciudad, _load_font(28), _WHITE_DIM, sh=1)

    # Línea dorada sutil
    draw.line([(VW // 4, VH - 400), (3 * VW // 4, VH - 400)],
              fill=(255, 210, 0, 90), width=1)

    if precio:
        _txt_center(draw, VH - 370, precio, _load_font(66, bold=True), _GOLD, sh=3)

    path = str(Path(tempfile.mkdtemp()) / "s_cierre.png")
    ov.save(path, "PNG")
    return path


# ── Fábrica de overlays ───────────────────────────────────────────────────────

def _build_sequence(specs: dict) -> List[str]:
    """
    Narrativa intercalada: spec → amenidad → spec → amenidad → cierre.
    Cada amenidad tiene su propio slide con prefijo 'am:'.
    Las amenidades se distribuyen a lo largo del video, no todas juntas.
    """
    seq = ["intro"]

    specs_slides: List[str] = []
    if specs.get("metros") or specs.get("metros_construidos"):
        specs_slides.append("area")
    if specs.get("habitaciones"):
        specs_slides.append("habitaciones")
    if specs.get("banos"):
        specs_slides.append("banos")
    if specs.get("estacionamientos"):
        specs_slides.append("garaje")

    amenidades = list(specs.get("amenidades") or [])[:5]  # max 5 amenidades
    am_slides  = [f"am:{a}" for a in amenidades]

    # Intercalar: spec, amenidad, spec, amenidad, ...
    i_s, i_a = 0, 0
    while i_s < len(specs_slides) or i_a < len(am_slides):
        if i_s < len(specs_slides):
            seq.append(specs_slides[i_s]); i_s += 1
        if i_a < len(am_slides):
            seq.append(am_slides[i_a]); i_a += 1

    seq.append("cierre")
    return seq


def _build_overlays(specs: dict, nombre: str, sequence: List[str]
                    ) -> Dict[str, Optional[str]]:
    """Pre-genera cada tipo de overlay una sola vez (cacheado por tipo)."""
    cache: Dict[str, Optional[str]] = {}
    for stype in set(sequence):
        try:
            if stype == "intro":
                cache[stype] = _slide_intro(specs, nombre)
            elif stype == "area":
                v = str(specs.get("metros") or specs.get("metros_construidos") or "")
                cache[stype] = _slide_dato(v, "M²  ·  ÁREA", specs, nombre)
            elif stype == "habitaciones":
                v = str(specs.get("habitaciones") or "")
                cache[stype] = _slide_dato(v, "HABITACIONES", specs, nombre)
            elif stype == "banos":
                v = str(specs.get("banos") or "")
                cache[stype] = _slide_dato(v, "BAÑOS", specs, nombre)
            elif stype == "garaje":
                v = str(specs.get("estacionamientos") or "")
                cache[stype] = _slide_dato(v, "GARAJE", specs, nombre)
            elif stype == "amenidades":
                cache[stype] = _slide_amenidades(specs, nombre)
            elif stype == "cierre":
                cache[stype] = _slide_cierre(specs, nombre)
            elif stype.startswith("am:"):
                amenidad_name = stype[3:]
                cache[stype] = _slide_amenidad_single(amenidad_name, specs, nombre)
            log.info("Overlay '%s' OK", stype)
        except Exception as e:
            log.warning("Overlay '%s' falló: %s", stype, e)
            cache[stype] = None
    return cache


# ─── Outro ────────────────────────────────────────────────────────────────────

def _create_outro(nombre: str, telefono: str, specs: dict) -> str:
    """
    Pantalla de cierre: fondo oscuro elegante + logo + foto circular agente
    con anillo dorado + nombre + WhatsApp en dorado.
    """
    from PIL import Image, ImageDraw, ImageFilter

    W, H = VW, VH

    # Fondo degradado oscuro
    tiny = Image.new("RGBA", (1, 2))
    tiny.putpixel((0, 0), (10, 10, 16, 255))
    tiny.putpixel((0, 1), (22, 18, 14, 255))
    frame = tiny.resize((W, H), Image.BILINEAR).convert("RGBA")

    # Glow dorado central suavísimo
    try:
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(
            [W // 4, H // 5, 3 * W // 4, 4 * H // 5],
            fill=(65, 48, 6, 30))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=220))
        frame = Image.alpha_composite(frame, glow)
    except Exception:
        pass

    draw       = ImageDraw.Draw(frame)
    gold       = (255, 210, 0, 255)
    nombre_inm = str(specs.get("nombre_inmobiliaria") or nombre or "")
    logo_src   = str(specs.get("logo_path") or specs.get("logo_url") or "")
    foto_ag    = str(specs.get("foto_agente") or "")
    cy         = 130

    # Logo
    logo_local = _fetch_img(logo_src)
    if logo_local:
        try:
            logo_img = Image.open(logo_local).convert("RGBA")
            logo_img.thumbnail((90, 90), Image.LANCZOS)
            lx = (W - logo_img.width) // 2
            frame.paste(logo_img, (lx, cy), logo_img)
            cy += logo_img.height + 24
        except Exception:
            pass

    # Línea dorada
    draw.rectangle([W // 3, cy, 2 * W // 3, cy + 2], fill=gold)
    cy += 40

    # Nombre del usuario / empresa (sin prefijo "Inmobiliaria")
    if nombre_inm:
        fi = _load_font(23)
        bb = draw.textbbox((0, 0), nombre_inm.upper(), font=fi)
        draw.text(((W - (bb[2] - bb[0])) // 2, cy), nombre_inm.upper(), font=fi,
                  fill=(175, 175, 175, 175))
        cy += 50

    cy = max(cy, 480)

    # Foto circular del agente
    foto_local = _fetch_img(foto_ag)
    if foto_local:
        try:
            size = 160
            ag   = Image.open(foto_local).convert("RGBA").resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
            circle = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            circle.paste(ag, (0, 0), mask)

            # Anillo dorado
            ring_sz = size + 8
            ring    = Image.new("RGBA", (ring_sz, ring_sz), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse(
                [0, 0, ring_sz - 1, ring_sz - 1],
                outline=(255, 210, 0, 190), width=3)
            ring.paste(circle, (4, 4), circle)

            lx = (W - ring_sz) // 2
            frame.paste(ring, (lx, cy), ring)
            cy += ring_sz + 26
        except Exception:
            pass

    # Nombre agente
    if nombre:
        fn = _load_font(52, bold=True)
        bb = draw.textbbox((0, 0), nombre, font=fn)
        draw.text(((W - (bb[2] - bb[0])) // 2, cy), nombre, font=fn,
                  fill=(255, 255, 255, 255))
        cy += 74

    # Separador
    draw.rectangle([(W // 2 - 22), cy, (W // 2 + 22), cy + 2], fill=gold)
    cy += 40

    # WhatsApp
    if telefono:
        fl2 = _load_font(20)
        lbl = "WhatsApp · Llama ahora"
        bb  = draw.textbbox((0, 0), lbl, font=fl2)
        draw.text(((W - (bb[2] - bb[0])) // 2, cy), lbl, font=fl2,
                  fill=(145, 145, 145, 155))
        cy += 38
        ft2 = _load_font(44, bold=True)
        bb  = draw.textbbox((0, 0), telefono, font=ft2)
        draw.text(((W - (bb[2] - bb[0])) // 2, cy), telefono, font=ft2, fill=gold)

    # Branding
    fb    = _load_font(15)
    brand = "Creado con LISTAPRO"
    bb    = draw.textbbox((0, 0), brand, font=fb)
    draw.text(((W - (bb[2] - bb[0])) // 2, H - 60), brand, font=fb,
              fill=(60, 60, 60, 140))

    path = str(Path(tempfile.mkdtemp()) / "outro.png")
    frame.save(path, "PNG")
    return path


def _outro_clip(outro_png: str, dur: float = 4.0) -> str:
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
    return out


# ─── clip factory ─────────────────────────────────────────────────────────────

def _make_clip(jpeg: str, idx: int, overlay_path: Optional[str] = None,
               dur: float = DUR_PER) -> str:
    """
    JPEG → clip MP4 1080×1350 con Smart Crop centrado.

    Smart Crop:
      scale con force_original_aspect_ratio=increase escala la foto hasta
      que CUBRE completamente el marco 4:5 (sin barras ni blur).
      crop=1080:1350 recorta al centro lo que sobre → cero píxeles vacíos.

    Con overlay: el PNG Pillow (vignette + textos) se pega encima del crop.
    """
    out         = str(Path(tempfile.mkdtemp()) / f"clip_{idx}.mp4")
    fade_out_st = max(0.0, dur - FADE_DUR)

    if overlay_path:
        # Secuencia cinematográfica:
        #   0s         → FADE_DUR : foto aparece desde negro (clip transition)
        #   FADE_DUR   → +TEXT_FADE_IN : vignette + textos se disuelven suavemente
        #   resto      : foto + datos 100% visibles
        #   fade_out_st → fin : clip funde a negro (transición siguiente)
        fc = (
            f"[0:v]scale={VW}:{VH}:force_original_aspect_ratio=increase,"
            f"crop={VW}:{VH}[photo];"
            f"[1:v]format=rgba,"
            f"fade=t=in:st={FADE_DUR:.3f}:d={TEXT_FADE_IN:.3f}:alpha=1[ov];"
            f"[photo][ov]overlay=0:0[main];"
            f"[main]fade=t=in:st=0:d={FADE_DUR},"
            f"fade=t=out:st={fade_out_st:.3f}:d={FADE_DUR}[out]"
        )
        inputs = ["-loop", "1", "-i", jpeg, "-loop", "1", "-i", overlay_path]
    else:
        fc = (
            f"[0:v]scale={VW}:{VH}:force_original_aspect_ratio=increase,"
            f"crop={VW}:{VH},"
            f"fade=t=in:st=0:d={FADE_DUR},"
            f"fade=t=out:st={fade_out_st:.3f}:d={FADE_DUR}[out]"
        )
        inputs = ["-loop", "1", "-i", jpeg]

    cmd = [_ffmpeg_bin(), "-y"] + inputs + [
        "-filter_complex", fc, "-map", "[out]",
        "-t", str(dur), "-r", str(FPS), "-map_metadata", "-1",
        "-c:v", "libx264", "-profile:v", "high", "-level:v", "4.2",
        "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-bsf:v", "filter_units=remove_types=6", out,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace")[-600:])
    size = os.path.getsize(out)
    if size < 1000:
        raise RuntimeError(f"Clip {idx} vacío ({size} bytes)")
    log.info("Clip %d OK (%d bytes)", idx, size)
    return out


# ─── pipeline principal ───────────────────────────────────────────────────────

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
      1. Fotos → JPEG limpio (sin ICC)
      2. Secuencia de slides según datos disponibles
      3. Overlays PNG pre-generados por tipo (Pillow, cacheados)
      4. Clips: blur bg + overlay + fade in/out (FFmpeg, sin Ken Burns)
      5. Outro de contacto del agente
      6. Concat -c copy + faststart
    """
    if not ffmpeg_available():
        raise RuntimeError("FFmpeg no está instalado en este servidor.")

    specs = specs or {}

    # 1. Fotos → JPEG
    jpegs: List[str] = []
    for src in photo_sources[:6]:
        try:
            jpegs.append(_to_jpeg(src))
            log.info("Foto %d/%d OK", len(jpegs), min(len(photo_sources), 6))
        except Exception as e:
            log.warning("Foto omitida (%s): %s", src, e)

    if not jpegs:
        raise ValueError("No se pudo obtener ninguna foto.")

    # 2. Secuencia de slides
    sequence = _build_sequence(specs)

    # 3. Pre-generar overlays
    ov_cache = _build_overlays(specs, nombre, sequence)

    # 4. Clips — añade zona de foto (Sala, Cocina…) si el usuario la nombró
    foto_labels = specs.get("foto_labels") or []
    clips: List[str] = []
    for i, jp in enumerate(jpegs):
        stype    = sequence[i % len(sequence)]
        base_ov  = ov_cache.get(stype)
        zone     = foto_labels[i] if i < len(foto_labels) else ""
        ov       = _add_zone(base_ov, zone) if zone else base_ov
        clips.append(_make_clip(jp, i, overlay_path=ov, dur=dur_per))

    # 5. Outro
    try:
        outro_png  = _create_outro(nombre, telefono, specs)
        outro_clip = _outro_clip(outro_png, dur=4.0)
        clips.append(outro_clip)
        log.info("Outro OK")
    except Exception as e:
        log.warning("Outro omitido: %s", e)

    # 6. Concat -c copy
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
            f"Concat error:\n{r.stderr.decode('utf-8', errors='replace')[-800:]}")

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
