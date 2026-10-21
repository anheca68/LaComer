"""Rutas de la aplicación.

El código vive en el repositorio; los datos persistentes viven en ``DATA_DIR``.
En desarrollo, ``DATA_DIR`` apunta a ``backend/`` para conservar el
comportamiento actual. En Docker se define ``DATA_DIR=/app/data`` y se monta
un volumen en esa ruta, de modo que reconstruir la imagen no toque los datos.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Directorio raíz de los datos persistentes: base SQLite, PDFs, resultados y
# backups. En local se mantiene dentro de backend/; en Docker se monta aparte.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR))).expanduser()

UPLOAD_DIR = DATA_DIR / "uploads"
PROCESADOS_DIR = DATA_DIR / "procesados"
RESULTADOS_DIR = DATA_DIR / "resultados"
STAGING_DIR = DATA_DIR / "staging"
DESCARTADOS_DIR = DATA_DIR / "descartados"
BACKUPS_DIR = DATA_DIR / "backups"

FRONTEND_DIR = BASE_DIR.parent / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

DATA_DIR.mkdir(parents=True, exist_ok=True)

for directorio in (
    UPLOAD_DIR,
    PROCESADOS_DIR,
    RESULTADOS_DIR,
    STAGING_DIR,
    DESCARTADOS_DIR,
    BACKUPS_DIR,
):
    directorio.mkdir(parents=True, exist_ok=True)

# Ruta opcional del Excel usado en la carga inicial. Ya no es parte del flujo
# normal; si se necesita, se puede montar en DATA_DIR o definir CATALOGO_EXCEL.
CATALOGO_EXCEL_PATH = os.environ.get(
    "CATALOGO_EXCEL",
    str(DATA_DIR / "DESPENSA.xlsx"),
)

# Catálogo normalizado en SQLite. CATALOGO_DB_DIR se conserva por compatibilidad;
# por defecto la base vive dentro de DATA_DIR.
CATALOGO_DB_DIR = Path(
    os.environ.get("CATALOGO_DB_DIR", str(DATA_DIR))
).expanduser()
CATALOGO_DB_PATH = CATALOGO_DB_DIR / "despensa.db"
CATALOGO_DB_DIR.mkdir(parents=True, exist_ok=True)
