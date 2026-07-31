# Dockerfile — DOT API (FastAPI backend)
#
# Build:
#   docker build -t nordik-api -f apps/dot/backend/Dockerfile .
#
# Run:
#   docker run -p 8000:8000 --env-file apps/dot/backend/.env nordik-api
#
# Multi-stage: builder instala dependencias, runtime solo lo necesario.
# Sin compilación de extensiones nativas pesadas — el stage único es suficiente.

FROM python:3.12-slim-bookworm

# Variables de build (sin valores por defecto — falla si no se definen)
ARG DOT_ENV=production
ENV DOT_ENV=${DOT_ENV}

WORKDIR /app

# Instalar dependencias del sistema necesarias para psycopg-binary y PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar el paquete compartido dot-billing primero (cambia menos frecuentemente)
COPY packages/dot-billing/ /app/packages/dot-billing/
RUN pip install --no-cache-dir -e /app/packages/dot-billing[full]

# Copiar requirements del backend e instalar
COPY apps/dot/backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copiar código de la aplicación
COPY apps/dot/backend/ /app/apps/dot/backend/

# Directorio de trabajo: raíz del backend
WORKDIR /app/apps/dot/backend

# Puerto por defecto (FastAPI)
EXPOSE 8000

# Health check interno
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

# Entry point
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
