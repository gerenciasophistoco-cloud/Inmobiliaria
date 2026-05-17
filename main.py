import asyncio
import json as _json
import logging
import os
import re
import shutil
import tempfile
import unicodedata
import uuid

log = logging.getLogger(__name__)
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from anthropic import AsyncAnthropic
from pydantic import BaseModel

import db
import storage

load_dotenv()

app = FastAPI(title="ListaPro")

# ── Protección del panel de administración ────────────────────────────────────
_http_basic = HTTPBasic(auto_error=False)

def require_admin(credentials: Optional[HTTPBasicCredentials] = Depends(_http_basic)):
    """
    Protege todas las rutas /admin con HTTP Basic Auth.
    Configura en Railway → Variables:
      ADMIN_USER     = tu_usuario   (defecto: "admin")
      ADMIN_PASSWORD = tu_contraseña_secreta
    Si ADMIN_PASSWORD no está configurada, el panel queda desprotegido
    y aparece un aviso en los logs (solo para desarrollo local).
    """
    import secrets
    pwd = os.getenv("ADMIN_PASSWORD", "").strip()
    usr = os.getenv("ADMIN_USER", "admin").strip()

    if not pwd:
        log.warning("⚠️  ADMIN_PASSWORD no configurada — panel de admin SIN protección")
        return "dev"

    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Acceso al panel de administración requerido.",
            headers={"WWW-Authenticate": 'Basic realm="ListaPro Admin"'},
        )

    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), usr.encode("utf-8")
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), pwd.encode("utf-8")
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Usuario o contraseña incorrectos.",
            headers={"WWW-Authenticate": 'Basic realm="ListaPro Admin"'},
        )
    return credentials.username

# ── Patrón UUID para distinguir IDs legacy de slugs amigables ────────────────
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _make_slug(tipo: str, direccion: str, ciudad: str) -> str:
    """
    Genera un slug SEO-friendly.
    Ej: 'Casa Cra 70c Medellín' → 'casa-cra-70c-medellin'
    """
    # Tomar solo la primera parte de la dirección (antes de la coma o #)
    dir_short = re.split(r'[,#]', direccion or '')[0].strip()[:35]
    raw  = f"{tipo} {dir_short} {ciudad}"
    # Quitar tildes y diacríticos
    norm = unicodedata.normalize('NFKD', raw)
    text = ''.join(c for c in norm if not unicodedata.combining(c))
    # Solo alfanuméricos y espacios, luego reemplazar espacios por guiones
    text = re.sub(r'[^a-z0-9\s]', '', text.lower())
    text = re.sub(r'\s+', '-', text.strip())
    return text[:65]


def _unique_slug(base: str) -> str:
    """Garantiza que el slug sea único en la DB añadiendo -1, -2… si hay colisión."""
    if not db.get_property_by_slug(base):
        return base
    for i in range(1, 200):
        candidate = f"{base}-{i}"
        if not db.get_property_by_slug(candidate):
            return candidate
    return f"{base}-{uuid.uuid4().hex[:6]}"   # fallback extremo


BASE_DIR = Path(__file__).parent
_tpl_dir = BASE_DIR / "Templates"
if not _tpl_dir.exists():
    _tpl_dir = BASE_DIR / "templates"
templates = Jinja2Templates(directory=str(_tpl_dir))

# Crear carpetas necesarias si no existen (por si Railway no las recibe del repo)
_static_dir  = BASE_DIR / "static"
_uploads_dir = BASE_DIR / "uploads"
_static_dir.mkdir(exist_ok=True)
_uploads_dir.mkdir(exist_ok=True)

app.mount("/static",   StaticFiles(directory=str(_static_dir)),   name="static")
app.mount("/uploads",  StaticFiles(directory=str(_uploads_dir)),  name="uploads")


# ── Modelo para video y página web ───────────────────────────────────────────
class PropertyRequest(BaseModel):
    tipo_propiedad: str
    operacion: str
    direccion: str
    ciudad: str
    precio: str
    habitaciones: Optional[str] = None
    banos: Optional[str] = None
    metros_construidos: Optional[str] = None
    metros_terreno: Optional[str] = None
    estacionamientos: Optional[str] = None
    amenidades: List[str] = []
    descripcion: str
    descripcion_2: Optional[str] = None
    frase_inspiradora: Optional[str] = None
    fotos: List[str] = []
    nombre_agente: str
    telefono_agente: str
    email_agente: Optional[str] = None
    logo: Optional[str] = None
    foto_agente: Optional[str] = None
    estrato: Optional[str] = None
    ano_construccion: Optional[str] = None
    nombre_inmobiliaria: Optional[str] = None
    label_2: Optional[str] = None
    label_3: Optional[str] = None
    label_4: Optional[str] = None
    label_5: Optional[str] = None
    label_6: Optional[str] = None
    label_7: Optional[str] = None
    label_8: Optional[str] = None
    label_9: Optional[str] = None
    label_10: Optional[str] = None
    property_id: Optional[str] = None        # para actualizar DB cuando el video termine
    video_url_propio: Optional[str] = None   # Plan A: URL del video subido por el usuario


def extract_logo_palette(logo_path: str) -> dict:
    try:
        from PIL import Image
        img = Image.open(logo_path).convert("RGB").resize((120, 120))
        q = img.quantize(colors=8, method=2)
        pal = q.getpalette()[:24]
        raw = [(pal[i], pal[i+1], pal[i+2]) for i in range(0, 24, 3)]
        filtered = [c for c in raw if 30 < (c[0]+c[1]+c[2])/3 < 220]
        if not filtered:
            filtered = raw
        p = filtered[0] if filtered else (12, 38, 82)
        s = filtered[1] if len(filtered) > 1 else (205, 162, 50)
        a = filtered[2] if len(filtered) > 2 else (29, 78, 216)
        return {"primary": list(p), "secondary": list(s), "accent": list(a)}
    except Exception:
        return {"primary": [12, 38, 82], "secondary": [205, 162, 50], "accent": [29, 78, 216]}


