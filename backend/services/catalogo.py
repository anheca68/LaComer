import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from backend.database import get_db_connection

SIN_CATEGORIA = "sin categoria"
SIN_SUBCATEGORIA = "sin subcategoria"

UMBRAL_SIMILITUD = 0.88

COLUMNAS_CSV = [
    "cantidad",
    "sku",
    "articulo",
    "precio_regular",
    "precio_promocion",
    "total",
    "CATEGORIA",
    "SUB_CATEGORIA",
    "fecha_compra",
    "hora_compra",
]


class ErrorCatalogo(ValueError):
    pass


def normalizar(texto: Any) -> str:
    """Mayúsculas, sin espacios sobrantes y sin acentos, para comparar nombres."""
    descompuesto = unicodedata.normalize("NFKD", str(texto or ""))
    sin_acentos = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acentos).strip().upper()


def _similitud(a: str, b: str) -> float:
    return SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()


# ==========================================
# Consultas
# ==========================================

def obtener_arbol_categorias() -> Dict[str, List[str]]:
    """Categorías con sus subcategorías, tal como están en la base de datos."""
    conn = get_db_connection()
    try:
        categorias = conn.execute("SELECT id, nombre FROM categorias ORDER BY nombre").fetchall()
        subcategorias = conn.execute(
            "SELECT categoria_id, nombre FROM subcategorias"
        ).fetchall()
    finally:
        conn.close()

    nombre_por_id = {c["id"]: c["nombre"] for c in categorias}
    arbol: Dict[str, set] = {}
    for sub in subcategorias:
        categoria = nombre_por_id.get(sub["categoria_id"])
        if categoria is None:
            continue
        arbol.setdefault(categoria, set()).add(sub["nombre"])

    return {c: sorted(s) for c, s in sorted(arbol.items())}


def _cargar_catalogo():
    conn = get_db_connection()
    try:
        categorias = {r["id"]: r["nombre"] for r in conn.execute("SELECT id, nombre FROM categorias")}
        subcategorias = {r["id"]: r["nombre"] for r in conn.execute("SELECT id, nombre FROM subcategorias")}
        productos = conn.execute(
            "SELECT id, sku, descripcion, categoria_id, subcategoria_id FROM productos"
        ).fetchall()
    finally:
        conn.close()
    return categorias, subcategorias, productos


def enriquecer_articulos(datos_ticket: Dict[str, Any]) -> None:
    """Cruza los artículos del ticket contra el catálogo por nombre normalizado,
    con el SKU como segunda opción."""
    categorias, subcategorias, productos = _cargar_catalogo()

    por_nombre: Dict[str, sqlite3.Row] = {}
    por_sku: Dict[str, sqlite3.Row] = {}
    for producto in productos:
        por_nombre.setdefault(normalizar(producto["descripcion"]), producto)
        if producto["sku"]:
            por_sku.setdefault(normalizar(producto["sku"]), producto)

    for articulo in datos_ticket["articulos"]:
        encontrado = por_nombre.get(normalizar(articulo["articulo"])) or por_sku.get(
            normalizar(articulo.get("sku"))
        )
        if encontrado and encontrado["categoria_id"] and encontrado["subcategoria_id"]:
            articulo["categoria"] = categorias.get(encontrado["categoria_id"], SIN_CATEGORIA)
            articulo["subcategoria"] = subcategorias.get(
                encontrado["subcategoria_id"], SIN_SUBCATEGORIA
            )
            articulo["match"] = True
        else:
            articulo["categoria"] = SIN_CATEGORIA
            articulo["subcategoria"] = SIN_SUBCATEGORIA
            articulo["match"] = False
        articulo["en_catalogo"] = encontrado is not None


def enriquecer_por_nombre(datos_ticket: Dict[str, Any]) -> Dict[str, Any]:
    if not datos_ticket["articulos"]:
        raise ValueError("No se encontraron artículos en el ticket.")
    ticket = dict(datos_ticket)
    enriquecer_articulos(ticket)
    return ticket


