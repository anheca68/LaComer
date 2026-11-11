"""Base de datos separada de los archivos: DB_DIR y el script bd_volumen."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import bd_volumen

RAIZ = Path(__file__).resolve().parents[1]


def _rutas_con_entorno(tmp_path, **variables) -> dict:
    """Importa backend.config en un proceso aparte con las variables dadas."""
    entorno = {k: v for k, v in os.environ.items()
               if k not in ("DB_DIR", "CATALOGO_DB_DIR", "DATA_DIR")}
    entorno.update(variables)
    codigo = (
        "import json; from backend import config; "
        "print(json.dumps({'db': str(config.CATALOGO_DB_PATH), "
        "'backups': str(config.BACKUPS_DIR)}))"
    )
    salida = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ, env=entorno,
        capture_output=True, text=True, check=True,
    )
    return json.loads(salida.stdout)


def test_db_dir_separa_la_base_de_los_archivos(tmp_path):
    rutas = _rutas_con_entorno(
        tmp_path, DATA_DIR=str(tmp_path / "data"), DB_DIR=str(tmp_path / "db")
    )
    assert rutas["db"] == str(tmp_path / "db" / "despensa.db")
    assert rutas["backups"] == str(tmp_path / "data" / "backups")


def test_sin_db_dir_la_base_sigue_en_data_dir(tmp_path):
    rutas = _rutas_con_entorno(tmp_path, DATA_DIR=str(tmp_path / "data"))
    assert rutas["db"] == str(tmp_path / "data" / "despensa.db")


def test_catalogo_db_dir_se_conserva_por_compatibilidad(tmp_path):
    rutas = _rutas_con_entorno(
        tmp_path, DATA_DIR=str(tmp_path / "data"), CATALOGO_DB_DIR=str(tmp_path / "viejo")
    )
    assert rutas["db"] == str(tmp_path / "viejo" / "despensa.db")


def _base(ruta: Path, tickets: int = 0) -> Path:
    conn = sqlite3.connect(ruta)
    conn.execute("CREATE TABLE tickets (id INTEGER PRIMARY KEY, total REAL)")
    conn.execute("CREATE TABLE productos (id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT INTO tickets (total) VALUES (?)", [(10.0,)] * tickets)
    conn.commit()
    conn.close()
    return ruta


def _tickets(ruta: Path) -> int:
    conn = sqlite3.connect(ruta)
    try:
        return conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    finally:
        conn.close()


def test_importar_copia_a_un_volumen_vacio(tmp_path):
    origen = _base(tmp_path / "origen.db", tickets=3)
    destino = tmp_path / "db" / "despensa.db"

    r = bd_volumen.importar(origen, destino, dir_respaldos=tmp_path / "backups")

    assert _tickets(destino) == 3
    assert r["respaldo"] is None


def test_importar_reemplaza_la_base_vacia_que_crea_la_app(tmp_path):
    origen = _base(tmp_path / "origen.db", tickets=2)
    destino = _base(tmp_path / "despensa.db", tickets=0)

    bd_volumen.importar(origen, destino, dir_respaldos=tmp_path / "backups")

    assert _tickets(destino) == 2


def test_importar_no_pisa_una_base_con_datos(tmp_path):
    origen = _base(tmp_path / "origen.db", tickets=2)
    destino = _base(tmp_path / "despensa.db", tickets=5)

    with pytest.raises(bd_volumen.ErrorBD, match="--reemplazar"):
        bd_volumen.importar(origen, destino, dir_respaldos=tmp_path / "backups")
    assert _tickets(destino) == 5


def test_importar_con_reemplazar_respalda_antes(tmp_path):
    origen = _base(tmp_path / "origen.db", tickets=2)
    destino = _base(tmp_path / "despensa.db", tickets=5)

    r = bd_volumen.importar(origen, destino, reemplazar=True,
                            dir_respaldos=tmp_path / "backups")

    assert _tickets(destino) == 2
    assert r["respaldo"].name.startswith("despensa_backup_")
    assert _tickets(r["respaldo"]) == 5


def test_importar_rechaza_un_archivo_que_no_es_sqlite(tmp_path):
    origen = tmp_path / "origen.db"
    origen.write_text("esto no es una base")

    with pytest.raises(bd_volumen.ErrorBD):
        bd_volumen.importar(origen, tmp_path / "despensa.db",
                            dir_respaldos=tmp_path / "backups")


def test_respaldar_usa_el_nombre_que_lista_la_app(tmp_path):
    base = _base(tmp_path / "despensa.db", tickets=1)

    respaldo = bd_volumen.respaldar(base, tmp_path / "backups")

    assert respaldo.match("despensa_backup_*.db")
    assert _tickets(respaldo) == 1
