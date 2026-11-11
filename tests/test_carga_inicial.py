"""La carga inicial vive fuera de la aplicación principal."""

import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.auth import crear_usuario
from tests.conftest import PASSWORD_PRUEBA


@pytest.fixture
def cliente_carga():
    """Cliente de la herramienta aparte con un usuario de los roles dados."""
    from carga_inicial.app import app

    def _iniciar(*roles):
        usuario = "carga-" + "-".join(roles)
        crear_usuario(usuario, PASSWORD_PRUEBA, roles)
        cliente = TestClient(app)
        respuesta = cliente.post(
            "/login",
            data={"usuario": usuario, "password": PASSWORD_PRUEBA},
            follow_redirects=False,
        )
        assert respuesta.status_code == 303, respuesta.text
        return cliente

    return _iniciar


@pytest.mark.parametrize("metodo, ruta", [
    ("get", "/importar"),
    ("get", "/importar/plan"),
    ("post", "/importar/preparar"),
    ("post", "/importar/aplicar"),
])
def test_app_principal_no_expone_importar(bd_temporal, iniciar_sesion, metodo, ruta):
    cliente = iniciar_sesion("admin")
    assert getattr(cliente, metodo)(ruta).status_code == 404


def test_menu_principal_no_ofrece_carga_inicial(bd_temporal, iniciar_sesion):
    html = iniciar_sesion("admin").get("/").text
    assert "/importar" not in html


def test_app_principal_no_lee_el_excel():
    from backend import config
    assert not hasattr(config, "CATALOGO_EXCEL_PATH")


def test_herramienta_abre_importar_para_admin(bd_temporal, cliente_carga):
    respuesta = cliente_carga("admin").get("/importar")
    assert respuesta.status_code == 200
    assert "Carga inicial de histórico" in respuesta.text


@pytest.mark.parametrize("roles", [("capturista",), ("consulta",)])
def test_herramienta_solo_para_admin(bd_temporal, cliente_carga, roles):
    assert cliente_carga(*roles).get("/importar").status_code == 403


def test_herramienta_se_cierra_con_tickets(bd_temporal, cliente_carga):
    conn = database.get_db_connection()
    with conn:
        conn.execute(
            "INSERT INTO tickets (archivo, sha256, fecha, total) "
            "VALUES ('a.pdf', 'h', '2026-01-01', 10)"
        )
    conn.close()

    respuesta = cliente_carga("admin").get("/importar", follow_redirects=False)
    assert respuesta.status_code == 303
    assert respuesta.headers["location"].startswith("/tickets")


def test_herramienta_avisa_si_falta_el_excel(bd_temporal, cliente_carga, monkeypatch, tmp_path):
    from carga_inicial import servicio

    monkeypatch.setattr(servicio, "CATALOGO_EXCEL_PATH", str(tmp_path / "no-existe.xlsx"))
    with pytest.raises(servicio.ErrorImportacion):
        servicio.leer_excel()
