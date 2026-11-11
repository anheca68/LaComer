"""Infraestructura común de las vistas.

Centraliza el objeto de plantillas y las variables que existen en todas las
pantallas, para que ningún router tenga que acordarse de pasarlas. Antes cada
router armaba su propio `Jinja2Templates` y si se olvidaba de una variable la
plantilla la Veía vacía en lugar de avisar.
"""

from typing import Any, Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates

from backend.config import CATALOGO_DB_PATH, TEMPLATES_DIR, STATIC_DIR

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# Variables disponibles en cualquier plantilla sin pasarlas por el contexto.
templates.env.globals["db_path"] = str(CATALOGO_DB_PATH)


def render(
    request: Request,
    nombre: str,
    seccion: str,
    context: Optional[dict] = None,
    status_code: int = 200,
    **params: Any,
):
    """Renderiza una plantilla con la sección marcada para la barra lateral.

    El parámetro se llama `context` y no `contexto` a propósito: así coincide
    con Starlette y con lo que ya escribían las rutas. Con los dos nombres, un
    `context=` a secas se iba en `**params` y la plantilla recibía el contexto
    vacío sin quejarse.

    `usuario` es quien inició sesión (o None en el login): la barra lateral lo
    usa para mostrar solo lo que su rol permite.
    """
    return templates.TemplateResponse(
        request=request,
        name=nombre,
        context={
            "seccion": seccion,
            "usuario": getattr(request.state, "usuario", None),
            **(context or {}),
            **params,
        },
        status_code=status_code,
    )