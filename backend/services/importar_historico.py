"""Carga inicial del histórico de gastos.

El histórico vive en dos fuentes que no se parecen:

  * El Excel `DESPENSA.xlsx`, hoja DATA: 1181 renglones con fecha, cantidad,
    precio y categoría, pero **sin** ticket, sin tienda y con la hora sucia.
  * Los PDFs ya archivados en `procesados/`, que sí traen ficha completa pero
    nunca se guardaron en la base.

Este módulo arma un *plan*: una lista de tickets candidatos, con lo que sabe
y lo que no saber de cada uno, para que la persona decida antes de escribir.
"""

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.config import CATALOGO_EXCEL_PATH, PROCESADOS_DIR
from backend.services.catalogo import (
    normalizar,
    resolver_categoria,
    resolver_subcategoria,
)
from backend.services.pdf_parser import parsear_ticket_pdf

HOJA_DATOS = "DATA"
COLUMNAS_REQUERIDAS = [
    "CATIDAD", "SKU", "ARTICULO", "PRECIO REG", "PRECIO PROM", "TOTAL",
    "CATEGORIA", "SUB_CATEGORIA", "FECHA_TICKET", "HORA_COMPRA",
]
# Tolerancia al comparar el total del PDF contra la suma de sus renglones.
TOLERANCIA = 0.01


class ErrorImportacion(Exception):
    """Error pensable para mostrar en la pantalla, no una traza."""


# ═══════════════════════════════════════════════════════════════════════════
# Fuente 1: el Excel
# ═══════════════════════════════════════════════════════════════════════════

def leer_excel(ruta: Optional[str] = None) -> pd.DataFrame:
    """Lee la hoja de movimientos y normaliza los tipos de las columnas."""
    ruta = Path(ruta or CATALOGO_EXCEL_PATH)
    if not ruta.exists():
        raise ErrorImportacion(f"No se encontró el archivo {ruta.name}.")

    df = pd.read_excel(ruta, sheet_name=HOJA_DATOS)
    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in df.columns]
    if faltantes:
        raise ErrorImportacion(f"Le faltan columnas en el Excel: {', '.join(faltantes)}.")

    df = df.dropna(subset=["ARTICULO", "FECHA_TICKET"]).copy()
    df["_fecha"] = pd.to_datetime(df["FECHA_TICKET"]).dt.date
    df["_hora"] = df["HORA_COMPRA"].map(_normalizar_hora)
    return df


def _normalizar_hora(valor: Any) -> str:
    """Deja 'HH:MM:SS', o '' cuando la hora no es confiable.

    Devolver cadena vacía en vez de None es a propósito: pandas convierte los
    None de una columna de texto en la cadena 'nan', que es una hora válida
    para cualquier `if` posterior y arruinaría el agrupado.

    El Excel mezcla tres basura distintas: celdas vacías, medianoche (que en la
    captura significa "no la anoté") y un `2000-09-12` de una lectura corrida.
    """
    if valor is None or pd.isna(valor):
        return ""
    texto = str(valor).strip()
    if "2000-" in texto:                       # timestamp corrupto
        return ""
    if texto.startswith("0 days "):            # timedelta de pandas
        texto = texto[8:]
    partes = texto.split(":")
    if len(partes) < 2 or not (partes[0] + partes[1]).isdigit():
        return ""
    if int(partes[0]) == 0 and int(partes[1]) == 0:
        return ""                              # medianoche = hora no capturada
    segundos = partes[2] if len(partes) > 2 and partes[2][:2].isdigit() else "00"
    return f"{int(partes[0]):02d}:{int(partes[1]):02d}:{int(segundos[:2]):02d}"


