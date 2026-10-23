"""Administración de usuarios y corrección de tickets registrados (solo admin)."""

from typing import List
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.auth import (
    ROLES,
    ErrorUsuario,
    actualizar_usuario,
    cambiar_password,
    crear_usuario,
    listar_usuarios,
    solo_admin,
)
from backend.services.consultas import buscar_ticket
from backend.services.edicion_tickets import (
    CAMPOS_EDITABLES,
    ErrorEdicion,
    actualizar_ticket,
    cambiar_estado,
    obtener_ticket,
)
from backend.web import render

router = APIRouter(tags=["Administración"], dependencies=[Depends(solo_admin)])


def _redir(ruta: str, mensaje: str = None, error: str = None) -> RedirectResponse:
    if mensaje:
        ruta += f"?mensaje={quote(mensaje)}"
    elif error:
        ruta += f"?error={quote(error)}"
    return RedirectResponse(ruta, status_code=303)


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------

@router.get("/admin/usuarios", response_class=HTMLResponse)
async def usuarios(request: Request, mensaje: str = None, error: str = None):
    return render(
        request,
        "admin_usuarios.html",
        "usuarios",
        context={
            "usuarios": listar_usuarios(),
            "roles": ROLES,
            "mensaje": mensaje,
            "error": error,
        },
    )


@router.post("/admin/usuarios")
async def crear(
    usuario: str = Form(...),
    nombre: str = Form(""),
    password: str = Form(...),
    roles: List[str] = Form([]),
):
    try:
        crear_usuario(usuario, password, roles, nombre)
    except ErrorUsuario as e:
        return _redir("/admin/usuarios", error=str(e))
    return _redir("/admin/usuarios", mensaje=f"Usuario '{usuario.strip()}' creado.")


@router.post("/admin/usuarios/{usuario_id}")
async def actualizar(
    usuario_id: int,
    nombre: str = Form(""),
    activo: bool = Form(False),
    roles: List[str] = Form([]),
):
    try:
        actualizar_usuario(usuario_id, roles, activo, nombre)
    except ErrorUsuario as e:
        return _redir("/admin/usuarios", error=str(e))
    return _redir("/admin/usuarios", mensaje="Usuario actualizado.")


@router.post("/admin/usuarios/{usuario_id}/password")
async def nueva_password(usuario_id: int, password: str = Form(...)):
    try:
        cambiar_password(usuario_id, password)
    except ErrorUsuario as e:
        return _redir("/admin/usuarios", error=str(e))
    return _redir("/admin/usuarios", mensaje="Contraseña cambiada; se cerraron sus sesiones.")


# ---------------------------------------------------------------------------
# Tickets registrados
# ---------------------------------------------------------------------------

@router.get("/admin/tickets/{ticket_id}", response_class=HTMLResponse)
async def editar_ticket(request: Request, ticket_id: int, mensaje: str = None, error: str = None):
    ticket = obtener_ticket(ticket_id)
    if ticket is None:
        return _redir("/ticket", error=f"No existe el ticket #{ticket_id}.")
    detalle = buscar_ticket(str(ticket_id)) or {}
    return render(
        request,
        "admin_ticket.html",
        "ticket",
        context={
            "ticket": ticket,
            "renglones": detalle.get("renglones", []),
            "mensaje": mensaje,
            "error": error,
        },
    )


@router.post("/admin/tickets/{ticket_id}")
async def guardar_ticket(request: Request, ticket_id: int):
    formulario = await request.form()
    datos = {c: formulario.get(c) for c in CAMPOS_EDITABLES if c in formulario}
    ruta = f"/admin/tickets/{ticket_id}"
    try:
        cambiados = actualizar_ticket(ticket_id, datos)
    except ErrorEdicion as e:
        return _redir(ruta, error=str(e))
    if not cambiados:
        return _redir(ruta, mensaje="No había cambios que guardar.")
    return _redir(ruta, mensaje="Ticket actualizado: " + ", ".join(cambiados) + ".")


@router.post("/admin/tickets/{ticket_id}/anular")
async def anular_ticket(ticket_id: int, motivo: str = Form("")):
    ruta = f"/admin/tickets/{ticket_id}"
    try:
        cambiar_estado(ticket_id, "anulado", motivo)
    except ErrorEdicion as e:
        return _redir(ruta, error=str(e))
    return _redir(ruta, mensaje="Ticket anulado: ya no cuenta en panel ni reportes.")


@router.post("/admin/tickets/{ticket_id}/reactivar")
async def reactivar_ticket(ticket_id: int, motivo: str = Form("")):
    ruta = f"/admin/tickets/{ticket_id}"
    try:
        cambiar_estado(ticket_id, "confirmado", motivo)
    except ErrorEdicion as e:
        return _redir(ruta, error=str(e))
    return _redir(ruta, mensaje="Ticket reactivado.")
