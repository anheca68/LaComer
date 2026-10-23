"""Usuarios, sesiones y permisos por rol."""

import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.auth import (
    ErrorUsuario,
    actualizar_usuario,
    autenticar,
    crear_admin_inicial,
    crear_usuario,
    hash_password,
    listar_usuarios,
    verificar_password,
)
from tests.conftest import PASSWORD_PRUEBA


def _cliente_sin_sesion():
    from backend.main import app

    return TestClient(app)


def _insertar_ticket(folio="T-1") -> int:
    conn = database.get_db_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO tickets (archivo, sha256, fecha, total, folio) "
            "VALUES ('prueba.pdf', ?, '2026-10-01', 100, ?)",
            (f"hash-{folio}", folio),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Contraseñas y usuarios
# ---------------------------------------------------------------------------

def test_hash_password_usa_sal_y_verifica():
    a, b = hash_password("secreta-123"), hash_password("secreta-123")
    assert a != b
    assert a.startswith("scrypt$")
    assert verificar_password("secreta-123", a)
    assert not verificar_password("otra-clave", a)
    assert not verificar_password("secreta-123", "formato-viejo")


def test_usuario_con_varios_roles(bd_temporal):
    crear_usuario("ana", PASSWORD_PRUEBA, ["consulta", "capturista"])
    usuario = autenticar("ana", PASSWORD_PRUEBA)
    assert usuario.roles == {"consulta", "capturista"}
    assert usuario.puede_capturar and not usuario.es_admin


@pytest.mark.parametrize(
    "usuario, password, roles, mensaje",
    [
        ("", PASSWORD_PRUEBA, ["consulta"], "obligatorio"),
        ("ana", "corta", ["consulta"], "8 caracteres"),
        ("ana", PASSWORD_PRUEBA, [], "al menos un rol"),
        ("ana", PASSWORD_PRUEBA, ["jefe"], "Rol desconocido"),
    ],
)
def test_crear_usuario_valida_datos(bd_temporal, usuario, password, roles, mensaje):
    with pytest.raises(ErrorUsuario, match=mensaje):
        crear_usuario(usuario, password, roles)


def test_usuario_repetido_sin_importar_mayusculas(bd_temporal):
    crear_usuario("Ana", PASSWORD_PRUEBA, ["consulta"])
    with pytest.raises(ErrorUsuario, match="ya existe"):
        crear_usuario("ana", PASSWORD_PRUEBA, ["consulta"])


def test_no_se_puede_quedar_sin_admin_activo(bd_temporal):
    admin_id = crear_usuario("jefe", PASSWORD_PRUEBA, ["admin"])
    with pytest.raises(ErrorUsuario, match="administrador activo"):
        actualizar_usuario(admin_id, ["consulta"], activo=True)
    with pytest.raises(ErrorUsuario, match="administrador activo"):
        actualizar_usuario(admin_id, ["admin"], activo=False)
    assert listar_usuarios()[0]["roles"] == ["admin"]


def test_admin_inicial_desde_variables_de_entorno(bd_temporal, monkeypatch):
    monkeypatch.setenv("ADMIN_USUARIO", "dueño")
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD_PRUEBA)
    assert crear_admin_inicial() is not None
    assert autenticar("dueño", PASSWORD_PRUEBA).es_admin
    # Con usuarios ya creados no vuelve a crear nada.
    assert crear_admin_inicial() is None


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------

def test_sin_sesion_la_api_responde_401(bd_temporal):
    cliente = _cliente_sin_sesion()
    assert cliente.get("/api/categorias").status_code == 401
    assert cliente.post("/confirmar-ticket/", data={"ticket_id": "x"}).status_code == 401
    assert cliente.post("/tickets/manual", data={"fecha": "2026-10-01"}).status_code == 401


def test_sin_sesion_el_navegador_va_al_login(bd_temporal):
    respuesta = _cliente_sin_sesion().get(
        "/reportes", headers={"accept": "text/html"}, follow_redirects=False
    )
    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/login?siguiente=/reportes"


def test_rutas_publicas_sin_sesion(bd_temporal):
    cliente = _cliente_sin_sesion()
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/login").status_code == 200


