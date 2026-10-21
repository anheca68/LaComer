import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config import STAGING_DIR, UPLOAD_DIR
from backend.services.pdf_parser import parsear_ticket_pdf
from backend.services.catalogo import (
    SIN_CATEGORIA,
    SIN_SUBCATEGORIA,
    enriquecer_articulos,
    enriquecer_por_nombre,
    revisar_correcciones,
)

__all__ = [
    "SIN_CATEGORIA",
    "SIN_SUBCATEGORIA",
    "cargar_staging",
    "crear_staging_desde_ticket",
    "eliminar_staging",
    "guardar_staging",
    "listar_staging",
]


def _ruta_staging(ticket_id: str) -> Path:
    # Solo el nombre: un ticket_id con `../` no puede salirse de staging/.
    return STAGING_DIR / f"{Path(ticket_id).name}.json"


def construir_ticket_id(archivo_nombre: str) -> str:
    return Path(archivo_nombre).stem


def guardar_staging(datos_ticket: Dict[str, Any], ticket_id: str) -> Path:
    ruta = _ruta_staging(ticket_id)
    ruta.write_text(
        json.dumps(datos_ticket, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ruta


def _actualizar_contra_catalogo(ticket: Dict[str, Any], ticket_id: str) -> Dict[str, Any]:
    cambio = _completar_descuentos(ticket)
    if _requiere_enriquecer(ticket):
        try:
            enriquecer_articulos(ticket)
            cambio = True
        except Exception:
            pass
    if cambio:
        guardar_staging(ticket, ticket_id)
    return ticket


def _completar_descuentos(ticket: Dict[str, Any]) -> bool:
    """Los staging creados antes de leer los descuentos no traen ese campo.

    Se vuelven a leer del PDF (solo los descuentos y el ahorro, sin tocar los
    artículos ni lo ya validado) para que la conciliación no los tome por una
    diferencia sin explicar.
    """
    if "descuentos" in ticket:
        return False
    pdf = UPLOAD_DIR / ticket.get("archivo", "")
    if not ticket.get("archivo") or not pdf.exists():
        return False
    try:
        leido = parsear_ticket_pdf(str(pdf))
    except Exception:
        return False
    ticket["descuentos"] = leido.get("descuentos", [])
    ticket.setdefault("ahorro", leido.get("ahorro"))
    return True


def aplicar_correcciones_staging(
    ticket: Dict[str, Any], correcciones: List[Dict[str, Any]]
) -> int:
    """Deja las correcciones dentro del propio ticket en revisión, para que
    sobrevivan a un refresco de la página.

    Solo se guardan los renglones completos: los que están a medias se dejan
    intactos para poder retomarlos después. Devuelve cuántos se guardaron.
    """
    articulos = ticket["articulos"]
    indices_incompletos = {
        i["indice"] for i in revisar_correcciones(ticket, correcciones)
    }
    guardados = 0

    for cambio in correcciones:
        indice = cambio.get("indice")
        if not isinstance(indice, int) or not 0 <= indice < len(articulos):
            continue
        if indice in indices_incompletos:
            continue

        articulo = articulos[indice]
        articulo["categoria"] = cambio["categoria"].upper()
        articulo["subcategoria"] = cambio["subcategoria"].upper()
        articulo["match"] = True
        articulo["registrar_producto"] = bool(cambio.get("registrar_producto"))
        guardados += 1

    return guardados


def cargar_staging(ticket_id: str) -> Optional[Dict[str, Any]]:
    ruta = _ruta_staging(ticket_id)
    if not ruta.exists():
        return None
    ticket = json.loads(ruta.read_text(encoding="utf-8"))
    return _actualizar_contra_catalogo(ticket, ticket_id)


def _requiere_enriquecer(ticket: Dict[str, Any]) -> bool:
    """Los staging guardados antes de que existiera el campo en_catalogo quedan
    desactualizados: hay que volver a cruzarlos contra el catálogo."""
    return any("en_catalogo" not in a for a in ticket.get("articulos", []))


def listar_staging() -> List[Dict[str, Any]]:
    tickets = []
    for ruta in STAGING_DIR.glob("*.json"):
        try:
            ticket = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        tickets.append(_actualizar_contra_catalogo(ticket, ruta.stem))

    return sorted(tickets, key=lambda t: t.get("ticket_id", ""))


def eliminar_staging(ticket_id: str) -> None:
    _ruta_staging(ticket_id).unlink(missing_ok=True)


def crear_staging_desde_ticket(
    datos_ticket: Dict[str, Any], archivo_nombre: str
) -> Dict[str, Any]:
    ticket = enriquecer_por_nombre(datos_ticket)
    ticket["ticket_id"] = construir_ticket_id(archivo_nombre)
    ticket["archivo"] = archivo_nombre
    guardar_staging(ticket, ticket["ticket_id"])
    return ticket
