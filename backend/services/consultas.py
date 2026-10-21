"""Consultas de detalle: por artículo y por ticket.

La consulta por artículo acepta coincidencia parcial (como "Caf*") y muestra
la descripción, categoría, subcategoría, precios durante el año y los descuentos
que ha tenido por mes.

La consulta por ticket busca por ticket_id o folio y muestra los detalles
cargados junto con sus totales.
"""

from typing import Any, Dict, List, Optional

from backend.database import get_db_connection
from backend.services.catalogo import normalizar


# ═══════════════════════════════════════════════════════════════════════════
# Consulta por artículo
# ═══════════════════════════════════════════════════════════════════════════

def buscar_articulos_por_nombre(texto: str, limite: int = 50) -> List[Dict[str, Any]]:
    """Busca artículos por coincidencia parcial de nombre o SKU.

    Acepta comodines como "Caf*" para buscar todo lo que empiece con "Caf".
    La búsqueda es case-insensitive e ignora acentos usando la columna
    descripcion_normalizada.
    """
    if not texto or len(texto.strip()) < 2:
        return []

    conn = get_db_connection()
    try:
        # Normalizar el texto de búsqueda (sin acentos, mayúsculas)
        texto_norm = normalizar(texto.strip())
        # Convertir el patrón de búsqueda: "Caf*" -> "%CAF%"
        patron = texto_norm.replace("*", "%")
        if "%" not in patron:
            # Si no hay comodín, buscar coincidencia parcial
            patron = f"%{patron}%"

        filas = conn.execute(
            """
            SELECT p.id, p.descripcion, p.sku,
                   c.nombre AS categoria,
                   s.nombre AS subcategoria
            FROM   productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            LEFT JOIN subcategorias s ON s.id = p.subcategoria_id
            WHERE  p.descripcion_normalizada LIKE ? OR p.sku LIKE ?
            ORDER BY p.descripcion
            LIMIT ?
            """,
            (patron, patron, limite),
        ).fetchall()

        return [dict(f) for f in filas]
    finally:
        conn.close()


