"""Inicio y cierre de sesión."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.auth import (
    COOKIE_SESION,
    DURACION_SESION,
    autenticar,
    cerrar_sesion,
    crear_sesion,
)
from backend.config import COOKIE_SEGURA
from backend.web import render

router = APIRouter(tags=["Sesión"])


def _destino_seguro(siguiente: str) -> str:
    """Solo rutas locales: evita que el login redirija a otro sitio."""
    if siguiente.startswith("/") and not siguiente.startswith("//"):
        return siguiente
    return "/"


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request, siguiente: str = "/", error: str = None):
    return render(
        request,
        "login.html",
        "login",
        context={"siguiente": _destino_seguro(siguiente), "error": error},
    )


@router.post("/login")
async def login_post(
    request: Request,
    usuario: str = Form(...),
    password: str = Form(...),
    siguiente: str = Form("/"),
):
    encontrado = autenticar(usuario, password)
    if encontrado is None:
        return render(
            request,
            "login.html",
            "login",
            context={
                "siguiente": _destino_seguro(siguiente),
                "error": "Usuario o contraseña incorrectos.",
                "usuario_escrito": usuario,
            },
            status_code=401,
        )

    response = RedirectResponse(_destino_seguro(siguiente), status_code=303)
    response.set_cookie(
        key=COOKIE_SESION,
        value=crear_sesion(encontrado.id),
        httponly=True,
        max_age=int(DURACION_SESION.total_seconds()),
        samesite="lax",
        secure=COOKIE_SEGURA,
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    cerrar_sesion(request.cookies.get(COOKIE_SESION))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_SESION)
    return response


@router.get("/admin/login")
async def admin_login_anterior():
    """La ruta del login anterior sigue funcionando para enlaces guardados."""
    return RedirectResponse("/login", status_code=303)
