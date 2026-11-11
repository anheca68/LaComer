# LaComer

App para registro de tickets de la Comer -- Análisis de Gastos de Super.

## Desarrollo local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # dependencias de la app + pytest
ADMIN_USUARIO=admin ADMIN_PASSWORD='una-contraseña-larga' python run.py
```

La aplicación queda disponible en `http://localhost:8000`. La primera vez,
`ADMIN_USUARIO` y `ADMIN_PASSWORD` crean el primer administrador (ver
**Usuarios y roles**); después ya no hace falta definirlas.

Pruebas: `python scripts/run_tests.py` (o `python -m pytest`). En producción
basta con `requirements.txt`; `requirements-dev.txt` agrega las herramientas de
desarrollo.

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

### Usuarios y roles

Toda la aplicación pide iniciar sesión (salvo `/login` y `/health`). Cada
persona tiene su usuario y contraseña, y puede tener uno o varios roles:

| Rol | Puede |
|-----|-------|
| `admin` | Lo mismo que `capturista` y `consulta`, más gestionar usuarios (**Administración → Usuarios**), corregir o anular tickets registrados y normalizar productos |
| `capturista` | Subir tickets PDF, capturar tickets a mano y, en **Registros**, ver y clasificar el catálogo y el registro de cambios |
| `consulta` | Ver panel, reportes y consultas |

- **Primer administrador:** si la base no tiene usuarios, al arrancar se crea
  uno con `ADMIN_USUARIO` (por defecto `admin`) y `ADMIN_PASSWORD`. Con
  usuarios ya creados, esas variables no tienen efecto.
- **Contraseñas:** mínimo 8 caracteres, guardadas con `scrypt` y sal.
- **Sesiones:** duran 8 horas y se guardan en la base, así que sobreviven a un
  reinicio. Cambiar la contraseña o desactivar a un usuario cierra sus sesiones.
- **Trazabilidad:** cada ticket guarda quién lo registró y quién lo modificó
  por última vez; el registro de cambios guarda el usuario de cada cambio.
- **Corregir o anular tickets:** desde **Consulta por ticket**, el `admin` usa
  **Corregir o anular**. Se editan los datos generales (fecha, hora, folio,
  establecimiento, forma de pago, tarjeta, notas); los importes no. Un ticket
  anulado deja de contar en panel y reportes y se puede reactivar.
- **HTTPS:** si la aplicación se sirve con HTTPS, define `COOKIE_SEGURA=1`.

La migración 9 agrega las tablas de usuarios y se aplica sola al arrancar; los
tickets anteriores quedan con el usuario que los registró vacío.

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

La aplicación usa dos volúmenes, separados del código:

| Volumen | Ruta en el contenedor | Contenido |
|---------|-----------------------|-----------|
| `lacomer_db` (volumen nombrado de Docker) | `/app/db` | La base SQLite `despensa.db` |
| `./data` (carpeta del NAS) | `/app/data` | PDFs, CSV, staging y respaldos |

La base vive en su propio volumen: reconstruir la imagen, `docker compose down`
o borrar el contenedor no la tocan. Solo se borra con `docker compose down -v` o
`docker volume rm lacomer_db`; **no uses esos comandos** sin un respaldo.

### Instalación nueva

1. Crear el archivo de entorno y definir una contraseña segura:

   ```bash
   cp .env.example .env
   ```

   `ADMIN_USUARIO` y `ADMIN_PASSWORD` crean el primer administrador la primera
   vez que arranca la aplicación.

2. Crear la carpeta de archivos, construir y arrancar:

   ```bash
   mkdir -p data
   docker compose build
   docker compose up -d
   ```

   En instalaciones con Docker Compose v1 usa `docker-compose` en lugar de
   `docker compose`.

3. Verificar:

   ```bash
   curl http://localhost:8001/health
   docker compose logs -f app
   ```

La aplicación queda disponible en `http://IP_DEL_NAS:8001`.

### Actualizar una instalación que tenía la base en `data/`

Hasta ahora la base estaba en `data/despensa.db`. Hay que pasarla al volumen
`lacomer_db` **una sola vez**, con la aplicación detenida:

```bash
cd /share/Container/LaComer
docker compose down                        # detiene la versión anterior
cp data/despensa.db data/despensa.db.antes-del-volumen   # respaldo extra
# ...actualizar el código (git pull o copiar los archivos nuevos)...
docker compose build
docker compose run --rm app python scripts/bd_volumen.py importar /app/data/despensa.db
docker compose up -d
```

