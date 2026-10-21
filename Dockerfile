FROM python:3.13-slim

WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto de la aplicación
COPY . .

# Crear directorios necesarios
RUN mkdir -p backend/uploads backend/procesados backend/resultados backend/staging backend/descartados backend/backups

# Exponer puerto
EXPOSE 8001

# Comando para ejecutar
CMD ["sh", "-c", "cd /app && pip install -r requirements.txt && uvicorn backend.main:app --host 0.0.0.0 --port 8001"]
