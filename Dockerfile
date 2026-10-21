FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias del sistema. gcc se conserva por compatibilidad con wheels que
# no estén disponibles para alguna arquitectura; se puede retirar si el build
# funciona sin él.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python durante el build, no en cada arranque.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar la aplicación. .dockerignore excluye datos, PDFs, bases y secretos.
COPY . .

# El volumen de datos se monta en /app/data en producción.
RUN mkdir -p /app/data

EXPOSE 8001

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
