"""
Capa de acceso a datos.
Usa Supabase si las variables de entorno están configuradas,
de lo contrario cae a un diccionario en memoria (desarrollo local).
"""
import os
import logging
from typing import Optional

log = logging.getLogger(__name__)

# Almacén en memoria como fallback
_memory_store: dict = {}


def _get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:
        log.warning("No se pudo conectar a Supabase: %s", e)
        return None


def save_property(property_id: str, data: dict) -> str:
    """Guarda o actualiza una propiedad. Retorna el property_id."""
    client = _get_client()
    if client is None:
        _memory_store[property_id] = data
        return property_id
    try:
        client.table("propiedades").upsert(
            {"id": property_id, "datos": data}
        ).execute()
    except Exception as e:
        log.error("Error guardando en Supabase: %s", e)
        _memory_store[property_id] = data
    return property_id


def get_property(property_id: str) -> Optional[dict]:
    """Obtiene una propiedad por su ID."""
    client = _get_client()
    if client is None:
        return _memory_store.get(property_id)
    try:
        result = (
            client.table("propiedades")
            .select("datos")
            .eq("id", property_id)
            .single()
            .execute()
        )
        return result.data["datos"] if result.data else None
    except Exception as e:
        log.error("Error leyendo de Supabase: %s", e)
        return _memory_store.get(property_id)


def update_property(property_id: str, fields: dict) -> bool:
    """Actualiza campos específicos de una propiedad (ej: video_url)."""
    existing = get_property(property_id)
    if existing is None:
        return False
    existing.update(fields)
    save_property(property_id, existing)
    return True