def guardar_csv(ticket: Dict[str, Any], csv_salida_path: str) -> None:
    import pandas as pd

    # Importación local: `registro` depende de este módulo.
    from backend.services.registro import conciliar, renglon_cash_back

    renglones = list(ticket["articulos"])
    cash_back = renglon_cash_back(conciliar(ticket))
    if cash_back:
        # Con el CASH BACK la suma de la columna `total` es lo pagado.
        renglones.append(cash_back)

    df = pd.DataFrame(renglones)
    df["CATEGORIA"] = df["categoria"]
    df["SUB_CATEGORIA"] = df["subcategoria"]

    for campo in ("rfc_emisor", "regimen_fiscal", "cliente", "tarjeta"):
        df[campo] = ticket.get(campo, "")
    df["fecha_compra"] = ticket.get("fecha_compra", "")
    df["hora_compra"] = ticket.get("hora_compra", "")

    df[COLUMNAS_CSV].to_csv(csv_salida_path, index=False, encoding="utf-8-sig")


# ==========================================
# Validación y alta de valores nuevos
# ==========================================

def _validar_contra_parecidos(nombre: str, existentes: List[str], tipo: str) -> None:
    for candidato in existentes:
        if _similitud(nombre, candidato) >= UMBRAL_SIMILITUD:
            raise ErrorCatalogo(
                f'"{nombre}" se parece demasiado a "{candidato}". '
                f'Revisa el nombre, o usa el {tipo} que ya existe.'
            )


def _buscar_categoria(conn: sqlite3.Connection, nombre: str) -> Optional[int]:
    clave = normalizar(nombre)
    for fila in conn.execute("SELECT id, nombre FROM categorias"):
        if normalizar(fila["nombre"]) == clave:
            return fila["id"]
    return None


def _buscar_subcategoria(conn: sqlite3.Connection, categoria_id: int, nombre: str) -> Optional[int]:
    clave = normalizar(nombre)
    for fila in conn.execute(
        "SELECT id, nombre FROM subcategorias WHERE categoria_id = ?", (categoria_id,)
    ):
        if normalizar(fila["nombre"]) == clave:
            return fila["id"]
    return None


def resolver_categoria(
    conn: sqlite3.Connection,
    nombre: str,
    creadas: List[str],
    cache: Optional[Dict[str, int]] = None,
) -> int:
    """Devuelve el id de la categoría, creándola si hace falta.

    `cache` es opcional y solo sirve para no repetir la consulta cuando se
    resuelven miles de renglones de golpe (lo usa la carga de histórico).
    """
    from backend.services.log import registrar_cambio

    clave = normalizar(nombre)
    if cache is not None and clave in cache:
        return cache[clave]

    existente = _buscar_categoria(conn, nombre)
    if existente is not None:
        if cache is not None:
            cache[clave] = existente
        return existente

    nombres = [f["nombre"] for f in conn.execute("SELECT nombre FROM categorias")]
    _validar_contra_parecidos(nombre, nombres, "catálogo")

    cursor = conn.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre.upper(),))
    creadas.append(f"categoría «{nombre.upper()}»")
    if cache is not None:
        cache[clave] = cursor.lastrowid

    # Registrar en log
    registrar_cambio(conn, "categorias", cursor.lastrowid, "INSERT", "nombre", None, nombre.upper())

    return cursor.lastrowid