`docker compose run` crea el volumen la primera vez. Si la aplicación nueva ya
se arrancó antes de importar, no pasa nada: la base vacía que creó se reemplaza
sin pedir confirmación.

El script verifica la integridad de la base, la copia al volumen y muestra
cuántos tickets, productos y usuarios quedaron. No sobrescribe una base que ya
tenga datos salvo con `--reemplazar`, y en ese caso la respalda antes.
Con la app en marcha, detenla antes (`docker compose stop app`).

Cuando compruebes en la aplicación que están tus tickets, renombra
`data/despensa.db` (por ejemplo a `despensa.db.migrada`) para que no se
confunda con la base en uso.

### Respaldos

La base ya no está en una carpeta visible del NAS, así que los respaldos van a
`data/backups/`:

```bash
docker compose exec app python scripts/bd_volumen.py respaldar
```

Los respaldos que genera **Normalizar productos** también quedan ahí, y ambos
se pueden restaurar desde esa pantalla. Conviene respaldar antes de cada
actualización y copiar `data/backups/` fuera del NAS de vez en cuando.

### Variables de rutas

- `DB_DIR`: carpeta de `despensa.db`. En Docker, `/app/db`.
- `DATA_DIR`: carpeta de archivos y respaldos. En Docker, `/app/data`.
- Sin ninguna de las dos (desarrollo local), todo se guarda en `backend/`.
  `CATALOGO_DB_DIR` sigue funcionando como nombre anterior de `DB_DIR`.

### Nota para QNAP

No instalar el proyecto dentro de `/share/Web`: esa carpeta la publica el
servidor web de QNAP y dejaría accesibles `.env`, la base de datos y los
tickets. En el NAS se usa `/share/Container/LaComer`, que no está publicado por
Apache.

La base de datos y los archivos de tickets no deben ser accesibles por HTTP.
Expón únicamente el puerto `8001` del contenedor.

## Actualizar dependencias

Nada se actualiza solo. Todas las versiones están fijas y solo cambian cuando
alguien las actualiza a mano:

| Qué | Dónde se fija |
|-----|---------------|
| Paquetes de Python (incluidas las dependencias indirectas) | `requirements.txt` con `==` |
| Herramientas de pruebas | `requirements-dev.txt` con `==` |
| Python y sistema base de la imagen | `FROM` del `Dockerfile`, con versión exacta y `@sha256:` |
| Chart.js | Copia local en `frontend/static/js/chart.umd.min.js`; no se descarga de internet |

Además, en Docker `pip` instala con `--no-deps` y termina con `pip check`: si
falta algún paquete en `requirements.txt`, el build falla en lugar de traer uno
por su cuenta. Las pruebas (`tests/test_versiones_fijas.py`) fallan si una
versión queda sin fijar.

Para actualizar, cuando tú lo decidas:

```bash
# 1. Python: subir la versión de un paquete y regenerar la lista completa
#    (el .venv se crea con uv; con un venv de pip usa `pip` en lugar de `uv pip`)
uv pip install --python .venv/bin/python --upgrade <paquete>
uv pip freeze --python .venv/bin/python --exclude pytest --exclude iniconfig \
    --exclude packaging --exclude pluggy --exclude pygments > requirements.txt
.venv/bin/python scripts/run_tests.py

# 2. Imagen base: elegir la versión exacta (por ejemplo 3.13.17-slim-trixie),
#    obtener su digest y ponerlo en el FROM del Dockerfile
docker pull python:3.13.17-slim-trixie
docker inspect --format '{{index .RepoDigests 0}}' python:3.13.17-slim-trixie

# 3. Reconstruir la imagen en el NAS
docker compose build && docker compose up -d
```

No uses `docker compose build --pull` ni herramientas de actualización
automática de contenedores (como Watchtower) con este proyecto.

## Carga inicial del histórico

La importación del histórico (Excel `DESPENSA.xlsx` y PDFs antiguos) ya no es
parte de la aplicación: vive aparte en `carga_inicial/` y no entra en la imagen
de Docker. Si se vuelve a necesitar, se levanta por separado con
`python -m carga_inicial`; ver `carga_inicial/README.md`.
