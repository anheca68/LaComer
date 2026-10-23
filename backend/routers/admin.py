"""Router de administración: normalización de productos (solo admin)."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.auth import solo_admin
from backend.services.admin_normalizacion import (
    detectar_duplicados,
    crear_copia_seguridad,
    fusionar_productos,
    obtener_copias_seguridad,
    restaurar_copia_seguridad,
)
from backend.web import render

router = APIRouter(tags=["Administración"], dependencies=[Depends(solo_admin)])


@router.get("/admin/normalizar-productos", response_class=HTMLResponse)
async def admin_normalizar(request: Request):
    """Vista previa de productos duplicados."""
    duplicados = detectar_duplicados()
    copias = obtener_copias_seguridad()

    return render(
        request,
        "admin_normalizar.html",
        "admin",
        context={
            "duplicados": duplicados,
            "copias": copias,
            "total_grupos": len(duplicados),
            "total_duplicados": sum(len(g["productos"]) - 1 for g in duplicados),
        },
    )


@router.post("/admin/normalizar-productos/ejecutar")
async def admin_ejecutar_normalizacion(
    request: Request,
    canonical_id: int = Form(...),
    grupo_norm: str = Form(...),
):
    """Ejecuta la fusión de un grupo de duplicados."""
    # Crear copia de seguridad antes de proceder
    backup_path = crear_copia_seguridad()

    # Buscar el grupo correspondiente
    duplicados = detectar_duplicados()
    grupo = next(
        (g for g in duplicados if g["descripcion_normalizada"] == grupo_norm),
        None,
    )

    if not grupo:
        return RedirectResponse(
            "/admin/normalizar-productos?error=No+se+encontró+el+grupo",
            status_code=303,
        )

    # Verificar que el canonical_id pertenece al grupo
    if not any(p["id"] == canonical_id for p in grupo["productos"]):
        return RedirectResponse(
            "/admin/normalizar-productos?error=ID+canónico+inválido",
            status_code=303,
        )

    resultado = fusionar_productos(grupo, canonical_id)

    return RedirectResponse(
        f"/admin/normalizar-productos?mensaje={resultado['mensaje']}",
        status_code=303,
    )


@router.post("/admin/normalizar-productos/deshacer")
async def admin_deshacer(
    request: Request,
    ruta_copia: str = Form(...),
):
    """Restaura la base de datos desde una copia de seguridad."""
    exito = restaurar_copia_seguridad(ruta_copia)

    if exito:
        return RedirectResponse(
            "/admin/normalizar-productos?mensaje=Copia+restaurada+correctamente",
            status_code=303,
        )
    else:
        return RedirectResponse(
            "/admin/normalizar-productos?error=No+se+pudo+restaurar+la+copia",
            status_code=303,
        )
