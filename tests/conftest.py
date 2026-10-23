"""Fixtures compartidas: base temporal y clientes con sesión iniciada."""

import os
import tempfile

# `backend.database` migra la base al importarse. Sin esto, correr las pruebas
# migraría la base real de backend/; tiene que ir antes de importar backend.
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="lacomer-pruebas-"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import database  # noqa: E402
from backend.auth import crear_usuario  # noqa: E402

PASSWORD_PRUEBA = "clave-de-prueba"


@pytest.fixture
def bd_temporal(tmp_path, monkeypatch):
    """Base vacía y migrada en un tmp_path."""
    db_path = tmp_path / "despensa.db"
    monkeypatch.setattr(database, "CATALOGO_DB_PATH", db_path)
    database.init_db()
    return db_path


@pytest.fixture
def iniciar_sesion():
    """Crea un usuario con los roles dados y devuelve un cliente con su sesión.

    Usa la base que ya haya preparado otra fixture (`bd_temporal` o
    `datos_temporales`), por eso no depende de ninguna.
    """
    from backend.main import app

    def _iniciar(*roles, usuario=None):
        usuario = usuario or "-".join(roles) or "sin-roles"
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