def resolver_subcategoria(
    conn: sqlite3.Connection,
    categoria_id: int,
    nombre: str,
    creadas: List[str],
    cache: Optional[Dict[Tuple[int, str], int]] = None,
) -> int:
    """Devuelve el id de la subcategoría dentro de la categoría, creándola si
    hace falta. `cache` se indexa por (categoria_id, nombre normalizado)."""
    from backend.services.log import registrar_cambio

    clave = (categoria_id, normalizar(nombre))
    if cache is not None and clave in cache:
        return cache[clave]

    existente = _buscar_subcategoria(conn, categoria_id, nombre)
    if existente is not None:
        if cache is not None:
            cache[clave] = existente
        return existente

    nombres = [
        f["nombre"]
        for f in conn.execute(
            "SELECT nombre FROM subcategorias WHERE categoria_id = ?", (categoria_id,)
        )
    ]
    _validar_contra_parecidos(nombre, nombres, "subcategoría de esa categoría")

    cursor = conn.execute(
        "INSERT INTO subcategorias (categoria_id, nombre) VALUES (?, ?)",
        (categoria_id, nombre.upper()),
    )
    creadas.append(f"subcategoría «{nombre.upper()}»")
    if cache is not None:
        cache[clave] = cursor.lastrowid

    # Registrar en log
    registrar_cambio(conn, "subcategorias", cursor.lastrowid, "INSERT", "nombre", None, nombre.upper())

    return cursor.lastrowid


def registrar_producto(
    conn: sqlite3.Connection,
    articulo: Dict[str, Any],
    categoria_id: int,
    subcategoria_id: int,
    creados: List[str],
) -> None:
    from backend.services.log import registrar_cambio

    descripcion = str(articulo.get("articulo", "")).strip()
    if not descripcion:
        return

    clave = normalizar(descripcion)
    for fila in conn.execute("SELECT id, sku, descripcion FROM productos"):
        if normalizar(fila["descripcion"]) == clave:
            # Registrar cambios en log
            registrar_cambio(conn, "productos", fila["id"], "UPDATE", "categoria_id",
                             str(fila["categoria_id"]) if "categoria_id" in fila.keys() else None,
                             str(categoria_id))
            registrar_cambio(conn, "productos", fila["id"], "UPDATE", "subcategoria_id",
                             str(fila["subcategoria_id"]) if "subcategoria_id" in fila.keys() else None,
                             str(subcategoria_id))

            conn.execute(
                "UPDATE productos SET categoria_id = ?, subcategoria_id = ? WHERE id = ?",
                (categoria_id, subcategoria_id, fila["id"]),
            )
            conn.execute(
                "UPDATE productos SET sku = COALESCE(sku, ?) WHERE id = ?",
                (str(articulo.get("sku") or "").strip() or None, fila["id"]),
            )
            return

    cursor = conn.execute(
        "INSERT INTO productos (sku, descripcion, descripcion_normalizada, categoria_id, subcategoria_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            str(articulo.get("sku") or "").strip() or None,
            descripcion,
            normalizar(descripcion),
            categoria_id,
            subcategoria_id,
        ),
    )
    creados.append(f"producto «{descripcion}»")

    # Registrar en log
    registrar_cambio(conn, "productos", cursor.lastrowid, "INSERT", "descripcion", None, descripcion)


