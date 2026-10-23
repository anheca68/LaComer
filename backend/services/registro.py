"""Registro de un ticket confirmado en `tickets` y `detalle_tickets`.

Hasta ahora confirmar un ticket solo tocaba el catálogo, escribía el CSV y
archivaba el PDF: la compra nunca llegaba a la base y el panel no la veía.
Aquí se cierra ese hueco, en la misma transacción que el catálogo.

También vive aquí la conciliación: los artículos más el CASH BACK tienen que
dar el total que dice el ticket. Los descuentos de la sección de promociones se
leen uno por uno para comprobarlo, pero se guardan como un solo renglón
`CASH BACK` de tipo `descuento`, igual que en el histórico.
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.auth import usuario_en_curso
from backend.database import get_db_connection
from backend.services.catalogo import (
    SIN_CATEGORIA,
    SIN_SUBCATEGORIA,
    ErrorCatalogo,
    aplicar_en,
    normalizar,
    resolver_categoria,
    resolver_subcategoria,
)

DESCRIPCION_CASH_BACK = "CASH BACK"
TOLERANCIA = 0.01


class ErrorRegistro(ValueError):
    """Motivo legible por el que un ticket no se puede registrar."""


class TicketDuplicado(ErrorRegistro):
    pass


# ═══════════════════════════════════════════════════════════════════════════
# Conciliación
# ═══════════════════════════════════════════════════════════════════════════

def conciliar(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """Compara los artículos más los descuentos leídos contra el total del ticket.

    Estados:
      * ``cuadra``    – la suma da el total, al centavo.
      * ``ajuste``    – falta descuento por explicar: el CASH BACK se completa
                        con la diferencia y se avisa (igual que el histórico).
      * ``faltante``  – el ticket dice más de lo que suman los artículos: falta
                        algún renglón por leer. Bloquea la confirmación.
      * ``sin_total`` – no se pudo leer el total; se usa la suma y se avisa.
    """
    productos = round(sum(float(a.get("total") or 0) for a in ticket["articulos"]), 2)
    desglose = ticket.get("descuentos") or []
    leidos = round(sum(float(d.get("total") or 0) for d in desglose), 2)
    total_ticket = ticket.get("total_ticket")

    if total_ticket is None:
        return {
            "estado": "sin_total",
            "productos": productos,
            "descuentos_leidos": leidos,
            "ajuste": 0.0,
            "cash_back": leidos,
            "calculado": round(productos + leidos, 2),
            "total_ticket": None,
            "total_a_registrar": round(productos + leidos, 2),
            "diferencia": 0.0,
            "desglose": desglose,
            "bloquea": False,
            "mensaje": "No se encontró el TOTAL en el PDF: se registrará la suma de los renglones.",
        }

    total_ticket = round(float(total_ticket), 2)
    diferencia = round(total_ticket - (productos + leidos), 2)

    if abs(diferencia) <= TOLERANCIA:
        estado, ajuste, mensaje = "cuadra", 0.0, "La suma de los renglones cuadra con el total del ticket."
    elif diferencia < 0:
        estado, ajuste = "ajuste", diferencia
        mensaje = (
            f"Los descuentos leídos no explican ${-diferencia:,.2f}: "
            f"se suman al CASH BACK como ajuste."
        )
    else:
        estado, ajuste = "faltante", 0.0
        mensaje = (
            f"El total del ticket es ${diferencia:,.2f} mayor que la suma de los "
            f"renglones. Falta algún artículo por leer: revisa el PDF."
        )

    cash_back = round(leidos + ajuste, 2)
    return {
        "estado": estado,
        "productos": productos,
        "descuentos_leidos": leidos,
        "ajuste": ajuste,
        "cash_back": cash_back,
        "calculado": round(productos + cash_back, 2),
        "total_ticket": total_ticket,
        "total_a_registrar": total_ticket,
        "diferencia": diferencia,
        "desglose": desglose,
        "bloquea": estado == "faltante",
        "mensaje": mensaje,
    }


def renglon_cash_back(conciliacion: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """El renglón único que resume los descuentos, o None si no hubo."""
    if conciliacion["cash_back"] >= 0:
        return None
    return {
        "cantidad": 1.0,
        "sku": "",
        "articulo": DESCRIPCION_CASH_BACK,
        "precio_regular": conciliacion["cash_back"],
        "precio_promocion": "",
        "total": conciliacion["cash_back"],
        "categoria": "",
        "subcategoria": "",
        "tipo": "descuento",
    }


def _nota(conciliacion: Dict[str, Any]) -> Optional[str]:
    """Deja en el ticket el desglose del CASH BACK, que en la base es un renglón."""
    partes = []
    if conciliacion["desglose"]:
        detalle = "; ".join(
            f"{d['articulo']} {d['total']:.2f}" for d in conciliacion["desglose"]
        )
        partes.append(f"CASH BACK = {detalle}.")
    if conciliacion["estado"] == "ajuste":
        partes.append(
            f"Ajuste por diferencia no explicada: {conciliacion['ajuste']:.2f}."
        )
    if conciliacion["estado"] == "sin_total":
        partes.append("Sin TOTAL en el PDF: se registró la suma de los renglones.")
    return " ".join(partes) or None


def _notas_ticket(
    ticket: Dict[str, Any], conciliacion: Dict[str, Any]
) -> Optional[str]:
    """Une la nota capturada por el usuario con la explicación de la conciliación."""
    partes = []
    if ticket.get("notas"):
        partes.append(str(ticket["notas"]).strip())
    nota = _nota(conciliacion)
    if nota:
        partes.append(nota)
    return " ".join(p for p in partes if p) or None


# ═══════════════════════════════════════════════════════════════════════════
# Registro
# ═══════════════════════════════════════════════════════════════════════════

def sha256_de(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def sha256_de_ticket(ticket: Dict[str, Any]) -> str:
    """Huella estable de un ticket capturado a mano.

    No se calcula sobre el PDF porque no existe. Se usan los datos que
    identifican la compra (fecha, folio, total y renglones), sin categorías ni
    campos de revisión, para que corregir una categoría no cambie la identidad
    del ticket y para que volver a capturarlo se detecte como duplicado.
    """
    renglones = []
    for articulo in ticket.get("articulos", []):
        renglones.append(
            {
                "articulo": articulo.get("articulo"),
                "sku": articulo.get("sku"),
                "cantidad": articulo.get("cantidad"),
                "precio_regular": articulo.get("precio_regular"),
                "precio_promocion": articulo.get("precio_promocion"),
                "total": articulo.get("total"),
            }
        )
    payload = {
        "fecha_iso": ticket.get("fecha_iso"),
        "hora_compra": ticket.get("hora_compra"),
        "establecimiento": ticket.get("establecimiento"),
        "folio": ticket.get("folio"),
        "total_ticket": ticket.get("total_ticket"),
        "articulos": renglones,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def ya_registrado(sha256: str) -> Optional[Dict[str, Any]]:
    """El ticket ya guardado con ese mismo contenido, si existe."""
    conn = get_db_connection()
    try:
        fila = conn.execute(
            "SELECT id, archivo, fecha, total FROM tickets WHERE sha256 = ?", (sha256,)
        ).fetchone()
    finally:
        conn.close()
    return dict(fila) if fila else None


def confirmar_y_registrar(
    ticket: Dict[str, Any],
    correcciones: List[Dict[str, Any]],
    sha256: str,
) -> Dict[str, Any]:
    """Aplica el catálogo y guarda el ticket en una sola transacción.

    Si algo falla (un renglón rechazado, un duplicado, un error de SQL) no se
    escribe nada y el ticket sigue en revisión para corregirlo.
    """
    conciliacion = conciliar(ticket)
    if conciliacion["bloquea"]:
        raise ErrorRegistro(conciliacion["mensaje"])
    if not ticket.get("fecha_iso"):
        raise ErrorRegistro("No se pudo leer la fecha del ticket.")

    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        _validar_no_duplicado(conn, ticket, sha256)

        informe = aplicar_en(conn, ticket, correcciones)
        if informe["rechazados"]:
            # Un renglón rechazado se quedaría sin categoría en la base.
            raise ErrorCatalogo(
                "Renglones rechazados, corrígelos antes de confirmar: "
                + "; ".join(informe["rechazados"])
            )

        ticket_id = _insertar_ticket(conn, ticket, sha256, conciliacion)
        renglones = _insertar_detalle(conn, ticket_id, ticket, conciliacion)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    informe.update(
        ticket_db_id=ticket_id,
        renglones=renglones,
        conciliacion=conciliacion,
    )
    return informe


def _validar_no_duplicado(conn: sqlite3.Connection, ticket: Dict[str, Any], sha256: str) -> None:
    fila = conn.execute(
        "SELECT id, archivo FROM tickets WHERE sha256 = ?", (sha256,)
    ).fetchone()
    if fila:
        raise TicketDuplicado(
            f"Este ticket ya está registrado como #{fila['id']} ({fila['archivo']})."
        )

    folio = (ticket.get("folio") or "").strip()
    if folio:
        fila = conn.execute(
            "SELECT id, archivo FROM tickets WHERE folio = ? AND fecha = ? AND estado = 'confirmado'",
            (folio, ticket["fecha_iso"]),
        ).fetchone()
        if fila:
            raise TicketDuplicado(
                f"Ya existe un ticket con el folio {folio} del {ticket['fecha_iso']} "
                f"(#{fila['id']}, {fila['archivo']})."
            )


def _insertar_ticket(
    conn: sqlite3.Connection,
    ticket: Dict[str, Any],
    sha256: str,
    conciliacion: Dict[str, Any],
) -> int:
    forma_pago = ticket.get("forma_pago") or (
        "TARJETA" if ticket.get("tarjeta") else None
    )
    cursor = conn.execute(
        """
        INSERT INTO tickets (archivo, sha256, fecha, hora, establecimiento,
                             rfc_emisor, regimen_fiscal, folio, cliente,
                             forma_pago, tarjeta, total, ahorro, descuento,
                             subtotal, iva, ieps, articulos_declarados,
                             origen, notas, creado_por)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket["archivo"], sha256, ticket["fecha_iso"],
            ticket.get("hora_compra") or None,
            ticket.get("establecimiento") or None,
            ticket.get("rfc_emisor") or None,
            ticket.get("regimen_fiscal") or None,
            ticket.get("folio") or None,
            ticket.get("cliente") or None,
            forma_pago,
            ticket.get("tarjeta") or None,
            conciliacion["total_a_registrar"],
            ticket.get("ahorro") or 0.0,
            conciliacion["cash_back"],
            conciliacion["productos"],
            ticket.get("iva"),
            ticket.get("ieps"),
            ticket.get("articulos_declarados"),
            ticket.get("origen") or "pdf",
            _notas_ticket(ticket, conciliacion),
            usuario_en_curso.get(),
        ),
    )
    return cursor.lastrowid


