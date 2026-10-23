# LaComer

App para registro de tickets de la Comer -- Análisis de Gastos de Super.

## Desarrollo local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

La aplicación queda disponible en `http://localhost:8000`.

En local, los datos se guardan por defecto en `backend/`:

```text
backend/despensa.db
backend/uploads/
backend/procesados/
backend/resultados/
backend/staging/
backend/descartados/
backend/backups/
```

### Captura manual de tickets

Además de los PDFs, la pantalla **Tickets** permite capturar una compra a mano
con el botón **Capturar ticket manualmente**. La captura pasa por la misma
sección de revisión que los PDFs: se validan categorías y la suma de renglones
antes de registrarla en la base.

Los tickets manuales no generan PDF. Al confirmarlos se guardan con
`origen='manual'`, se genera su CSV y quedan disponibles en el panel y en
**Consulta por ticket**.

La primera vez que se abre esta versión sobre una base existente se aplica la
migración 8, que reconstruye la tabla `tickets` para permitir el origen
`manual`. Conviene respaldar `despensa.db` antes de actualizar.

## Despliegue con Docker

1. Crear el archivo de entorno:

   ```bash
   cp .env.example .env
   ```

   Editar `.env` y definir una contraseña segura:

   ```text
   ADMIN_PASSWORD=una-contraseña-larga
   ```

2. Crear la carpeta de datos persistentes:

   ```bash
   mkdir -p data
   ```

3. Copiar la base y los datos existentes a `data/`:

   ```text
   data/
     despensa.db
     uploads/
     procesados/
     resultados/
     staging/
     descartados/
     backups/
   ```

4. Construir y arrancar:

   ```bash
   docker compose build
   docker compose up -d
   ```

   En instalaciones con Docker Compose v1:

   ```bash
   docker-compose build
   docker-compose up -d
   ```

5. Verificar:

   ```bash
   curl http://localhost:8001/health
   docker compose logs -f app
   ```

La aplicación queda disponible en `http://IP_DEL_NAS:8001`.

### Separación entre código y datos

El contenedor guarda el código en `/app` y monta `./data` en `/app/data`.
Esto permite reconstruir la imagen sin perder la base ni los archivos de
tickets.

La ruta de datos se controla con `DATA_DIR`:

- Sin variable: se usa `backend/` (desarrollo local).
- En Docker: `DATA_DIR=/app/data`.

### Backups

Los respaldos que genera el panel de administración se guardan en
`data/backups/`. Conviene respaldar esa carpeta y `data/despensa.db` antes de
cada actualización.

### Nota para QNAP

No instalar el proyecto dentro de `/share/Web`: esa carpeta la publica el
servidor web de QNAP y dejaría accesibles `.env`, la base de datos y los
tickets. En el NAS se usa `/share/Container/LaComer`, que no está publicado por
Apache.

La base de datos y los archivos de tickets no deben ser accesibles por HTTP.
Expón únicamente el puerto `8001` del contenedor.

El archivo `DESPENSA.xlsx` ya no es necesario para el flujo normal. Solo se
usaría para una carga inicial histórica.