def plan_desde_excel(df: pd.DataFrame) -> Dict[str, Any]:
    """Agrupa los renglones del Excel en tickets candidatos.

    Regla: (fecha, hora) cuando hay hora; la fecha sola cuando no la hay. Pero
    si una fecha tiene unas filas con hora y otras sin ella, esas se separan
    como *huerfanas*: no se pueden ubicar solas y necesitan una decisión.
    """
    fechas_con_hora = set(df.loc[df["_hora"] != "", "_fecha"])
    df = df.copy()
    df["_huerfano"] = (df["_hora"] == "") & df["_fecha"].isin(fechas_con_hora)
    df["_clave"] = [
        f"xlsx|{fecha}|{hora}{'|huerfano' if huerfano else ''}"
        for fecha, hora, huerfano in zip(df["_fecha"], df["_hora"], df["_huerfano"])
    ]

    grupos = [
        _grupo_de_excel(clave, bloque)
        for clave, bloque in df.groupby("_clave", sort=True)
    ]
    return {"grupos": grupos, "resumen": resumir(grupos)}


COLUMNAS_EXCEL = [
    "SKU", "ARTICULO", "CATIDAD", "PRECIO REG", "PRECIO PROM",
    "TOTAL", "CATEGORIA", "SUB_CATEGORIA",
]


def _grupo_de_excel(clave: str, bloque: pd.DataFrame) -> Dict[str, Any]:
    _, fecha, resto = clave.split("|", 2)
    hora, _, sufijo = resto.partition("|")
    huerfano = sufijo == "huerfano"

    # itertuples con name=None entrega las columnas en el orden en que se
    # pidieron, que es el de COLUMNAS_EXCEL: nada depende de nombres inválidos
    # como "PRECIO REG" ni de su posición en la hoja.
    registros = bloque[COLUMNAS_EXCEL].itertuples(index=False, name=None)
    lineas = [
        {
            "sku": str(int(sku)) if pd.notna(sku) else "",
            "descripcion": str(articulo).strip(),
            "cantidad": float(cantidad),
            "precio_regular": float(precio_regular),
            "precio_promo": float(precio_promo) if pd.notna(precio_promo) else None,
            "total": float(total),
            "categoria": str(categoria).strip(),
            "subcategoria": str(subcategoria).strip(),
        }
        for sku, articulo, cantidad, precio_regular, precio_promo, total, \
            categoria, subcategoria in registros
    ]
    return _armar_grupo(
        clave=clave,
        origen="historico",
        archivo=f"historico/{clave.replace('|', '_')}.xlsx",
        fecha=str(fecha),
        hora=hora or None,
        lineas=lineas,
        huerfano=huerfano,
        extra={"establecimiento": "", "forma_pago": ""},
    )


# ═══════════════════════════════════════════════════════════════════════════
# Fuente 2: los PDFs ya archivados
# ═══════════════════════════════════════════════════════════════════════════

def plan_desde_pdfs(directorio: Path = PROCESADOS_DIR) -> Dict[str, Any]:
    """Un PDF = un ticket, así que aquí no hay nada que adivinar."""
    grupos = []
    for pdf in sorted(Path(directorio).glob("*.pdf")):
        try:
            ticket = parsear_ticket_pdf(str(pdf))
        except Exception as exc:                       # un PDF corrupto no
            raise ErrorImportacion(                  # debe tumbar la carga
                f"No se pudo leer {pdf.name}: {exc}"
            ) from exc
        if not ticket["articulos"]:
            raise ErrorImportacion(f"{pdf.name} no tiene renglones legibles.")
        grupos.append(_grupo_de_pdf(pdf, ticket))
    return {"grupos": grupos, "resumen": resumir(grupos)}


