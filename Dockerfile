# ── Imagen base ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── Variables de entorno del sistema ─────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# ── Dependencias del sistema ─────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl wget gnupg ca-certificates \
        # ── FFmpeg (video) ──
        ffmpeg \
        # ── Fuentes para overlays de texto ──
        fonts-dejavu-core \
        fonts-dejavu \
        fonts-liberation \
        fontconfig \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    # Actualizar caché de fuentes
    && fc-cache -fv

# ── Verificar que FFmpeg está instalado (falla el build si no) ───────────────
RUN ffmpeg -version 2>&1 | head -1 && \
    echo "✅ FFmpeg instalado correctamente" && \
    ffprobe -version 2>&1 | head -1

# ── Verificar fuentes disponibles ────────────────────────────────────────────
RUN fc-list | grep -i "dejavu\|liberation" | head -5 && \
    echo "✅ Fuentes instaladas correctamente"

# ── Directorio de trabajo ─────────────────────────────────────────────────────
WORKDIR /app

# ── Dependencias Python ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Código fuente ─────────────────────────────────────────────────────────────
COPY . .

# ── Directorios necesarios ────────────────────────────────────────────────────
RUN mkdir -p video_output uploads

# ── Puerto ────────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Arrancar ──────────────────────────────────────────────────────────────────
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
