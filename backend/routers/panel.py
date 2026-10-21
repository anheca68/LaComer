"""Panel de control, reportes y exportación.

`/` es el dashboard y por eso este router se registra después de `tickets`:
si no, `/tickets` seguiría reclamando la raíz.
"""

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from backend.services import panel
from backend.services.exportar import construir_libro
from backend.web import render

router = APIRouter()


def _contexto(periodo: str) -> dict:
    """Todo lo que el panel necesita, ya acotado al período.

    Las tablas las pinta Jinja y las gráficas el navegador, pero salen de las
    mismas funciones de `panel` con el mismo `periodo`: no hay dos caminos que
    puedan dar números distintos.
    """
    return {
        "ind": panel.indicadores(periodo),
        "meses": panel.por_mes(periodo),
        "dias": panel.por_dia(periodo),
        "categorias": panel.por_categoria(periodo),
        "subcategorias": panel.top_subcategorias(10, periodo),
        "productos": panel.top_productos(12, periodo),
        "tickets_top": panel.top_tickets(10, periodo),
        "dia_semana": panel.gasto_por_dia_semana(periodo),
        "periodos": panel.periodos_disponibles(),
    }


@router.get("/", response_class=HTMLResponse)
async def panel_control(request: Request, periodo: str = None,
                        mensaje: str = None, error: str = None):
    """Dashboard de entrada: cifras de gasto, desglose mensual y gráficas.

    `periodo` viaja en la URL (`?periodo=2026-09`) para que la vista sea
    compartible y sobreviva a un recarga. Un panel vacío con el mensaje de
    error es más útil que una traceback: los datos pueden estar mal sin que la
    navegación deba romperse.
    """
    try:
        ctx = _contexto(panel.normalizar(periodo))
    except Exception as e:
        ctx = {"error": f"No se pudieron calcular los indicadores: {e}"}

    ctx["mensaje"] = mensaje
    ctx["error"] = error or ctx.get("error")
    ctx["periodo_activo"] = panel.normalizar(periodo)
    return render(request, "panel.html", "panel", context=ctx)


@router.get("/panel/datos")
async def datos_panel(periodo: str = None):
    """Alimenta las gráficas del panel.

    Van por endpoint y no embebidos en el HTML a propósito: el HTML ya trae
    las tablas pintadas por Jinja, y meter el JSON en un `<script>` inline lo
    dejaba atado al orden de los `<script>`. Con `fetch` el orden deja de
    importar y además se puede probar el endpoint suelto con curl.
    """
    p = panel.normalizar(periodo)
    ind = panel.indicadores(p)
    return JSONResponse(
        {
            "periodo": p,
            # Con un mes suelto la serie mensual se reemplaza por la diaria: una
            # gráfica con una sola barra no dice nada.
            "meses": panel.por_dia(p) if panel.es_mes(p) else panel.por_mes(p),
            "granularidad": "dia" if panel.es_mes(p) else "mes",
            "categorias": panel.por_categoria(p),
            "subcategorias": panel.top_subcategorias(10, p),
            "productos": panel.top_productos(12, p),
            "dias_semana": panel.gasto_por_dia_semana(p),
            "totales": ind,
        }
    )


@router.get("/exportar/excel")
async def exportar_excel(periodo: str = None):
    """Libro con los mismos cortes que el panel, más el detalle completo.

    Acepta el mismo `periodo` que la vista, así que lo que se descarga es
    exactamente lo que se está viendo en pantalla.
    """
    p = panel.normalizar(periodo)
    nombre = f"gastos-{p}-{datetime.now():%Y-%m-%d}.xlsx"
    # El nombre va entre comillas: sin ellas, Safari corta la extensión si el
    # archivo trajera algún carácter que no exista en su codificación.
    disposition = f"attachment; filename=\"{nombre}\"; filename*=UTF-8''{quote(nombre)}"
    return Response(
        content=construir_libro(p),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": disposition},
    )


@router.get("/reportes", response_class=HTMLResponse)
async def reportes(request: Request):
    """Centro de reportes.

    Los PDF preconstruidos están deshabilitados a propósito: falta definir qué
    deben contener. La hoja deja el hueco visible en vez de esconderlo.
    """
    return render(
        request,
        "reportes.html",
        "reportes",
        context={
            "ind": panel.indicadores(None),
            "excel_url": "/exportar/excel",
        },
    )