def _parse_descriptions(raw: str) -> list:
    """
    Extrae el array de descripciones de la respuesta del modelo.
    Tolera markdown (```json...```), texto previo/posterior y arrays anidados.
    """
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
    if m:
        try:
            result = _json.loads(m.group(1).strip())
            if isinstance(result, list) and result:
                return [str(s).strip() for s in result if s]
        except Exception:
            pass

    try:
        start = raw.index('[')
        depth, end = 0, -1
        in_string, escape = False, False
        for i in range(start, len(raw)):
            c = raw[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_string:
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if not in_string:
                if c == '[':
                    depth += 1
                elif c == ']':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
        if end > start:
            result = _json.loads(raw[start:end + 1])
            if isinstance(result, list) and result:
                return [str(s).strip() for s in result if s]
    except Exception:
        pass

    try:
        found = re.findall(r'"((?:[^"\\]|\\.){20,})"', raw)
        if found:
            return [s.strip() for s in found[:5]]
    except Exception:
        pass

    return [raw]


def get_client() -> AsyncAnthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY no configurada. Agrégala en Railway → Variables.",
        )
    return AsyncAnthropic(api_key=api_key)


def _whatsapp_link(telefono: str, mensaje: str = "") -> str:
    clean = re.sub(r"\D", "", telefono)
    import urllib.parse
    return f"https://wa.me/57{clean}?text={urllib.parse.quote(mensaje)}" if clean else "#"


# ── Página principal (formulario) ────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


# ── Editar propiedad existente ────────────────────────────────────────────────
@app.get("/admin/editar/{property_id}", response_class=HTMLResponse)
async def editar_propiedad(property_id: str, _: str = Depends(require_admin)):
    data = db.get_property(property_id)
    if not data:
        raise HTTPException(status_code=404, detail="Propiedad no encontrada")
    # Extraer precio numérico del formato "$850.000.000 COP"
    precio_raw = re.sub(r"[^\d]", "", data.get("precio", ""))
    edit_payload = _json.dumps({
        "property_id":       property_id,
        "tipo_propiedad":    data.get("tipo_propiedad", ""),
        "operacion":         data.get("operacion", "Venta"),
        "ciudad":            data.get("ciudad", ""),
        "precio":            precio_raw,
        "direccion":         data.get("direccion", ""),
        "habitaciones":      data.get("habitaciones") or "",
        "banos":             data.get("banos") or "",
        "metros_construidos": data.get("metros") or "",
        "metros_terreno":    data.get("metros_terreno") or "",
        "estacionamientos":  data.get("estacionamientos") or "",
        "estrato":           data.get("estrato") or "",
        "ano_construccion":  data.get("ano_construccion") or "",
        "otras_caracteristicas":  data.get("otras_caracteristicas") or "",
        "caracteristicas_extra":  data.get("caracteristicas_extra") or [],
        "nombre_inmobiliaria": data.get("nombre_inmobiliaria") or "",
        "nombre_agente":     data.get("nombre_agente") or "",
        "telefono_agente":   data.get("telefono_agente") or "",
        "email_agente":      data.get("email_agente") or "",
        "amenidades":        data.get("amenidades") or [],
        "coordenadas":       data.get("coordenadas") or "",
        "fotos":             data.get("fotos") or [],
        "foto_labels":       data.get("foto_labels") or [],
        "foto_descriptions": data.get("foto_descriptions") or [],
        "video_recorrido_url": data.get("video_recorrido_url") or "",
        "slug":              data.get("slug") or property_id,
    }, ensure_ascii=False)
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()
    inject = (
        f'<script>window.EDIT_MODE=true;window.EDIT_DATA={edit_payload};</script>\n'
    )
    return html.replace("</head>", inject + "</head>", 1)


