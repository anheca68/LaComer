"""Instancia de LaComer con la pantalla de carga inicial habilitada.

Es la misma aplicación (sesión, roles, plantillas y base de datos) más las
rutas de ``/importar``. La aplicación principal no las incluye.
"""

from pathlib import Path

from jinja2 import ChoiceLoader, FileSystemLoader

from backend.main import crear_app
from backend.web import templates
from carga_inicial.router import router

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# `importar.html` vive aquí y hereda de `base.html`, que sigue en frontend/.
templates.env.loader = ChoiceLoader(
    [templates.env.loader, FileSystemLoader(str(TEMPLATES_DIR))]
)

app = crear_app(routers_extra=[router])
