"""Consultas del panel de control.

Todas parten de `v_detalle`, que ya filtra por `tickets.estado = 'confirmado'`.
Los renglones de tipo `descuento` se excluyen del gasto real porque no son
compra: son cash back o descuentos que restan, y se suman aparte. Los totales
devueltos usan `total` (importe de línea), no `precio_unit`, porque las
cantidades del Excel son fraccionadas.

Todas las funciones aceptan `periodo`, y es la única forma de acotar los datos:
`"todo"`, un año `"2026"` o un mes `"2026-09"`. El filtro entra en el SQL y no
como recorte en Python, para que los conteos y las sumas se hagan sobre el
subconjunto correcto.

Las tablas del panel las pinta Jinja y las gráficas el navegador, pero ambas
salen de estas mismas funciones con el mismo `periodo`: así no pueden
contradecirse aunque una se actualice y la otra no.
"""

from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_db_connection

# Un ticket sin hora sigue siendo un gasto válido, así que en los cortes entra
# igual. Lo que se documenta es su proporción, no se los descarta.
_SOLO_GASTO = "tipo = 'producto'"

TODO = "todo"

# Meses en español, indexados como devuelve `strftime('%m')`, que va de 01 a 12
# con cero a la izquierda.
MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _filas(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    # `get_db_connection` ya deja row_factory = sqlite3.Row, así que cada fila
    # se convierte con dict() sin boilerplate.
    conn = get_db_connection()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _pct(parte: float, total: float) -> float:
    return round(parte * 100.0 / total, 1) if total else 0.0


# ── Período ──────────────────────────────────────────────────────────────────

def es_anio(periodo: Optional[str]) -> bool:
    return bool(periodo) and len(periodo) == 4 and periodo.isdigit()


def es_mes(periodo: Optional[str]) -> bool:
    if not periodo or len(periodo) != 7 or periodo[4] != "-":
        return False
    anio, num = periodo[:4], periodo[5:]
    return anio.isdigit() and num.isdigit()


def normalizar(periodo: Optional[str]) -> str:
    """Deja solo `todo`, un año o un mes. Cualquier otra cosa cae en `todo`.

    El valor viene de la URL, así que no se le puede dejar pasar tal cual: sin
    esto, `/panel/datos?periodo=' OR 1=1 --` llegaría al SQL concatenado.
    """
    if es_anio(periodo):
        return periodo
    if es_mes(periodo):
        anio, num = periodo.split("-")
        if 1 <= int(num) <= 12:
            return periodo
    return TODO


def _condicion_fecha(periodo: Optional[str], columna: str = "fecha",
                      prefijo: str = "") -> Tuple[str, tuple]:
    """Condición SQL SOLO de fecha, sin el filtro de tipo de línea.

    Se separa de `_alcance` porque algunas consultas corren contra `tickets` y no
    pueden filtrar por `tipo`, que es una columna de `detalle_tickets`. Ahí se
    necesita únicamente el recorte de fecha.

    `prefijo` es el alias de tabla (con punto incluido, `"v."`). Hace falta
    cuando la consulta une `tickets` con `v_detalle`: las dos tienen columna
    `fecha` y SQLite la marca como ambigua.
    """
    col = f"{prefijo}{columna}"
    p = normalizar(periodo)
    if es_anio(p):
        return (f"substr({col}, 1, 4) = ?", (p,))
    if es_mes(p):
        if columna == "mes":
            return (f"{col} = ?", (p,))
        return (f"strftime('%Y-%m', {col}) = ?", (p,))
    return ("1=1", ())


def _alcance(periodo: Optional[str], columna: str = "fecha",
             prefijo: str = "") -> Tuple[str, tuple]:
    """Condición completa: tipo producto + recorte del período.

    `columna` permite filtrar por `fecha` o por `mes` según la consulta: la
    vista mensual ya trae la columna `mes` y agrupar sobre ella evita repetir
    el `strftime` en cada fila.
    """
    cond, params = _condicion_fecha(periodo, columna, prefijo)
    return (f"({prefijo}tipo = 'producto' AND {cond})", params)


def periodos_disponibles() -> Dict[str, Any]:
    """Qué hay en la base, para ofrecer solo opciones con datos.

    Un selector lleno de meses sin información hace perder tiempo: se listan
    únicamente los años y meses que efectivamente tienen tickets confirmados.
    """
    filas = _filas(
        """
        SELECT DISTINCT strftime('%Y-%m', fecha) AS mes
        FROM   v_detalle
        WHERE  tipo = 'producto'
        ORDER BY mes DESC
        """
    )
    meses = [f["mes"] for f in filas]
    anios: List[str] = []
    for m in meses:
        a = m.split("-")[0]
        if a not in anios:
            anios.append(a)

    def etiqueta(mes: str) -> str:
        anio, num = mes.split("-")
        return f"{MESES_ES[int(num) - 1]} {anio}"

    return {
        "anios": [{"valor": a, "etiqueta": a, "meses": 0} for a in anios],
        "meses": [{"valor": m, "etiqueta": etiqueta(m), "anio": m[:4]} for m in meses],
        "hay_datos": bool(meses),
    }


def periodo_info(periodo: Optional[str]) -> Dict[str, Any]:
    """Describe el período activo para que la plantilla no vuelva a adivinar.

    `granularidad` decide cómo se presenta el desglose: un mes único en la tabla
    "por mes" sería una sola fila, así que en ese caso el desglose baja a
    cortes por día.
    """
    p = normalizar(periodo)
    info = {
        "valor": p,
        "granularidad": "mes",
        "etiqueta": "Todo el historial",
        "mes_incompleto": False,
    }
    if es_mes(p):
        anio, num = p.split("-")
        info.update(
            granularidad="dia",
            etiqueta=f"{MESES_ES[int(num) - 1]} de {anio}",
            mes_incompleto=_mes_en_curso(p),
        )
    elif es_anio(p):
        info.update(granularidad="mes", etiqueta=f"Año {p}")
    return info


def _mes_en_curso(mes: str) -> bool:
    """Cierto si el mes sigue abierto: hoy cae dentro de ese mes."""
    from datetime import date

    anio, num = mes.split("-")
    return date.today().year == int(anio) and date.today().month == int(num)


# ── Cortes ───────────────────────────────────────────────────────────────────

def por_mes(periodo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Desglose mensual: bruto, descuentos y neto, en orden cronológico.

    Cada lado se agrega en su propia CTE antes del join. Si se unieran las
    líneas sin agrupar, el total del mes saldría una fila por ticket: el
    `bruto` es por ticket y sin `SUM` SQLite se queda con una fila arbitraria.
    """
    if es_mes(periodo):
        # El caller pidió un mes suelto: el desglose por día lo cubre mejor.
        return []
    cond, params = _condicion_fecha(periodo, "mes")
    return _filas(
        f"""
        WITH prod AS (
            SELECT mes,
                   SUM(total)                AS bruto,
                   COUNT(DISTINCT ticket_id) AS tickets,
                   COUNT(*)                  AS renglones
            FROM   v_detalle
            WHERE  {_SOLO_GASTO} AND {cond}
            GROUP BY mes
        ), desc AS (
            SELECT mes, SUM(total) AS descuentos
            FROM   v_detalle
            WHERE  tipo = 'descuento' AND {cond}
            GROUP BY mes
        )
        SELECT p.mes,
               p.tickets,
               p.renglones,
               ROUND(p.bruto, 2)                     AS bruto,
               ROUND(COALESCE(d.descuentos, 0), 2)   AS descuentos,
               ROUND(p.bruto + COALESCE(d.descuentos, 0), 2) AS neto,
               ROUND((p.bruto + COALESCE(d.descuentos, 0)) / p.tickets, 2) AS promedio
        FROM   prod p
        LEFT JOIN desc d ON d.mes = p.mes
        ORDER BY p.mes
        """,
        params + params,
    )


def por_dia(periodo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Desglose por día. Solo tiene sentido acotado a un mes.

    El mes se pide porque una tabla de 200 días no sirve de nada: el filtro es
    la granularidad de esta vista.
    """
    if not es_mes(periodo):
        return []
    cond, params = _condicion_fecha(periodo)
    return _filas(
        f"""
        WITH prod AS (
            SELECT fecha AS dia,
                   SUM(total)                AS bruto,
                   COUNT(DISTINCT ticket_id) AS tickets,
                   COUNT(*)                  AS renglones
            FROM   v_detalle
            WHERE  {_SOLO_GASTO} AND {cond}
            GROUP BY fecha
        ), desc AS (
            SELECT fecha AS dia, SUM(total) AS descuentos
            FROM   v_detalle
            WHERE  tipo = 'descuento' AND {cond}
            GROUP BY fecha
        )
        SELECT p.dia,
               p.tickets,
               p.renglones,
               ROUND(p.bruto, 2)                     AS bruto,
               ROUND(COALESCE(d.descuentos, 0), 2)   AS descuentos,
               ROUND(p.bruto + COALESCE(d.descuentos, 0), 2) AS neto,
               ROUND((p.bruto + COALESCE(d.descuentos, 0)) / p.tickets, 2) AS promedio
        FROM   prod p
        LEFT JOIN desc d ON d.dia = p.dia
        ORDER BY p.dia
        """,
        params + params,
    )



def por_categoria(periodo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Gasto por categoría. Es el corte que más rápido muestra en qué se va."""
    where, params = _alcance(periodo)
    filas = _filas(
        f"""
        SELECT COALESCE(categoria, 'Sin categoría') AS categoria,
               ROUND(SUM(total), 2)                 AS importe,
               COUNT(*)                             AS renglones,
               ROUND(SUM(cantidad), 2)              AS unidades
        FROM   v_detalle
        WHERE  {where}
        GROUP BY COALESCE(categoria, 'Sin categoría')
        ORDER BY importe DESC
        """,
        params,
    )
    total = sum(f["importe"] for f in filas)
    for f in filas:
        f["porcentaje"] = _pct(f["importe"], total)
    return filas


def _total_categoria(periodo: Optional[str] = None) -> float:
    return round(sum(f["importe"] for f in por_categoria(periodo)), 2)


def top_subcategorias(limite: int = 10,
                      periodo: Optional[str] = None) -> List[Dict[str, Any]]:
    where, params = _alcance(periodo)
    filas = _filas(
        f"""
        SELECT COALESCE(subcategoria, 'Sin subcategoría') AS subcategoria,
               COALESCE(categoria, 'Sin categoría')       AS categoria,
               ROUND(SUM(total), 2)                       AS importe
        FROM   v_detalle
        WHERE  {where}
        GROUP BY COALESCE(subcategoria, 'Sin subcategoría'),
                 COALESCE(categoria, 'Sin categoría')
        ORDER BY importe DESC
        LIMIT  ?
        """,
        params + (limite,),
    )
    total = _total_categoria(periodo)
    for f in filas:
        f["porcentaje"] = _pct(f["importe"], total)
    return filas


def top_productos(limite: int = 12,
                  periodo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Productos o marcas por importe acumulado.

    Se agrupa por `descripcion` porque las 1149 líneas se reducen a 463
    descripciones distintas: comprarse tres veces el mismo producto debe sumar
    en una sola barra, no aparecer en tres filas.
    """
    where, params = _alcance(periodo)
    return _filas(
        f"""
        SELECT descripcion,
               COALESCE(categoria, 'Sin categoría') AS categoria,
               ROUND(SUM(total), 2)                 AS importe,
               ROUND(SUM(cantidad), 2)              AS unidades,
               COUNT(DISTINCT ticket_id)            AS compras
        FROM   v_detalle
        WHERE  {where}
        GROUP BY descripcion, COALESCE(categoria, 'Sin categoría')
        ORDER BY importe DESC
        LIMIT  ?
        """,
        params + (limite,),
    )


def top_tickets(limite: int = 10,
                periodo: Optional[str] = None) -> List[Dict[str, Any]]:
    # El prefijo `v.` es obligatorio: el join con `tickets` deja `fecha`
    # ambigua y SQLite rechaza la consulta.
    where, params = _alcance(periodo, "fecha", "v.")
    return _filas(
        f"""
        SELECT t.id,
               t.fecha,
               t.hora,
               t.folio,
               COALESCE(t.establecimiento, 'Sin registro') AS establecimiento,
               ROUND(t.total, 2)                            AS total,
               ROUND(SUM(v.total), 2)                       AS productos
        FROM   tickets t
        JOIN   v_detalle v ON v.ticket_id = t.id
        WHERE  {where}
        GROUP BY t.id
        ORDER BY t.total DESC
        LIMIT  ?
        """,
        params + (limite,),
    )


def gasto_por_dia_semana(periodo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Detecta en qué día de la semana se concentra la compra.

    SQLite no trae nombres de día en español, así que se traducen aquí: `%w` da
    0=domingo. Sin esta capa el gráfico tendría que mostrarlos en inglés.
    """
    where, params = _alcance(periodo)
    filas = _filas(
        f"""
        SELECT CAST(strftime('%w', fecha) AS INTEGER) AS dia,
               ROUND(SUM(total), 2)                  AS importe,
               COUNT(DISTINCT ticket_id)             AS tickets
        FROM   v_detalle
        WHERE  {where}
        GROUP BY dia
        ORDER BY dia
        """,
        params,
    )
    por_dia = {f["dia"]: f for f in filas}
    nombres = ["Domingo", "Lunes", "Martes", "Miércoles",
               "Jueves", "Viernes", "Sábado"]
    return [
        {
            "dia": nombres[i],
            "dia_corto": nombres[i][:3],
            "importe": por_dia.get(i, {}).get("importe", 0.0),
            "tickets": por_dia.get(i, {}).get("tickets", 0),
        }
        for i in range(7)
    ]


def indicadores(periodo: Optional[str] = None) -> Dict[str, Any]:
    """Cifras de la cabecera del panel, acotadas al período."""
    alcance, params = _alcance(periodo)
    # La condición de fecha suelta, para las consultas que corren sobre
    # `tickets` y no pueden filtrar por `tipo`.
    solo_fecha, params_fecha = _condicion_fecha(periodo)
    conn = get_db_connection()
    try:
        def uno(sql, extra=()):
            fila = conn.execute(sql, params + extra).fetchone()
            return fila[0] if fila else None

        def uno_fecha(sql):
            fila = conn.execute(sql, params_fecha).fetchone()
            return fila[0] if fila else None

        info = periodo_info(periodo)

        # El desglose que corresponda al período: por mes salvo que se haya
        # pedido un mes suelto, en cuyo caso se usa el desglose diario. Los
        # promedios y las comparaciones salen de la misma serie que las tablas.
        serie = por_dia(periodo) if info["granularidad"] == "dia" else por_mes(periodo)

        total_bruto = round(sum(s["bruto"] for s in serie), 2)
        ahorro = round(sum(s["descuentos"] for s in serie), 2)
        gasto_neto = round(total_bruto + ahorro, 2)

        tickets = uno("SELECT COUNT(DISTINCT ticket_id) FROM v_detalle WHERE " + alcance)

        # Comparación contra el corte inmediato anterior dentro de la serie.
        # Solo tiene sentido con granularidad mensual: en un mes suelto la serie
        # es de días y esto compararía el último día con el anterior, que es
        # otra cosa distinta. Con un mes abierto tampoco se calcula, porque
        # siempre parecería una caída.
        variacion = None
        if (
            len(serie) >= 2
            and info["granularidad"] == "mes"
            and not info["mes_incompleto"]
        ):
            actual, previo = serie[-1], serie[-2]
            base = previo["neto"] or 0
            if base:
                variacion = round((actual["neto"] - base) * 100.0 / abs(base), 1)

        ticket_max = uno_fecha(
            """
            SELECT fecha || COALESCE(' ' || hora, '')
              || '  ·  ' || COALESCE(folio, 'sin folio')
              || '  ·  ' || printf('%.2f', total)
            FROM   tickets
            WHERE  estado = 'confirmado' AND """ + solo_fecha + """
            ORDER BY total DESC LIMIT 1
            """
        )

        # Tendencia: comparar últimos 3 meses vs los 3 anteriores
        tendencia = None
        if info["granularidad"] == "mes" and len(serie) >= 6:
            ultimos_3 = sum(s["neto"] for s in serie[-3:])
            anteriores_3 = sum(s["neto"] for s in serie[-6:-3])
            if anteriores_3 > 0:
                tendencia = round((ultimos_3 - anteriores_3) * 100.0 / anteriores_3, 1)

        # Día de la semana con más gasto
        dia_semana_top = None
        dias = gasto_por_dia_semana(periodo)
        if dias:
            dia_top = max(dias, key=lambda d: d["importe"])
            if dia_top["importe"] > 0:
                dia_semana_top = dia_top["dia"]

        return {
            "gasto_neto": gasto_neto,
            "gasto_bruto": total_bruto,
            "ahorro": ahorro,
            "tickets": tickets or 0,
            "renglones": uno("SELECT COUNT(*) FROM v_detalle WHERE " + alcance) or 0,
            "categorias": uno(
                "SELECT COUNT(DISTINCT categoria) FROM v_detalle WHERE " + alcance
            ) or 0,
            "productos": uno(
                "SELECT COUNT(DISTINCT descripcion) FROM v_detalle WHERE " + alcance
            ) or 0,
            "ticket_promedio": round(gasto_neto / tickets, 2) if tickets else 0.0,
            "ticket_max": ticket_max,
            "sin_hora": uno_fecha(
                "SELECT COUNT(*) FROM tickets WHERE estado = 'confirmado' "
                "AND hora IS NULL AND " + solo_fecha
            ) or 0,
            # La etiqueta del último corte visible: el mes pedido si el
            # período es un mes, o el último mes de la serie si es más amplio.
            "ultimo_periodo": (
                serie[-1]["mes"] if info["granularidad"] == "mes" and serie
                else (normalizar(periodo) if info["granularidad"] == "dia" else None)
            ),
            "variacion_mes": variacion,
            "tendencia_3m": tendencia,
            "dia_semana_top": dia_semana_top,
            "periodo": info,
            "hay_datos": bool(serie),
        }
    finally:
        conn.close()