def normalizar_correcciones(
    ticket: Dict[str, Any], correcciones: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Devuelve una entrada por cada artículo del ticket: lo enviado si viene en el
    formulario y, si no, lo que el propio ticket ya tenía guardado.

    Así ningún renglón se escapa de la validación aunque el cliente mande una lista
    vacía, parcial o manipulada.
    """
    por_indice = {
        c["indice"]: c
        for c in correcciones
        if isinstance(c.get("indice"), int)
    }

    normalizadas = []
    for indice, articulo in enumerate(ticket["articulos"]):
        cambio = por_indice.get(indice, {})
        normalizadas.append(
            {
                "indice": indice,
                "categoria": (
                    cambio.get("categoria") or articulo.get("categoria") or ""
                ).strip(),
                "subcategoria": (
                    cambio.get("subcategoria") or articulo.get("subcategoria") or ""
                ).strip(),
                "registrar_producto": cambio.get(
                    "registrar_producto", articulo.get("registrar_producto", True)
                ),
            }
        )
    return normalizadas


def revisar_correcciones(
    ticket: Dict[str, Any], correcciones: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Renglones que quedarían sin categoría y subcategoría válidas.

    Se evalúa el ticket completo, no solo lo enviado. Mientras devuelva algo, el
    ticket no se puede confirmar ni guardar.
    """
    articulos = ticket["articulos"]
    incompletos: List[Dict[str, Any]] = []

    for indice, articulo in enumerate(articulos):
        cambio = next(
            (c for c in correcciones if c.get("indice") == indice), {}
        )
        categoria = (cambio.get("categoria") or "").strip()
        subcategoria = (cambio.get("subcategoria") or "").strip()

        falta_categoria = not categoria or categoria == SIN_CATEGORIA
        falta_subcategoria = not subcategoria or subcategoria == SIN_SUBCATEGORIA
        if not (falta_categoria or falta_subcategoria):
            continue

        incompletos.append(
            {
                "indice": indice,
                "articulo": articulo.get("articulo", ""),
                "falta_categoria": falta_categoria,
                "falta_subcategoria": falta_subcategoria,
            }
        )

    return incompletos


def aplicar_confirmacion(
    ticket: Dict[str, Any],
    correcciones: List[Dict[str, Any]],
    *,
    permitir_parcial: bool = False,
) -> Dict[str, Any]:
    """Aplica la revisión: valida cada valor contra el catálogo, crea los que falten
    (incluyendo el producto, si el usuario lo pidió) y devuelve el informe.

    Con ``permitir_parcial`` los renglones incompletos se saltan en vez de bloquear,
    para poder guardar el avance y seguir otro día.
    """
    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        informe = aplicar_en(
            conn, ticket, correcciones, permitir_parcial=permitir_parcial
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return informe


def aplicar_en(
    conn: sqlite3.Connection,
    ticket: Dict[str, Any],
    correcciones: List[Dict[str, Any]],
    *,
    permitir_parcial: bool = False,
) -> Dict[str, Any]:
    """Lo mismo que `aplicar_confirmacion`, pero dentro de una transacción ajena.

    No abre, confirma ni cierra la conexión: así el registro del ticket puede
    ir en la misma transacción que el catálogo y entra todo o no entra nada.
    """
    incompletos = revisar_correcciones(ticket, correcciones)
    if incompletos and not permitir_parcial:
        raise ErrorCatalogo(
            f"{len(incompletos)} renglón(es) sin categoría o subcategoría completa."
        )

    indices_incompletos = {i["indice"] for i in incompletos}
    articulos = ticket["articulos"]
    creados: List[str] = []
    rechazados: List[str] = []
    sin_categorizar = 0
    aplicados = 0

    for cambio in correcciones:
        indice = cambio.get("indice")
        if not isinstance(indice, int) or not 0 <= indice < len(articulos):
            continue

        # En guardado parcial lo que está a medias se deja como está.
        if indice in indices_incompletos:
            continue

        articulo = articulos[indice]
        categoria = (cambio.get("categoria") or "").strip()
        subcategoria = (cambio.get("subcategoria") or "").strip()

        if not categoria or categoria == SIN_CATEGORIA:
            articulo["categoria"] = SIN_CATEGORIA
            articulo["subcategoria"] = SIN_SUBCATEGORIA
            sin_categorizar += 1
            continue

        try:
            categoria_id = resolver_categoria(conn, categoria, creados)
            subcategoria_id = resolver_subcategoria(
                conn, categoria_id, subcategoria or SIN_SUBCATEGORIA, creados
            )
        except ErrorCatalogo as e:
            rechazados.append(f"{articulo.get('articulo', '')}: {e}")
            continue

        articulo["categoria"] = categoria.upper()
        articulo["subcategoria"] = subcategoria.upper() if subcategoria else SIN_SUBCATEGORIA
        articulo["match"] = True
        aplicados += 1

        if cambio.get("registrar_producto") and not articulo.get("en_catalogo"):
            registrar_producto(conn, articulo, categoria_id, subcategoria_id, creados)

    return {
        "creados": creados,
        "rechazados": rechazados,
        "sin_categorizar": sin_categorizar,
        "aplicados": aplicados,
        "pendientes": len(indices_incompletos),
    }


# ==========================================
# Editor de catálogo
# ==========================================

def listar_productos(
    texto: str = "", categoria: str = "", limite: int = 300
) -> List[Dict[str, Any]]:
    """Productos con su clasificación actual. La búsqueda ignora acentos y mayúsculas."""
    conn = get_db_connection()
    try:
        filas = conn.execute(
            """
            SELECT p.id, p.sku, p.descripcion,
                   c.nombre AS categoria, s.nombre AS subcategoria
            FROM productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            LEFT JOIN subcategorias s ON s.id = p.subcategoria_id
            ORDER BY p.descripcion
            """
        ).fetchall()
    finally:
        conn.close()

    productos = [dict(f) for f in filas]

    if categoria:
        clave = normalizar(categoria)
        productos = [p for p in productos if normalizar(p["categoria"] or "") == clave]

    if texto:
        clave = normalizar(texto)
        productos = [
            p
            for p in productos
            if clave in normalizar(p["descripcion"]) or clave in normalizar(p["sku"])
        ]

    return productos[:limite]


def _buscar_producto_id(conn: sqlite3.Connection, descripcion: str) -> Optional[int]:
    clave = normalizar(descripcion)
    for fila in conn.execute("SELECT id, descripcion FROM productos"):
        if normalizar(fila["descripcion"]) == clave:
            return fila["id"]
    return None


def reclasificar_producto(
    descripcion: str, categoria: str, subcategoria: str
) -> Dict[str, Any]:
    """Corrige de raíz la clasificación de un producto ya catalogado.

    También crea la categoría o subcategoría si no existen todavía.
    """
    from backend.services.log import registrar_cambio

    categoria = categoria.strip()
    subcategoria = subcategoria.strip()
    if not categoria or categoria == SIN_CATEGORIA:
        raise ErrorCatalogo("Elige una categoría antes de guardar.")

    creados: List[str] = []
    conn = get_db_connection()
    try:
        conn.execute("BEGIN")
        producto_id = _buscar_producto_id(conn, descripcion)
        if producto_id is None:
            raise ErrorCatalogo(f'"{descripcion}" no existe en el catálogo.')

        # Obtener valores anteriores para el log
        fila_ant = conn.execute(
            "SELECT categoria_id, subcategoria_id FROM productos WHERE id = ?",
            (producto_id,)
        ).fetchone()
        cat_ant = fila_ant["categoria_id"] if fila_ant else None
        sub_ant = fila_ant["subcategoria_id"] if fila_ant else None

        categoria_id = resolver_categoria(conn, categoria, creados)
        subcategoria_id = resolver_subcategoria(conn, categoria_id, subcategoria, creados)

        # Registrar cambios en log
        if cat_ant != categoria_id:
            registrar_cambio(conn, "productos", producto_id, "UPDATE", "categoria_id",
                             str(cat_ant) if cat_ant else None, str(categoria_id))
        if sub_ant != subcategoria_id:
            registrar_cambio(conn, "productos", producto_id, "UPDATE", "subcategoria_id",
                             str(sub_ant) if sub_ant else None, str(subcategoria_id))

        conn.execute(
            "UPDATE productos SET categoria_id = ?, subcategoria_id = ?, "
            "descripcion_normalizada = ? WHERE id = ?",
            (categoria_id, subcategoria_id, normalizar(descripcion), producto_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "id": producto_id,
        "categoria": categoria.upper(),
        "subcategoria": subcategoria.upper(),
        "creados": creados,
    }