def test_login_incorrecto_y_usuario_inactivo(bd_temporal, iniciar_sesion):
    iniciar_sesion("admin", usuario="jefe")
    crear_usuario("ana", PASSWORD_PRUEBA, ["consulta"])
    cliente = _cliente_sin_sesion()
    malo = cliente.post("/login", data={"usuario": "ana", "password": "equivocada"})
    assert malo.status_code == 401

    ana = next(u for u in listar_usuarios() if u["usuario"] == "ana")
    actualizar_usuario(ana["id"], ["consulta"], activo=False)
    inactivo = cliente.post(
        "/login", data={"usuario": "ana", "password": PASSWORD_PRUEBA}, follow_redirects=False
    )
    assert inactivo.status_code == 401


def test_login_no_redirige_a_otro_sitio(bd_temporal):
    crear_usuario("ana", PASSWORD_PRUEBA, ["consulta"])
    respuesta = _cliente_sin_sesion().post(
        "/login",
        data={"usuario": "ana", "password": PASSWORD_PRUEBA, "siguiente": "//malicioso.com"},
        follow_redirects=False,
    )
    assert respuesta.headers["location"] == "/"


def test_logout_invalida_la_sesion(bd_temporal, iniciar_sesion):
    cliente = iniciar_sesion("consulta")
    assert cliente.get("/api/categorias").status_code == 200
    cliente.post("/logout", follow_redirects=False)
    cliente.cookies.clear()
    assert cliente.get("/api/categorias").status_code == 401


def test_cambiar_password_cierra_sesiones(bd_temporal, iniciar_sesion):
    admin = iniciar_sesion("admin", usuario="jefe")
    ana = iniciar_sesion("consulta", usuario="ana")
    ana_id = next(u["id"] for u in listar_usuarios() if u["usuario"] == "ana")
    admin.post(f"/admin/usuarios/{ana_id}/password", data={"password": "nueva-clave-1"})
    assert ana.get("/api/categorias").status_code == 401


# ---------------------------------------------------------------------------
# Permisos por rol: 403 sin el rol, 200/303 con él
# ---------------------------------------------------------------------------

RUTAS_CAPTURA = [
    ("get", "/tickets"),
    ("get", "/tickets/manual"),
    ("post", "/tickets/manual"),
    ("post", "/cargar-archivos/"),
    ("post", "/revisar-ticket/"),
    ("post", "/guardar-cambios/"),
    ("post", "/confirmar-ticket/"),
    ("post", "/descartar-ticket/"),
    ("post", "/catalogo/reclasificar"),
]

RUTAS_ADMIN = [
    ("get", "/admin/usuarios"),
    ("post", "/admin/usuarios"),
    ("get", "/admin/normalizar-productos"),
    ("post", "/admin/normalizar-productos/deshacer"),
    ("get", "/importar"),
    ("post", "/importar/aplicar"),
    ("get", "/admin/tickets/1"),
    ("post", "/admin/tickets/1/anular"),
]


@pytest.mark.parametrize("metodo, ruta", RUTAS_CAPTURA + RUTAS_ADMIN)
def test_consulta_no_escribe(bd_temporal, iniciar_sesion, metodo, ruta):
    cliente = iniciar_sesion("consulta")
    assert getattr(cliente, metodo)(ruta).status_code == 403


@pytest.mark.parametrize("metodo, ruta", RUTAS_ADMIN)
def test_capturista_no_administra(bd_temporal, iniciar_sesion, metodo, ruta):
    cliente = iniciar_sesion("capturista")
    assert getattr(cliente, metodo)(ruta).status_code == 403


@pytest.mark.parametrize("ruta", ["/", "/reportes", "/ticket", "/articulo", "/catalogo", "/log"])
def test_consulta_ve_pantallas_de_lectura(bd_temporal, iniciar_sesion, ruta):
    assert iniciar_sesion("consulta").get(ruta).status_code == 200


@pytest.mark.parametrize("roles", [("capturista",), ("admin",), ("consulta", "capturista")])
def test_roles_de_captura_abren_la_captura(bd_temporal, iniciar_sesion, roles):
    assert iniciar_sesion(*roles).get("/tickets/manual").status_code == 200


def test_menu_segun_rol(bd_temporal, iniciar_sesion):
    consulta = iniciar_sesion("consulta").get("/").text
    assert "/tickets/manual" not in consulta and "/admin/usuarios" not in consulta
    capturista = iniciar_sesion("capturista").get("/").text
    assert "/tickets/manual" in capturista and "/admin/usuarios" not in capturista
    admin = iniciar_sesion("admin").get("/").text
    assert "/tickets/manual" in admin and "/admin/usuarios" in admin


# ---------------------------------------------------------------------------
# Administración de usuarios y tickets
# ---------------------------------------------------------------------------