def _grupo_de_pdf(pdf: Path, ticket: Dict[str, Any]) -> Dict[str, Any]:
    lineas = [
        {
            "sku": a["sku"],
            "descripcion": a["articulo"],
            "cantidad": a["cantidad"],
            "precio_regular": a["precio_regular"],
            "precio_promo": (
                float(a["precio_promocion"]) if a["precio_promocion"] != "" else None
            ),
            "total": a["total"],
            # La clasificación del catálogo la resuelve el importador, igual que
            # para el histórico: aquí solo se copia lo que dice el texto.
            "categoria": "",
            "subcategoria": "",
        }
        for a in ticket["articulos"]
    ]
    grupo = _armar_grupo(
        clave=f"pdf|{pdf.stem}",
        origen="pdf",
        archivo=pdf.name,
        fecha=ticket["fecha_iso"],
        hora=ticket["hora_compra"] or None,
        lineas=lineas,
        huerfano=False,
        extra={
            "establecimiento": ticket["establecimiento"],
            "forma_pago": "TARJETA" if ticket["tarjeta"] else "",
        },
        sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
    )
    # El total que trae el ticket manda sobre la suma de los renglones: es lo
    # que se pagó de verdad. La diferencia es el descuento o el cashback, y se
    # guarda como renglón para que la suma de los renglones vuelva a dar el
    # total pagado y el descuento quede a la vista.
    if ticket["total_ticket"] is not None:
        _centavos(grupo)
        suma = round(sum(linea["total"] for linea in grupo["lineas"]), 2)
        diferencia = round(ticket["total_ticket"] - suma, 2)
        grupo["total"] = ticket["total_ticket"]
        grupo["descuento"] = diferencia
        if diferencia < 0:
            grupo["lineas"].append({
                "sku": "",
                "descripcion": "CASH BACK",
                "cantidad": 1.0,
                "precio_regular": diferencia,
                "precio_promo": None,
                "total": diferencia,
                "categoria": "",
                "subcategoria": "",
                "tipo": "descuento",
            })
        elif diferencia > 0:
            # El ticket dice más de lo que suman los artículos. No es un
            # descuento, así que no se inventa ninguna línea: se avisa para que
            # se agregue a mano el renglón que falte parsear.
            grupo["anomalias"].append(
                f"El total del ticket es ${diferencia:,.2f} mayor que la suma de "
                f"los renglones. Revisa si falta alguno."
            )
            grupo["anomalia"] = True

    grupo["cabecera"] = {
        "rfc_emisor": ticket["rfc_emisor"],
        "regimen_fiscal": ticket["regimen_fiscal"],
        "folio": ticket["folio"],
        "cliente": ticket["cliente"],
        "tarjeta": ticket["tarjeta"],
        "iva": ticket["iva"],
        "ieps": ticket["ieps"],
        "articulos_declarados": ticket["articulos_declarados"],
    }
    return grupo


# ═══════════════════════════════════════════════════════════════════════════
# Construcción y diagnóstico de un grupo
# ═══════════════════════════════════════════════════════════════════════════

def _armar_grupo(
    clave: str,
    origen: str,
    archivo: str,
    fecha: str,
    hora: Optional[str],
    lineas: List[Dict[str, Any]],
    huerfano: bool,
    extra: Dict[str, Any],
    sha256: Optional[str] = None,
) -> Dict[str, Any]:
    # Los importes se van a centavos antes de sumar nada: el Excel calcula sus
    # totales con cuatro decimales y eso descuadraría centavo con centavo.
    for linea in lineas:
        linea["total"] = round(float(linea["total"]), 2)
        if linea.get("precio_regular") is not None:
            linea["precio_regular"] = round(float(linea["precio_regular"]), 2)

    total = round(sum(l["total"] for l in lineas), 2)
    ahorro = round(
        sum(
            (l["precio_regular"] - l["precio_promo"]) * l["cantidad"]
            for l in lineas
            if l["precio_promo"] is not None
        ),
        2,
    )
    repetidas = _detectar_repetidas(lineas)
    anomalias = []
    if repetidas["sospechoso"]:
        anomalias.append(repetidas["motivo"])
    if huerfano:
        anomalias.append(
            "Estos renglones no tienen hora, pero la fecha sí tiene otras "
            "compras. Ubicarlos a mano."
        )
    if not fecha:
        anomalias.append("Sin fecha legible.")

    return {
        "clave": clave,
        "origen": origen,
        "archivo": archivo,
        "ticket_legacy": clave.split("|", 1)[1],
        "fecha": fecha,
        "hora": hora,
        "huerfano": huerfano,
        "lineas": lineas,
        "lineas_originales": len(lineas),
        "total": total,
        "ahorro": ahorro,
        "descuento": 0.0,
        "sha256": sha256,
        "cabecera": {},
        **extra,
        "omitidas": [],
        "diagnostico": repetidas,
        "anomalia": bool(anomalias),
        "anomalias": anomalias,
        # Lo que un ticket repetido necesita arreglar se queda pendiente, no
        # excluido: se importa una vez, que es lo correcto.
        "pendiente": "condensar" if repetidas["sospechoso"] else None,
        "excluir": False,
        "motivo_exclusion": "",
    }


