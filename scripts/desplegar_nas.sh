#!/usr/bin/env bash
# Despliega LaComer en el NAS (QNAP + Docker) desde el Mac.
#
# Uso:
#   scripts/desplegar_nas.sh [--simular] [--sin-pruebas] [rama-o-commit]
#
#   rama-o-commit  Qué versión desplegar (por defecto: main). Debe estar
#                  subida a GitHub, para que lo que corre en producción siempre
#                  exista también allí.
#   --simular      Hace todas las verificaciones, sube el código a una carpeta
#                  temporal del NAS y muestra qué archivos cambiarían, pero no
#                  respalda, no toca la carpeta de la app ni reinicia nada.
#   --sin-pruebas  No ejecuta las pruebas antes de desplegar.
#
# Qué viaja al NAS: solo los archivos versionados en git del commit elegido
# (`git archive`). La base de datos del Mac nunca viaja: no está en git, y el
# script se detiene si encuentra una base, un .env o la carpeta data/ dentro
# del commit.
#
# Qué NO se toca en el NAS:
#   - el volumen `lacomer_db` (la base productiva): no se usa `down -v` ni
#     `volume rm`; solo `build` y `up -d`;
#   - la carpeta data/ (tickets y respaldos), el .env y cualquier base SQLite.
#
# Antes de cambiar el código respalda la base productiva en data/backups/ con
# scripts/bd_volumen.py; si el respaldo falla, el despliegue se detiene.
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

# Lo que rsync nunca debe borrar ni sobrescribir en la carpeta de la app.
EXCLUSIONES=(
    --exclude=/data/
    --exclude=/backups/
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
)
# Las exclusiones ya escapadas para pasarlas a la línea de comandos del NAS.
EXCL_REMOTO="$(printf '%q ' "${EXCLUSIONES[@]}")"

REF="main"
SIMULAR=0
SIN_PRUEBAS=0
for arg in "$@"; do
    case "$arg" in
        --simular) SIMULAR=1 ;;
        --sin-pruebas) SIN_PRUEBAS=1 ;;
        -h|--help) sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "Opción desconocida: $arg" >&2; exit 2 ;;
        *) REF="$arg" ;;
    esac
done

paso() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
error() { printf '\n\033[31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Ejecuta un script sh en el NAS con docker en el PATH y en la carpeta de la app.
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
docker volume inspect $VOLUMEN_BD >/dev/null 2>&1 || { echo 'No existe el volumen $VOLUMEN_BD: la base productiva no está donde se espera. No sigo.'; exit 1; }
echo \"Compose: \$DC\"
echo \"Versión actual: \$(cat \"\$NAS_DIR/.version-desplegada\" 2>/dev/null || echo desconocida)\"
" || error "El NAS no está listo para desplegar."

# --- 4. Subir el código a una carpeta temporal ------------------------------
paso "Subiendo el código de $CORTO a $NAS_TMP"
git archive --format=tar "$COMMIT" \
    | ssh -o BatchMode=yes "$NAS_HOST" "rm -rf '$NAS_TMP' && mkdir -p '$NAS_TMP' && tar -xf - -C '$NAS_TMP'"

if [ "$SIMULAR" -eq 1 ]; then
    paso "Simulación: cambios que se aplicarían en $NAS_DIR"
    remoto "rsync -a --delete --dry-run --itemize-changes $EXCL_REMOTO \"\$NAS_TMP/\" \"\$NAS_DIR/\""
    echo
    echo "Simulación terminada. No se respaldó, no se cambió el código y no se reinició nada."
    exit 0
fi

# --- 5. Respaldar la base productiva ----------------------------------------
paso "Respaldando la base productiva (data/backups/)"
remoto "
cd \"\$NAS_DIR\"
if [ -n \"\$(docker ps -q --filter name=^despensa-app\$)\" ]; then
    \$DC exec -T app python scripts/bd_volumen.py respaldar
else
    \$DC run --rm --no-deps app python scripts/bd_volumen.py respaldar
fi
" || error "No se pudo respaldar la base. No se cambió nada en producción."

# --- 6. Actualizar el código, reconstruir y arrancar ------------------------
paso "Actualizando el código y reconstruyendo la imagen"
remoto "
cd \"\$NAS_DIR\"
cp .version-desplegada .version-anterior 2>/dev/null || true
rsync -a --delete $EXCL_REMOTO \"\$NAS_TMP/\" \"\$NAS_DIR/\"
echo '$COMMIT $REF $(date '+%Y-%m-%d %H:%M')' > .version-desplegada
rm -rf \"\$NAS_TMP\"
\$DC build
\$DC up -d
" || error "Falló la actualización o el build. La base está respaldada en data/backups/; revisa: ssh $NAS_HOST, cd $NAS_DIR, docker compose logs app"

# --- 7. Verificar que la app responde ---------------------------------------
paso "Esperando a que la app responda en /health"
for i in $(seq 1 30); do
    if remoto "curl -fsS http://127.0.0.1:$NAS_PUERTO_APP/health >/dev/null 2>&1 || wget -qO- http://127.0.0.1:$NAS_PUERTO_APP/health >/dev/null 2>&1" 2>/dev/null; then
        printf '\n\033[32mDespliegue correcto:\033[0m %s (%s) en %s\n' "$REF" "$CORTO" "$NAS_HOST"
        exit 0
    fi
    sleep 3
done

ANTERIOR="$(remoto 'cut -d" " -f1 "$NAS_DIR/.version-anterior" 2>/dev/null' || true)"
error "La app no respondió en 90 s. Revisa: ssh $NAS_HOST, cd $NAS_DIR, docker compose logs app
Para volver a la versión anterior: scripts/desplegar_nas.sh ${ANTERIOR:-<commit-anterior>}
La base se respaldó en data/backups/ antes de cambiar nada; se restaura desde Normalizar productos."
