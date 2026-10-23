#!/usr/bin/env bash
# Levanta LaComer en modo local (sin Docker) en http://localhost:8000.
#
# Las variables (ADMIN_USUARIO, ADMIN_PASSWORD, ...) se leen de .env, que no se
# versiona: copia .env.example como .env y define la contraseña ahí.
set -euo pipefail

# Carpeta del proyecto: la del script, sin importar desde dónde se ejecute.
PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROYECTO"

# Entorno virtual del proyecto
source "$PROYECTO/.venv/bin/activate"

# Variables de entorno desde .env
if [[ -f .env ]]; then
    set -a
    source .env
    set +a
else
    echo "Aviso: no existe .env; sin ADMIN_PASSWORD no se crea el primer administrador." >&2
fi

# Servidor (uvicorn con recarga automática, ver run.py)
python run.py
