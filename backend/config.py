import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

UPLOAD_DIR = BASE_DIR / "uploads"
PROCESADOS_DIR = BASE_DIR / "procesados"
RESULTADOS_DIR = BASE_DIR / "resultados"
STAGING_DIR = BASE_DIR / "staging"
DESCARTADOS_DIR = BASE_DIR / "descartados"
FRONTEND_DIR = BASE_DIR.parent / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

for directorio in (
    UPLOAD_DIR,
    PROCESADOS_DIR,
    RESULTADOS_DIR,
    STAGING_DIR,
    DESCARTADOS_DIR,
):
    directorio.mkdir(parents=True, exist_ok=True)

CATALOGO_EXCEL_PATH = os.environ.get(
    "CATALOGO_EXCEL",
    "/Users/anheca/Documents/DESPENSA.xlsx",
)

# Catálogo normalizado en SQLite. CATALOGO_DB_DIR permite sacar la base de datos
# fuera del proyecto; mientras no se defina, vive junto al backend.
CATALOGO_DB_DIR = Path(os.environ.get("CATALOGO_DB_DIR", str(BASE_DIR)))
CATALOGO_DB_PATH = CATALOGO_DB_DIR / "despensa.db"
CATALOGO_DB_DIR.mkdir(parents=True, exist_ok=True)