def _detectar_repetidas(lineas: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Detecta tickets cargados más de una vez en el Excel.

    La firma de un renglón es todo su contenido. Si *todas* las firmas del
    grupo salen el mismo número de veces (y es más de una), lo más probable es
    que el ticket completo esté repetido, no que falte una mano de carga.
    """
    firmas = Counter(
        (l["sku"], l["descripcion"], l["cantidad"], l["precio_regular"], l["total"])
        for l in lineas
    )
    repetidas = {f: n for f, n in firmas.items() if n > 1}
    if not repetidas:
        return {"sospechoso": False, "motivo": "", "factor": 1,
                "renglones": 0, "cobertura": 0.0}

    factores = set(repetidas.values())
    involucrados = sum(repetidas.values())
    cobertura = involucrados / len(lineas)
    completo = cobertura == 1.0 and len(factores) == 1

    if completo:
        factor = factores.pop()
        motivo = f"El ticket completo está repetido {factor}× en el Excel."
    elif cobertura >= 0.3:
        factor = 1
        motivo = f"{involucrados} de {len(lineas)} renglones con contenido repetido."
    else:
        return {"sospechoso": False, "motivo": "", "factor": 1,
                "renglones": involucrados, "cobertura": round(cobertura, 3)}

    return {
        "sospechoso": True,
        "motivo": motivo,
        "factor": factor,
        "renglones": involucrados,
        "cobertura": round(cobertura, 3),
    }


def condensar(grupo: Dict[str, Any]) -> Dict[str, Any]:
    """Deja una sola copia de cada renglón repetido y recalcula el total.

    Es la respuesta al caso "el ticket está cargado dos veces": en lugar de
    descartarlo, se importa bien. El sha256 se recalcula después, al escribir,
    porque depende del total final.
    """
    vistas: set = set()
    unicas = []
    for linea in grupo["lineas"]:
        firma = (
            linea["sku"], linea["descripcion"], linea["cantidad"],
            linea["precio_regular"], linea["total"],
        )
        if firma in vistas:
            continue
        vistas.add(firma)
        unicas.append(linea)

    quitadas = len(grupo["lineas"]) - len(unicas)
    grupo["lineas"] = unicas
    grupo["total"] = round(sum(l["total"] for l in unicas), 2)
    grupo["ahorro"] = round(
        sum(
            (l["precio_regular"] - l["precio_promo"]) * l["cantidad"]
            for l in unicas
            if l["precio_promo"] is not None
        ),
        2,
    )
    grupo["diagnostico"] = _detectar_repetidas(unicas)
    grupo["anomalia"] = bool(grupo["huerfano"])
    grupo["anomalias"] = (
        ["Estos renglones no tienen hora, pero la fecha sí tiene otras compras."]
        if grupo["huerfano"] else []
    )
    grupo["pendiente"] = None
    grupo["nota"] = f"Se quitaron {quitadas} renglones duplicados."
    return grupo


def detectar_solapamientos(grupos: List[Dict[str, Any]]) -> List[str]:
    """El Excel y los PDF describen a veces la misma compra, y si se aceptan
    los dos, esa compra se cuenta dos veces.

    Cuando dos grupos coinciden en fecha y hora son el mismo ticket, y gana el
    PDF: trae RFC, folio, IVA y el total del emisor, que el Excel no tiene. El
    perdedor queda excluido pero no borrado, y la pantalla deja volver a
    activarlo por si la detección se equivoca.
    """
    por_momento: Dict[Any, List[Dict[str, Any]]] = {}
    for grupo in grupos:
        if grupo["fecha"] and grupo["hora"]:
            por_momento.setdefault((grupo["fecha"], grupo["hora"]), []).append(grupo)

    # Segunda pasada: los que no tienen hora se buscan por fecha e importe, con
    # medio peso de tolerancia por si el Excel redondeó.
    for grupo in grupos:
        if grupo["fecha"] and not grupo["hora"]:
            clave = (grupo["fecha"], round(grupo["total"], 2))
            similares = [
                otro for otro in grupos
                if otro["fecha"] == clave[0] and not otro["hora"]
                and abs(otro["total"] - clave[1]) < 0.5
            ]
            if len(similares) > 1:
                por_momento.setdefault(clave, similares)

    resueltos = []
    for coincidentes in por_momento.values():
        if len(coincidentes) < 2:
            continue
        ganador = _mejor_de(coincidentes)
        for grupo in coincidentes:
            if grupo is ganador:
                continue
            grupo["excluir"] = True
            grupo["motivo_exclusion"] = (
                f"Misma compra que «{ganador['archivo']}» "
                f"({ganador['fecha']} {ganador['hora'] or ''}). Se conserva el PDF."
            )
            resueltos.append(grupo["clave"])
    return resueltos


def _mejor_de(grupos: List[Dict[str, Any]]) -> Dict[str, Any]:
    return next((g for g in grupos if g["origen"] == "pdf"), grupos[0])


def resumir(grupos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cifras de cabecera para la pantalla de revisión."""
    return {
        "grupos": len(grupos),
        "renglones": sum(len(g["lineas"]) for g in grupos),
        "importe": round(sum(g["total"] for g in grupos if not g["excluir"]), 2),
        "anomalias": sum(1 for g in grupos if g["anomalia"]),
        "pendientes": sum(1 for g in grupos if g["pendiente"]),
        "excluidos": sum(1 for g in grupos if g["excluir"]),
        "huerfanos": sum(1 for g in grupos if g["huerfano"]),
        "sin_fecha": sum(1 for g in grupos if not g["fecha"]),
        "editados": sum(1 for g in grupos if g.get("omitidas")),
    }


def sugerir_comunes(grupos: List[Dict[str, Any]]) -> Dict[str, str]:
    """El valor que comparten los PDF, que es la única evidencia dura de de dónde
    salió cada compra: traen RFC, razón social y tarjeta.

    Solo propone algo si TODOS los PDF coinciden. Si difieren entre sí, el
    histórico del Excel puede abarcar varias tiendas y no hay con qué decidir,
    así que no se supone nada y lo captura la persona.
    """
    propuesta: Dict[str, str] = {}
    pdfs = [g for g in grupos if g["origen"] == "pdf"]

    for campo in ("establecimiento", "forma_pago"):
        valores = {(g.get(campo) or "").strip() for g in pdfs}
        valores.discard("")
        if len(valores) == 1:
            propuesta[campo] = valores.pop()
    return propuesta


def completar_vacios(
    grupos: List[Dict[str, Any]], valores: Dict[str, str]
) -> Dict[str, int]:
    """Rellena lo que las fuentes no traen con lo que sí traen otras.

    Lo rellenado queda marcado en `grupo["sugerido"]` porque no venía en el dato
    original: se dedujo de los PDF. La persona tiene que poder verlo y cambiarlo.
    Solo toca campos vacíos, nunca pisa lo que ya está puesto.
    """
    llenados = {campo: 0 for campo, valor in valores.items() if valor}
    for grupo in grupos:
        for campo, valor in valores.items():
            if not valor or (grupo.get(campo) or "").strip():
                continue
            grupo[campo] = valor
            sugeridos = grupo.setdefault("sugerido", [])
            if campo not in sugeridos:
                sugeridos.append(campo)
            llenados[campo] += 1
    return {campo: n for campo, n in llenados.items() if n}


def _centavos(grupo: Dict[str, Any]) -> None:
    """Deja todos los importes del grupo en centavos.

    El Excel trae importes de cuatro decimales porque son `cantidad × precio` y
    no un total real de caja: 5,506.3265. Si el renglón guarda esa precisión y el
    total del ticket se redondea a dos, las dos cifras dejan de cuadrar por un
    par de centavos. Un importe no tiene centavos de más, así que se redondea
    una sola vez, aquí, y todo lo demás se deriva de ahí.
    """
    for linea in grupo["lineas"]:
        linea["total"] = round(float(linea["total"]), 2)
        if linea.get("precio_regular") is not None:
            linea["precio_regular"] = round(float(linea["precio_regular"]), 2)


def _recalcular_total(grupo: Dict[str, Any]) -> None:
    """El total del ticket es la suma de sus renglones, descuentos incluidos.

    Así `gastos - descuentos = monto pagado` y no hay dos cifras que puedan
    dejar de cuadrar entre sí.
    """
    _centavos(grupo)
    grupo["total"] = round(sum(linea["total"] for linea in grupo["lineas"]), 2)
    grupo["descuento"] = round(
        sum(linea["total"] for linea in grupo["lineas"]
            if linea.get("tipo") == "descuento"),
        2,
    )


def _buscar(plan: Dict[str, Any], clave: str) -> Dict[str, Any]:
    for grupo in plan["grupos"]:
        if grupo["clave"] == clave:
            return grupo
    raise ErrorImportacion(f"No se encontró el ticket {clave!r}.")


def eliminar_linea(plan: Dict[str, Any], clave: str, indice: int) -> Dict[str, Any]:
    """Quita un renglón que no es parte de la compra.

    No se borra de la nada: se anota en `omitidas` para que quede constancia en
    el ticket de qué se sacó y por qué.
    """
    grupo = _buscar(plan, clave)
    if not 0 <= indice < len(grupo["lineas"]):
        raise ErrorImportacion("Ese renglón ya no existe.")

    linea = grupo["lineas"].pop(indice)
    grupo.setdefault("omitidas", []).append({
        "descripcion": linea["descripcion"],
        "total": linea["total"],
    })
    grupo["lineas_originales"] = max(
        grupo.get("lineas_originales", 0), len(grupo["lineas"]) + 1
    )
    _recalcular_total(grupo)
    plan["resumen"] = resumir(plan["grupos"])
    return grupo


def quitar_sin_importe(plan: Dict[str, Any]) -> int:
    """Quita de golpe los renglones que no aportan nada al total.

    Fresko imprime líneas informativas como "RECOGER EN TIENDA" o "CAJA 1 PZA"
    que no son ni un producto ni un cargo: salen con importe cero. Como no suman,
    quitarlas no altera el total, solo deja el ticket con lo que realmente se
    compró.
    """
    quitados = 0
    for grupo in plan["grupos"]:
        if grupo.get("excluir"):
            continue
        conservadas = []
        for linea in grupo["lineas"]:
            # Los descuentos los agrega el sistema, no la persona: se respetan.
            if linea["total"] == 0 and linea.get("tipo") != "descuento":
                grupo.setdefault("omitidas", []).append({
                    "descripcion": linea["descripcion"],
                    "total": linea["total"],
                })
                quitados += 1
            else:
                conservadas.append(linea)
        if len(conservadas) != len(grupo["lineas"]):
            grupo["lineas_originales"] = len(grupo["lineas"])
            grupo["lineas"] = conservadas
            _recalcular_total(grupo)
    plan["resumen"] = resumir(plan["grupos"])
    return quitados


def agregar_linea(
    plan: Dict[str, Any],
    clave: str,
    descripcion: str,
    monto: float,
    tipo: str = "descuento",
) -> Dict[str, Any]:
    """Agrega un renglón al ticket: un descuento de tienda, un cashback, etc.

    `monto` se guarda tal cual, así que un descuento se captura en negativo y
    baja el total pagado.
    """
    grupo = _buscar(plan, clave)

    descripcion = (descripcion or "").strip()
    if not descripcion:
        raise ErrorImportacion("El renglón necesita una descripción.")
    try:
        monto = float(monto)
    except (TypeError, ValueError):
        raise ErrorImportacion("El importe del renglón no es un número.")
    if tipo not in ("producto", "descuento"):
        raise ErrorImportacion("Tipo de renglón inválido.")

    grupo["lineas"].append({
        "sku": "",
        "descripcion": descripcion,
        "cantidad": 1.0,
        "precio_regular": monto,
        "precio_promo": None,
        "total": monto,
        "categoria": "",
        "subcategoria": "",
        "tipo": tipo,
    })
    _recalcular_total(grupo)
    plan["resumen"] = resumir(plan["grupos"])
    return grupo


def aplicar_correcciones(plan: Dict[str, Any], correcciones: str) -> Dict[str, Any]:
    """Rehace el plan con lo que la persona ajustó a mano."""
    cambios = _parsear_correcciones(correcciones)
    por_clave = {c["clave"]: c for c in cambios}

    for grupo in plan["grupos"]:
        ajuste = por_clave.get(grupo["clave"])
        if not ajuste:
            continue
        if "establecimiento" in ajuste:
            grupo["establecimiento"] = (ajuste["establecimiento"] or "").strip()
        if "forma_pago" in ajuste:
            grupo["forma_pago"] = (ajuste["forma_pago"] or "").strip()
        if "excluir" in ajuste:
            grupo["excluir"] = bool(ajuste["excluir"])

    plan["resumen"] = resumir(plan["grupos"])
    return plan


def _parsear_correcciones(correcciones: str) -> List[Dict[str, Any]]:
    try:
        datos = json.loads(correcciones or "[]")
    except json.JSONDecodeError as exc:
        raise ErrorImportacion(f"Correcciones con formato inválido: {exc}") from exc
    if not isinstance(datos, list):
        raise ErrorImportacion("Las correcciones deben ser una lista.")
    return [d for d in datos if isinstance(d, dict)]


# ═══════════════════════════════════════════════════════════════════════════
# Escritura
# ═══════════════════════════════════════════════════════════════════════════

def aplicar_plan(
    conn: sqlite3.Connection,
    plan: Dict[str, Any],
    resolver_categorias: bool = True,
) -> Dict[str, Any]:
    """Escribe el plan en una sola transacción: entra todo o no entra nada.

    `resolver_categorias` en False deja la clasificación en NULL. Solo se usa
    para validar el agrupado sin tocar el catálogo.
    """
    categorias: Dict[str, int] = {}
    subcategorias: Dict[Any, int] = {}
    productos = _indice_productos(conn)
    creados: List[str] = []
    insertados: List[Dict[str, Any]] = []
    omitidos: List[Dict[str, str]] = []
    renglones = 0

    conn.execute("BEGIN")
    try:
        for grupo in plan["grupos"]:
            if grupo["excluir"]:
                omitidos.append({
                    "clave": grupo["clave"],
                    "motivo": grupo["motivo_exclusion"] or "excluido a mano",
                })
                continue
            try:
                ticket_id = _insertar_ticket(conn, grupo)
            except sqlite3.IntegrityError:
                omitidos.append({"clave": grupo["clave"], "motivo": "ya estaba importado"})
                continue
            renglones += _insertar_lineas(
                conn, ticket_id, grupo, productos, categorias, subcategorias,
                creados, resolver_categorias,
            )
            insertados.append({"id": ticket_id, "clave": grupo["clave"]})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "tickets": len(insertados),
        "renglones": renglones,
        "importe": round(
            sum(g["total"] for g in plan["grupos"]
                if not g["excluir"]
                and g["clave"] in {i["clave"] for i in insertados}),
            2,
        ),
        "omitidos": omitidos,
        "creados": sorted(set(creados)),
    }


