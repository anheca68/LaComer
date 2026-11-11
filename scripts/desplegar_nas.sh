#!/usr/bin/env bash
# Despliega LaComer en el NAS (QNAP + Docker) desde el Mac.
#
# Uso:
#   scripts/desplegar_nas.sh [--simular] [--sin-pruebas] [--migrar-bd] [rama-o-commit]
#
#   rama-o-commit  Qué versión desplegar (por defecto: main). Debe estar
#                  subida a GitHub, para que lo que corre en producción siempre
#                  exista también allí.
#   --simular      Hace todas las verificaciones, sube el código a una carpeta
#                  temporal del NAS y muestra qué archivos cambiarían, pero no
#                  respalda, no toca la carpeta de la app ni reinicia nada.
#   --sin-pruebas  No ejecuta las pruebas antes de desplegar.
#   --migrar-bd    Solo una vez: pasa la base de data/despensa.db (versiones
#                  anteriores) al volumen lacomer_db. Con la app detenida la
#                  copia a data/backups/ y la importa sin borrar el original.
#
# Qué viaja al NAS: solo los archivos versionados en git del commit elegido
# (`git archive`). La base de datos del Mac nunca viaja: no está en git, y el
# script se detiene si encuentra una base, un .env o la carpeta data/ dentro
# del commit.
#
# Qué NO se toca en el NAS:
#   - el volumen `lacomer_db` (la base productiva): no se usa `down -v` ni
#     `volume rm`; solo `build` y `up -d`;
#   - data/, procesados/, el .env, bases SQLite, PDFs, CSV, Excel y respaldos.
#
# Antes de cambiar nada respalda la base productiva en data/backups/, guarda
# el código actual en _backup_codigo/ y la imagen actual con la etiqueta
# `anterior`. Si el respaldo de la base falla, el despliegue se detiene.
#
# Configuración (variables de entorno, opcionales):
#   NAS_HOST        alias de ~/.ssh/config          (por defecto: anhecans)
#   NAS_DIR         carpeta de la app en el NAS     (por defecto: /share/Container/LaComer)
#   NAS_PUERTO_APP  puerto publicado de la app      (por defecto: 8001)
#   NAS_PATH_EXTRA  rutas donde están docker y compose en el NAS

set -euo pipefail

NAS_HOST="${NAS_HOST:-anhecans}"
NAS_DIR="${NAS_DIR:-/share/Container/LaComer}"
NAS_PUERTO_APP="${NAS_PUERTO_APP:-8001}"
NAS_PATH_EXTRA="${NAS_PATH_EXTRA:-/share/CACHEDEV1_DATA/.qpkg/container-station/bin:/usr/local/bin:/opt/bin}"
NAS_TMP="${NAS_DIR%/}.despliegue-tmp"
VOLUMEN_BD="lacomer_db"
CONTENEDOR="despensa-app"

# Lo que rsync nunca debe borrar ni sobrescribir en la carpeta de la app:
# datos, secretos, respaldos y cualquier archivo que no sea código.
EXCLUSIONES=(
    --exclude=/data/
    --exclude=/backups/
    --exclude=/procesados/
    --exclude=/backend/backups/
    --exclude=/backend/uploads/
    --exclude=/backend/procesados/
    --exclude=/backend/resultados/
    --exclude=/backend/staging/
    --exclude=/backend/descartados/
    --exclude=/_backup_codigo/
    --exclude='/_backup_*/'
    --exclude=/.env
    --exclude=/.git/
    --exclude=/docker-compose.override.yml
    --exclude=/.version-desplegada
    --exclude=/.version-anterior
    --exclude='*.db'
    --exclude='*.db-*'
    --exclude='*.db.*'
    --exclude='*.sqlite'
    --exclude='*.sqlite3'
    --exclude='*.pdf'
    --exclude='*.csv'
    --exclude='*.xlsx'
    --exclude='*.xls'
    --exclude='*.bak'
    --exclude='*.tar.gz'
)
# Las exclusiones ya escapadas para pasarlas a la línea de comandos del NAS.
EXCL_REMOTO="$(printf '%q ' "${EXCLUSIONES[@]}")"