@app.post("/admin/actualizar/{property_id}")
async def actualizar_propiedad(
    property_id: str,
    _: str = Depends(require_admin),
    tipo_propiedad: str = Form(...),
    operacion:      str = Form(...),
    direccion:      str = Form(...),
    ciudad:         str = Form(...),
    precio:         str = Form(...),
    habitaciones:   Optional[str] = Form(None),
    banos:          Optional[str] = Form(None),
    metros_construidos: Optional[str] = Form(None),
    metros_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    estrato:        Optional[str] = Form(None),
    ano_construccion: Optional[str] = Form(None),
    amenidades:     List[str] = Form(default=[]),
    otras_caracteristicas: Optional[str] = Form(None),
    caracteristicas_extra: Optional[str] = Form(default="[]"),  # JSON: [{"nombre":"Cocinas","valor":"2"}]
    nombre_inmobiliaria: Optional[str] = Form(None),
    nombre_agente:  str = Form(...),
    telefono_agente: str = Form(...),
    email_agente:   Optional[str] = Form(None),
    coordenadas:    Optional[str] = Form(None),
    fotos_existentes:   List[str] = Form(default=[]),     # URLs que el usuario conservó
    labels_existentes:  Optional[str] = Form(default="[]"), # labels de las fotos existentes conservadas
    descs_existentes:   Optional[str] = Form(default="[]"), # descs  de las fotos existentes conservadas
    foto_labels:        Optional[str] = Form(default="[]"), # labels de las fotos NUEVAS
    foto_descriptions:  Optional[str] = Form(default="[]"), # descs  de las fotos NUEVAS
    video_recorrido_url: Optional[str] = Form(default=None),
    fotos:          List[UploadFile] = File(default=[]),
    foto_agente:    Optional[UploadFile] = File(default=None),
):
    existing = db.get_property(property_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Propiedad no encontrada")

    precio_digits = "".join(filter(str.isdigit, precio))
    precio_num    = int(precio_digits) if precio_digits else 0
    precio_fmt    = "$" + f"{precio_num:,}".replace(",", ".") + " COP"

    # Subir fotos nuevas si las hay
    new_foto_paths: List[str] = []
    for foto in fotos:
        if foto.filename and foto.filename.strip():
            url = storage.upload_file(foto.file, foto.filename, folder="listapro/fotos")
            if url:
                new_foto_paths.append(url)

    # Base de fotos: las que el usuario conservó (enviadas desde el frontend).
    # Si no se envió nada (petición legacy), mantener todas las existentes.
    old_fotos = existing.get("fotos") or []
    if fotos_existentes:
        foto_paths = [u for u in fotos_existentes if u]
        # Eliminar de Cloudinary las fotos que el usuario borró
        removed = [u for u in old_fotos if u and u not in set(foto_paths)]
        if removed:
            import threading as _th
            _th.Thread(target=storage.delete_files, args=(removed,), daemon=True).start()
            log.info("Eliminando %d foto(s) de Cloudinary en background", len(removed))
    else:
        foto_paths = old_fotos
    foto_paths = foto_paths + new_foto_paths

    # Foto del agente: reusar existente si no se subió nueva
    foto_agente_path = existing.get("foto_agente_url") or ""
    if foto_agente and foto_agente.filename and foto_agente.filename.strip():
        url = storage.upload_file(foto_agente.file, foto_agente.filename, folder="listapro/agentes")
        if url:
            foto_agente_path = url

    # Labels: [labels de fotos existentes conservadas] + [labels de fotos nuevas]
    labs_ex   = _json.loads(labels_existentes  or "[]")
    desc_ex   = _json.loads(descs_existentes   or "[]")
    labs_new  = _json.loads(foto_labels        or "[]")
    descs_new = _json.loads(foto_descriptions  or "[]")
    final_labels = labs_ex + labs_new
    final_descs  = desc_ex + descs_new

    # Video de recorrido: usar el nuevo si se envió, sino conservar el existente
    video_rec = video_recorrido_url or existing.get("video_recorrido_url") or None

    updated = {
        **existing,
        "tipo_propiedad":    tipo_propiedad,
        "operacion":         operacion,
        "direccion":         direccion,
        "ciudad":            ciudad,
        "precio":            precio_fmt,
        "habitaciones":      habitaciones or "",
        "banos":             banos or "",
        "metros":            metros_construidos or "",
        "metros_terreno":    metros_terreno or "",
        "estacionamientos":  estacionamientos or "",
        "estrato":           estrato or "",
        "ano_construccion":  ano_construccion or "",
        "amenidades":        amenidades or [],
        "otras_caracteristicas":  otras_caracteristicas or "",
        "caracteristicas_extra":  _json.loads(caracteristicas_extra or "[]"),
        "nombre_inmobiliaria": nombre_inmobiliaria or nombre_agente,
        "nombre_agente":     nombre_agente,
        "telefono_agente":   telefono_agente,
        "email_agente":      email_agente or "",
        "coordenadas":       coordenadas or "",
        "fotos":             foto_paths,
        "foto_labels":       final_labels,
        "foto_descriptions": final_descs,
        "foto_agente_url":   foto_agente_path,
        "video_recorrido_url": video_rec,
        "whatsapp_link":     _whatsapp_link(
            telefono_agente,
            f"Hola, estoy interesado en la propiedad en {direccion}, {ciudad}"
        ),
    }
    # Regenerar descripción con IA si el usuario puso notas en "otras_caracteristicas"
    descripciones_nuevas: list = []
    ig_copy_nuevo: str = ""
    frase_nueva: str = ""
    if otras_caracteristicas and otras_caracteristicas.strip():
        try:
            specs_list = []
            if habitaciones and habitaciones.strip() and habitaciones != "0":
                specs_list.append(f"{habitaciones} habitaciones")
            if banos and banos.strip() and banos != "0":
                specs_list.append(f"{banos} baños")
            if metros_construidos and metros_construidos.strip():
                specs_list.append(f"{metros_construidos} m² construidos")
            if metros_terreno and metros_terreno.strip():
                specs_list.append(f"{metros_terreno} m² de terreno")
            if estacionamientos and estacionamientos.strip() and estacionamientos != "0":
                specs_list.append(f"{estacionamientos} garaje(s)")
            otras_str = otras_caracteristicas.strip()
            amenidades_str = ", ".join(amenidades) if amenidades else "Ninguna especificada"
            property_info = (
                f"Tipo de propiedad: {tipo_propiedad}\nOperación: {operacion}\n"
                f"Ubicación: {direccion}, {ciudad}, Colombia\nPrecio: {precio_fmt}\n"
                f"Especificaciones: {', '.join(specs_list) if specs_list else 'No especificadas'}\n"
                f"Amenidades: {amenidades_str}\n"
                f"DETALLES CLAVE (OBLIGATORIO incluirlos): {otras_str}\n"
                f"Contacto: {nombre_agente} | {telefono_agente}"
            )
            desc_p = (
                f"Eres un experto en bienes raíces en Colombia.\n"
                f"Genera 5 descripciones DIFERENTES para esta propiedad en {operacion.lower()}. "
                f"Cada una con un enfoque distinto: 1.Emocional 2.Ubicación 3.Técnica 4.Estilo de vida 5.Breve.\n"
                f"Requisitos: español colombiano, tono elegante, 50-70 palabras, sin markdown.\n"
                f"RESPONDE SOLO con el array JSON sin texto adicional:\n"
                f'["desc1","desc2","desc3","desc4","desc5"]\nDatos:\n{property_info}'
            )
            ig_p = (
                f"Crea un copy irresistible para Instagram sobre esta propiedad en {operacion.lower()}. "
                f"Inicia con gancho+emojis, destaca 3-4 características, menciona precio y ubicación, "
                f"CTA para contactar a {nombre_agente} al {telefono_agente}, "
                f"cierra con 15-20 hashtags colombianos. Máx 2200 caracteres, texto plano.\nDatos:\n{property_info}"
            )
            frase_p = (
                f"Crea UNA frase corta y poética (máx 18 palabras) en español que inspire a querer vivir "
                f"en esta propiedad. Sin signos de exclamación, sin hashtags. Solo la frase.\nDatos:\n{property_info}"
            )
            ai = get_client()
            dr, ir, fr = await asyncio.gather(
                ai.messages.create(model="claude-sonnet-4-5", max_tokens=500,
                                   messages=[{"role": "user", "content": desc_p}]),
                ai.messages.create(model="claude-sonnet-4-5", max_tokens=800,
                                   messages=[{"role": "user", "content": ig_p}]),
                ai.messages.create(model="claude-sonnet-4-5", max_tokens=80,
                                   messages=[{"role": "user", "content": frase_p}]),
            )
            descripciones_nuevas = _parse_descriptions(dr.content[0].text.strip())
            ig_copy_nuevo  = ir.content[0].text.strip()
            frase_nueva    = fr.content[0].text.strip().strip('"').strip("'")
            # Guardar la primera descripción generada (el usuario puede cambiarla luego)
            updated["descripcion"]       = descripciones_nuevas[0]
            updated["frase_inspiradora"] = frase_nueva
            log.info("Descripciones regeneradas para %s (%d opciones)", property_id, len(descripciones_nuevas))
        except Exception as ai_err:
            log.warning("No se pudo regenerar descripción: %s", ai_err)

    db.save_property(property_id, updated)

    # Regenerar video siempre que haya fotos (mismo link, video actualizado)
    from video_utils import ffmpeg_available
    if ffmpeg_available() and foto_paths:
        import threading as _th
        task_id = str(uuid.uuid4())
        _video_tasks[task_id] = {
            "status": "running", "progress": 0,
            "status_text": "regenerando video",
            "output_path": None, "error": None, "video_url": None,
            "property_id": property_id,
        }
        video_data = {
            "fotos":               foto_paths,
            "nombre_agente":       nombre_agente,
            "telefono_agente":     telefono_agente,
            "habitaciones":        habitaciones or "",
            "banos":               banos or "",
            "metros_construidos":  metros_construidos or "",
            "estacionamientos":    estacionamientos or "",
            "precio":              precio_fmt,
            "ciudad":              ciudad,
            "direccion":           direccion,
            "tipo_propiedad":      tipo_propiedad,
            "operacion":           operacion,
            "nombre_inmobiliaria": nombre_inmobiliaria or nombre_agente,
            "amenidades":          amenidades or [],
            "foto_labels":         final_labels,
            "foto_descriptions":   final_descs,
            "foto_agente_url":     foto_agente_path,
            "logo_url":            existing.get("logo_url") or "",
            "video_url_propio":    None,
        }
        db.update_property(property_id, {"video_url": None, "video_ready": False})
        _th.Thread(
            target=_video_task,
            args=(task_id, video_data, property_id, "video_url"),
            daemon=True,
        ).start()

    slug = existing.get("slug") or property_id
    return JSONResponse({
        "ok":                True,
        "property_id":       property_id,
        "property_slug":     slug,
        "regenerating_video": bool(foto_paths),
        "descripciones":     descripciones_nuevas,
        "descripcion":       descripciones_nuevas[0] if descripciones_nuevas else "",
        "ig_copy":           ig_copy_nuevo,
        "frase_inspiradora": frase_nueva,
    })


# ── Diagnóstico de Cloudinary ────────────────────────────────────────────────
@app.get("/admin/test-cloudinary")
async def test_cloudinary(_: str = Depends(require_admin)):
    """
    Verifica si Cloudinary está correctamente configurado y operativo.
    Abre este link en Railway para diagnosticar problemas de subida de fotos.
    """
    result = storage.diagnose()
    return JSONResponse(result)


# ── Guardar descripción elegida por el usuario después de la edición ─────────
@app.post("/admin/descripcion/{property_id}")
async def guardar_descripcion(
    property_id: str,
    _: str = Depends(require_admin),
    descripcion:       str = Form(...),
    ig_copy:           Optional[str] = Form(None),
    frase_inspiradora: Optional[str] = Form(None),
):
    fields: dict = {"descripcion": descripcion}
    if ig_copy:           fields["ig_copy"]           = ig_copy
    if frase_inspiradora: fields["frase_inspiradora"] = frase_inspiradora
    ok = db.update_property(property_id, fields)
    return JSONResponse({"ok": ok})


# ── Panel de administración ───────────────────────────────────────────────────
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, _: str = Depends(require_admin)):
    properties  = db.get_all_properties()
    db_status   = db.connection_status()
    return templates.TemplateResponse("admin.html", {
        "request":        request,
        "properties":     properties,
        "db_persistente": db_status["connected"],
        "db_error":       db_status["error"],
        "db_url":         db_status["url"],
    })


