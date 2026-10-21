"""Autenticación simple para el panel de administración.

Usa una contraseña definida en la variable de entorno ADMIN_PASSWORD.
La sesión se maneja con un token simple en cookie.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps

from fastapi import Request, Response

# Token de sesión: {token: expiracion}
_sesiones: dict[str, datetime] = {}

# Duración de la sesión: 8 horas
DURACION_SESION = timedelta(hours=8)


def _hash_password(password: str) -> str:
    """Hash simple de la contraseña para comparación segura."""
    return hashlib.sha256(password.encode()).hexdigest()


def verificar_password(password: str) -> bool:
    """Verifica si la contraseña es correcta."""
    esperada = os.environ.get("ADMIN_PASSWORD", "")
    if not esperada:
        return False
    return hmac.compare_digest(_hash_password(password), _hash_password(esperada))


def crear_sesion() -> str:
    """Crea una nueva sesión y devuelve el token."""
    token = secrets.token_urlsafe(32)
    _sesiones[token] = datetime.now() + DURACION_SESION
    return token


def validar_sesion(token: str) -> bool:
    """Verifica si un token de sesión es válido."""
    if not token:
        return False
    expiracion = _sesiones.get(token)
    if not expiracion:
        return False
    if datetime.now() > expiracion:
        del _sesiones[token]
        return False
    return True


def cerrar_sesion(token: str) -> None:
    """Cierra una sesión."""
    _sesiones.pop(token, None)


def requiere_admin(func):
    """Decorador que protege rutas de administración."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Buscar el Request en los argumentos
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        if request is None:
            for v in kwargs.values():
                if isinstance(v, Request):
                    request = v
                    break

        if request is None:
            return Response("No autorizado", status_code=401)

        token = request.cookies.get("admin_token")
        if not validar_sesion(token):
            return Response("No autorizado", status_code=401)

        return await func(*args, **kwargs)
    return wrapper
