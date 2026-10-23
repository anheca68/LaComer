"""Usuarios, roles y sesiones.

Cada persona entra con su usuario y contraseña. Un usuario puede tener varios
roles y basta con que tenga uno de los permitidos para usar una ruta:

- ``admin``: gestiona usuarios; agrega, modifica y anula tickets.
- ``capturista``: agrega tickets (PDF o manuales) y clasifica productos.
- ``consulta``: solo ve panel, consultas y reportes.

``MiddlewareSesion`` exige sesión en toda la aplicación salvo en las rutas
públicas, así que una ruta nueva queda protegida aunque se olvide declararla.
Los permisos por rol se piden en cada ruta con ``Depends(requiere_rol(...))``.
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Optional
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.database import get_db_connection

ROLES = ("admin", "capturista", "consulta")

COOKIE_SESION = "sesion"
DURACION_SESION = timedelta(hours=8)

# Rutas que se pueden abrir sin sesión.
RUTAS_PUBLICAS = ("/login", "/health")
PREFIJOS_PUBLICOS = ("/static/",)

# Parámetros de scrypt: ~16 MB de memoria por intento, suficiente para que un
# ataque de diccionario sea caro sin volver lento el inicio de sesión.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1

# Usuario de la petición en curso, para que `registrar_cambio` sepa quién hizo
# el cambio sin pasarlo por todas las funciones del catálogo.
usuario_en_curso: ContextVar[Optional[int]] = ContextVar("usuario_en_curso", default=None)


@dataclass
class Usuario:
    id: int
    usuario: str
    nombre: Optional[str]
    roles: set = field(default_factory=set)

    def tiene_rol(self, *roles: str) -> bool:
        """True si el usuario tiene al menos uno de los roles indicados."""
        return bool(self.roles.intersection(roles))

    @property
    def iniciales(self) -> str:
        """Hasta dos letras para el avatar: de las dos primeras palabras del nombre."""
        palabras = (self.nombre or self.usuario).split()
        return "".join(p[0] for p in palabras[:2]).upper() or "?"

    @property
    def es_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def puede_capturar(self) -> bool:
        return self.tiene_rol("admin", "capturista")


class ErrorUsuario(ValueError):
    """Dato de usuario inválido: nombre repetido, rol inexistente, etc."""


# ---------------------------------------------------------------------------
# Contraseñas
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash con sal en formato ``scrypt$n$r$p$sal$hash``."""
    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(
        password.encode(), salt=sal, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${sal.hex()}${derivada.hex()}"


def verificar_password(password: str, guardado: str) -> bool:
    try:
        algoritmo, n, r, p, sal, esperado = guardado.split("$")
    except (AttributeError, ValueError):
        return False
    if algoritmo != "scrypt":
        return False
    derivada = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(sal), n=int(n), r=int(r), p=int(p)
    )
    return hmac.compare_digest(derivada.hex(), esperado)


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------

def _roles_de(conn: sqlite3.Connection, usuario_id: int) -> set:
    filas = conn.execute(
        """
        SELECT r.nombre FROM usuario_roles ur JOIN roles r ON r.id = ur.rol_id
        WHERE ur.usuario_id = ?
        """,
        (usuario_id,),
    ).fetchall()
    return {f["nombre"] for f in filas}


def _validar_roles(roles: Iterable[str]) -> list:
    roles = sorted(set(roles))
    if not roles:
        raise ErrorUsuario("El usuario necesita al menos un rol.")
    desconocidos = [r for r in roles if r not in ROLES]
    if desconocidos:
        raise ErrorUsuario(f"Rol desconocido: {', '.join(desconocidos)}.")
    return roles


def _validar_password(password: str) -> None:
    if len(password or "") < 8:
        raise ErrorUsuario("La contraseña debe tener al menos 8 caracteres.")


def _asignar_roles(conn: sqlite3.Connection, usuario_id: int, roles: list) -> None:
    conn.execute("DELETE FROM usuario_roles WHERE usuario_id = ?", (usuario_id,))
    conn.executemany(
        """
        INSERT INTO usuario_roles (usuario_id, rol_id)
        SELECT ?, id FROM roles WHERE nombre = ?
        """,
        [(usuario_id, r) for r in roles],
    )


def _admins_activos(conn: sqlite3.Connection) -> int:
    return conn.execute(
        """
        SELECT COUNT(DISTINCT u.id) FROM usuarios u
        JOIN usuario_roles ur ON ur.usuario_id = u.id
        JOIN roles r ON r.id = ur.rol_id
        WHERE u.activo = 1 AND r.nombre = 'admin'
        """
    ).fetchone()[0]


