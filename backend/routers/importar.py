"""Pantalla de carga inicial del histórico.

Existe una sola vez en la vida del proyecto: mientras la tabla `tickets` esté
vacía. En cuanto se importa, las rutas se auto-deshabilitan, así que nadie
puede volver a meter los 1181 renglones del Excel por error.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from backend.config import CATALOGO_EXCEL_PATH, PROCESADOS_DIR, STAGING_DIR
from backend.web import render
from backend.database import get_db_connection
from backend.services.importar_historico import (
    ErrorImportacion,
    # Aliados: el router expone rutas con estos mismos nombres, y una función
    # definida después se quedaría con el nombre del endpoint y se llamaría a
    # sí misma.
    agregar_linea as agregar_linea_plan,
    aplicar_correcciones,
    aplicar_plan,
    completar_vacios,
    condensar,
    detectar_solapamientos,
    eliminar_linea,
    leer_excel,
    plan_desde_excel,
    plan_desde_pdfs,
    quitar_sin_importe as quitar_sin_importe_plan,
    resumir,
    sugerir_comunes,
)

router = APIRouter()
logger = logging.getLogger(__name__)

ARCHIVO_PLAN = STAGING_DIR / "importacion_historica.json"


def _carga_abierta() -> bool:
    conn = get_db_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 0
    finally:
        conn.close()


def _guardia() -> Optional[RedirectResponse]:
    if _carga_abierta():
        return None
    # Va a /tickets, no a /: la raíz ahora es el panel, que no lee el parámetro
    # `aviso`, así que el mensaje se perdería en silencio.
    return RedirectResponse(
        "/tickets?aviso=La+carga+inicial+ya+se+realizo", status_code=303
    )


def _redir(**params) -> RedirectResponse:
    import urllib.parse

    limpio = {k: v for k, v in params.items() if v}
    consulta = urllib.parse.urlencode(limpio)
    return RedirectResponse(f"/importar?{consulta}" if consulta else "/importar",
                            status_code=303)


def _leer_plan() -> Optional[dict]:
    if not ARCHIVO_PLAN.exists():
        return None
    return json.loads(ARCHIVO_PLAN.read_text(encoding="utf-8"))


def _guardar_plan(plan: dict) -> None:
    ARCHIVO_PLAN.write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8"
    )


def _con_plan(clave: str, cambio, aviso_ok: str) -> RedirectResponse:
    """Aplica un cambio al plan guardado y lo vuelve a escribir.

    Todas las operaciones sobre renglones pasan por aquí para que el plan en
    disco y el que se está viendo no se separen nunca.
    """
    bloqueo = _guardia()
    if bloqueo:
        return bloqueo

    plan = _leer_plan()
    if plan is None:
        return _redir(error="No hay ningún plan cargado. Prepara uno primero.")

    try:
        aviso = cambio(plan) or aviso_ok
    except ErrorImportacion as exc:
        return _redir(error=str(exc))
    except (KeyError, IndexError) as exc:
        return _redir(error=f"No se pudo aplicar el cambio: {exc}")

    _guardar_plan(plan)
    return _redir(aviso=aviso)


@router.get("/importar")
async def vista_importar(request: Request, aviso: str = "", error: str = ""):
    bloqueo = _guardia()
    if bloqueo:
        return bloqueo

    plan = _leer_plan()
    return render(
        request,
        "importar.html",
        "importar",
        context={
            "excel": CATALOGO_EXCEL_PATH,
            "excel_existe": Path(CATALOGO_EXCEL_PATH).exists(),
            "pdfs": len(list(PROCESADOS_DIR.glob("*.pdf"))),
            "hay_plan": plan is not None,
            "resumen": (plan or {}).get("resumen", {}),
            "sugeridos": (plan or {}).get("sugeridos", {}),
            "aviso": aviso,
            "error": error,
                    },
    )


@router.get("/importar/plan")
async def ver_plan():
    bloqueo = _guardia()
    if bloqueo:
        return bloqueo
    return _leer_plan() or {"grupos": [], "resumen": {}}


@router.post("/importar/preparar")
async def preparar(fuente: str = Form("ambas")):
    """Arma el plan proposed. No escribe nada en la base todavía."""
    bloqueo = _guardia()
    if bloqueo:
        return bloqueo

    try:
        grupos = []
        if fuente in ("excel", "ambas"):
            grupos += plan_desde_excel(leer_excel())["grupos"]
        if fuente in ("pdfs", "ambas"):
            grupos += plan_desde_pdfs()["grupos"]
    except ErrorImportacion as exc:
        return _redir(error=str(exc))

    # Un ticket completo repetido N veces se importa una sola: se deja decidido
    # de antemano y la pantalla enseña qué se quitó, por si no es lo esperado.
    for grupo in grupos:
        if grupo["pendiente"] == "condensar":
            condensar(grupo)

    solapados = detectar_solapamientos(grupos)

    # El Excel no trae ni tienda ni forma de pago. Cuando los PDF coinciden entre
    # sí, ese valor es la mejor evidencia disponible y se propone ya puesto, en
    # vez de obligar a escribirlo 52 veces. Queda marcado como sugerido.
    llenados = completar_vacios(grupos, sugerir_comunes(grupos))

    plan = {
        "grupos": grupos,
        "resumen": resumir(grupos),
        "fuente": fuente,
        "sugeridos": llenados,
    }
    _guardar_plan(plan)

    aviso = f"Plan armado: {len(grupos)} tickets por revisar."
    if solapados:
        aviso += (f" {len(solapados)} del Excel coinciden con un PDF y quedaron "
                  f"excluidos.")
    for campo, n in llenados.items():
        aviso += f" {n} sin {campo.replace('_', ' ')}, deducido de los PDF."
    return _redir(aviso=aviso)


@router.post("/importar/guardar")
async def guardar(correcciones: str = Form("[]")):
    """Guarda lo corregido a mano, para que sobreviva a un refresco."""
    bloqueo = _guardia()
    if bloqueo:
        return bloqueo

    plan = _leer_plan()
    if plan is None:
        return _redir(error="No hay ningún plan cargado. Prepara uno primero.")

    try:
        plan = aplicar_correcciones(plan, correcciones)
    except ErrorImportacion as exc:
        return _redir(error=str(exc))

    _guardar_plan(plan)
    return _redir(aviso="Cambios guardados.")


@router.post("/importar/condensar")
async def condensar_grupo(clave: str = Form("")):
    """Quita los renglones repetidos de un ticket completo duplicado."""
    bloqueo = _guardia()
    if bloqueo:
        return bloqueo

    plan = _leer_plan()
    if plan is None:
        return _redir(error="No hay ningún plan cargado.")

    for grupo in plan["grupos"]:
        if grupo["clave"] == clave:
            condensar(grupo)
            plan["resumen"] = resumir(plan["grupos"])
            _guardar_plan(plan)
            return _redir(aviso=grupo.get("nota", "Renglones duplicados quitados."))
    return _redir(error="No se encontró ese ticket.")


@router.post("/importar/linea/eliminar")
async def quitar_linea(clave: str = Form(""), indice: int = Form(0)):
    """Saca un renglón que no es parte de la compra, como "RECOGER EN TIENDA"."""
    return _con_plan(clave, lambda plan: eliminar_linea(plan, clave, indice),
                     "Renglón quitado.")


@router.post("/importar/linea/sin-importe")
async def quitar_sin_importe():
    """Quita de golpe todos los renglones con importe cero del plan."""
    def _cambio(plan):
        return f"{quitar_sin_importe_plan(plan)} renglón(es) sin importe quitados."

    return _con_plan("", _cambio, "")


@router.post("/importar/linea/agregar")
async def agregar_linea(
    clave: str = Form(""),
    descripcion: str = Form(""),
    monto: str = Form("0"),
    tipo: str = Form("descuento"),
):
    """Agrega un renglón: un descuento de tienda, un cashback, lo que sea.

    El importe va con su signo, así que un descuento se captura en negativo.
    """
    def _cambio(plan):
        agregar_linea_plan(plan, clave, descripcion, monto, tipo)
        return f"Renglón «{descripcion.strip()}» agregado."

    return _con_plan(clave, _cambio, "")


@router.post("/importar/aplicar")
async def aplicar(correcciones: str = Form("[]")):
    """Importa. Una sola transacción: entra el histórico completo o nada."""
    bloqueo = _guardia()
    if bloqueo:
        return bloqueo

    plan = _leer_plan()
    if plan is None:
        return _redir(error="No hay ningún plan cargado.")

    # La pantalla permite ajustar y pulsar Importar sin pasar por Guardar, así que
    # lo que se edited en la tabla manda sobre lo que hay en el archivo.
    try:
        plan = aplicar_correcciones(plan, correcciones)
    except ErrorImportacion as exc:
        return _redir(error=str(exc))

    conn = get_db_connection()
    try:
        resultado = aplicar_plan(conn, plan)
    except Exception as exc:
        # El plan sobrevive: si algo falla, se reintenta sin volver a armarlo.
        logger.exception("Fallo al aplicar el plan de importación histórica")
        return _redir(error=(
            "No se pudo importar y no se escribió nada: la base está intacta. "
            "Arma el plan otra vez para corregirlo. Detalle: "
            f"{type(exc).__name__}"
        ))
    else:
        ARCHIVO_PLAN.unlink(missing_ok=True)

    detalles = (
        f"{resultado['tickets']} tickets, {resultado['renglones']} renglones, "
        f"${resultado['importe']:,.2f}"
    )
    if resultado["omitidos"]:
        detalles += f" · {len(resultado['omitidos'])} omitidos"
    return RedirectResponse(f"/?mensaje={detalles}", status_code=303)
