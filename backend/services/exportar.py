"""Exportación de los datos del panel a un .xlsx real.

Se arma el libro en memoria con openpyxl y se devuelve como bytes; el
`Content-Disposition` lleva el nombre entre comillas para que Safari no lo
trunque en acentos.
"""

import io
from datetime import datetime
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from backend.database import get_db_connection
from backend.services import panel

# openpyxl no escribe fórmulas, así que el total se calcula en Python. Si se
# dejara una fórmula, el archivo se abriría bien pero `pandas.read_excel`
# devolvería None en esa celda hasta que Excel la evaluara al abrirlo.
_ENCABEZADO = PatternFill("solid", fgColor="2C3E50")
_ENCABEZADO_FUENTE = Font(color="FFFFFF", bold=True)

# Moneda y porcentaje: el 0.00 con formato hace que Excel muestre "1,234.56"
# en vez del float crudo, y los negativos en rojo para que destaquen.
formato_monto = '#,##0.00;[Red]-#,##0.00'
formato_pct = '0.0"%"'


def _hoja(wb: Workbook, titulo: str, encab: List[str], filas: List[Dict[str, Any]],
          anchos: List[int], montos: set = None, pcts: set = None):
    ws = wb.create_sheet(titulo[:31])
    ws.append(encab)
    for c in ws[1]:
        c.fill = _ENCABEZADO
        c.font = _ENCABEZADO_FUENTE
        c.alignment = Alignment(horizontal="center", vertical="center")

    for f in filas:
        ws.append([f.get(k) for k in encab])

    montos = montos or set()
    pcts = pcts or set()
    for idx, nombre in enumerate(encab, start=1):
        letra = get_column_letter(idx)
        if nombre in montos:
            for fila in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                for celda in fila:
                    celda.number_format = formato_monto
        if nombre in pcts:
            for fila in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
                for celda in fila:
                    celda.number_format = formato_pct
        ws.column_dimensions[letra].width = anchos[idx - 1]

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def _detalle_completo(periodo: str = None) -> List[Dict[str, Any]]:
    """Detalle línea por línea, acotado al período que se está viendo.

    No se apoya en `v_detalle` porque esa vista no expone `hora`, que es lo que
    ordena dos compras del mismo día. Se hace el join a mano para además llevar
    `ticket_id` y `linea`, con los que se puede rastrear cualquier importe de
    vuelta a su ticket.
    """
    cond, params = panel._condicion_fecha(periodo)
    conn = get_db_connection()
    try:
        return [
            dict(r)
            for r in conn.execute(
                f"""
                SELECT t.id AS ticket_id,
                       t.fecha,
                       COALESCE(t.hora, '') AS hora,
                       t.folio,
                       COALESCE(t.establecimiento, '') AS establecimiento,
                       COALESCE(c.nombre, '') AS categoria,
                       COALESCE(s.nombre, '') AS subcategoria,
                       d.linea,
                       d.descripcion,
                       COALESCE(d.sku, '') AS sku,
                       d.cantidad,
                       d.precio_unit,
                       d.total,
                       d.tipo
                FROM   tickets t
                JOIN   detalle_tickets d ON d.ticket_id = t.id
                LEFT JOIN categorias    c ON c.id = d.categoria_id
                LEFT JOIN subcategorias s ON s.id = d.subcategoria_id
                WHERE  t.estado = 'confirmado'
                  AND  {cond}
                ORDER BY t.fecha, t.hora, t.id, d.linea
                """,
                params,
            ).fetchall()
        ]
    finally:
        conn.close()


def construir_libro(periodo: str = None) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)

    i = panel.indicadores(periodo)

    # ── Portada: las cifras sueltas que se piden ver de un vistazo ──────────
    ws = wb.create_sheet("Resumen")
    ws["A1"] = "Resumen de gastos"
    ws["A1"].font = Font(size=14, bold=True, color="2C3E50")
    datos = [
        ("Generado", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Periodo filtrado", i["periodo"]["etiqueta"]),
        ("Neto del periodo", i["gasto_neto"]),
        ("", ""),
        ("Gasto bruto", i["gasto_bruto"]),
        ("Descuentos", i["ahorro"]),
        ("Gasto neto", i["gasto_neto"]),
        ("", ""),
        ("Tickets", i["tickets"]),
        ("Renglones", i["renglones"]),
        ("Productos distintos", i["productos"]),
        ("Categorías", i["categorias"]),
        ("Ticket promedio", i["ticket_promedio"]),
        ("Ticket más caro", i["ticket_max"]),
        ("Tickets sin hora", i["sin_hora"]),
    ]
    for r, (k, v) in enumerate(datos, start=3):
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v)

    for r, k in enumerate(datos, start=3):
        if k in {"Gasto bruto", "Descuentos", "Gasto neto", "Ticket promedio",
              "Neto del periodo"}:
            ws.cell(row=r, column=2).number_format = formato_monto

    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 46

    # ── Los cuatro cortes del panel, para que el Excel tenga lo mismo que la web ──
    if panel.es_mes(periodo):
        _hoja(wb, "Por dia", ["dia", "tickets", "renglones", "bruto", "descuentos",
                               "neto", "promedio"],
              panel.por_dia(periodo), [12, 9, 11, 13, 13, 13, 13],
              montos={"bruto", "descuentos", "neto", "promedio"})
    else:
        _hoja(wb, "Por mes", ["mes", "tickets", "renglones", "bruto", "descuentos",
                              "neto", "promedio"],
              panel.por_mes(periodo), [11, 9, 11, 13, 13, 13, 13],
              montos={"bruto", "descuentos", "neto", "promedio"})

    _hoja(wb, "Por categoria", ["categoria", "importe", "renglones", "unidades",
                                 "porcentaje"],
          panel.por_categoria(periodo), [30, 14, 11, 11, 11],
          montos={"importe"}, pcts={"porcentaje"})

    _hoja(wb, "Top subcategorias", ["subcategoria", "categoria", "importe",
                                    "porcentaje"],
          panel.top_subcategorias(50, periodo), [34, 30, 14, 11],
          montos={"importe"}, pcts={"porcentaje"})

    _hoja(wb, "Top productos", ["descripcion", "categoria", "importe", "unidades",
                                "compras"],
          panel.top_productos(200, periodo), [40, 30, 14, 11, 10],
          montos={"importe"})

    _hoja(wb, "Por dia de semana", ["dia", "tickets", "importe"],
          panel.gasto_por_dia_semana(periodo), [14, 10, 14],
          montos={"importe"})

    # ── Detalle completo: la hoja que hace útil filtrar y agrupar ─────────────
    encab = ["ticket_id", "fecha", "hora", "folio", "establecimiento",
             "categoria", "subcategoria", "linea", "descripcion", "sku",
             "cantidad", "precio_unit", "total", "tipo"]
    _hoja(wb, "Detalle", encab, _detalle_completo(periodo),
          [10, 12, 9, 14, 30, 28, 30, 7, 40, 9, 10, 13, 13, 11],
          montos={"precio_unit", "total"})

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()