import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from backend.config import (
    DESCARTADOS_DIR,
    PROCESADOS_DIR,
    RESULTADOS_DIR,
    TEMPLATES_DIR,
    UPLOAD_DIR,
)
from backend.services.catalogo import (
    SIN_CATEGORIA,
    SIN_SUBCATEGORIA,
    ErrorCatalogo,
    aplicar_confirmacion,
    guardar_csv,
    obtener_arbol_categorias,
    normalizar_correcciones,
    revisar_correcciones,
)
from backend.services.log import obtener_cambios
from backend.services.pdf_parser import parsear_ticket_pdf
from backend.services.registro import (
    ErrorRegistro,
    conciliar,
    confirmar_y_registrar,
    sha256_de,
    ya_registrado,
)
from backend.web import render
from backend.services.staging import (
    aplicar_correcciones_staging,
    cargar_staging,
    construir_ticket_id,
    crear_staging_desde_ticket,
    eliminar_staging,
    guardar_staging,
    listar_staging,
)

router = APIRouter(tags=["Tickets"])



def _resumen(ticket: dict) -> dict:
    articulos = ticket.get("articulos", [])
    return {
        "articulos": len(articulos),
        "cantidad": round(sum(a.get("cantidad") or 0 for a in articulos), 3),
        "importe": round(sum(a.get("total") or 0 for a in articulos), 2),
    }


def _nombre_seguro(nombre: str) -> str:
    """Solo el nombre del archivo: un `../` no puede salirse de la carpeta."""
    return Path(nombre or "").name


def _leer_correcciones(texto: str) -> list:
    """El formulario manda JSON; si llega roto se trata como lista vacía, y la
    validación del servidor decide con lo que el ticket ya tenía guardado."""
    try:
        datos = json.loads(texto or "[]")
    except json.JSONDecodeError:
        return []
    return datos if isinstance(datos, list) else []


def _redir(mensaje: str = None, error: str = None) -> RedirectResponse:
    partes = []
    if mensaje:
        partes.append(f"mensaje={quote(mensaje)}")
    if error:
        partes.append(f"error={quote(error)}")
    sufijo = "&".join(partes)
    return RedirectResponse(url=f"/tickets?{sufijo}" if sufijo else "/tickets",
                        status_code=303)


@router.get("/tickets", response_class=HTMLResponse)
async def tickets(request: Request, mensaje: str = None, aviso: str = None,
                 error: str = None):
    try:
        arbol = obtener_arbol_categorias()
        error_catalogo = None
    except Exception as e:
        arbol, error_catalogo = {}, f"No se pudo leer el catálogo: {e}"

    en_revision = listar_staging()
    ya_en_revision = {t["archivo"] for t in en_revision}
    for ticket in en_revision:
        ticket["resumen"] = _resumen(ticket)
        # Se calcula con la misma regla que valida el servidor, para que la barra
        # de avance no parpadee en cero antes de que corra el JavaScript.
        pendientes = len(
            revisar_correcciones(ticket, normalizar_correcciones(ticket, []))
        )
        total = len(ticket["articulos"])
        ticket["avance"] = {
            "total": total,
            "validados": total - pendientes,
            "pendientes": pendientes,
            "porcentaje": round((total - pendientes) * 100 / total) if total else 0,
        }
        ticket["conciliacion"] = conciliar(ticket)

    return render(
        request,
        "index.html",
        "tickets",
        context={
            "revision": en_revision,
            "pendientes": [
                f.name for f in UPLOAD_DIR.glob("*.pdf") if f.name not in ya_en_revision
            ],
            "procesados": [f.name for f in PROCESADOS_DIR.glob("*.pdf")],
            "descartados": [f.name for f in DESCARTADOS_DIR.glob("*.pdf")],
            "arbol_categorias": arbol,
            "sin_categoria": SIN_CATEGORIA,
            "sin_subcategoria": SIN_SUBCATEGORIA,
            "mensaje": mensaje,
            "aviso": aviso,
            "error": error or error_catalogo,
        },
    )


