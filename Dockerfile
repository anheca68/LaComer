# Imagen base fijada por versión exacta y por digest: reconstruir nunca trae
# otra versión de Python ni del sistema base. Para actualizarla, ver
# "Actualizar dependencias" en el README.
FROM python:3.13.16-slim-trixie@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f

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
# requirements.txt fija todas las versiones, incluidas las indirectas. Con
# --no-deps pip no puede traer por su cuenta un paquete que falte, y
# `pip check` hace fallar el build si a alguno le falta una dependencia.
COPY requirements.txt .
RUN pip install --no-cache-dir --no-deps -r requirements.txt \
    && pip check

# Copiar la aplicación. .dockerignore excluye datos, PDFs, bases y secretos.
COPY . .

# Datos persistentes fuera del código, en dos volúmenes:
#   /app/db   -> base SQLite (despensa.db), en su propio volumen
#   /app/data -> PDFs, CSV, staging y respaldos
# Se declaran como VOLUME para que, aunque se arranque la imagen sin compose,
# Docker no guarde la base dentro de la capa del contenedor.
ENV DB_DIR=/app/db \
    DATA_DIR=/app/data
RUN mkdir -p /app/db /app/data
VOLUME ["/app/db", "/app/data"]

EXPOSE 8001

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8001"]
