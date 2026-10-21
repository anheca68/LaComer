"""Router de consultas: detalle por artículo y por ticket."""

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from backend.services.consultas import (
    buscar_articulos_por_nombre,
    buscar_ticket,
    detalle_articulo_por_anio,
    listar_tickets_recientes,
    precios_articulo_serie,
)
from backend.web import render

router = APIRouter(tags=["Consultas"])

# Nombres de meses en español para las tablas de consulta
MESES_NOMBRE = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril",
    "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto",
    "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
}


# ═══════════════════════════════════════════════════════════════════════════
# Consulta por artículo
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/articulo", response_class=HTMLResponse)
async def consultar_articulo(
    request: Request,
    q: str = "",
    id: Optional[int] = None,
    anio: Optional[str] = None,
):
    """Consulta de artículo: busca por nombre y muestra detalle anual."""
    resultados = None
    detalle = None
    texto_busqueda = q

    if id:
        # Se seleccionó un artículo específico, mostrar su detalle
        detalle = detalle_articulo_por_anio(id, anio)
        if not detalle:
            return render(
                request,
                "articulo.html",
                "articulo",
                context={
                    "error": f"No se encontró el artículo con ID {id}.",
                    "texto_busqueda": "",
                    "resultados": [],
                    "detalle": None,
                    "meses_nombre": MESES_NOMBRE,
                    "tickets_recientes": listar_tickets_recientes(10),
                },
            )
    elif q and len(q.strip()) >= 2:
        # Buscar coincidencias
        resultados = buscar_articulos_por_nombre(q)

    return render(
        request,
        "articulo.html",
        "articulo",
        context={
            "texto_busqueda": texto_busqueda,
            "resultados": resultados or [],
            "detalle": detalle,
            "anio_seleccionado": anio,
            "meses_nombre": MESES_NOMBRE,
            "tickets_recientes": listar_tickets_recientes(10),
        },
    )


@router.get("/api/articulos/buscar")
async def api_buscar_articulos(q: str):
    """Endpoint AJAX para búsqueda de artículos por nombre."""
    if not q or len(q.strip()) < 2:
        return JSONResponse({"resultados": []})

    resultados = buscar_articulos_por_nombre(q)
    return JSONResponse({"resultados": resultados})


# ═══════════════════════════════════════════════════════════════════════════
# Consulta por ticket
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/ticket", response_class=HTMLResponse)
async def consultar_ticket(
    request: Request,
    q: str = "",
):
    """Consulta de ticket: busca por ID o folio."""
    ticket = None
    busqueda = q

    if q:
        ticket = buscar_ticket(q)
        if not ticket:
            return render(
                request,
                "consultar_ticket.html",
                "ticket",
                context={
                    "error": f"No se encontró el ticket '{q}'.",
                    "busqueda": busqueda,
                    "ticket": None,
                    "tickets_recientes": listar_tickets_recientes(10),
                },
            )

    return render(
        request,
        "consultar_ticket.html",
        "ticket",
        context={
            "busqueda": busqueda,
            "ticket": ticket,
            "tickets_recientes": listar_tickets_recientes(10),
        },
    )


@router.get("/api/articulos/precios/{articulo_id}")
async def api_precios_articulo(articulo_id: int, anio: Optional[str] = None):
    """Endpoint AJAX con la serie de precios mensuales para el gráfico de evolución."""
    serie = precios_articulo_serie(articulo_id, anio)
    if not serie:
        return JSONResponse({"error": "artículo no encontrado"})
    return JSONResponse(serie)


@router.get("/api/ticket/buscar")
async def api_buscar_ticket(q: str):
    """Endpoint AJAX para búsqueda de tickets."""
    if not q:
        return JSONResponse({"ticket": None})

    ticket = buscar_ticket(q)
    return JSONResponse({"ticket": ticket})
