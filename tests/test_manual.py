"""Tests de la captura manual y del total histórico de tickets."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.services import panel, staging
from backend.services.registro import (
    TicketDuplicado,
    confirmar_y_registrar,
    sha256_de_ticket,
)
from backend.services.catalogo import normalizar_correcciones


@pytest.fixture
def datos_temporales(tmp_path, monkeypatch):
    """Aísla la BD, el staging y los directorios de archivos en un tmp_path."""
    db_path = tmp_path / "despensa.db"
    monkeypatch.setattr(database, "CATALOGO_DB_PATH", db_path)
    database.init_db()

    for nombre in ("uploads", "staging", "resultados", "procesados", "descartados"):
        (tmp_path / nombre).mkdir()

    monkeypatch.setattr(staging, "STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(staging, "UPLOAD_DIR", tmp_path / "uploads")

    from backend.routers import tickets as tickets_router

    monkeypatch.setattr(tickets_router, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(tickets_router, "RESULTADOS_DIR", tmp_path / "resultados")
    monkeypatch.setattr(tickets_router, "PROCESADOS_DIR", tmp_path / "procesados")
    monkeypatch.setattr(tickets_router, "DESCARTADOS_DIR", tmp_path / "descartados")

    return tmp_path


def _datos_manual(total=25.0):
    return {
        "rfc_emisor": "",
        "regimen_fiscal": "",
        "cliente": "",
        "tarjeta": "1234",
        "fecha_compra": "21/Oct/26",
        "hora_compra": "14:30",
        "fecha_iso": "2026-10-21",
        "folio": "MANUAL-1",
        "establecimiento": "Tienda de prueba",
        "total_ticket": total,
        "iva": None,
        "ieps": None,
        "articulos_declarados": 1,
        "ahorro": 0.0,
        "articulos": [
            {
                "articulo": "Producto manual",
                "sku": "",
                "cantidad": 1.0,
                "precio_regular": total,
                "precio_promocion": None,
                "total": total,
                "categoria": "ABARROTES",
                "subcategoria": "BASICOS",
                "registrar_producto": True,
                "tipo": "producto",
            }
        ],
        "descuentos": [],
        "origen": "manual",
        "notas": "Carga manual.",
    }


def test_total_tickets_sigue_el_periodo_del_panel(datos_temporales):
    ticket = staging.crear_staging_manual(_datos_manual(), "manual_test", "MANUAL-TEST")
    correcciones = normalizar_correcciones(ticket, [])
    confirmar_y_registrar(ticket, correcciones, sha256_de_ticket(ticket))

    todo = panel.indicadores(None)
    octubre = panel.indicadores("2026-10")
    septiembre = panel.indicadores("2026-09")

    assert todo["tickets_total"] == 1
    assert octubre["tickets_total"] == 1
    assert septiembre["tickets_total"] == 0


def test_confirmar_manual_registra_origen_y_detalle(datos_temporales):
    ticket = staging.crear_staging_manual(_datos_manual(), "manual_db", "MANUAL-DB")
    correcciones = normalizar_correcciones(ticket, [])
    informe = confirmar_y_registrar(
        ticket, correcciones, sha256_de_ticket(ticket)
    )

    conn = database.get_db_connection()
    try:
        cabecera = conn.execute(
            "SELECT origen, archivo, total FROM tickets WHERE id = ?",
            (informe["ticket_db_id"],),
        ).fetchone()
        detalle = conn.execute(
            "SELECT descripcion, total FROM detalle_tickets WHERE ticket_id = ?",
            (informe["ticket_db_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert cabecera["origen"] == "manual"
    assert cabecera["archivo"] == "MANUAL-DB"
    assert cabecera["total"] == 25.0
    assert detalle["descripcion"] == "Producto manual"
    assert detalle["total"] == 25.0


def test_confirmar_manual_detecta_duplicado(datos_temporales):
    ticket = staging.crear_staging_manual(_datos_manual(), "manual_dup", "MANUAL-DUP")
    correcciones = normalizar_correcciones(ticket, [])
    sha = sha256_de_ticket(ticket)
    confirmar_y_registrar(ticket, correcciones, sha)

    with pytest.raises(TicketDuplicado):
        confirmar_y_registrar(ticket, correcciones, sha)


def test_flujo_http_manual_crea_staging_y_confirma(datos_temporales):
    from backend.main import app

    cliente = TestClient(app)

    respuesta = cliente.get("/tickets/manual")
    assert respuesta.status_code == 200
    assert "Captura manual de ticket" in respuesta.text

    filas = [
        {
            "descripcion": "Café manual",
            "sku": "",
            "cantidad": "2",
            "precio_regular": "10",
            "precio_promocion": "",
            "total": "20",
            "categoria": "ABARROTES",
            "subcategoria": "BASICOS",
            "registrar_producto": True,
        }
    ]
    datos = {
        "fecha": "2026-10-21",
        "hora": "09:15",
        "establecimiento": "Tienda HTTP",
        "folio": "HTTP-1",
        "forma_pago": "EFECTIVO",
        "tarjeta": "",
        "rfc_emisor": "",
        "cliente": "",
        "total_ticket": "20",
        "notas": "",
        "renglones": json.dumps(filas),
    }
    respuesta = cliente.post("/tickets/manual", data=datos, follow_redirects=False)
    assert respuesta.status_code == 303

    revision = cliente.get("/tickets")
    assert "MANUAL-" in revision.text
    assert "Café manual" in revision.text

    archivos = list((datos_temporales / "staging").glob("manual_*.json"))
    assert len(archivos) == 1
    ticket_id = archivos[0].stem

    correcciones = [
        {
            "indice": 0,
            "categoria": "ABARROTES",
            "subcategoria": "BASICOS",
            "registrar_producto": True,
        }
    ]
    respuesta = cliente.post(
        "/confirmar-ticket/",
        data={"ticket_id": ticket_id, "correcciones": json.dumps(correcciones)},
        follow_redirects=False,
    )
    assert respuesta.status_code == 303

    conn = database.get_db_connection()
    try:
        fila = conn.execute(
            "SELECT origen, folio, total FROM tickets WHERE folio = 'HTTP-1'"
        ).fetchone()
    finally:
        conn.close()

    assert fila["origen"] == "manual"
    assert fila["total"] == 20.0
    assert not (datos_temporales / "staging" / f"{ticket_id}.json").exists()


def test_migracion_8_conserva_tickets_y_permite_origen_manual(tmp_path):
    conn = sqlite3.connect(tmp_path / "migracion.db")
    conn.row_factory = sqlite3.Row
    try:
        for version, sql in database.MIGRACIONES[:7]:
            for sentencia in database._sentencias(sql):
                conn.execute(sentencia)
            conn.execute(f"PRAGMA user_version = {version}")
        conn.execute(
            "INSERT INTO tickets (archivo, sha256, fecha, total) "
            "VALUES ('viejo.pdf', 'hash-viejo', '2026-01-01', 10)"
        )
        conn.execute(
            "INSERT INTO detalle_tickets "
            "(ticket_id, linea, descripcion, cantidad, precio_regular, total) "
            "VALUES (1, 1, 'Producto viejo', 1, 10, 10)"
        )
        conn.commit()

        aplicadas = database.migrar(conn)

        assert 8 in aplicadas
        assert database.version_actual(conn) == 8
        assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM detalle_tickets").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        conn.execute(
            "INSERT INTO tickets (archivo, sha256, fecha, total, origen) "
            "VALUES ('manual', 'hash-manual', '2026-01-02', 5, 'manual')"
        )
        assert conn.execute(
            "SELECT origen FROM tickets WHERE archivo = 'manual'"
        ).fetchone()[0] == "manual"
    finally:
        conn.close()
