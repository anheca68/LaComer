import re
from typing import Any, Dict

import pdfplumber

# Fecha del ticket en formato español: 07/Sep/26
MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def parsear_ticket_pdf(pdf_path: str) -> Dict[str, Any]:
    texto_completo = ""
    with pdfplumber.open(pdf_path) as pdf:
        for pagina in pdf.pages:
            texto_pagina = pagina.extract_text()
            if texto_pagina:
                texto_completo += texto_pagina + "\n"

    lineas = [linea.strip() for linea in texto_completo.split("\n") if linea.strip()]

    datos_ticket = {
        "rfc_emisor": "",
        "regimen_fiscal": "",
        "cliente": "",
        "tarjeta": "",
        "fecha_compra": "",
        "hora_compra": "",
        "fecha_iso": "",
        "folio": "",
        "establecimiento": "",
        "razon_social": "",
        "total_ticket": None,
        "iva": None,
        "ieps": None,
        "articulos_declarados": None,
        "ahorro": None,
        "articulos": [],
        "descuentos": [],
    }

    _buscar_texto(datos_ticket, "rfc_emisor", r"RFC\s+([A-Z0-9]{12,13})", texto_completo)
    _buscar_texto(datos_ticket, "regimen_fiscal", r"Regimen\s+(.+)", texto_completo, True)
    _buscar_texto(datos_ticket, "cliente", r"Cliente\s+(.+)", texto_completo, True)
    _buscar_texto(datos_ticket, "tarjeta", r"Tarjeta:\s*(.+)", texto_completo)

    # `SUC\.` con punto, para no confundirse con el encabezado "SUCURSAL".
    _buscar_texto(datos_ticket, "establecimiento", r"SUC\.\s*([^│\n]+)", texto_completo)
    _buscar_texto(
        datos_ticket, "razon_social",
        r"(Comercial\s+City\s+Fresko\s+S\.\s*de\s*R\.L\.\s*de\s*C\.V\.)",
        texto_completo,
    )
    _buscar_texto(datos_ticket, "folio", r"Folio:\s*(\d+)", texto_completo)

    # El gran total exige el signo de pesos pegado a TOTAL: así "TOTAL PESOS
    # $113.00", que es el efectivo entregado, no se confunde con el total.
    _buscar_numero(datos_ticket, "total_ticket", r"TOTAL\s+\$\s*([\d,]+\.\d{2})", texto_completo)
    _buscar_numero(datos_ticket, "iva", r"IVA\s+\d+%\s+([\d,]+\.\d{2})", texto_completo)
    _buscar_numero(datos_ticket, "ieps", r"IEPS\s+\d+%\s+([\d,]+\.\d{2})", texto_completo)
    # Lo que el ticket dice que ahorraste en total (ofertas, monedero, combos).
    # Es informativo: incluye el monedero, que no resta del total pagado.
    _buscar_numero(datos_ticket, "ahorro", r"AHORRASTE\s+EN\s+LA\s+COMER\s+([\d,]+\.\d{2})", texto_completo)
    match_articulos = re.search(r"(?i)\barticulos\s+(\d+)", texto_completo)
    if match_articulos:
        datos_ticket["articulos_declarados"] = int(match_articulos.group(1))

    coincidencia = re.search(r"(\d{2})/(\w{3})/(\d{2})\s+(\d{2}:\d{2}:\d{2})", texto_completo)
    if coincidencia:
        dia, mes, anio, hora = coincidencia.groups()
        datos_ticket["fecha_compra"] = f"{dia}/{mes}/{anio}"
        datos_ticket["hora_compra"] = hora
        datos_ticket["fecha_iso"] = fecha_a_iso(dia, mes, anio)

    pattern_articulo = re.compile(
        r"^(\d+(?:\.\d+)?)\s+"
        r"(\d+)\s+"
        r"(.+?)\s+"
        r"(\d+\.\d{2})\s+"
        r"(?:(\d+\.\d{2})\s+)?"
        r"(\d+\.\d{2})$"
    )

    for linea in lineas:
        match = pattern_articulo.match(linea)
        if match:
            cant, sku, articulo, p_reg, p_promo, total = match.groups()
            datos_ticket["articulos"].append(
                {
                    "cantidad": float(cant),
                    "sku": str(sku).strip(),
                    "articulo": articulo.strip(),
                    "precio_regular": float(p_reg),
                    "precio_promocion": float(p_promo) if p_promo else "",
                    "total": float(total),
                }
            )

    datos_ticket["descuentos"] = extraer_descuentos(lineas)
    return datos_ticket


# Renglón de descuento: "2 383 TE LIPTON 600 ML -4.40" o
# "-1 458 CACAHUATES SABRITAS -29.50". Siempre termina en un importe negativo.
PATRON_DESCUENTO = re.compile(
    r"^(-?\d+(?:\.\d+)?)\s+"
    r"(\d+)\s+"
    r"(.+?)\s+"
    r"(-\d+\.\d{2})$"
)

# "Compra 2/Gratis 1/2 @ -57.50" repite la suma de los renglones de arriba: si
# se contara, el descuento saldría doble.
PATRON_SUBTOTAL_PROMO = re.compile(r"^Compra\b.*@\s*-[\d,]+\.\d{2}$", re.IGNORECASE)


def extraer_descuentos(lineas: list) -> list:
    """Renglones con importe negativo de la sección de promociones.

    Solo se leen los que están antes del `TOTAL $`: lo que viene después
    (monedero, "AHORRASTE…") es informativo y no resta del total pagado.
    """
    descuentos = []
    for linea in lineas:
        if re.match(r"^TOTAL\s+\$", linea):
            break
        if PATRON_SUBTOTAL_PROMO.match(linea):
            continue
        match = PATRON_DESCUENTO.match(linea)
        if match:
            cant, sku, articulo, importe = match.groups()
            descuentos.append(
                {
                    "cantidad": float(cant),
                    "sku": sku.strip(),
                    "articulo": articulo.strip(),
                    "total": float(importe),
                }
            )
    return descuentos


def fecha_a_iso(dia: str, mes: str, anio: str) -> str:
    """'07', 'Sep', '26' -> '2026-09-07'. El PDF usa año de dos dígitos."""
    numero_mes = MESES.get(mes.lower())
    if not numero_mes:
        return ""
    return f"20{anio}-{numero_mes:02d}-{int(dia):02d}"


def _buscar_texto(datos, campo, patron, texto, ignorar_mayus=False) -> None:
    flags = re.IGNORECASE if ignorar_mayus else 0
    match = re.search(patron, texto, flags)
    if match:
        datos[campo] = match.group(1).strip()


def _buscar_numero(datos, campo, patron, texto) -> None:
    match = re.search(patron, texto)
    if match:
        datos[campo] = float(match.group(1).replace(",", ""))
