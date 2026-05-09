"""
Capa de almacenamiento de archivos.
Usa Cloudinary si CLOUDINARY_URL está configurado,
de lo contrario guarda en disco local (desarrollo).
"""
import os
import uuid
import logging
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _cloudinary_enabled() -> bool:
    url = os.getenv("CLOUDINARY_URL")
    if not url:
        return False
    try:
        import cloudinary
        cloudinary.config(cloudinary_url=url)
        return True
    except Exception:
        return False


def upload_file(file_obj, filename: str, folder: str = "listapro") -> Optional[str]:
    """
    Sube un archivo y retorna su URL pública.
    - En producción: Cloudinary
    - En desarrollo: disco local → /uploads/...
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None

    unique_name = f"{uuid.uuid4()}{ext}"

    # ── Cloudinary ──────────────────────────────────────────────────────────
    if _cloudinary_enabled():
        try:
            import cloudinary.uploader
            data = file_obj.read() if hasattr(file_obj, "read") else file_obj
            result = cloudinary.uploader.upload(
                data,
                public_id=f"{folder}/{unique_name.replace(ext, '')}",
                resource_type="image",
                overwrite=True,
            )
            return result["secure_url"]
        except Exception as e:
            log.error("Error subiendo a Cloudinary: %s", e)
            # Caer a disco local si Cloudinary falla
            if hasattr(file_obj, "seek"):
                file_obj.seek(0)

    # ── Disco local ─────────────────────────────────────────────────────────
    upload_dir = _local_upload_dir()
    filepath = upload_dir / unique_name
    if hasattr(file_obj, "read"):
        with open(filepath, "wb") as f:
            shutil.copyfileobj(file_obj, f)
    else:
        filepath.write_bytes(file_obj)

    return f"/uploads/{unique_name}"


def _local_upload_dir() -> Path:
    is_vercel = os.getenv("VERCEL") == "1"
    d = Path("/tmp/uploads") if is_vercel else Path("uploads")
    d.mkdir(parents=True, exist_ok=True)
    return d