@app.delete("/admin/propiedad/{property_id}")
async def eliminar_propiedad(property_id: str, _: str = Depends(require_admin)):
    """Elimina una propiedad permanentemente y borra sus fotos de Cloudinary."""
    data = db.get_property(property_id)
    if not data:
        raise HTTPException(status_code=404, detail="Propiedad no encontrada")

    # Eliminar fotos de Cloudinary en background (no bloquea la respuesta)
    fotos_a_borrar = [u for u in (data.get("fotos") or []) if u]
    if fotos_a_borrar:
        import threading as _th
        _th.Thread(target=storage.delete_files, args=(fotos_a_borrar,), daemon=True).start()

    ok = db.delete_property(property_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Propiedad no encontrada")
    return JSONResponse({"deleted": True, "fotos_eliminadas": len(fotos_a_borrar)})


@app.post("/admin/acceso/{property_id}")
async def toggle_acceso(property_id: str, _: str = Depends(require_admin)):
    """Activa o desactiva el acceso público a un inmueble."""
    data = db.get_property(property_id)
    if not data:
        raise HTTPException(status_code=404)
    nuevo = not bool(data.get("acceso_activo", True))
    db.update_property(property_id, {"acceso_activo": nuevo})
    return JSONResponse({"acceso_activo": nuevo})


# ── Ruta de prueba con datos de ejemplo ──────────────────────────────────────
@app.get("/test-video")
async def test_video_generation():
    """
    Endpoint de prueba interna del motor de video.
    Llama a /test-video en Railway para verificar sin llenar el formulario.
    Usa 3 fotos reales de Unsplash (JPEG sin ICC Profile problemático).
    """
    import video_utils
    import traceback

    TEST_PHOTOS = [
        "https://images.unsplash.com/photo-1560448204-603b3fc33ddc?w=800",
        "https://images.unsplash.com/photo-1600210492486-724fe5c67fb0?w=800",
        "https://images.unsplash.com/photo-1484154218962-a197022b5858?w=800",
    ]

    if not video_utils.ffmpeg_available():
        return JSONResponse({"ok": False, "error": "FFmpeg no disponible en este servidor"})

    try:
        output = video_utils.generate_slideshow(
            photo_sources=TEST_PHOTOS,
            nombre="Test Agente",
            telefono="300 000 0000",
            specs={},
            dur_per=3.0,
        )
        size_kb = os.path.getsize(output) // 1024
        return JSONResponse({
            "ok": True,
            "mensaje": f"Video generado correctamente ({size_kb} KB)",
            "path": output,
        })
    except Exception as e:
        return JSONResponse({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc()[-1000:],
        })


@app.get("/test")
async def test_propiedad(request: Request):
    datos_ejemplo = {
        "tipo_propiedad":    "Apartamento",
        "operacion":         "Venta",
        "ciudad":            "Bogotá",
        "direccion":         "Calle 127 # 15-40, Usaquén",
        "precio":            "$850.000.000 COP",
        "habitaciones":      "3",
        "banos":             "2",
        "metros":            "95",
        "metros_terreno":    None,
        "estacionamientos":  "1",
        "estrato":           "5",
        "ano_construccion":  "2019",
        "amenidades": [
            "Piscina", "Gimnasio", "Salón comunal",
            "Seguridad 24h", "Ascensor", "BBQ / Asador",
        ],
        "descripcion": (
            "Moderno apartamento ubicado en uno de los sectores más exclusivos de Bogotá. "
            "Amplios espacios con acabados de primera, iluminación natural en todos los ambientes "
            "y una vista privilegiada de la ciudad. El conjunto residencial cuenta con completas "
            "zonas comunes diseñadas para el disfrute de toda la familia. Una oportunidad única "
            "para vivir con confort, seguridad y distinción."
        ),
        "frase_inspiradora": "Donde cada amanecer se convierte en el horizonte que siempre soñaste.",
        "fotos": [
            "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1200",
            "https://images.unsplash.com/photo-1600210492486-724fe5c67fb0?w=800",
            "https://images.unsplash.com/photo-1560448204-603b3fc33ddc?w=800",
            "https://images.unsplash.com/photo-1484154218962-a197022b5858?w=800",
            "https://images.unsplash.com/photo-1586105251261-72a756497a11?w=800",
            "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=800",
            "https://images.unsplash.com/photo-1618221195710-dd6b41faaea6?w=800",
            "https://images.unsplash.com/photo-1615529328331-f8917597711f?w=800",
            "https://images.unsplash.com/photo-1631049307264-da0ec9d70304?w=800",
        ],
        "logo_url":            None,
        "foto_agente_url":     None,
        "nombre_agente":       "María Fernanda Gómez",
        "telefono_agente":     "310 456 7890",
        "email_agente":        "mfgomez@inmobiliaria.co",
        "nombre_inmobiliaria": "Sophisto Inmobiliaria",
        "whatsapp_link":       "https://wa.me/573104567890?text=Hola%2C%20me%20interesa%20el%20apartamento",
        "video_url":           "https://www.w3schools.com/html/mov_bbb.mp4",
        "otras_propiedades": [
            {"nombre": "Apartamento en Tintal",   "precio": "$280.000.000 COP", "metros": "62", "habitaciones": "3", "banos": "2", "badge": "NUEVO",
             "foto": "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=600"},
            {"nombre": "Apartamento en Modelia",  "precio": "$410.000.000 COP", "metros": "75", "habitaciones": "3", "banos": "2", "badge": None,
             "foto": "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=600"},
            {"nombre": "Apartamento en Hayuelos", "precio": "$320.000.000 COP", "metros": "65", "habitaciones": "3", "banos": "2", "badge": None,
             "foto": "https://images.unsplash.com/photo-1570129477492-45c003edd2be?w=600"},
        ],
    }
    return templates.TemplateResponse("propiedad.html", {"request": request, **datos_ejemplo})


# ── Generación de contenido ──────────────────────────────────────────────────
@app.post("/generate")
async def generate_content(
    tipo_propiedad: str = Form(...),
    operacion: str = Form(...),
    direccion: str = Form(...),
    ciudad: str = Form(...),
    precio: str = Form(...),
    habitaciones: Optional[str] = Form(None),
    banos: Optional[str] = Form(None),
    metros_construidos: Optional[str] = Form(None),
    metros_terreno: Optional[str] = Form(None),
    estacionamientos: Optional[str] = Form(None),
    estrato: Optional[str] = Form(None),
    ano_construccion: Optional[str] = Form(None),
    amenidades: List[str] = Form(default=[]),
    otras_caracteristicas: Optional[str] = Form(None),
    caracteristicas_extra: Optional[str] = Form(default="[]"),
    foto_labels:        Optional[str] = Form(default="[]"),  # JSON: ["Sala","Cocina",…]
    foto_descriptions:  Optional[str] = Form(default="[]"),  # JSON: ["Americana","Principal",…]
    account_type: str = Form(default="particular"),
    nombre_inmobiliaria: Optional[str] = Form(None),
    nombre_agente: str = Form(...),
    telefono_agente: str = Form(...),
    email_agente: Optional[str] = Form(None),
    coordenadas: Optional[str] = Form(None),
    video_recorrido_url: Optional[str] = Form(None),
    fotos: List[UploadFile] = File(default=[]),
    logo: Optional[UploadFile] = File(default=None),
    foto_agente: Optional[UploadFile] = File(default=None),
):
    # Guardar logo
    # ── Subir archivos (Cloudinary en prod, disco local en dev) ──────────────
    logo_path = None
    logo_colors = None
    if logo and logo.filename and logo.filename.strip():
        logo_path = storage.upload_file(logo.file, logo.filename, folder="listapro/logos")
        if logo_path and logo_path.startswith("/uploads/"):
            logo_colors = extract_logo_palette(str(BASE_DIR / logo_path.lstrip("/")))

    foto_agente_path = None
    if foto_agente and foto_agente.filename and foto_agente.filename.strip():
        foto_agente_path = storage.upload_file(
            foto_agente.file, foto_agente.filename, folder="listapro/agentes"
        )

    foto_paths = []
    for foto in fotos:
        if foto.filename and foto.filename.strip():
            url = storage.upload_file(foto.file, foto.filename, folder="listapro/fotos")
            if url:
                foto_paths.append(url)

    # Formatear precio
    precio_digits = "".join(filter(str.isdigit, precio))
    precio_num = int(precio_digits) if precio_digits else 0
    precio_formatted = "$" + f"{precio_num:,}".replace(",", ".") + " COP"

    # Construir contexto para los prompts
    specs = []
    if habitaciones and habitaciones.strip() and habitaciones != "0":
        specs.append(f"{habitaciones} habitaciones")
    if banos and banos.strip() and banos != "0":
        specs.append(f"{banos} baños")
    if metros_construidos and metros_construidos.strip():
        specs.append(f"{metros_construidos} m² construidos")
    if metros_terreno and metros_terreno.strip():
        specs.append(f"{metros_terreno} m² de terreno")
    if estacionamientos and estacionamientos.strip() and estacionamientos != "0":
        specs.append(f"{estacionamientos} garaje(s)")

    amenidades_str = ", ".join(amenidades) if amenidades else "Ninguna especificada"
    otras_str = otras_caracteristicas.strip() if otras_caracteristicas else ""
    property_info = f"""Tipo de propiedad: {tipo_propiedad}
Operación: {operacion}
Ubicación: {direccion}, {ciudad}, Colombia
Precio: {precio_formatted}
Especificaciones: {", ".join(specs) if specs else "No especificadas"}
Amenidades: {amenidades_str}
{("DETALLES CLAVE del agente (OBLIGATORIO incluirlos en las descripciones): " + otras_str) if otras_str else ""}
Contacto: {nombre_agente} | {telefono_agente}{" | " + email_agente if email_agente else ""}"""

    desc_prompt = f"""Eres un experto en bienes raíces en Colombia con años de experiencia redactando descripciones que venden propiedades.

Genera 5 descripciones DIFERENTES para esta propiedad en {operacion.lower()}. Cada una con un enfoque distinto:
1. Emocional y aspiracional
2. Enfocada en la ubicación y el barrio
3. Técnica y detallada (características y especificaciones)
4. Estilo de vida (qué ofrece vivir ahí)
5. Breve y directa al grano

Requisitos por descripción:
- Español colombiano, tono elegante y persuasivo
- Entre 50 y 70 palabras
- Texto plano, sin asteriscos ni markdown

IMPORTANTE: Responde SOLO con el array JSON, sin texto antes ni después, sin bloques de código, sin comillas triples:
["descripción 1", "descripción 2", "descripción 3", "descripción 4", "descripción 5"]

Datos:
{property_info}"""

    ig_prompt = f"""Eres un especialista en marketing digital inmobiliario en Colombia.

Crea un copy irresistible para Instagram sobre esta propiedad en {operacion.lower()}.
- Inicia con un gancho con emojis
- Destaca 3-4 características
- Menciona precio y ubicación
- CTA para contactar a {nombre_agente} al {telefono_agente}
- Cierra con 15-20 hashtags colombianos de bienes raíces
- Máximo 2200 caracteres, texto plano sin markdown

Datos:
{property_info}"""

    frase_prompt = f"""Crea UNA frase corta y poética (máximo 18 palabras) en español que inspire a querer vivir en esta propiedad.
Sin signos de exclamación, sin hashtags. Solo la frase.

Datos:
{property_info}"""

    client = get_client()

    try:
        desc_resp, ig_resp, frase_resp = await asyncio.gather(
            client.messages.create(model="claude-sonnet-4-5", max_tokens=500,
                                   messages=[{"role": "user", "content": desc_prompt}]),
            client.messages.create(model="claude-sonnet-4-5", max_tokens=800,
                                   messages=[{"role": "user", "content": ig_prompt}]),
            client.messages.create(model="claude-sonnet-4-5", max_tokens=80,
                                   messages=[{"role": "user", "content": frase_prompt}]),
        )
        raw_desc = desc_resp.content[0].text.strip()
        descripciones = _parse_descriptions(raw_desc)
        descripcion = descripciones[0]
        ig_copy = ig_resp.content[0].text.strip()
        frase_inspiradora = frase_resp.content[0].text.strip().strip('"').strip("'")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar contenido: {str(e)}")


    # Generar slug amigable único
    property_id   = str(uuid.uuid4())
    property_slug = _unique_slug(_make_slug(tipo_propiedad, direccion, ciudad))

    db.save_property(property_id, {
        "slug":              property_slug,
        "tipo_propiedad":    tipo_propiedad,
        "operacion":         operacion,
        "direccion":         direccion,
        "ciudad":            ciudad,
        "precio":            precio_formatted,
        "habitaciones":      habitaciones,
        "banos":             banos,
        "metros":            metros_construidos,
        "metros_terreno":    metros_terreno,
        "estacionamientos":  estacionamientos,
        "estrato":           estrato,
        "ano_construccion":  ano_construccion,
        "amenidades":        amenidades,
        "foto_labels":        _json.loads(foto_labels       or "[]"),
        "foto_descriptions":  _json.loads(foto_descriptions or "[]"),
        "otras_caracteristicas":  otras_caracteristicas or "",
        "caracteristicas_extra":  _json.loads(caracteristicas_extra or "[]"),
        "descripcion":       descripcion,
        "frase_inspiradora": frase_inspiradora,
        "fotos":             foto_paths,
        "logo_url":          logo_path,
        "foto_agente_url":   foto_agente_path,
        "nombre_agente":     nombre_agente,
        "telefono_agente":   telefono_agente,
        "email_agente":      email_agente or "",
        "nombre_inmobiliaria": nombre_inmobiliaria or nombre_agente,
        "account_type":      account_type,
        "coordenadas":       coordenadas or "",
        "whatsapp_link":     _whatsapp_link(
            telefono_agente,
            f"Hola, estoy interesado en la propiedad en {direccion}, {ciudad}"
        ),
        "video_url":              None,
        "video_recorrido_url":    video_recorrido_url or None,
        # Si el usuario ya subió su video, el link está listo de inmediato
        "video_ready":            bool(video_recorrido_url),
        "acceso_activo":          True,
        "otras_propiedades":      None,
    })

    # ── Auto-generar video (FFmpeg) → subir Cloudinary → video_ready = True ──
    import threading
    from video_utils import ffmpeg_available

    if ffmpeg_available() and foto_paths:
        _auto_task_id = str(uuid.uuid4())
        _video_tasks[_auto_task_id] = {
            "status": "running", "progress": 0, "status_text": "iniciando",
            "output_path": None, "error": None, "video_url": None,
            "property_id": property_id,
        }
        _auto_video_data = {
            "fotos":              foto_paths,
            "nombre_agente":      nombre_agente,
            "telefono_agente":    telefono_agente,
            "habitaciones":       habitaciones or "",
            "banos":              banos or "",
            "metros_construidos": metros_construidos or "",
            "estacionamientos":   estacionamientos or "",
            "precio":             precio_formatted,
            "ciudad":             ciudad,
            "direccion":          direccion,
            # Contexto adicional para overlays del video
            "tipo_propiedad":     tipo_propiedad,
            "operacion":          operacion,
            "nombre_inmobiliaria": nombre_inmobiliaria or nombre_agente,
            "amenidades":         amenidades or [],
            "foto_labels":        _json.loads(foto_labels       or "[]"),
            "foto_descriptions":  _json.loads(foto_descriptions or "[]"),
            "logo_url":           logo_path or "",
            "foto_agente_url":    foto_agente_path or "",
            "video_url_propio":   None,
        }
        threading.Thread(
            target=_video_task,
            args=(_auto_task_id, _auto_video_data, property_id, "video_url"),
            daemon=True,
        ).start()
        log.info("Video task iniciado: %s para propiedad %s", _auto_task_id, property_id)
    else:
        # Sin FFmpeg o sin fotos: el link queda listo de inmediato
        db.update_property(property_id, {"video_ready": True})
        log.warning("FFmpeg no disponible o sin fotos — video_ready=True inmediato.")

    return JSONResponse({
        "descripcion":       descripcion,
        "descripciones":     descripciones,
        "ig_copy":           ig_copy,
        "frase_inspiradora": frase_inspiradora,
        "fotos":             foto_paths,
        "logo":              logo_path,
        "foto_agente":       foto_agente_path,
        "colors":            logo_colors,
        "property_id":       property_id,
        "property_slug":     property_slug,
        "propiedad": {
            "tipo":      tipo_propiedad,
            "operacion": operacion,
            "direccion": direccion,
            "ciudad":    ciudad,
            "precio":    precio_formatted,
            "agente":    nombre_agente,
            "telefono":  telefono_agente,
            "email":     email_agente or "",
        },
        "specs": {
            "habitaciones":      habitaciones,
            "banos":             banos,
            "metros_construidos": metros_construidos,
            "metros_terreno":    metros_terreno,
            "estacionamientos":  estacionamientos,
            "estrato":           estrato,
            "ano_construccion":  ano_construccion,
            "amenidades":        amenidades,
            "nombre_inmobiliaria": nombre_inmobiliaria,
        },
    })


# ── Upload de video del usuario (Plan A) ─────────────────────────────────────
@app.post("/upload-video")
async def upload_video_endpoint(video: UploadFile = File(...)):
    """Recibe el video del usuario y lo sube a Cloudinary. Devuelve la URL."""
    ext = Path(video.filename or "video.mp4").suffix.lower()
    if ext not in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="Formato de video no soportado")

    # Guardar temporalmente
    tmp = Path(tempfile.mkdtemp()) / f"{uuid.uuid4()}{ext}"
    with open(tmp, "wb") as f:
        content = await video.read()
        f.write(content)

    # Intentar Cloudinary primero
    try:
        if os.getenv("CLOUDINARY_URL"):
            import cloudinary
            import cloudinary.uploader
            cloudinary.config(cloudinary_url=os.getenv("CLOUDINARY_URL"))
            result = cloudinary.uploader.upload(
                str(tmp),
                resource_type="video",
                folder="listapro/videos_usuarios",
                public_id=str(uuid.uuid4()),
            )
            tmp.unlink(missing_ok=True)
            return JSONResponse({"url": result["secure_url"]})
    except Exception as e:
        pass

    # Fallback: guardar local
    dest = _uploads_dir / tmp.name
    shutil.move(str(tmp), str(dest))
    return JSONResponse({"url": f"/uploads/{dest.name}"})


