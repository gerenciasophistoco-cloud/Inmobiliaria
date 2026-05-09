"""
Maneja el renderizado de video con Remotion en un hilo de fondo.
"""
import base64
import json
import os
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

VIDEO_OUTPUT_DIR = Path(__file__).parent / "video_output"
VIDEO_OUTPUT_DIR.mkdir(exist_ok=True)

# Estado de las tareas: task_id -> dict
video_tasks: dict = {}


def _img_b64(path: str) -> str:
    if not path or not os.path.exists(str(path)):
        return ""
    ext = Path(path).suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
    with open(path, "rb") as f:
        return f"data:image/{mime};base64,{base64.b64encode(f.read()).decode()}"


def _build_video_props(data: dict) -> dict:
    fotos = data.get("fotos", [])
    valid_fotos = [f for f in fotos[:4] if f and os.path.exists(str(f))]

    # Labels para cada foto (índice 0 = portada, etc.)
    labels = [
        data.get("label_1") or "",   # portada
        data.get("label_2") or "",   # foto 2
        data.get("label_3") or "",   # foto 3
        data.get("label_4") or "",   # foto 4
    ]

    return {
        "fotos":              [_img_b64(f) for f in valid_fotos],
        "labels":             labels[:len(valid_fotos)],
        "precio":             data.get("precio", ""),
        "ciudad":             data.get("ciudad", ""),
        "tipo":               data.get("tipo_propiedad", ""),
        "operacion":          data.get("operacion", "Venta"),
        "direccion":          data.get("direccion", ""),
        "habitaciones":       str(data.get("habitaciones") or ""),
        "banos":              str(data.get("banos") or ""),
        "m2_construidos":     str(data.get("metros_construidos") or ""),
        "estrato":            str(data.get("estrato") or ""),
        "nombre_agente":      data.get("nombre_agente", ""),
        "telefono":           data.get("telefono_agente", ""),
        "email":              data.get("email_agente") or "",
        "amenidades":         data.get("amenidades", []),
        "logo":               _img_b64(data.get("logo") or ""),
        "foto_agente":        _img_b64(data.get("foto_agente") or ""),
        "nombre_inmobiliaria": data.get("nombre_inmobiliaria") or data.get("nombre_agente", ""),
        "frase_inspiradora":  data.get("frase_inspiradora") or "",
    }


def _render_thread(task_id: str, props: dict):
    video_dir   = Path(__file__).parent / "video"
    render_js   = video_dir / "render.js"
    output_path = VIDEO_OUTPUT_DIR / f"{task_id}.mp4"
    props_path  = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        ) as f:
            json.dump(props, f)
            props_path = f.name

        proc = subprocess.Popen(
            ["node", str(render_js), props_path, str(output_path)],
            cwd=str(video_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        for line in proc.stdout:
            line = line.strip()
            if line:
                try:
                    msg = json.loads(line)
                    video_tasks[task_id]["progress"] = msg.get("progress", 0)
                    video_tasks[task_id]["status_text"] = msg.get("status", "rendering")
                except Exception:
                    pass

        proc.wait()
        stderr_out = proc.stderr.read()

        if proc.returncode != 0:
            raise RuntimeError(stderr_out or "Remotion render failed")

        video_tasks[task_id].update({"status": "done", "progress": 100, "output_path": str(output_path)})

    except Exception as e:
        video_tasks[task_id].update({"status": "error", "error": str(e)})
    finally:
        if props_path:
            try:
                os.unlink(props_path)
            except OSError:
                pass


def start_video_render(data: dict) -> str:
    """Inicia el renderizado en un hilo. Retorna el task_id."""
    task_id = str(uuid.uuid4())
    props   = _build_video_props(data)

    video_tasks[task_id] = {
        "status": "running",
        "progress": 0,
        "status_text": "iniciando",
        "output_path": None,
        "error": None,
    }

    t = threading.Thread(target=_render_thread, args=(task_id, props), daemon=True)
    t.start()
    return task_id


def get_task_status(task_id: str) -> dict | None:
    return video_tasks.get(task_id)


def get_task_output_path(task_id: str) -> str | None:
    task = video_tasks.get(task_id)
    if task and task["status"] == "done":
        return task.get("output_path")
    return None
