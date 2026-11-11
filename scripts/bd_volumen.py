#!/usr/bin/env python3
"""Pasa la base SQLite a su volumen y la respalda.

Uso (en Docker, con la app detenida para `importar`):

    docker compose stop app
    docker compose run --rm app python scripts/bd_volumen.py importar /app/data/despensa.db
    docker compose start app

    docker compose exec app python scripts/bd_volumen.py respaldar

`importar` copia una base existente a ``DB_DIR``. Si en el destino ya hay una
base con tickets o productos, solo la reemplaza con ``--reemplazar`` y después
de respaldarla. Una base vacía (la que crea la app al arrancar por primera vez)
se reemplaza sin pedirlo.

`respaldar` deja una copia en ``DATA_DIR/backups`` con el mismo nombre que usan
los respaldos de la app, así que aparece en *Normalizar productos* para
restaurarla.

Las copias usan la API de respaldo de SQLite, no una copia de archivo: el
resultado es consistente aunque la base tenga transacciones a medio escribir.
Solo importa ``backend.config``, que no crea ni migra la base.
"""

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import BACKUPS_DIR, CATALOGO_DB_PATH  # noqa: E402


class ErrorBD(Exception):
    """Error que se muestra tal cual en consola."""


def _copiar(origen: Path, destino: Path) -> None:
    src = sqlite3.connect(f"file:{origen}?mode=ro", uri=True)
    dst = sqlite3.connect(destino)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _verificar(ruta: Path) -> None:
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        resultado = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise ErrorBD(f"{ruta} no es una base SQLite válida: {exc}") from exc
    finally:
        conn.close()
    if resultado != "ok":
        raise ErrorBD(f"{ruta} no pasó la verificación de integridad: {resultado}")


def _tiene_datos(ruta: Path) -> bool:
    """Cierto si la base tiene tickets o productos registrados."""
    if not ruta.exists():
        return False
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        tablas = {f[0] for f in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return any(
            conn.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0] > 0
            for tabla in ("tickets", "productos")
            if tabla in tablas
        )
    finally:
        conn.close()


def resumen(ruta: Path) -> str:
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        partes = []
        for tabla in ("tickets", "productos", "usuarios"):
            try:
                partes.append(f"{conn.execute(f'SELECT COUNT(*) FROM {tabla}').fetchone()[0]} {tabla}")
            except sqlite3.OperationalError:
                pass
        return ", ".join(partes) or "sin tablas"
    finally:
        conn.close()


def respaldar(origen: Path = CATALOGO_DB_PATH, dir_respaldos: Path = BACKUPS_DIR) -> Path:
    if not origen.exists():
        raise ErrorBD(f"No existe la base {origen}.")
    dir_respaldos.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = dir_respaldos / f"despensa_backup_{marca}.db"
    _copiar(origen, destino)
    _verificar(destino)
    return destino


def importar(
    origen: Path,
    destino: Path = CATALOGO_DB_PATH,
    reemplazar: bool = False,
    dir_respaldos: Path = BACKUPS_DIR,
) -> dict:
    origen, destino = Path(origen).resolve(), Path(destino).resolve()
    if not origen.is_file():
        raise ErrorBD(f"No existe la base de origen {origen}.")
    if origen == destino:
        raise ErrorBD("El origen y el destino son el mismo archivo.")
    _verificar(origen)

    respaldo = None
    if _tiene_datos(destino):
        if not reemplazar:
            raise ErrorBD(
                f"{destino} ya tiene datos ({resumen(destino)}). "
                "Usa --reemplazar para sustituirla; antes se respalda."
            )
        respaldo = respaldar(destino, dir_respaldos)

    destino.parent.mkdir(parents=True, exist_ok=True)
    _copiar(origen, destino)
    _verificar(destino)
    return {"destino": destino, "respaldo": respaldo, "resumen": resumen(destino)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="accion", required=True)

    p_imp = sub.add_parser("importar", help="copia una base existente al volumen de la BD")
    p_imp.add_argument("origen", type=Path)
    p_imp.add_argument("--reemplazar", action="store_true",
                       help="sustituye una base con datos (se respalda antes)")

    sub.add_parser("respaldar", help="copia la base actual a DATA_DIR/backups")

    args = parser.parse_args(argv)
    try:
        if args.accion == "importar":
            r = importar(args.origen, reemplazar=args.reemplazar)
            if r["respaldo"]:
                print(f"Respaldo de la base anterior: {r['respaldo']}")
            print(f"Base copiada a {r['destino']} ({r['resumen']}).")
        else:
            print(f"Respaldo creado: {respaldar()}")
    except ErrorBD as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
