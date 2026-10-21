Comandos útiles para el futuro:
# Ver logs
docker logs despensa-app

# Reiniciar
docker restart despensa-app

# Actualizar código (después de hacer cambios)
cd /share/Web/LaComer
docker-compose down
docker-compose build
docker-compose up -d