@router.post("/cargar-archivos/")
async def cargar_archivos(archivos: List[UploadFile] = File(...)):
    subidos, fallidos, repetidos = 0, [], []
    for archivo in archivos:
        nombre = _nombre_seguro(archivo.filename)
        if not nombre or not nombre.lower().endswith(".pdf"):
            continue

        contenido = await archivo.read()
        # Un PDF ya registrado no vuelve a entrar: se reconoce por su huella,
        # no por el nombre, que puede cambiar al descargarlo de nuevo.
        previo = ya_registrado(hashlib.sha256(contenido).hexdigest())
        if previo:
            repetidos.append(f"{nombre} (ya es el ticket #{previo['id']} del {previo['fecha']})")
            continue

        (UPLOAD_DIR / nombre).write_bytes(contenido)
        subidos += 1

        try:
            crear_staging_desde_ticket(parsear_ticket_pdf(str(UPLOAD_DIR / nombre)), nombre)
        except Exception as e:
            fallidos.append(f"{nombre} ({e})")

    errores = []
    if fallidos:
        errores.append("No se pudo interpretar: " + ", ".join(fallidos) + ".")
    if repetidos:
        errores.append("Ya estaban registrados y no se cargaron: " + ", ".join(repetidos) + ".")
    if errores:
        return _redir(
            mensaje=f"Se cargaron {subidos} archivos; revisa los tickets pendientes.",
            error=" ".join(errores),
        )
    return _redir(mensaje=f"Se cargaron {subidos} archivos. Revísalos antes de confirmar.")


@router.post("/revisar-ticket/")
async def revisar_ticket(archivo_nombre: str = Form(...)):
    archivo_nombre = _nombre_seguro(archivo_nombre)
    pdf_path = UPLOAD_DIR / archivo_nombre
    if not archivo_nombre or not pdf_path.is_file():
        return _redir(error="El archivo no existe en pendientes.")

    if cargar_staging(construir_ticket_id(archivo_nombre)) is not None:
        return _redir(error=f"'{archivo_nombre}' ya está en la sección de revisión.")

    try:
        ticket = crear_staging_desde_ticket(
            parsear_ticket_pdf(str(pdf_path)), archivo_nombre
        )
    except Exception as e:
        return _redir(error=f"Error al interpretar '{archivo_nombre}': {e}")

    return _redir(
        mensaje=f"Ticket '{archivo_nombre}' listo para revisar "
        f"({len(ticket['articulos'])} artículos)."
    )


def _detalle_incompletos(incompletos: List[dict], limite: int = 5) -> str:
    piezas = []
    for item in incompletos[:limite]:
        falta = []
        if item["falta_categoria"]:
            falta.append("categoría")
        if item["falta_subcategoria"]:
            falta.append("subcategoría")
        nombre = item["articulo"] or f"fila {item['indice'] + 1}"
        piezas.append(f"{nombre} (falta {' y '.join(falta)})")
    if len(incompletos) > limite:
        piezas.append(f"y {len(incompletos) - limite} más")
    return "; ".join(piezas)


def _correcciones_guardadas(ticket: dict) -> List[dict]:
    """Correcciones tal como están guardadas en el propio ticket."""
    return normalizar_correcciones(ticket, [])