def _insertar_detalle(
    conn: sqlite3.Connection,
    ticket_id: int,
    ticket: Dict[str, Any],
    conciliacion: Dict[str, Any],
) -> int:
    # Índices del catálogo tal como quedó tras aplicar la revisión, que pudo
    # haber dado de alta productos nuevos en esta misma transacción.
    por_nombre: Dict[str, int] = {}
    por_sku: Dict[str, int] = {}
    for fila in conn.execute("SELECT id, sku, descripcion FROM productos"):
        por_nombre.setdefault(normalizar(fila["descripcion"]), fila["id"])
        if fila["sku"]:
            por_sku.setdefault(normalizar(fila["sku"]), fila["id"])

    renglones = list(ticket["articulos"])
    cash_back = renglon_cash_back(conciliacion)
    if cash_back:
        renglones.append(cash_back)

    for numero, articulo in enumerate(renglones, start=1):
        descripcion = str(articulo.get("articulo") or "").strip()
        clave = normalizar(descripcion)
        es_descuento = articulo.get("tipo") == "descuento"

        if es_descuento:
            producto_id = categoria_id = subcategoria_id = None
        else:
            producto_id = por_nombre.get(clave) or por_sku.get(
                normalizar(articulo.get("sku"))
            )
            categoria_id, subcategoria_id = _ids_clasificacion(conn, articulo)

        cantidad = float(articulo.get("cantidad") or 1.0)
        total = round(float(articulo.get("total") or 0), 2)
        promo = articulo.get("precio_promocion")
        conn.execute(
            """
            INSERT INTO detalle_tickets
                (ticket_id, linea, producto_id, sku, descripcion, desc_norm,
                 cantidad, precio_regular, precio_promo, precio_unit, total,
                 categoria_id, subcategoria_id, tipo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id, numero, producto_id,
                str(articulo.get("sku") or "").strip() or None,
                descripcion, clave, cantidad,
                float(articulo.get("precio_regular") or 0),
                float(promo) if promo not in (None, "") else None,
                round(total / cantidad, 4) if cantidad else total,
                total, categoria_id, subcategoria_id,
                "descuento" if es_descuento else "producto",
            ),
        )
    return len(renglones)


def _ids_clasificacion(conn: sqlite3.Connection, articulo: Dict[str, Any]):
    """Ids de la categoría y subcategoría ya validadas por `aplicar_en`."""
    categoria = (articulo.get("categoria") or "").strip()
    subcategoria = (articulo.get("subcategoria") or "").strip()
    if not categoria or categoria == SIN_CATEGORIA:
        return None, None
    creadas: List[str] = []
    categoria_id = resolver_categoria(conn, categoria, creadas)
    if not subcategoria or subcategoria == SIN_SUBCATEGORIA:
        return categoria_id, None
    return categoria_id, resolver_subcategoria(conn, categoria_id, subcategoria, creadas)
