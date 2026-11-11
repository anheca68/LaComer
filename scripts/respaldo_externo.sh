#!/bin/sh
# Copia los respaldos de LaComer al disco externo conectado al NAS.
#
# Se ejecuta EN EL NAS (a mano o con cron):
#   /share/Container/LaComer/scripts/respaldo_externo.sh [--simular] [--sin-respaldo-nuevo]
#
#   --simular             Solo verifica el disco y muestra qué se copiaría.
#   --sin-respaldo-nuevo  No genera un respaldo nuevo de la base; copia los
#                         que ya existen en data/backups/.
#
# Pasos:
#   1. Verifica que el disco externo esté montado de verdad. Si no lo está,
#      se detiene: nunca escribe en el disco interno creyendo que respalda.
#   2. Genera un respaldo consistente de la base productiva
#      (scripts/bd_volumen.py respaldar) en data/backups/.
#   3. Copia data/ (bases respaldadas, PDFs, CSV) y los tickets históricos que
#      aún estén fuera de data/ a <disco>/LaComer/. Nunca borra nada en el
#      disco externo: lo que se copió una vez, se queda.
#   4. Compara byte a byte cada base de data/backups/ con su copia.
#   5. Deja constancia en <disco>/LaComer/ULTIMO_RESPALDO.txt y en el log.
#
# El .env (contraseñas) no se copia: el disco externo puede extraviarse.
#
# Configuración (variables de entorno, opcionales):
#   DESTINO_RAIZ  carpeta del disco externo  (por defecto: /share/Respaldo_QN)
#   APP_DIR       carpeta de la app          (por defecto: la carpeta padre de scripts/)

set -eu

APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
DESTINO_RAIZ="${DESTINO_RAIZ:-/share/Respaldo_QN}"
ARCHIVO_MONTAJES="${ARCHIVO_MONTAJES:-/proc/mounts}"
CONTENEDOR="despensa-app"
PATH="$PATH:/share/CACHEDEV1_DATA/.qpkg/container-station/bin:/usr/local/bin"
# El docker de Container Station guarda su configuración en una carpeta del
# sistema donde un usuario normal no puede escribir.
DOCKER_CONFIG="${DOCKER_CONFIG:-${HOME:-/tmp}/.docker}"
export PATH DOCKER_CONFIG

SIMULAR=0
RESPALDO_NUEVO=1
for arg in "$@"; do
    case "$arg" in
        --simular) SIMULAR=1 ;;
        --sin-respaldo-nuevo) RESPALDO_NUEVO=0 ;;
        -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Opción desconocida: $arg" >&2; exit 2 ;;
    esac
done

LOG="$APP_DIR/data/respaldo_externo.log"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }
falla() { log "ERROR: $*"; exit 1; }

mkdir -p "$APP_DIR/data"
log "Inicio del respaldo externo (simular=$SIMULAR)"

# --- 1. ¿El disco externo está montado? --------------------------------------
[ -d "$DESTINO_RAIZ" ] || falla "No existe $DESTINO_RAIZ. ¿Está conectado el disco externo?"
REAL="$(cd "$DESTINO_RAIZ" && pwd -P)"
# Busca el punto de montaje que contiene a REAL (el más largo que coincida).
MONTAJE="$(awk -v r="$REAL" '
    { p = $2; if ((r == p || index(r, p "/") == 1) && length(p) > length(m)) m = p }
    END { print m }' "$ARCHIVO_MONTAJES")"
if [ -z "$MONTAJE" ] || [ "$MONTAJE" = "/" ]; then
    falla "$REAL no está en un disco montado. ¿Está conectado el disco externo?"
fi
DISP_DESTINO="$(df -P "$REAL" | awk 'NR==2 {print $1}')"
DISP_APP="$(df -P "$APP_DIR" | awk 'NR==2 {print $1}')"
[ "$DISP_DESTINO" != "$DISP_APP" ] \
    || falla "$REAL está en el mismo disco que la app ($DISP_APP): no sería un respaldo externo."
DESTINO="$REAL/LaComer"
log "Disco externo: $REAL (montado en $MONTAJE, dispositivo $DISP_DESTINO)"

# Tickets que quedaron fuera de data/ en versiones anteriores de la app.
HISTORICOS=""
for d in procesados backend/procesados backend/descartados backend/resultados backend/backups; do
    [ -d "$APP_DIR/$d" ] && HISTORICOS="$HISTORICOS $d"
done

if [ "$SIMULAR" -eq 1 ]; then
    echo
    echo "Se copiaría a $DESTINO:"
    echo "  data/  ($(du -sh "$APP_DIR/data" | cut -f1), $(find "$APP_DIR/data" -type f | wc -l | tr -d ' ') archivos)"
    for d in $HISTORICOS; do
        echo "  historico/$d  ($(find "$APP_DIR/$d" -type f | wc -l | tr -d ' ') archivos)"
    done
    echo "Espacio libre en el disco externo: $(df -Ph "$REAL" | awk 'NR==2 {print $4}')"
    log "Simulación terminada; no se copió nada."
    exit 0
fi

# --- 2. Respaldo nuevo de la base productiva ---------------------------------
if [ "$RESPALDO_NUEVO" -eq 1 ]; then
    cd "$APP_DIR"
    mkdir -p "$DOCKER_CONFIG"
    if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi
    if [ -n "$(docker ps -q --filter "name=^$CONTENEDOR\$")" ]; then
        $DC exec -T app python scripts/bd_volumen.py respaldar >>"$LOG" 2>&1 \
            || falla "No se pudo generar el respaldo de la base."
    else
        $DC run --rm --no-deps app python scripts/bd_volumen.py respaldar >>"$LOG" 2>&1 \
            || falla "No se pudo generar el respaldo de la base."
    fi
    log "Respaldo nuevo de la base generado en data/backups/"
fi

# --- 3. Copiar al disco externo ----------------------------------------------
# exFAT no guarda permisos ni dueños: se copian contenido y fechas (-rt).
# Sin --delete: el disco externo conserva todo lo que se copió alguna vez.
COPIAR="rsync -rt --modify-window=2"
mkdir -p "$DESTINO/data"
$COPIAR "$APP_DIR/data/" "$DESTINO/data/" || falla "Falló la copia de data/."
for d in $HISTORICOS; do
    mkdir -p "$DESTINO/historico/$d"
    $COPIAR "$APP_DIR/$d/" "$DESTINO/historico/$d/" || falla "Falló la copia de $d/."
done

# --- 4. Verificar las bases copiadas -----------------------------------------
TOTAL=0
for f in "$APP_DIR"/data/backups/*.db; do
    [ -f "$f" ] || continue
    cmp -s "$f" "$DESTINO/data/backups/$(basename "$f")" \
        || falla "La copia de $(basename "$f") no coincide con el original."
    TOTAL=$((TOTAL + 1))
done
[ "$TOTAL" -gt 0 ] || falla "No hay ninguna base en data/backups/ que respaldar."

# --- 5. Constancia ------------------------------------------------------------
ULTIMA="$(ls -t "$APP_DIR"/data/backups/*.db | head -1)"
{
    echo "Último respaldo externo: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "Base más reciente: $(basename "$ULTIMA")"
    echo "Bases verificadas byte a byte: $TOTAL"
    echo "Origen: $APP_DIR"
} > "$DESTINO/ULTIMO_RESPALDO.txt"
cp "$LOG" "$DESTINO/respaldo_externo.log" 2>/dev/null || true
log "Respaldo externo correcto: $TOTAL bases verificadas; la más reciente es $(basename "$ULTIMA")"