def crear_usuario(
    usuario: str, password: str, roles: Iterable[str], nombre: str = ""
) -> int:
    usuario = (usuario or "").strip()
    if not usuario:
        raise ErrorUsuario("El nombre de usuario es obligatorio.")
    _validar_password(password)
    roles = _validar_roles(roles)

    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        try:
            cursor = conn.execute(
                "INSERT INTO usuarios (usuario, nombre, password_hash) VALUES (?, ?, ?)",
                (usuario, nombre.strip() or None, hash_password(password)),
            )
        except sqlite3.IntegrityError:
            raise ErrorUsuario(f"El usuario '{usuario}' ya existe.")
        _asignar_roles(conn, cursor.lastrowid, roles)
        conn.commit()
        return cursor.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def actualizar_usuario(
    usuario_id: int, roles: Iterable[str], activo: bool, nombre: str = ""
) -> None:
    """Cambia roles, nombre y estado. Nunca deja la aplicación sin un admin activo."""
    roles = _validar_roles(roles)
    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        if not conn.execute("SELECT 1 FROM usuarios WHERE id = ?", (usuario_id,)).fetchone():
            raise ErrorUsuario("El usuario no existe.")
        conn.execute(
            "UPDATE usuarios SET nombre = ?, activo = ? WHERE id = ?",
            (nombre.strip() or None, 1 if activo else 0, usuario_id),
        )
        _asignar_roles(conn, usuario_id, roles)
        if _admins_activos(conn) == 0:
            raise ErrorUsuario("Debe quedar al menos un administrador activo.")
        if not activo:
            conn.execute("DELETE FROM sesiones WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cambiar_password(usuario_id: int, password: str) -> None:
    _validar_password(password)
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE usuarios SET password_hash = ? WHERE id = ?",
            (hash_password(password), usuario_id),
        )
        # Las sesiones abiertas con la contraseña anterior dejan de valer.
        conn.execute("DELETE FROM sesiones WHERE usuario_id = ?", (usuario_id,))
        conn.commit()
    finally:
        conn.close()


def listar_usuarios() -> list:
    conn = get_db_connection()
    try:
        filas = conn.execute(
            "SELECT id, usuario, nombre, activo, creado_en FROM usuarios ORDER BY usuario"
        ).fetchall()
        return [{**dict(f), "roles": sorted(_roles_de(conn, f["id"]))} for f in filas]
    finally:
        conn.close()


def autenticar(usuario: str, password: str) -> Optional[Usuario]:
    conn = get_db_connection()
    try:
        fila = conn.execute(
            "SELECT * FROM usuarios WHERE usuario = ? AND activo = 1",
            ((usuario or "").strip(),),
        ).fetchone()
        if not fila or not verificar_password(password, fila["password_hash"]):
            return None
        return Usuario(fila["id"], fila["usuario"], fila["nombre"], _roles_de(conn, fila["id"]))
    finally:
        conn.close()


def crear_admin_inicial() -> Optional[int]:
    """Crea el primer admin con ADMIN_USUARIO y ADMIN_PASSWORD si no hay usuarios.

    Sin usuarios nadie podría entrar a crear el primero; después de eso las
    variables de entorno ya no tienen efecto.
    """
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not password:
        return None
    conn = get_db_connection()
    try:
        if conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]:
            return None
    finally:
        conn.close()
    usuario = os.environ.get("ADMIN_USUARIO", "admin")
    return crear_usuario(usuario, password, ["admin"], nombre="Administrador")


# ---------------------------------------------------------------------------
# Sesiones
# ---------------------------------------------------------------------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def crear_sesion(usuario_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM sesiones WHERE expira_en < ?", (datetime.now().isoformat(),))
        conn.execute(
            "INSERT INTO sesiones (token_hash, usuario_id, expira_en) VALUES (?, ?, ?)",
            (_hash_token(token), usuario_id, (datetime.now() + DURACION_SESION).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def usuario_de_sesion(token: Optional[str]) -> Optional[Usuario]:
    if not token:
        return None
    conn = get_db_connection()
    try:
        fila = conn.execute(
            """
            SELECT u.id, u.usuario, u.nombre FROM sesiones s
            JOIN usuarios u ON u.id = s.usuario_id
            WHERE s.token_hash = ? AND s.expira_en > ? AND u.activo = 1
            """,
            (_hash_token(token), datetime.now().isoformat()),
        ).fetchone()
        if not fila:
            return None
        return Usuario(fila["id"], fila["usuario"], fila["nombre"], _roles_de(conn, fila["id"]))
    finally:
        conn.close()


def cerrar_sesion(token: Optional[str]) -> None:
    if not token:
        return
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM sesiones WHERE token_hash = ?", (_hash_token(token),))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Integración con FastAPI
# ---------------------------------------------------------------------------

def _es_publica(path: str) -> bool:
    return path in RUTAS_PUBLICAS or path.startswith(PREFIJOS_PUBLICOS)


def _espera_html(request: Request) -> bool:
    """Una navegación del navegador se redirige al login; lo demás recibe 401."""
    return (
        request.method == "GET"
        and not request.url.path.startswith("/api/")
        and "text/html" in request.headers.get("accept", "")
    )


class MiddlewareSesion(BaseHTTPMiddleware):
    """Exige sesión en toda la aplicación salvo las rutas públicas."""

    async def dispatch(self, request: Request, call_next):
        if _es_publica(request.url.path):
            return await call_next(request)

        usuario = usuario_de_sesion(request.cookies.get(COOKIE_SESION))
        if usuario is None:
            if _espera_html(request):
                destino = request.url.path
                if request.url.query:
                    destino += "?" + request.url.query
                return RedirectResponse(f"/login?siguiente={quote(destino)}", status_code=303)
            return JSONResponse({"detail": "Inicia sesión para continuar."}, status_code=401)

        request.state.usuario = usuario
        marca = usuario_en_curso.set(usuario.id)
        try:
            return await call_next(request)
        finally:
            usuario_en_curso.reset(marca)


def usuario_actual(request: Request) -> Usuario:
    usuario = getattr(request.state, "usuario", None)
    if usuario is None:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
    return usuario


def requiere_rol(*roles: str):
    """Dependencia que deja pasar si el usuario tiene alguno de los roles."""

    def dependencia(request: Request) -> Usuario:
        usuario = usuario_actual(request)
        if not usuario.tiene_rol(*roles):
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para esta acción.",
            )
        return usuario

    return dependencia


# Atajos para las combinaciones que usan los routers.
solo_admin = requiere_rol("admin")
captura = requiere_rol("admin", "capturista")
