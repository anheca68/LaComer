"""Migra el catálogo del Excel a la base de datos normalizada.

Uso:  ./venv/bin/python scripts/migrar_excel.py [ruta_excel]

Es idempotente: se puede correr las veces que quieras sin duplicar nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from backend.config import CATALOGO_DB_PATH, CATALOGO_EXCEL_PATH
from backend.database import get_db_connection, init_db
from backend.services.catalogo import normalizar


def _indice_nombres(conn, tabla: str, columna_id: str = "id") -> dict:
    return {
        normalizar(f["nombre"]): f[columna_id]
        for f in conn.execute(f"SELECT {columna_id}, nombre FROM {tabla}")
    }


def migrar(excel_path: str) -> dict:
    df = pd.read_excel(excel_path, sheet_name="catalogo").dropna(subset=["ARTICULO"])
    df = df.drop_duplicates(subset=["ARTICULO"], keep="first")

    init_db()
    conn = get_db_connection()
    resumen = {"categorias": 0, "subcategorias": 0, "productos": 0, "actualizados": 0}

    try:
        conn.execute("BEGIN")
        categorias = _indice_nombres(conn, "categorias")
        productos = {
            normalizar(f["descripcion"]): f["id"]
            for f in conn.execute("SELECT id, descripcion FROM productos")
        }

        for fila in df.itertuples():
            categoria = str(fila.CATEGORIA).strip()
            subcategoria = str(fila.SUB_CATEGORIA).strip()
            articulo = str(fila.ARTICULO).strip()

            clave_cat = normalizar(categoria)
            if clave_cat not in categorias:
                cursor = conn.execute("INSERT INTO categorias (nombre) VALUES (?)", (categoria,))
                categorias[clave_cat] = cursor.lastrowid
                resumen["categorias"] += 1

            categoria_id = categorias[clave_cat]

            clave_sub = (categoria_id, normalizar(subcategoria))
            subcategorias = {
                (f["categoria_id"], normalizar(f["nombre"])): f["id"]
                for f in conn.execute("SELECT id, categoria_id, nombre FROM subcategorias")
            }
            if clave_sub not in subcategorias:
                cursor = conn.execute(
                    "INSERT INTO subcategorias (categoria_id, nombre) VALUES (?, ?)",
                    (categoria_id, subcategoria),
                )
                subcategorias[clave_sub] = cursor.lastrowid
                resumen["subcategorias"] += 1

            subcategoria_id = subcategorias[clave_sub]

            clave_prod = normalizar(articulo)
            if clave_prod in productos:
                conn.execute(
                    "UPDATE productos SET categoria_id = ?, subcategoria_id = ? WHERE id = ?",
                    (categoria_id, subcategoria_id, productos[clave_prod]),
                )
                resumen["actualizados"] += 1
            else:
                conn.execute(
                    "INSERT INTO productos (descripcion, categoria_id, subcategoria_id) "
                    "VALUES (?, ?, ?)",
                    (articulo, categoria_id, subcategoria_id),
                )
                productos[clave_prod] = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
                resumen["productos"] += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return resumen


if __name__ == "__main__":
    ruta = sys.argv[1] if len(sys.argv) > 1 else CATALOGO_EXCEL_PATH
    print(f"Origen:  {ruta}")
    print(f"Destino: {CATALOGO_DB_PATH}\n")

    resultado = migrar(ruta)

    print(f"Categorías nuevas:    {resultado['categorias']}")
    print(f"Subcategorías nuevas: {resultado['subcategorias']}")
    print(f"Productos nuevos:     {resultado['productos']}")
    print(f"Productos actualizados: {resultado['actualizados']}")