def test_admin_crea_usuario_con_varios_roles(bd_temporal, iniciar_sesion):
    admin = iniciar_sesion("admin")
    respuesta = admin.post(
        "/admin/usuarios",
        data={"usuario": "luis", "password": PASSWORD_PRUEBA, "roles": ["consulta", "capturista"]},
        follow_redirects=False,
    )
    assert respuesta.status_code == 303 and "mensaje=" in respuesta.headers["location"]
    assert autenticar("luis", PASSWORD_PRUEBA).roles == {"consulta", "capturista"}


def test_admin_corrige_ticket_y_queda_en_el_log(bd_temporal, iniciar_sesion):
    ticket_id = _insertar_ticket()
    admin = iniciar_sesion("admin", usuario="jefe")
    respuesta = admin.post(
        f"/admin/tickets/{ticket_id}",
        data={"fecha": "2026-10-02", "establecimiento": "La Comer Centro"},
        follow_redirects=False,
    )
    assert "mensaje=" in respuesta.headers["location"]

    conn = database.get_db_connection()
    try:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        log = conn.execute(
            "SELECT l.campo, l.valor_anterior, l.valor_nuevo, u.usuario FROM log_cambios l "
            "JOIN usuarios u ON u.id = l.usuario_id WHERE l.tabla = 'tickets' ORDER BY l.id"
        ).fetchall()
    finally:
        conn.close()

    assert ticket["fecha"] == "2026-10-02"
    assert ticket["modificado_por"] is not None and ticket["modificado_en"]
    assert [tuple(f) for f in log] == [
        ("fecha", "2026-10-01", "2026-10-02", "jefe"),
        ("establecimiento", None, "La Comer Centro", "jefe"),
    ]


def test_fecha_invalida_no_cambia_nada(bd_temporal, iniciar_sesion):
    ticket_id = _insertar_ticket()
    admin = iniciar_sesion("admin")
    respuesta = admin.post(
        f"/admin/tickets/{ticket_id}", data={"fecha": "01/10/26"}, follow_redirects=False
    )
    assert "error=" in respuesta.headers["location"]


def test_anular_y_reactivar_ticket(bd_temporal, iniciar_sesion):
    ticket_id = _insertar_ticket()
    admin = iniciar_sesion("admin")

    sin_motivo = admin.post(f"/admin/tickets/{ticket_id}/anular", follow_redirects=False)
    assert "error=" in sin_motivo.headers["location"]

    admin.post(f"/admin/tickets/{ticket_id}/anular", data={"motivo": "Duplicado"})
    conn = database.get_db_connection()
    try:
        fila = conn.execute("SELECT estado, notas FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        assert fila["estado"] == "anulado"
        assert "Duplicado" in fila["notas"]
    finally:
        conn.close()

    admin.post(f"/admin/tickets/{ticket_id}/reactivar")
    conn = database.get_db_connection()
    try:
        estado = conn.execute("SELECT estado FROM tickets WHERE id = ?", (ticket_id,)).fetchone()[0]
    finally:
        conn.close()
    assert estado == "confirmado"


def test_restaurar_respaldo_rechaza_rutas_fuera_de_backups(bd_temporal, iniciar_sesion, tmp_path):
    ajeno = tmp_path / "despensa_backup_falso.db"
    ajeno.write_bytes(b"no es una base")
    admin = iniciar_sesion("admin")
    respuesta = admin.post(
        "/admin/normalizar-productos/deshacer",
        data={"ruta_copia": str(ajeno)},
        follow_redirects=False,
    )
    assert "error=" in respuesta.headers["location"]
    assert database.get_db_connection().execute("SELECT 1").fetchone()[0] == 1


def test_migracion_9_sobre_base_con_datos(tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "v8.db")
    conn.row_factory = sqlite3.Row
    try:
        for version, sql in database.MIGRACIONES[:8]:
            for sentencia in database._sentencias(sql):
                conn.execute(sentencia)
            conn.execute(f"PRAGMA user_version = {version}")
        conn.execute(
            "INSERT INTO tickets (archivo, sha256, fecha, total) VALUES ('a.pdf', 'h', '2026-01-01', 10)"
        )
        conn.commit()

        assert database.migrar(conn) == [9]
        fila = conn.execute("SELECT total, creado_por FROM tickets").fetchone()
        assert fila["total"] == 10 and fila["creado_por"] is None
        roles = {r[0] for r in conn.execute("SELECT nombre FROM roles")}
        assert roles == {"admin", "capturista", "consulta"}
    finally:
        conn.close()