def precios_articulo_serie(
    articulo_id: int,
    anio: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Serie mensual de precios para gráfico de evolución.

    Devuelve min/promedio/max por mes, listo para Chart.js.
    """
    if not anio:
        from datetime import datetime
        anio = str(datetime.now().year)

    conn = get_db_connection()
    try:
        filas = conn.execute(
            """
            SELECT strftime('%m', t.fecha) AS mes,
                   ROUND(MIN(d.precio_unit), 2) AS precio_min,
                   ROUND(AVG(d.precio_unit), 2) AS precio_prom,
                   ROUND(MAX(d.precio_unit), 2) AS precio_max
            FROM   tickets t
            JOIN   detalle_tickets d ON d.ticket_id = t.id
            WHERE  d.producto_id = ?
              AND  strftime('%Y', t.fecha) = ?
              AND  d.tipo = 'producto'
            GROUP BY strftime('%m', t.fecha)
            ORDER BY mes
            """,
            (articulo_id, anio),
        ).fetchall()

        if not filas:
            return None

        return {
            "labels": [f["mes"] for f in filas],
            "min": [f["precio_min"] for f in filas],
            "promedio": [f["precio_prom"] for f in filas],
            "max": [f["precio_max"] for f in filas],
        }
    finally:
        conn.close()


def detalle_articulo_por_anio(
    articulo_id: int,
    anio: Optional[str] = None,
) -> Dict[str, Any]:
    """Detalle de un artículo durante un año: precios, cantidades y descuentos por mes.

    Si no se especifica año, usa el año actual.
    """
    if not anio:
        from datetime import datetime
        anio = str(datetime.now().year)

    conn = get_db_connection()
    try:
        # Información del artículo
        art = conn.execute(
            """
            SELECT p.id, p.descripcion, p.sku,
                   c.nombre AS categoria,
                   s.nombre AS subcategoria
            FROM   productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            LEFT JOIN subcategorias s ON s.id = p.subcategoria_id
            WHERE  p.id = ?
            """,
            (articulo_id,),
        ).fetchone()

        if not art:
            return None

        # Desglose por mes: precios regular y promo, cantidad comprada, total
        meses = conn.execute(
            """
            SELECT strftime('%m', t.fecha) AS mes,
                   COUNT(*)                AS compras,
                   ROUND(SUM(d.cantidad), 2)  AS cantidad_total,
                   ROUND(MIN(d.precio_unit), 2) AS precio_min,
                   ROUND(MAX(d.precio_unit), 2) AS precio_max,
                   ROUND(AVG(d.precio_unit), 2) AS precio_promedio,
                   ROUND(SUM(d.total), 2)    AS total_gastado,
                   ROUND(SUM(
                       CASE WHEN d.precio_promo IS NOT NULL
                            THEN (d.precio_regular - d.precio_promo) * d.cantidad
                            ELSE 0
                       END
                   ), 2) AS descuento_ahorrado
            FROM   tickets t
            JOIN   detalle_tickets d ON d.ticket_id = t.id
            WHERE  d.producto_id = ?
              AND  strftime('%Y', t.fecha) = ?
              AND  d.tipo = 'producto'
            GROUP BY strftime('%m', t.fecha)
            ORDER BY mes
            """,
            (articulo_id, anio),
        ).fetchall()

        # Totales del año
        totales = conn.execute(
            """
            SELECT COUNT(*)                AS total_compras,
                   ROUND(SUM(d.cantidad), 2)  AS cantidad_total,
                   ROUND(SUM(d.total), 2)    AS total_gastado,
                   ROUND(SUM(
                       CASE WHEN d.precio_promo IS NOT NULL
                            THEN (d.precio_regular - d.precio_promo) * d.cantidad
                            ELSE 0
                       END
                   ), 2) AS descuento_total,
                   ROUND(AVG(d.precio_unit), 2) AS precio_promedio_anual
            FROM   tickets t
            JOIN   detalle_tickets d ON d.ticket_id = t.id
            WHERE  d.producto_id = ?
              AND  strftime('%Y', t.fecha) = ?
              AND  d.tipo = 'producto'
            """,
            (articulo_id, anio),
        ).fetchone()

        return {
            "articulo": dict(art),
            "anio": anio,
            "meses": [dict(m) for m in meses],
            "totales": dict(totales) if totales else {},
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# Consulta por ticket
# ═══════════════════════════════════════════════════════════════════════════

def buscar_ticket(identificador: str) -> Optional[Dict[str, Any]]:
    """Busca un ticket por su ID numérico o por folio.

    Devuelve el ticket completo con sus renglones y totales, o None si no existe.
    """
    conn = get_db_connection()
    try:
        # Intentar buscar por ID numérico primero
        fila = None
        try:
            ticket_id = int(identificador)
            fila = conn.execute(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()
        except ValueError:
            pass

        # Si no se encontró por ID, buscar por folio
        if not fila:
            fila = conn.execute(
                "SELECT * FROM tickets WHERE folio = ?", (identificador,)
            ).fetchone()

        if not fila:
            return None

        ticket = dict(fila)

        # Obtener los renglones del ticket
        renglones = conn.execute(
            """
            SELECT d.linea, d.descripcion, d.sku, d.cantidad,
                   d.precio_regular, d.precio_promo, d.precio_unit,
                   d.total, d.tipo,
                   c.nombre AS categoria,
                   s.nombre AS subcategoria
            FROM   detalle_tickets d
            LEFT JOIN categorias c ON c.id = d.categoria_id
            LEFT JOIN subcategorias s ON s.id = d.subcategoria_id
            WHERE  d.ticket_id = ?
            ORDER BY d.linea
            """,
            (ticket["id"],),
        ).fetchall()

        ticket["renglones"] = [dict(r) for r in renglones]

        # Calcular totales por tipo
        totales = {"productos": 0.0, "descuentos": 0.0, "total": 0.0}
        for r in ticket["renglones"]:
            if r["tipo"] == "descuento":
                totales["descuentos"] += r["total"]
            else:
                totales["productos"] += r["total"]
            totales["total"] += r["total"]

        ticket["totales_calculados"] = {
            "productos": round(totales["productos"], 2),
            "descuentos": round(totales["descuentos"], 2),
            "total": round(totales["total"], 2),
        }

        return ticket
    finally:
        conn.close()


def listar_tickets_recientes(limite: int = 20) -> List[Dict[str, Any]]:
    """Lista los tickets más recientes para referencia rápida."""
    conn = get_db_connection()
    try:
        filas = conn.execute(
            """
            SELECT id, fecha, hora, folio, establecimiento, total,
                   articulos_declarados
            FROM   tickets
            WHERE  estado = 'confirmado'
            ORDER BY fecha DESC, hora DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()

        return [dict(f) for f in filas]
    finally:
        conn.close()