def _insertar_ticket(conn: sqlite3.Connection, grupo: Dict[str, Any]) -> int:
    cab = grupo.get("cabecera") or {}
    # El histórico no tiene archivo, así que su identidad se deriva de la
    # fecha, la hora y el total: reintentar la importación choca con el
    # UNIQUE de sha256 y no duplica nada.
    sha256 = grupo["sha256"] or hashlib.sha256(
        f"HIST:{grupo['fecha']}:{grupo['hora'] or ''}:{grupo['total']:.2f}".encode()
    ).hexdigest()

    cursor = conn.execute(
        """
        INSERT INTO tickets (archivo, ticket_legacy, sha256, fecha, hora,
                             establecimiento, rfc_emisor, regimen_fiscal, folio,
                             cliente, forma_pago, tarjeta, total, ahorro, descuento,
                             subtotal, iva, ieps, articulos_declarados, origen, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            grupo["archivo"], grupo["ticket_legacy"], sha256,
            grupo["fecha"], grupo["hora"],
            grupo["establecimiento"] or None,
            cab.get("rfc_emisor") or None, cab.get("regimen_fiscal") or None,
            cab.get("folio") or None, cab.get("cliente") or None,
            grupo["forma_pago"] or None, cab.get("tarjeta") or None,
            grupo["total"], grupo["ahorro"], grupo.get("descuento", 0.0),
            None, cab.get("iva"), cab.get("ieps"),
            cab.get("articulos_declarados"), grupo["origen"],
            _nota_omitidas(grupo),
        ),
    )
    return cursor.lastrowid


def _nota_omitidas(grupo: Dict[str, Any]) -> Optional[str]:
    """Deja constancia de los renglones que no son parte de la compra.

    "RECOGER EN TIENDA" o "CAJA 1 PZA" sí venían en el ticket, pero no son ni un
    producto ni un cargo. No se guardan como renglón porque no son gasto, pero
    tampoco se pierden en silencio: quedan anotados en el propio ticket.
    """
    omitidas = grupo.get("omitidas") or []
    if not omitidas:
        return None
    nombres = ", ".join(o["descripcion"] for o in omitidas)
    return f"Renglones sin importe, fuera de la compra: {nombres}."


def _insertar_lineas(
    conn: sqlite3.Connection,
    ticket_id: int,
    grupo: Dict[str, Any],
    productos: Dict[str, int],
    categorias: Dict[str, int],
    subcategorias: Dict[Any, int],
    creados: List[str],
    resolver: bool,
) -> int:
    for numero, linea in enumerate(grupo["lineas"], start=1):
        descripcion = linea["descripcion"]
        clave_norm = normalizar(descripcion)
        producto_id = productos.get(clave_norm)
        es_descuento = linea.get("tipo") == "descuento"

        # Un descuento no pertenece a ninguna categoría: se le deja en NULL
        # para que no cuelgue de la del producto y las vistas lo excluyan.
        if es_descuento:
            producto_id = None
            categoria_id = subcategoria_id = None
        # Los PDF traen el nombre pero no la categoría: se busca en el catálogo.
        # El histórico ya trae ambas, y aun así se resuelven por id para que
        # la clasificación quede congelada igual que en los PDF.
        elif resolver:
            nombre_cat = linea["categoria"] or _categoria_de(conn, producto_id)
            nombre_sub = linea["subcategoria"] or _subcategoria_de(conn, producto_id)
            if nombre_cat:
                categoria_id = resolver_categoria(conn, nombre_cat, creados, categorias)
                subcategoria_id = resolver_subcategoria(
                    conn, categoria_id, nombre_sub or nombre_cat, creados, subcategorias
                )
            else:
                categoria_id = subcategoria_id = None
        else:
            categoria_id = subcategoria_id = None

        cantidad = linea["cantidad"] or 1.0
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
                linea["sku"] or None, descripcion, clave_norm,
                cantidad, linea["precio_regular"], linea["precio_promo"],
                round(linea["total"] / cantidad, 4) if cantidad else linea["total"],
                linea["total"], categoria_id, subcategoria_id,
                "descuento" if es_descuento else "producto",
            ),
        )
    return len(grupo["lineas"])


def _indice_productos(conn: sqlite3.Connection) -> Dict[str, int]:
    return {
        normalizar(f["descripcion"]): f["id"]
        for f in conn.execute("SELECT id, descripcion FROM productos")
    }


def _categoria_de(conn: sqlite3.Connection, producto_id: Optional[int]) -> str:
    if not producto_id:
        return ""
    fila = conn.execute(
        "SELECT c.nombre FROM productos p"
        " JOIN categorias c ON c.id = p.categoria_id WHERE p.id = ?",
        (producto_id,),
    ).fetchone()
    return fila["nombre"] if fila else ""


def _subcategoria_de(conn: sqlite3.Connection, producto_id: Optional[int]) -> str:
    if not producto_id:
        return ""
    fila = conn.execute(
        "SELECT s.nombre FROM productos p"
        " JOIN subcategorias s ON s.id = p.subcategoria_id WHERE p.id = ?",
        (producto_id,),
    ).fetchone()
    return fila["nombre"] if fila else ""