@router.post("/guardar-cambios/")
async def guardar_cambios(
    ticket_id: str = Form(...), correcciones: str = Form("[]")
):
    """Guarda el avance sin exigir que el ticket esté completo.

    Aplica al catálogo los renglones ya corregidos y los deja escritos en el
    ticket; los que siguen incompletos quedan pendientes para retomarlos. El PDF
    no se mueve y no se genera CSV: eso es lo de «Confirmar y procesar».
    """
    ticket = cargar_staging(ticket_id)
    if ticket is None:
        return _redir(error=f"El ticket '{ticket_id}' ya no está en revisión.")

    cambios = normalizar_correcciones(ticket, _leer_correcciones(correcciones))
    incompletos = revisar_correcciones(ticket, cambios)

    if len(incompletos) >= len(ticket["articulos"]):
        return _redir(
            error=(
                "No se guardó nada: todavía no hay ningún renglón con "
                "categoría y subcategoría completas."
            )
        )

    try:
        informe = aplicar_confirmacion(ticket, cambios, permitir_parcial=True)
    except Exception as e:
        return _redir(error=f"Error al guardar '{ticket_id}': {e}")

    guardados = aplicar_correcciones_staging(ticket, cambios)
    guardar_staging(ticket, ticket_id)

    pendientes = len(incompletos)
    if pendientes:
        mensaje = (
            f"Avance guardado: {guardados} renglón(es) aplicados al catálogo. "
            f"Quedan {pendientes} sin categoría por completar en '{ticket['archivo']}'."
        )
    else:
        mensaje = (
            f"'{ticket['archivo']}' quedó validado por completo. "
            f"Solo falta confirmar y procesar."
        )

    if informe["creados"]:
        resumen = ", ".join(informe["creados"][:3])
        if len(informe["creados"]) > 3:
            resumen += f" y {len(informe['creados']) - 3} más"
        mensaje += f" Agregados al catálogo: {resumen}."

    error = None
    if informe["rechazados"]:
        error = "Rechazados: " + "; ".join(informe["rechazados"][:3])

    return _redir(mensaje=mensaje, error=error)


def _validar_ticket_id(ticket_id: str) -> str:
    """Valida que el ticket_id sea seguro (solo caracteres alfanuméricos, guiones y guiones bajos)."""
    import re
    if not ticket_id or not re.match(r'^[a-zA-Z0-9_-]+$', ticket_id):
        raise ValueError("ID de ticket inválido")
    return ticket_id


