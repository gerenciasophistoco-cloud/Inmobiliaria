"""
Capa de almacenamiento de archivos.
Prioridad: Cloudinary (persistente) > disco local (efímero, solo dev).

Variables de entorno soportadas (configurar UNA de las dos opciones en Railway):

  Opción A — URL completa (recomendada):
    CLOUDINARY_URL = cloudinary://API_KEY:API_SECRET@CLOUD_NAME

  Opción B — variables separadas:
    CLOUDINARY_CLOUD_NAME = tu_cloud_name
    CLOUDINARY_API_KEY    = tu_api_key
    CLOUDINARY_API_SECRET = tu_api_secret
"""
import os
import re
import uuid
import logging
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


# ── Configuración de Cloudinary ───────────────────────────────────────────────

def _cloudinary_config() -> dict:
    """Devuelve kwargs para cloudinary.config() o {} si no está configurado."""
    url = os.getenv("CLOUDINARY_URL", "").strip()
    if url:
        return {"cloudinary_url": url}

    cloud = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    key   = os.getenv("CLOUDINARY_API_KEY",    "").strip()
    sec   = os.getenv("CLOUDINARY_API_SECRET",  "").strip()
    if cloud and key and sec:
        return {"cloud_name": cloud, "api_key": key, "api_secret": sec}

    return {}


def _setup() -> bool:
    """Configura la librería cloudinary. Retorna True si quedó lista."""
    cfg = _cloudinary_config()
    if not cfg:
        return False
    try:
        import cloudinary
        cloudinary.config(**cfg)
        return True
    except Exception as e:
        log.error("Error configurando Cloudinary: %s", e)
        return False


def cloudinary_enabled() -> bool:
    """True si hay credenciales de Cloudinary configuradas."""
    return bool(_cloudinary_config())


def diagnose() -> dict:
    """
    Verifica el estado de Cloudinary.
    Útil para el endpoint /admin/test-cloudinary.
    """
    cfg = _cloudinary_config()
    if not cfg:
        return {
            "ok": False,
            "reason": "No hay credenciales configuradas",
            "fix": (
                "En Railway → Variables, agrega:\n"
                "  CLOUDINARY_URL = cloudinary://API_KEY:API_SECRET@CLOUD_NAME\n"
                "Consíguela en cloudinary.com → Dashboard → 'API Environment variable'."
            ),
        }

    if not _setup():
        return {"ok": False, "reason": "No se pudo importar/configurar la librería cloudinary"}

    # Ping: listar recursos (0 descargados) para verificar credenciales
    try:
        import cloudinary.api
        cloudinary.api.ping()
        return {"ok": True, "reason": "Cloudinary operativo ✅"}
    except Exception as e:
        return {
            "ok": False,
            "reason": f"Credenciales inválidas o error de red: {e}",
            "fix": "Verifica que CLOUDINARY_URL sea correcta en Railway → Variables.",
        }


# ── Subida de archivos ────────────────────────────────────────────────────────

def upload_file(file_obj, filename: str, folder: str = "listapro") -> Optional[str]:
    """
    Sube un archivo y retorna su URL pública permanente.
    Si Cloudinary no está disponible, cae a disco local (solo válido en desarrollo).
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        log.warning("Extensión no permitida: %s", ext)
        return None

    public_id   = f"{folder}/{uuid.uuid4().hex}"
    unique_name = f"{uuid.uuid4()}{ext}"

    # ── Cloudinary (producción) ───────────────────────────────────────────────
    if _setup():
        try:
            import cloudinary.uploader
            data = file_obj.read() if hasattr(file_obj, "read") else file_obj
            result = cloudinary.uploader.upload(
                data,
                public_id=public_id,
                resource_type="image",
                overwrite=False,
            )
            url = result["secure_url"]
            log.info("✅ Cloudinary OK: %s", url[:80])
            return url
        except Exception as e:
            log.error("❌ Cloudinary upload falló: %s", e)
            # Resetear para poder leer de nuevo en el fallback
            if hasattr(file_obj, "seek"):
                file_obj.seek(0)
            log.warning("⚠️  Foto guardada en disco local como respaldo. "
                        "Verifica las credenciales de Cloudinary en Railway → Variables.")

    # ── Disco local (desarrollo / fallback) ──────────────────────────────────
    if cloudinary_enabled():
        log.warning("🚨 USANDO DISCO LOCAL aunque Cloudinary está configurado. "
                    "La foto se perderá al reiniciar/redesplegar Railway.")
    else:
        log.info("📁 Cloudinary no configurado — guardando en disco local (solo desarrollo).")

    upload_dir = _local_upload_dir()
    filepath   = upload_dir / unique_name
    if hasattr(file_obj, "read"):
        with open(filepath, "wb") as f:
            shutil.copyfileobj(file_obj, f)
    else:
        filepath.write_bytes(file_obj)

    return f"/uploads/{unique_name}"


# ── Eliminación de archivos ───────────────────────────────────────────────────

def delete_file(url: str) -> bool:
    """
    Elimina un archivo de Cloudinary a partir de su URL segura.
    Retorna True si se eliminó, False si no era de Cloudinary o hubo error.
    """
    if not url or not url.startswith("https://res.cloudinary.com/"):
        return False  # No es una URL de Cloudinary, nada que hacer

    if not _setup():
        log.warning("delete_file: Cloudinary no configurado, no se eliminó: %s", url[:60])
        return False

    try:
        import cloudinary.uploader

        # Extraer public_id desde la URL
        # Ejemplo: https://res.cloudinary.com/cloud/image/upload/v123456/listapro/fotos/abc.jpg
        # → public_id = listapro/fotos/abc
        m = re.search(r"/upload/(?:v\d+/)?(.+?)(?:\.[a-z]{2,5})?$", url, re.IGNORECASE)
        if not m:
            log.warning("No se pudo extraer public_id de: %s", url[:80])
            return False

        public_id = m.group(1)
        result    = cloudinary.uploader.destroy(public_id, resource_type="image")
        ok        = result.get("result") == "ok"
        if ok:
            log.info("✅ Eliminado de Cloudinary: %s", public_id)
        else:
            log.warning("Cloudinary destroy result=%s para %s", result.get("result"), public_id)
        return ok
    except Exception as e:
        log.error("Error al eliminar de Cloudinary (%s): %s", url[:60], e)
        return False


def delete_files(urls: list) -> int:
    """Elimina una lista de URLs de Cloudinary. Retorna cuántas se eliminaron."""
    return sum(1 for u in urls if delete_file(u))


# ── Utilidades ────────────────────────────────────────────────────────────────

def _local_upload_dir() -> Path:
    is_vercel = os.getenv("VERCEL") == "1"
    d = Path("/tmp/uploads") if is_vercel else Path("uploads")
    d.mkdir(parents=True, exist_ok=True)
    return d