REF="main"
SIMULAR=0
SIN_PRUEBAS=0
MIGRAR_BD=0
for arg in "$@"; do
    case "$arg" in
        --simular) SIMULAR=1 ;;
        --sin-pruebas) SIN_PRUEBAS=1 ;;
        --migrar-bd) MIGRAR_BD=1 ;;
        -h|--help) sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "Opción desconocida: $arg" >&2; exit 2 ;;
        *) REF="$arg" ;;
    esac
done

paso() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
error() { printf '\n\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Ejecuta un script sh en el NAS con docker en el PATH.
remoto() {
    ssh -o BatchMode=yes "$NAS_HOST" "sh -s" <<EOF
set -e
PATH="\$PATH:$NAS_PATH_EXTRA"
NAS_DIR='$NAS_DIR'
NAS_TMP='$NAS_TMP'
if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
$1
EOF
}

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"

# --- 1. Verificaciones en el Mac -------------------------------------------
paso "Verificando el repositorio local"
git fetch -q origin 2>/dev/null || echo "Aviso: no se pudo consultar GitHub; uso lo que ya conozco de origin."
COMMIT="$(git rev-parse --verify -q "${REF}^{commit}")" || error "No existe la rama o commit '$REF'."
CORTO="$(git rev-parse --short "$COMMIT")"
echo "Versión a desplegar: $REF ($CORTO) — $(git log -1 --format=%s "$COMMIT")"

if [ -z "$(git branch -r --contains "$COMMIT" 2>/dev/null)" ]; then
    error "El commit $CORTO no está en GitHub. Súbelo primero (git push) para que producción y GitHub coincidan."
fi

PROHIBIDOS="$(git ls-tree -r --name-only "$COMMIT" \
    | grep -Ei '(\.db|\.sqlite3?|\.db-(wal|shm|journal))$|(^|/)\.env$|^data/|^backups/' || true)"
if [ -n "$PROHIBIDOS" ]; then
    error "El commit contiene archivos que nunca deben ir a producción:
$PROHIBIDOS"
fi

# --- 2. Pruebas sobre exactamente ese commit -------------------------------
if [ "$SIN_PRUEBAS" -eq 0 ]; then
    paso "Ejecutando las pruebas de $CORTO"
    PYTHON="$RAIZ/.venv/bin/python"
    [ -x "$PYTHON" ] || error "No encuentro $PYTHON. Crea el entorno (ver README) o usa --sin-pruebas."
    ARBOL="$(mktemp -d)/lacomer-$CORTO"
    trap 'git -C "$RAIZ" worktree remove --force "$ARBOL" >/dev/null 2>&1 || true' EXIT
    git worktree add -q --detach "$ARBOL" "$COMMIT"
    (cd "$ARBOL" && "$PYTHON" -m pytest -q) || error "Las pruebas fallaron; no se despliega."
fi

# --- 3. Verificaciones en el NAS --------------------------------------------
paso "Conectando con el NAS ($NAS_HOST)"
ssh -o BatchMode=yes -o ConnectTimeout=10 "$NAS_HOST" true \
    || error "No hay conexión SSH con $NAS_HOST. ¿Estás en la red de casa?"

remoto "
[ -d \"\$NAS_DIR\" ] || { echo \"No existe \$NAS_DIR en el NAS.\"; exit 1; }
[ -f \"\$NAS_DIR/.env\" ] || { echo \"Falta \$NAS_DIR/.env en el NAS.\"; exit 1; }
command -v docker >/dev/null || { echo 'No encuentro docker en el NAS (revisa NAS_PATH_EXTRA).'; exit 1; }
command -v rsync >/dev/null || { echo 'No encuentro rsync en el NAS.'; exit 1; }
if docker volume inspect $VOLUMEN_BD >/dev/null 2>&1; then
    [ $MIGRAR_BD -eq 0 ] || { echo 'El volumen $VOLUMEN_BD ya existe: la base ya se migró. Despliega sin --migrar-bd.'; exit 1; }
elif [ -f \"\$NAS_DIR/data/despensa.db\" ]; then
    [ $MIGRAR_BD -eq 1 ] || { echo 'La base productiva sigue en data/despensa.db (versión anterior) y aún no existe el volumen $VOLUMEN_BD.'; echo 'Para pasarla al volumen una sola vez, repite con --migrar-bd.'; exit 1; }
    echo 'Migración: se pasará data/despensa.db al volumen $VOLUMEN_BD (el original no se borra).'
else
    echo 'No existe el volumen $VOLUMEN_BD ni data/despensa.db: no encuentro la base productiva. No sigo.'; exit 1
fi
echo \"Compose: \$DC\"
echo \"Versión actual: \$(cat \"\$NAS_DIR/.version-desplegada\" 2>/dev/null || echo desconocida)\"
" || error "El NAS no está listo para desplegar."

# --- 4. Subir el código a una carpeta temporal ------------------------------
paso "Subiendo el código de $CORTO a $NAS_TMP"
git archive --format=tar "$COMMIT" \
    | ssh -o BatchMode=yes "$NAS_HOST" "rm -rf '$NAS_TMP' && mkdir -p '$NAS_TMP' && tar -xf - -C '$NAS_TMP'"

if [ "$SIMULAR" -eq 1 ]; then
    paso "Simulación: cambios que se aplicarían en $NAS_DIR"
    # El rsync de QNAP no admite --dry-run: se ensaya en una copia del código
    # actual (sin datos) y se muestra lo que cambiaría allí.
    remoto "
ENSAYO=\"\$NAS_TMP.ensayo\"
rm -rf \"\$ENSAYO\"
rsync -a $EXCL_REMOTO \"\$NAS_DIR/\" \"\$ENSAYO/\"
rsync -a --delete --itemize-changes $EXCL_REMOTO \"\$NAS_TMP/\" \"\$ENSAYO/\" | grep -v '^\\.d' || true
rm -rf \"\$ENSAYO\" \"\$NAS_TMP\"
"
    echo
    echo "Simulación terminada. No se respaldó, no se cambió el código y no se reinició nada."
    exit 0
fi

FECHA="$(date '+%Y%m%d_%H%M%S')"

# --- 5. Respaldar base, código e imagen actuales ----------------------------
paso "Respaldando la base productiva, el código y la imagen actuales"
if [ "$MIGRAR_BD" -eq 1 ]; then
    # Versión anterior: la base es un archivo en data/. Con la app detenida
    # SQLite cierra la base limpia y una copia de archivo es consistente.
    remoto "
cd \"\$NAS_DIR\"
\$DC stop app
if [ -s data/despensa.db-wal ]; then
    echo 'Hay un despensa.db-wal con datos pendientes; no copio la base a medias.'
    \$DC start app; exit 1
fi
mkdir -p data/backups
cp -p data/despensa.db data/backups/despensa_backup_$FECHA.db
cp -p data/despensa.db data/despensa.db.antes-del-volumen
cmp data/despensa.db data/backups/despensa_backup_$FECHA.db
echo 'Base copiada a data/backups/despensa_backup_$FECHA.db y data/despensa.db.antes-del-volumen'
" || error "No se pudo respaldar la base. No se cambió el código; si la app quedó detenida: ssh $NAS_HOST, cd $NAS_DIR, docker compose start app"
else
    remoto "
cd \"\$NAS_DIR\"
if [ -n \"\$(docker ps -q --filter name=^$CONTENEDOR\$)\" ]; then
    \$DC exec -T app python scripts/bd_volumen.py respaldar
else
    \$DC run --rm --no-deps app python scripts/bd_volumen.py respaldar
fi
" || error "No se pudo respaldar la base. No se cambió nada en producción."
fi

remoto "
cd \"\$NAS_DIR\"
mkdir -p _backup_codigo
tar -czf _backup_codigo/codigo_$FECHA.tar.gz --exclude=./data --exclude=./_backup_codigo --exclude='./_backup_*' --exclude=./procesados --exclude=./backups --exclude=./.env --exclude='*.db' --exclude='*.tar.gz' --exclude='*.pdf' .
IMG=\$(docker inspect $CONTENEDOR --format '{{.Config.Image}}' 2>/dev/null || true)
if [ -n \"\$IMG\" ]; then docker tag \"\$IMG\" \"\${IMG%%:*}:anterior\" && echo \"Imagen actual guardada como \${IMG%%:*}:anterior\"; fi
echo 'Código actual guardado en _backup_codigo/codigo_$FECHA.tar.gz'
" || error "No se pudo respaldar el código actual. No se cambió el código."

# --- 6. Actualizar el código y reconstruir ----------------------------------
paso "Actualizando el código y reconstruyendo la imagen"
remoto "
cd \"\$NAS_DIR\"
cp .version-desplegada .version-anterior 2>/dev/null || true
rsync -a --delete $EXCL_REMOTO \"\$NAS_TMP/\" \"\$NAS_DIR/\"
echo '$COMMIT $REF $(date '+%Y-%m-%d %H:%M')' > .version-desplegada
rm -rf \"\$NAS_TMP\"
\$DC build
" || error "Falló la actualización o el build. La base está respaldada en data/backups/ y el código anterior en _backup_codigo/codigo_$FECHA.tar.gz"

if [ "$MIGRAR_BD" -eq 1 ]; then
    paso "Pasando la base al volumen $VOLUMEN_BD"
    remoto "
cd \"\$NAS_DIR\"
\$DC run --rm --no-deps app python scripts/bd_volumen.py importar /app/data/despensa.db
" || error "Falló la importación. La app quedó detenida y la base original sigue intacta en data/despensa.db.
Para volver a la versión anterior: ssh $NAS_HOST, cd $NAS_DIR, tar -xzf _backup_codigo/codigo_$FECHA.tar.gz, docker compose up -d --build"
fi

paso "Arrancando la nueva versión"
remoto "cd \"\$NAS_DIR\" && \$DC up -d" || error "No se pudo arrancar la app. Revisa: ssh $NAS_HOST, cd $NAS_DIR, docker compose logs app"

# --- 7. Verificar que la app responde ---------------------------------------
paso "Esperando a que la app responda en /health"
for i in $(seq 1 30); do
    if remoto "curl -fsS http://127.0.0.1:$NAS_PUERTO_APP/health >/dev/null 2>&1 || wget -qO- http://127.0.0.1:$NAS_PUERTO_APP/health >/dev/null 2>&1" 2>/dev/null; then
        if [ "$MIGRAR_BD" -eq 1 ]; then
            # La app ya usa el volumen; el archivo viejo se renombra para que
            # no se confunda con la base en uso (no se borra).
            remoto "cd \"\$NAS_DIR\" && mv data/despensa.db data/despensa.db.migrada" \
                && echo "data/despensa.db renombrada a data/despensa.db.migrada (la base en uso está en el volumen $VOLUMEN_BD)."
        fi
        printf '\n\033[32mDespliegue correcto:\033[0m %s (%s) en %s\n' "$REF" "$CORTO" "$NAS_HOST"
        exit 0
    fi
    sleep 3
done

error "La app no respondió en 90 s. Revisa: ssh $NAS_HOST, cd $NAS_DIR, docker compose logs app
La base se respaldó en data/backups/ antes de cambiar nada.
Código anterior: _backup_codigo/codigo_$FECHA.tar.gz (tar -xzf ... y docker compose up -d --build)."
