Comandos útiles para el futuro:

# Ver logs
docker logs despensa-app

# Reiniciar
docker restart despensa-app

# Estado y salud
docker ps
docker inspect despensa-app --format '{{json .State.Health}}'

# Actualizar código (después de hacer cambios)
cd /share/Container/LaComer
docker compose build
docker compose up -d

# En instalaciones con Compose v1:
# docker-compose build
# docker-compose up -d

# Los datos persistentes viven en ./data:
#   data/despensa.db
#   data/backups/
#   data/uploads/
#   data/procesados/
#   data/resultados/
#   data/staging/
#   data/descartados/
#
# No borrar ./data al actualizar la imagen.
