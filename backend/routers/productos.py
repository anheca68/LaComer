from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.auth import captura
from backend.web import render
from backend.services.catalogo import (
    SIN_CATEGORIA,
    SIN_SUBCATEGORIA,
    ErrorCatalogo,
    listar_productos,
    obtener_arbol_categorias,
    reclasificar_producto,
)

router = APIRouter(tags=["Catálogo"])



def _redir(mensaje: str = None, aviso: str = None, error: str = None) -> RedirectResponse:
    partes = []
    if mensaje:
        partes.append(f"mensaje={quote(mensaje)}")
    if aviso:
        partes.append(f"aviso={quote(aviso)}")
    if error:
        partes.append(f"error={quote(error)}")
    sufijo = "&".join(partes)
    return RedirectResponse(url=f"/catalogo?{sufijo}" if sufijo else "/catalogo", status_code=303)


@router.get("/catalogo", response_class=HTMLResponse, dependencies=[Depends(captura)])
async def editor_catalogo(
    request: Request,
    buscar: str = "",
    categoria: str = "",
    mensaje: str = None,
    aviso: str = None,
    error: str = None,
):
    productos = listar_productos(texto=buscar, categoria=categoria)

    return render(
        request,
        "catalogo.html",
        "catalogo",
        context={
            "productos": productos,
            "arbol_categorias": obtener_arbol_categorias(),
            "sin_categoria": SIN_CATEGORIA,
            "sin_subcategoria": SIN_SUBCATEGORIA,
            "buscar": buscar,
            "categoria": categoria,
            "mensaje": mensaje,
            "aviso": aviso,
            "error": error,
        },
    )


@router.post("/catalogo/reclasificar", dependencies=[Depends(captura)])
async def guardar_reclasificacion(
    descripcion: str = Form(...),
    sku: str = Form(""),
    categoria: str = Form(...),
    subcategoria: str = Form(""),
):
    try:
        resultado = reclasificar_producto(descripcion, categoria, subcategoria)
    except ErrorCatalogo as e:
        return _redir(error=str(e))
    except Exception as e:
        return _redir(error=f"No se pudo guardar: {e}")

    detalle = ""
    if resultado["creados"]:
        detalle = " Se agregó al catálogo: " + ", ".join(resultado["creados"]) + "."

    return _redir(
        mensaje=f'"{descripcion}" ahora es {resultado["categoria"]} / {resultado["subcategoria"]}.',
        aviso=detalle or None,
    )
