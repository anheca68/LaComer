"""Servicio de normalización de productos duplicados.

Detecta productos con la misma descripción normalizada y permite fusionarlos
de forma segura, creando una copia de seguridad antes de proceder.
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import BACKUPS_DIR, CATALOGO_DB_PATH
from backend.database import get_db_connection
from backend.services.catalogo import normalizar


def _normalizar_agresivo(descripcion: str) -> str:
    """Normalización más agresiva para detectar duplicados.

    Elimina acentos, convierte a mayúsculas y elimina TODOS los espacios
    para detectar productos que son iguales pero con espacios diferentes.
    """
    from backend.services.catalogo import normalizar
    return normalizar(descripcion).replace(" ", "")


def detectar_duplicados() -> List[Dict[str, Any]]:
    """Detecta grupos de productos con la misma descripción normalizada.

    Usa una normalización agresiva que elimina espacios internos para detectar
    productos como "CAFE GILA 340 GRS" y "CAFE GILA 340GRS" como duplicados.

    Devuelve una lista de grupos, cada uno con:
    - descripcion_normalizada: la clave de agrupación
    - productos: lista de productos en ese grupo
    - total_renglones: cuántos renglones usan estos productos
    """
    conn = get_db_connection()
    try:
        # Obtener todos los productos y agrupar por normalización agresiva
        productos = conn.execute(
            """
            SELECT id, descripcion, sku, categoria_id, subcategoria_id,
                   descripcion_normalizada
            FROM   productos
            WHERE  descripcion IS NOT NULL
            """
        ).fetchall()

        # Agrupar por normalización agresiva
        from collections import defaultdict
        grupos_dict = defaultdict(list)
        for p in productos:
            norm_agresivo = _normalizar_agresivo(p["descripcion"])
            grupos_dict[norm_agresivo].append(p)

        # Filtrar solo grupos con más de un producto
        grupos_filtrados = [
            (norm, prods) for norm, prods in grupos_dict.items()
            if len(prods) > 1
        ]

        # Ordenar por cantidad de productos (más duplicados primero)
        grupos_filtrados.sort(key=lambda x: len(x[1]), reverse=True)

        resultado = []
        for norm_agresivo, productos in grupos_filtrados:
            # Obtener información adicional de cada producto
            productos_info = []
            for p in productos:
                # Obtener categoría y subcategoría
                cat = conn.execute(
                    "SELECT nombre FROM categorias WHERE id = ?",
                    (p["categoria_id"],)
                ).fetchone()
                sub = conn.execute(
                    "SELECT nombre FROM subcategorias WHERE id = ?",
                    (p["subcategoria_id"],)
                ).fetchone()

                productos_info.append({
                    "id": p["id"],
                    "descripcion": p["descripcion"],
                    "sku": p["sku"],
                    "categoria_id": p["categoria_id"],
                    "subcategoria_id": p["subcategoria_id"],
                    "categoria": cat["nombre"] if cat else None,
                    "subcategoria": sub["nombre"] if sub else None,
                })

            # Contar cuántos renglones usan estos productos
            ids = [p["id"] for p in productos]
            placeholders = ",".join("?" * len(ids))
            renglones = conn.execute(
                f"""
                SELECT COUNT(*) as total
                FROM   detalle_tickets
                WHERE  producto_id IN ({placeholders})
                """,
                ids,
            ).fetchone()

            # Elegir el nombre canónico (el más frecuente en renglones)
            canonical_id = _elegir_canonical(conn, ids)

            resultado.append({
                "descripcion_normalizada": norm_agresivo,
                "productos": productos_info,
                "total_renglones": renglones["total"] if renglones else 0,
                "canonical_id": canonical_id,
            })

        return resultado
    finally:
        conn.close()


def _elegir_canonical(conn: sqlite3.Connection, ids: List[int]) -> int:
    """Elige el producto canónico: el que más renglones tiene."""
    placeholders = ",".join("?" * len(ids))
    fila = conn.execute(
        f"""
        SELECT producto_id, COUNT(*) as total
        FROM   detalle_tickets
        WHERE  producto_id IN ({placeholders})
        GROUP BY producto_id
        ORDER BY total DESC
        LIMIT 1
        """,
        ids,
    ).fetchone()
    return fila["producto_id"] if fila else ids[0]


def crear_copia_seguridad() -> Path:
    """Crea una copia de seguridad de la base de datos.

    Devuelve la ruta de la copia creada.
    """
    backup_dir = BACKUPS_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"despensa_backup_{timestamp}.db"

    # Copiar el archivo de la base de datos
    shutil.copy2(CATALOGO_DB_PATH, backup_path)

    # Limpiar copias antiguas (conservar solo las últimas 10)
    limpiar_copias_antiguas(backup_dir, conservar=10)

    return backup_path


def limpiar_copias_antiguas(backup_dir: Path, conservar: int = 10) -> None:
    """Elimina copias de seguridad antiguas, conservando solo las más recientes."""
    copias = sorted(backup_dir.glob("despensa_backup_*.db"), reverse=True)
    for copia in copias[conservar:]:
        copia.unlink(missing_ok=True)


def fusionar_productos(grupo: Dict[str, Any], canonical_id: int) -> Dict[str, Any]:
    """Fusiona los duplicados en el producto canónico.

    Actualiza las referencias en detalle_tickets y elimina los duplicados.
    Debe ejecutarse dentro de una transacción.
    """
    conn = get_db_connection()
    try:
        conn.execute("BEGIN")

        ids_a_eliminar = [p["id"] for p in grupo["productos"] if p["id"] != canonical_id]

        if not ids_a_eliminar:
            conn.rollback()
            return {"fusionados": 0, "eliminados": 0, "mensaje": "No hay duplicados para fusionar"}

        # Actualizar referencias en detalle_tickets
        placeholders = ",".join("?" * len(ids_a_eliminar))
        conn.execute(
            f"""
            UPDATE detalle_tickets
            SET    producto_id = ?
            WHERE  producto_id IN ({placeholders})
            """,
            [canonical_id] + ids_a_eliminar,
        )

        # Eliminar productos duplicados
        conn.execute(
            f"""
            DELETE FROM productos
            WHERE  id IN ({placeholders})
            """,
            ids_a_eliminar,
        )

        conn.commit()

        return {
            "fusionados": len(ids_a_eliminar),
            "eliminados": len(ids_a_eliminar),
            "mensaje": f"Se fusionaron {len(ids_a_eliminar)} producto(s) en el producto #{canonical_id}"
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def obtener_copias_seguridad() -> List[Dict[str, Any]]:
    """Lista las copias de seguridad disponibles."""
    backup_dir = BACKUPS_DIR
    if not backup_dir.exists():
        return []

    copias = []
    for copia in sorted(backup_dir.glob("despensa_backup_*.db"), reverse=True):
        stat = copia.stat()
        copias.append({
            "nombre": copia.name,
            "ruta": str(copia),
            "tamano": stat.st_size,
            "creada": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return copias


def restaurar_copia_seguridad(ruta: str) -> bool:
    """Restaura la base de datos desde una copia de seguridad.

    Crea una copia de la BD actual antes de restaurar.
    """
    backup_path = Path(ruta).resolve()
    # Solo se aceptan copias de la carpeta de respaldos: la ruta llega del
    # formulario y cualquier otro archivo se copiaría encima de la base.
    if (
        backup_path.parent != BACKUPS_DIR.resolve()
        or not backup_path.match("despensa_backup_*.db")
        or not backup_path.is_file()
    ):
        return False

    # Crear copia de seguridad de la BD actual antes de restaurar
    crear_copia_seguridad()

    # Restaurar
    shutil.copy2(backup_path, CATALOGO_DB_PATH)
    return True
