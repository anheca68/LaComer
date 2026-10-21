"""Registro de cambios en la base de datos.

Cada INSERT, UPDATE o DELETE en categorías, subcategorías o productos deja una
fila en `log_cambios` con el valor anterior y el nuevo. Esto permite auditar
qué se cambió, cuándo y por qué, y revertir cambios si es necesario.
"""

import sqlite3
from typing import Any, Dict, List, Optional

from backend.database import get_db_connection


def registrar_cambio(
    conn: sqlite3.Connection,
    tabla: str,
    registro_id: int,
    accion: str,
    campo: Optional[str] = None,
    valor_anterior: Optional[str] = None,
    valor_nuevo: Optional[str] = None,
) -> None:
    """Registra un cambio en la tabla log_cambios.

    Args:
        conn: Conexión activa a la base de datos (dentro de una transacción).
        tabla: Nombre de la tabla modificada ('categorias', 'subcategorias', 'productos').
        registro_id: ID del registro modificado.
        accion: Tipo de operación ('INSERT', 'UPDATE', 'DELETE').
        campo: Campo modificado (opcional).
        valor_anterior: Valor antes del cambio (opcional).
        valor_nuevo: Valor después del cambio (opcional).
    """
    conn.execute(
        """
        INSERT INTO log_cambios (tabla, registro_id, accion, campo, valor_anterior, valor_nuevo)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tabla, registro_id, accion, campo, valor_anterior, valor_nuevo),
    )


def obtener_cambios(
    tabla: Optional[str] = None,
    registro_id: Optional[int] = None,
    limite: int = 100,
) -> List[Dict[str, Any]]:
    """Obtiene los cambios registrados, opcionalmente filtrados.

    Args:
        tabla: Filtrar por tabla (opcional).
        registro_id: Filtrar por ID de registro (opcional).
        limite: Máximo número de resultados.

    Returns:
        Lista de diccionarios con los cambios.
    """
    conn = get_db_connection()
    try:
        sql = "SELECT * FROM log_cambios WHERE 1=1"
        params = []

        if tabla:
            sql += " AND tabla = ?"
            params.append(tabla)

        if registro_id is not None:
            sql += " AND registro_id = ?"
            params.append(registro_id)

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limite)

        filas = conn.execute(sql, params).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


def revertir_cambio(conn: sqlite3.Connection, log_id: int) -> bool:
    """Revierte un cambio específico basándose en su registro en log_cambios.

    Args:
        conn: Conexión activa a la base de datos.
        log_id: ID del registro en log_cambios a revertir.

    Returns:
        True si se revirtió exitosamente, False si no se pudo.
    """
    fila = conn.execute(
        "SELECT * FROM log_cambios WHERE id = ?", (log_id,)
    ).fetchone()

    if not fila:
        return False

    tabla = fila["tabla"]
    registro_id = fila["registro_id"]
    accion = fila["accion"]
    campo = fila["campo"]
    valor_anterior = fila["valor_anterior"]

    if accion == "INSERT":
        # Revertir un INSERT = eliminar el registro
        conn.execute(f"DELETE FROM {tabla} WHERE id = ?", (registro_id,))
    elif accion == "UPDATE":
        # Revertir un UPDATE = restaurar el valor anterior
        if campo and valor_anterior is not None:
            conn.execute(
                f"UPDATE {tabla} SET {campo} = ? WHERE id = ?",
                (valor_anterior, registro_id),
            )
    elif accion == "DELETE":
        # Revertir un DELETE requiere conocer todos los valores anteriores
        # Esto es más complejo y necesitaría un registro completo
        return False

    return True


def obtener_historial_registro(
    tabla: str,
    registro_id: int,
) -> List[Dict[str, Any]]:
    """Obtiene el historial completo de cambios de un registro específico.

    Args:
        tabla: Nombre de la tabla.
        registro_id: ID del registro.

    Returns:
        Lista de cambios ordenados cronológicamente.
    """
    conn = get_db_connection()
    try:
        filas = conn.execute(
            """
            SELECT * FROM log_cambios
            WHERE tabla = ? AND registro_id = ?
            ORDER BY id ASC
            """,
            (tabla, registro_id),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()
