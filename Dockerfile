# ── Imagen base ──────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ── Variables de entorno del sistema ─────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# ── Dependencias del sistema + Node.js 20 + Chrome ──────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl wget gnupg ca-certificates \
        # FFmpeg para generación de video
        ffmpeg \
        # Fuentes para los overlays de texto
        fonts-dejavu-core \
        fonts-liberation \
        # Chromium para Remotion (fallback)
        chromium \
        fonts-liberation libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libgbm1 libgtk-3-0 \
        libnss3 libxcomposite1 libxdamage1 libxfixes3 \
        libxkbcommon0 libxrandr2 libasound2 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_EXECUTABLE=/usr/bin/chromium

# ── Directorio de trabajo ─────────────────────────────────────────────────────
WORKDIR /app

# ── Dependencias Python ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Dependencias Node.js para el generador de video ──────────────────────────
COPY video/package.json video/package-lock.json* ./video/
RUN cd video && npm install --omit=dev

# ── Código fuente ─────────────────────────────────────────────────────────────
COPY . .

# ── Directorio de outputs de video ───────────────────────────────────────────
RUN mkdir -p video_output uploads

# ── Exponer puerto ────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Arrancar servidor ─────────────────────────────────────────────────────────
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