@router.get("/descargar-csv/{ticket_id}")
async def descargar_csv(ticket_id: str):
    """Descarga el CSV de la validación sin necesidad de confirmar el ticket."""
    try:
        ticket_id = _validar_ticket_id(ticket_id)
    except ValueError:
        return _redir(error="ID de ticket inválido.")
    ticket = cargar_staging(ticket_id)
    if ticket is None:
        return _redir(error=f"El ticket '{ticket_id}' ya no está en revisión.")

    incompletos = revisar_correcciones(
        ticket, _correcciones_guardadas(ticket)
    )
    if not incompletos:
        aplicar_correcciones_staging(ticket, _correcciones_guardadas(ticket))

    destino = RESULTADOS_DIR / f"{ticket_id}_categorizado.csv"
    guardar_csv(ticket, str(destino))
    return StreamingResponse(
        iter([destino.read_bytes()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{destino.name}"'},
    )


@router.get("/reporte/{ticket_id}", response_class=HTMLResponse)
async def reporte_ticket(request: Request, ticket_id: str):
    """Informe imprimible de la validación. Desde aquí el navegador guarda el PDF."""
    try:
        ticket_id = _validar_ticket_id(ticket_id)
    except ValueError:
        return _redir(error="ID de ticket inválido.")
    ticket = cargar_staging(ticket_id)
    if ticket is None:
        return _redir(error=f"El ticket '{ticket_id}' ya no está en revisión.")

    incompletos = revisar_correcciones(ticket, _correcciones_guardadas(ticket))
    return render(
        request,
        "reporte.html",
        "tickets",
        context={
            "ticket": ticket,
            "arbol": obtener_arbol_categorias(),
            "resumen": _resumen(ticket),
            "conciliacion": conciliar(ticket),
            "incompletos": incompletos,
            "faltantes": {i["indice"] for i in incompletos},
            "completos": len(ticket["articulos"]) - len(incompletos),
            "ahora": datetime.now().strftime("%d/%m/%Y %H:%M"),
        },
    )


@router.post("/confirmar-ticket/")
async def confirmar_ticket(
    ticket_id: str = Form(...), correcciones: str = Form("[]")
):
    ticket = cargar_staging(ticket_id)
    if ticket is None:
        return _redir(error=f"El ticket '{ticket_id}' ya no está en revisión.")

    cambios = normalizar_correcciones(ticket, _leer_correcciones(correcciones))
    incompletos = revisar_correcciones(ticket, cambios)
    if incompletos:
        return _redir(
            error=(
                f"No se puede confirmar: {len(incompletos)} renglón(es) incompletos. "
                f"{_detalle_incompletos(incompletos)}"
            )
        )

    pdf = UPLOAD_DIR / ticket["archivo"]
    if not pdf.is_file():
        return _redir(error=f"No se encontró el PDF '{ticket['archivo']}' en uploads/.")

    # 1. Catálogo y base de datos, en una sola transacción: si algo falla no
    #    se escribe nada y el ticket sigue en revisión.
    try:
        informe = confirmar_y_registrar(ticket, cambios, sha256_de(pdf))
    except (ErrorRegistro, ErrorCatalogo) as e:
        return _redir(error=f"No se confirmó '{ticket['archivo']}': {e}")
    except Exception as e:
        return _redir(error=f"Error al confirmar '{ticket_id}', no se guardó nada: {e}")

    # 2. Archivos. El ticket ya está en la base; si esto falla se avisa, pero
    #    no se deshace: volver a confirmar lo detectaría como duplicado.
    csv_salida = RESULTADOS_DIR / f"{ticket_id}_categorizado.csv"
    try:
        guardar_csv(ticket, str(csv_salida))
        pdf.replace(PROCESADOS_DIR / ticket["archivo"])
        eliminar_staging(ticket_id)
    except Exception as e:
        return _redir(
            mensaje=f"Ticket '{ticket['archivo']}' registrado en la base (#{informe['ticket_db_id']}).",
            error=f"Pero no se pudieron archivar sus archivos: {e}",
        )

    conc = informe["conciliacion"]
    mensaje = (
        f"Ticket '{ticket['archivo']}' confirmado y registrado (#{informe['ticket_db_id']}): "
        f"{informe['renglones']} renglones, total ${conc['total_a_registrar']:,.2f}"
    )
    if conc["cash_back"] < 0:
        mensaje += f" con CASH BACK de ${-conc['cash_back']:,.2f}"
    mensaje += "."
    if informe["creados"]:
        mensaje += " Agregado al catálogo: " + ", ".join(informe["creados"]) + "."

    return _redir(
        mensaje=mensaje,
        error=conc["mensaje"] if conc["estado"] in ("ajuste", "sin_total") else None,
    )


@router.post("/descartar-ticket/")
async def descartar_ticket(ticket_id: str = Form(...)):
    ticket = cargar_staging(ticket_id)
    if ticket is None:
        return _redir(error=f"El ticket '{ticket_id}' ya no está en revisión.")

    pdf = UPLOAD_DIR / ticket["archivo"]
    if pdf.exists():
        pdf.replace(DESCARTADOS_DIR / ticket["archivo"])
    eliminar_staging(ticket_id)
    return _redir(mensaje=f"Ticket '{ticket['archivo']}' descartado.")


@router.get("/api/categorias")
async def api_categorias():
    """Devuelve el árbol de categorías actualizado.

    Se usa desde el frontend para refrescar los selects después de crear
    una categoría o subcategoría nueva, sin necesidad de recargar la página.
    """
    try:
        arbol = obtener_arbol_categorias()
        return {"arbol": arbol}
    except Exception as e:
        return {"error": str(e)}


@router.get("/log")
async def ver_log(request: Request, tabla: str = None, limite: int = 100):
    """Vista de auditoría: muestra los cambios registrados en la base de datos."""
    cambios = obtener_cambios(tabla=tabla, limite=limite)
    return render(
        request,
        "log.html",
        "log",
        context={
            "cambios": cambios,
            "tabla_filtro": tabla,
        },
    )
