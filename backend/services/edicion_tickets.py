"""Corrección y anulación de tickets ya registrados (solo admin).

Se corrigen los datos generales del ticket; los importes y renglones no se
tocan porque el total tiene que seguir cuadrando con la suma de renglones. Un
ticket con importes equivocados se anula y se vuelve a capturar.

Cada cambio queda en `log_cambios` con el valor anterior, el nuevo y el
usuario, y el ticket guarda quién lo modificó por última vez y cuándo.
"""

import sqlite3
from datetime import date, datetime
from typing import Any, Dict, Optional

from backend.auth import usuario_en_curso
from backend.database import get_db_connection
from backend.services.log import registrar_cambio

CAMPOS_EDITABLES = ("fecha", "hora", "establecimiento", "folio", "forma_pago", "tarjeta", "notas")


class ErrorEdicion(ValueError):
    """Cambio inválido sobre un ticket registrado."""


def obtener_ticket(ticket_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        fila = conn.execute(
            """
            SELECT t.*, uc.usuario AS creado_por_usuario, um.usuario AS modificado_por_usuario
            FROM tickets t
            LEFT JOIN usuarios uc ON uc.id = t.creado_por
            LEFT JOIN usuarios um ON um.id = t.modificado_por
            WHERE t.id = ?
            """,
            (ticket_id,),
        ).fetchone()
        return dict(fila) if fila else None
    finally:
        conn.close()


def _normalizar(campo: str, valor: Any) -> Optional[str]:
    valor = (valor or "").strip()
    if campo == "fecha":
        try:
            return date.fromisoformat(valor).isoformat()
        except ValueError:
            raise ErrorEdicion("La fecha debe tener el formato AAAA-MM-DD.")
    if campo == "hora" and valor:
        # Los tickets PDF traen segundos; los manuales, no. Se respeta el que venga.
        for formato in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(valor, formato).strftime(formato)
            except ValueError:
                pass
        raise ErrorEdicion("La hora debe tener el formato HH:MM o HH:MM:SS.")
    if campo == "forma_pago":
        valor = valor.upper()
    return valor or None


def _marcar_modificado(conn: sqlite3.Connection, ticket_id: int) -> None:
    conn.execute(
        "UPDATE tickets SET modificado_por = ?, modificado_en = datetime('now') WHERE id = ?",
        (usuario_en_curso.get(), ticket_id),
    )


def _cargar(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    fila = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not fila:
        raise ErrorEdicion(f"No existe el ticket #{ticket_id}.")
    return fila


def actualizar_ticket(ticket_id: int, datos: Dict[str, Any]) -> list:
    """Aplica los campos que cambiaron y devuelve sus nombres."""
    nuevos = {c: _normalizar(c, datos.get(c)) for c in CAMPOS_EDITABLES if c in datos}
    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        actual = _cargar(conn, ticket_id)
        cambiados = [c for c, v in nuevos.items() if v != actual[c]]
        for campo in cambiados:
            # `campo` sale de CAMPOS_EDITABLES, nunca del formulario.
            conn.execute(f"UPDATE tickets SET {campo} = ? WHERE id = ?", (nuevos[campo], ticket_id))
            registrar_cambio(
                conn, "tickets", ticket_id, "UPDATE", campo, actual[campo], nuevos[campo]
            )
        if cambiados:
            _marcar_modificado(conn, ticket_id)
        conn.commit()
        return cambiados
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cambiar_estado(ticket_id: int, estado: str, motivo: str) -> None:
    """Anula o reactiva un ticket. Un ticket anulado sale de panel y reportes."""
    if estado not in ("confirmado", "anulado"):
        raise ErrorEdicion(f"Estado desconocido: {estado}.")
    motivo = (motivo or "").strip()
    if estado == "anulado" and not motivo:
        raise ErrorEdicion("Indica el motivo de la anulación.")

    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        actual = _cargar(conn, ticket_id)
        if actual["estado"] == estado:
            raise ErrorEdicion(f"El ticket #{ticket_id} ya está {estado}.")
        conn.execute("UPDATE tickets SET estado = ? WHERE id = ?", (estado, ticket_id))
        registrar_cambio(conn, "tickets", ticket_id, "UPDATE", "estado", actual["estado"], estado)
        if motivo:
            accion = "Anulado" if estado == "anulado" else "Reactivado"
            nota = f"{accion} el {date.today().isoformat()}: {motivo}"
            notas = f"{actual['notas']}\n{nota}" if actual["notas"] else nota
            conn.execute("UPDATE tickets SET notas = ? WHERE id = ?", (notas, ticket_id))
            registrar_cambio(conn, "tickets", ticket_id, "UPDATE", "notas", actual["notas"], notas)
        _marcar_modificado(conn, ticket_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
