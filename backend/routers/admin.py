"""Router de administración: login y normalización de productos."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from backend.auth import (
    cerrar_sesion,
    crear_sesion,
    requiere_admin,
    verificar_password,
)
from backend.services.admin_normalizacion import (
    detectar_duplicados,
    crear_copia_seguridad,
    fusionar_productos,
    obtener_copias_seguridad,
    restaurar_copia_seguridad,
)
from backend.web import render

router = APIRouter(tags=["Administración"])


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, error: str = None):
    """Muestra el formulario de login de administrador."""
    return render(
        request,
        "admin_login.html",
        "admin",
        context={"error": error},
    )


@router.post("/admin/login")
async def admin_login_post(password: str = Form(...)):
    """Valida la contraseña y crea la sesión."""
    if not verificar_password(password):
        return RedirectResponse(
            "/admin/login?error=Contraseña+incorrecta",
            status_code=303,
        )

    token = crear_sesion()
    response = RedirectResponse("/admin/normalizar-productos", status_code=303)
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        max_age=28800,  # 8 horas
        samesite="lax",
    )
    return response


@router.get("/admin/logout")
async def admin_logout(request: Request):
    """Cierra la sesión de administrador."""
    token = request.cookies.get("admin_token")
    cerrar_sesion(token)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("admin_token")
    return response


@router.get("/admin/normalizar-productos", response_class=HTMLResponse)
@requiere_admin
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
@requiere_admin
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
@requiere_admin
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