# ── Streaming de video local con soporte Range requests (seek funciona) ──────
@app.get("/video/{filename}")
async def stream_video(filename: str, request: Request):
    """Sirve archivos mp4 con soporte completo de HTTP Range para seek en browser."""
    file_path = _uploads_dir / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Video no encontrado")

    file_size = file_path.stat().st_size
    range_header = request.headers.get("range", "")

    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            end   = int(m.group(2)) if m.group(2) else file_size - 1
            end   = min(end, file_size - 1)
            length = end - start + 1

            def _iter():
                with open(file_path, "rb") as fh:
                    fh.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = fh.read(min(65536, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

            return StreamingResponse(
                _iter(), status_code=206, media_type="video/mp4",
                headers={
                    "Content-Range":  f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges":  "bytes",
                    "Content-Length": str(length),
                    "Cache-Control":  "public, max-age=3600",
                },
            )

    return FileResponse(
        str(file_path), media_type="video/mp4",
        headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
    )


# ── Toggle de pago (admin) ────────────────────────────────────────────────────
@app.post("/admin/pago/{property_id}")
async def toggle_pago(property_id: str, _: str = Depends(require_admin)):
    """
    Activa/desactiva pago_realizado.
    Al confirmar pago (True): limpia el video y lanza regeneración sin marca de agua.
    """
    import threading
    from video_utils import ffmpeg_available

    data = db.get_property(property_id)
    if not data:
        raise HTTPException(status_code=404)

    nuevo = not bool(data.get("pago_realizado", False))

    if nuevo:
        # ── Pago confirmado: borrar video con marca de agua y regenerar limpio ──
        db.update_property(property_id, {
            "pago_realizado":  True,
            "video_url":       None,
            "video_url_error": None,
            "video_ready":     False,
        })
        fotos = data.get("fotos") or []
        regenerating = bool(fotos) and ffmpeg_available()
        if regenerating:
            task_id = str(uuid.uuid4())
            _video_tasks[task_id] = {
                "status": "running", "progress": 0,
                "status_text": "regenerando video sin marca de agua",
                "output_path": None, "error": None, "video_url": None,
                "property_id": property_id,
            }
            video_data = {
                "fotos":               fotos,
                "nombre_agente":       data.get("nombre_agente", ""),
                "telefono_agente":     data.get("telefono_agente", ""),
                "habitaciones":        data.get("habitaciones") or "",
                "banos":               data.get("banos") or "",
                "metros_construidos":  data.get("metros") or "",
                "estacionamientos":    data.get("estacionamientos") or "",
                "precio":              data.get("precio", ""),
                "ciudad":              data.get("ciudad", ""),
                "direccion":           data.get("direccion", ""),
                "tipo_propiedad":      data.get("tipo_propiedad", ""),
                "operacion":           data.get("operacion", ""),
                "nombre_inmobiliaria": data.get("nombre_inmobiliaria", ""),
                "amenidades":          data.get("amenidades") or [],
                "foto_labels":         data.get("foto_labels") or [],
                "foto_descriptions":   data.get("foto_descriptions") or [],
                "logo_url":            data.get("logo_url") or "",
                "foto_agente_url":     data.get("foto_agente_url") or "",
                "video_url_propio":    None,
                "pago_realizado":      True,   # sin marca de agua
            }
            threading.Thread(
                target=_video_task,
                args=(task_id, video_data, property_id, "video_url"),
                daemon=True,
            ).start()
            log.info("Regenerando video limpio para %s (task %s)", property_id, task_id)
    else:
        # ── Pago revocado: solo actualizar el campo ──
        db.update_property(property_id, {"pago_realizado": False})
        regenerating = False

    return JSONResponse({"pago_realizado": nuevo, "regenerating": regenerating})


# ── Página web de la propiedad (acepta UUID legacy o slug amigable) ───────────
@app.get("/propiedad/{id_or_slug}", response_class=HTMLResponse)
async def ver_propiedad(id_or_slug: str, request: Request):
    # Detectar formato: UUID vs slug
    if _UUID_RE.match(id_or_slug):
        property_id = id_or_slug
        data        = db.get_property(property_id)
    else:
        result = db.get_property_by_slug(id_or_slug)
        if result is None:
            raise HTTPException(status_code=404, detail="Propiedad no encontrada.")
        property_id, data = result

    if not data:
        raise HTTPException(status_code=404, detail="Propiedad no encontrada.")

    # Verificar acceso: si está desactivado, mostrar pantalla de bloqueo
    if not bool(data.get("acceso_activo", True)):
        return templates.TemplateResponse("acceso_bloqueado.html", {
            "request": request,
        }, status_code=403)

    account_type = data.get("account_type", "particular")

    if account_type == "inmobiliaria":
        telefono = data.get("telefono_agente", "")
        otras = (
            db.get_agent_properties(telefono, exclude_id=property_id, limit=8)
            if telefono
            else db.get_recent_properties(limit=6, exclude_id=property_id)
        )
        otras = otras or None
    else:
        otras = None

    return templates.TemplateResponse("propiedad.html", {
        "request":           request,
        "property_id":       property_id,
        "otras_propiedades": otras,
        "account_type":      account_type,
        **data,
    })


# ── Consulta de video para la página pública ─────────────────────────────────
@app.get("/propiedad-video-status/{property_id}")
async def propiedad_video_status(property_id: str):
    data = db.get_property(property_id)
    if not data:
        raise HTTPException(status_code=404)
    # Filtrar solo las tareas de ESTA propiedad (no de otras)
    generating = any(
        t.get("status") == "running" and t.get("property_id") == property_id
        for t in _video_tasks.values()
    )
    return JSONResponse({
        "video_url":             data.get("video_url"),
        "video_url_error":       data.get("video_url_error"),
        "video_recorrido_url":   data.get("video_recorrido_url"),
        "video_recorrido_error": data.get("video_recorrido_url_error"),
        "generating":            generating,
        "video_ready":           bool(data.get("video_ready", False)),
    })


# ── Estado de preparación del link de la propiedad ───────────────────────────
@app.get("/property-ready/{property_id}")
async def property_ready(property_id: str):
    """
    El frontend hace polling aquí cada 5 s.
    Devuelve ready=True cuando el video ya está en Cloudinary (o si no hay video que generar).
    """
    data = db.get_property(property_id)
    if not data:
        raise HTTPException(status_code=404)
    return JSONResponse({
        "ready":     bool(data.get("video_ready", False)),
        "video_url": data.get("video_url"),
    })


# ── Consulta de video para la página pública ─────────────────────────────────
@app.get("/propiedad-video-status/{property_id}")
async def propiedad_video_status(property_id: str):
    """El template de propiedad hace polling a este endpoint para saber si el video ya está listo."""
    data = db.get_property(property_id)
    if not data:
        raise HTTPException(status_code=404)
    video_url = data.get("video_url")
    # Comprobar si hay alguna tarea de video corriendo para esta propiedad
    generating = any(
        t.get("status") == "running" for t in _video_tasks.values()
    )
    return JSONResponse({"video_url": video_url, "generating": generating})


# ── Video endpoints ───────────────────────────────────────────────────────────

# Estado en memoria de tareas de video (suficiente para un servidor persistente)
_video_tasks: dict = {}


def _video_task(task_id: str, data: dict, prop_id: Optional[str],
               field: str = "video_url"):
    """
    Hilo de fondo.  field indica qué campo actualizar en DB:
      "video_url"           → slideshow automático desde fotos
      "video_recorrido_url" → video del usuario con overlays
    """
    import video_utils

    def _up(**kw):
        _video_tasks[task_id].update(kw)

    try:
        _up(progress=5, status_text="preparando")

        nombre   = data.get("nombre_agente", "")
        telefono = data.get("telefono_agente", "") or data.get("telefono", "")
        specs    = {
            "metros":              data.get("metros_construidos") or data.get("metros", ""),
            "habitaciones":        data.get("habitaciones", ""),
            "banos":               data.get("banos", ""),
            "estacionamientos":    data.get("estacionamientos", ""),
            "precio":              data.get("precio", ""),
            "ciudad":              data.get("ciudad", ""),
            "direccion":           data.get("direccion", ""),
            "tipo_propiedad":      data.get("tipo_propiedad", ""),
            "operacion":           data.get("operacion", ""),
            "nombre_inmobiliaria": data.get("nombre_inmobiliaria", ""),
            "logo_path":           data.get("logo_url", "") or data.get("logo_path", ""),
            "amenidades":          data.get("amenidades") or [],
            "foto_labels":         data.get("foto_labels")        or [],
            "foto_descriptions":   data.get("foto_descriptions")   or [],
            "foto_agente":         data.get("foto_agente_url", "") or data.get("foto_agente", ""),
        }
        fotos            = [f for f in data.get("fotos", []) if f][:50]
        video_url_propio = data.get("video_url_propio")

        _up(progress=10, status_text="generando video")

        if video_url_propio:
            local_out = video_utils.add_overlays(video_url_propio, nombre, telefono, specs)
        else:
            if not fotos:
                raise ValueError("No hay fotos disponibles para generar el video.")
            local_out = video_utils.generate_slideshow(fotos, nombre, telefono, specs)

        _up(progress=75, status_text="subiendo a la nube")

        cloud_url = video_utils.upload_video(local_out)
        if cloud_url:
            video_url = cloud_url
        else:
            # Fallback: servir desde /video/ con soporte Range (seek funciona)
            dest = _uploads_dir / f"video_{task_id}.mp4"
            shutil.copy2(local_out, str(dest))
            video_url = f"/video/{dest.name}"

        if prop_id:
            update = {field: video_url, f"{field}_error": None}
            if field == "video_url":
                update["video_ready"] = True  # habilita el botón "Ver inmueble"
            db.update_property(prop_id, update)

        _up(status="done", progress=100, status_text="completado", video_url=video_url)

        try:
            Path(local_out).unlink(missing_ok=True)
        except Exception:
            pass

    except Exception as e:
        import traceback
        traceback.print_exc()
        raw = str(e)
        # Guardar en log el error completo; al usuario mostrar solo la causa raíz
        log.error("Video task %s falló: %s", task_id, raw[:500])
        # Mensaje limpio para el cliente: primera línea sin stderr de FFmpeg
        first_line = raw.split('\n')[0][:200]
        _up(status="error", error=first_line, progress=0)
        if prop_id:
            update_err = {f"{field}_error": first_line}
            if field == "video_url":
                update_err["video_ready"] = True
            db.update_property(prop_id, update_err)


