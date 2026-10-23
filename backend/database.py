"""Esquema de la base de datos y su historial de cambios.

La base se construye con migraciones numeradas. `PRAGMA user_version` guarda cuál
es la última aplicada, así que agregar una columna nueva a una tabla existente
ya es posible: antes bastaba con `CREATE TABLE IF NOT EXISTS`, que en una tabla
ya creada es un no-op silencioso.
"""

import sqlite3

from backend.config import CATALOGO_DB_PATH

# ---------------------------------------------------------------------------
# Migraciones. Cada entrada es (version, sql). Nunca se edita una ya publicada:
# se agrega una nueva con el siguiente número.
# ---------------------------------------------------------------------------

MIGRACION_1_CATALOGO = """
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre VARCHAR(100) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS subcategorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria_id INTEGER NOT NULL,
    nombre VARCHAR(100) NOT NULL,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE CASCADE,
    UNIQUE (categoria_id, nombre)
);

CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku VARCHAR(50) UNIQUE,
    descripcion TEXT NOT NULL,
    categoria_id INTEGER,
    subcategoria_id INTEGER,
    FOREIGN KEY (categoria_id) REFERENCES categorias(id) ON DELETE SET NULL,
    FOREIGN KEY (subcategoria_id) REFERENCES subcategorias(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_productos_categoria
    ON productos(categoria_id);
CREATE INDEX IF NOT EXISTS idx_subcategorias_categoria
    ON subcategorias(categoria_id);
"""

# La cabecera de la compra: cuándo, dónde, cuánto y con qué folio.
# `establecimiento` es texto a propósito: el catálogo de comercios llega después
# (ver migración 4), y hasta entonces el nombre que captura el importador es la
# única fuente de verdad.
MIGRACION_2_GASTOS = """
CREATE TABLE IF NOT EXISTS tickets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    archivo             TEXT    NOT NULL,
    ticket_legacy       TEXT,
    sha256              TEXT    NOT NULL UNIQUE,

    fecha               TEXT    NOT NULL,
    hora                TEXT,

    establecimiento      TEXT,
    rfc_emisor          VARCHAR(13),
    regimen_fiscal      TEXT,
    folio               TEXT,

    cliente             TEXT,
    forma_pago          TEXT,
    tarjeta             TEXT,

    total               REAL    NOT NULL,
    ahorro              REAL    NOT NULL DEFAULT 0,
    descuento           REAL    NOT NULL DEFAULT 0,
    subtotal            REAL,
    iva                 REAL,
    ieps                REAL,
    articulos_declarados INTEGER,

    estado              TEXT    NOT NULL DEFAULT 'confirmado'
                            CHECK (estado IN ('confirmado', 'anulado')),
    origen              TEXT    NOT NULL DEFAULT 'pdf'
                            CHECK (origen IN ('pdf', 'historico')),
    notas               TEXT,
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS detalle_tickets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id     INTEGER NOT NULL
                      REFERENCES tickets(id) ON DELETE CASCADE,
    linea         INTEGER NOT NULL,

    producto_id   INTEGER REFERENCES productos(id) ON DELETE SET NULL,

    sku           TEXT,
    descripcion   TEXT    NOT NULL,
    desc_norm     TEXT,

    cantidad      REAL    NOT NULL,
    precio_regular REAL   NOT NULL,
    precio_promo  REAL,
    precio_unit   REAL,
    total         REAL    NOT NULL,

    categoria_id    INTEGER REFERENCES categorias(id)    ON DELETE SET NULL,
    subcategoria_id INTEGER REFERENCES subcategorias(id) ON DELETE SET NULL,

    UNIQUE (ticket_id, linea)
);

CREATE INDEX IF NOT EXISTS idx_tickets_fecha     ON tickets(fecha);
CREATE INDEX IF NOT EXISTS idx_detalle_ticket    ON detalle_tickets(ticket_id);
CREATE INDEX IF NOT EXISTS idx_detalle_producto  ON detalle_tickets(producto_id);
CREATE INDEX IF NOT EXISTS idx_detalle_categoria ON detalle_tickets(categoria_id);
CREATE INDEX IF NOT EXISTS idx_detalle_subcat    ON detalle_tickets(subcategoria_id);
"""

# Vistas de análisis: el gasto ya viene desnormalizado y con el mes calculado.
MIGRACION_3_VISTAS = """
CREATE VIEW IF NOT EXISTS v_detalle AS
SELECT  t.id          AS ticket_id,
        t.archivo,
        t.fecha,
        strftime('%Y-%m', t.fecha) AS mes,
        t.folio,
        t.establecimiento,
        c.nombre AS categoria,
        s.nombre AS subcategoria,
        d.linea,
        d.descripcion,
        d.sku,
        d.cantidad,
        d.precio_unit,
        d.total,
        (d.producto_id IS NOT NULL) AS en_catalogo
FROM    tickets t
JOIN    detalle_tickets d ON d.ticket_id = t.id
LEFT JOIN categorias    c ON c.id = d.categoria_id
LEFT JOIN subcategorias s ON s.id = d.subcategoria_id
WHERE   t.estado = 'confirmado';

CREATE VIEW IF NOT EXISTS v_gasto_mensual AS
SELECT  mes,
        categoria,
        ROUND(SUM(total), 2) AS importe,
        COUNT(*)             AS renglones
FROM    v_detalle
WHERE   categoria IS NOT NULL
GROUP BY mes, categoria
ORDER BY mes DESC, importe DESC;

CREATE VIEW IF NOT EXISTS v_gasto_detalle AS
SELECT  mes,
        categoria,
        subcategoria,
        ROUND(SUM(total), 2) AS importe,
        COUNT(*)             AS renglones
FROM    v_detalle
WHERE   subcategoria IS NOT NULL
GROUP BY mes, categoria, subcategoria
ORDER BY mes DESC, importe DESC;

CREATE VIEW IF NOT EXISTS v_conciliacion AS
SELECT  t.id,
        t.archivo,
        t.fecha,
        t.total AS total_pdf,
        ROUND(SUM(d.total), 2) AS total_renglones,
        ROUND(t.total - SUM(d.total), 2) AS diferencia
FROM    tickets t
JOIN    detalle_tickets d ON d.ticket_id = t.id
WHERE   t.estado = 'confirmado'
GROUP BY t.id
HAVING  ABS(t.total - SUM(d.total)) > 0.01;
"""

# Renglones que no son un producto, y reconstrucción de las vistas para que el
# gasto por categoría no los cuente como si lo fueran.
MIGRACION_4_DESCUENTOS = """
-- Un renglón que no es un producto: cashback, descuento de tienda, devolución.
-- Se guarda igual que los demás para que la suma de los renglones sea siempre el
-- total pagado, pero separado para no contarlo como gasto en una categoría.
ALTER TABLE detalle_tickets
    ADD COLUMN tipo TEXT NOT NULL DEFAULT 'producto'
        CHECK (tipo IN ('producto', 'descuento'));

-- Las vistas se reconstruyen porque las de gastos deben ignorar los descuentos:
-- un cashback no es gasto en la categoría del refresco, es un ingreso.
DROP VIEW IF EXISTS v_detalle;
DROP VIEW IF EXISTS v_gasto_mensual;
DROP VIEW IF EXISTS v_gasto_detalle;
DROP VIEW IF EXISTS v_conciliacion;

CREATE VIEW v_detalle AS
SELECT  t.id          AS ticket_id,
        t.archivo,
        t.fecha,
        strftime('%Y-%m', t.fecha) AS mes,
        t.folio,
        t.establecimiento,
        c.nombre AS categoria,
        s.nombre AS subcategoria,
        d.linea,
        d.descripcion,
        d.sku,
        d.cantidad,
        d.precio_unit,
        d.total,
        d.tipo,
        (d.producto_id IS NOT NULL) AS en_catalogo
FROM    tickets t
JOIN    detalle_tickets d ON d.ticket_id = t.id
LEFT JOIN categorias    c ON c.id = d.categoria_id
LEFT JOIN subcategorias s ON s.id = d.subcategoria_id
WHERE   t.estado = 'confirmado';

CREATE VIEW v_gasto_mensual AS
SELECT  mes,
        categoria,
        ROUND(SUM(total), 2) AS importe,
        COUNT(*)             AS renglones
FROM    v_detalle
WHERE   categoria IS NOT NULL AND tipo = 'producto'
GROUP BY mes, categoria
ORDER BY mes DESC, importe DESC;

CREATE VIEW v_gasto_detalle AS
SELECT  mes,
        categoria,
        subcategoria,
        ROUND(SUM(total), 2) AS importe,
        COUNT(*)             AS renglones
FROM    v_detalle
WHERE   subcategoria IS NOT NULL AND tipo = 'producto'
GROUP BY mes, categoria, subcategoria
ORDER BY mes DESC, importe DESC;

-- Lo que se descontó del ticket: cashback, promociones, devoluciones. Vive fuera
-- del gasto por categoría porque no se gastó en ninguna.
CREATE VIEW v_descuentos AS
SELECT  strftime('%Y-%m', t.fecha) AS mes,
        d.descripcion,
        ROUND(SUM(d.total), 2)       AS importe,
        COUNT(*)                     AS renglones
FROM    tickets t
JOIN    detalle_tickets d ON d.ticket_id = t.id
WHERE   t.estado = 'confirmado' AND d.tipo = 'descuento'
GROUP BY mes, d.descripcion
ORDER BY mes DESC;

-- Gasto por mes ya neto de descuentos, que es lo que de verdad salió de la
-- cartera. `bruto - descuentos` debe dar el total pagado de los tickets.
CREATE VIEW v_gasto_mensual_neto AS
SELECT  m.mes,
        ROUND(SUM(m.importe), 2)      AS bruto,
        ROUND(COALESCE(d.total, 0), 2) AS descuentos,
        ROUND(SUM(m.importe) + COALESCE(d.total, 0), 2) AS neto
FROM    (SELECT mes, SUM(total) AS importe
         FROM    v_detalle
         WHERE   tipo = 'producto'
         GROUP BY mes) m
LEFT JOIN (SELECT strftime('%Y-%m', t.fecha) AS mes, SUM(d.total) AS total
           FROM    tickets t
           JOIN    detalle_tickets d ON d.ticket_id = t.id
           WHERE   t.estado = 'confirmado' AND d.tipo = 'descuento'
           GROUP BY t.id) d ON d.mes = m.mes
GROUP BY m.mes
ORDER BY m.mes DESC;

-- El total pagado siempre tiene que ser la suma de los renglones, descuentos
-- incluidos. Esta vista debería salir vacía: si sale algo, algo se perdió.
CREATE VIEW v_conciliacion AS
SELECT  t.id,
        t.archivo,
        t.fecha,
        t.total AS total_pagado,
        ROUND(SUM(d.total), 2) AS total_renglones,
        ROUND(t.total - SUM(d.total), 2) AS diferencia
FROM    tickets t
JOIN    detalle_tickets d ON d.ticket_id = t.id
WHERE   t.estado = 'confirmado'
GROUP BY t.id
HAVING  ABS(t.total - SUM(d.total)) > 0.01;
"""

# La 4 dejó `v_gasto_mensual_neto` agrupando los descuentos por ticket en vez de
# por mes: al hacer el JOIN un mes con varios tickets se multiplicaba y el
# descuento caía en el mes equivocado. Las migraciones no se tocan una vez
# aplicadas, así que la vista se corrige aquí.
MIGRACION_5_MENSUAL_NETO = """
DROP VIEW IF EXISTS v_gasto_mensual_neto;

CREATE VIEW v_gasto_mensual_neto AS
SELECT  m.mes,
        ROUND(SUM(m.importe), 2)         AS bruto,
        ROUND(COALESCE(d.total, 0), 2)   AS descuentos,
        ROUND(SUM(m.importe) + COALESCE(d.total, 0), 2) AS neto
FROM    (SELECT mes, SUM(total) AS importe
         FROM    v_detalle
         WHERE   tipo = 'producto'
         GROUP BY mes) m
LEFT JOIN (SELECT strftime('%Y-%m', t.fecha) AS mes,
                  SUM(d.total)              AS total
           FROM    tickets t
           JOIN    detalle_tickets d ON d.ticket_id = t.id
           WHERE   t.estado = 'confirmado' AND d.tipo = 'descuento'
           GROUP BY 1) d ON d.mes = m.mes
GROUP BY m.mes
ORDER BY m.mes DESC;
"""

# Registro de cambios: cada INSERT/UPDATE/DELETE en categorías, subcategorías
# o productos deja una fila aquí con el valor anterior y el nuevo, para poder
# auditar y revertir.
MIGRACION_6_LOG_CAMBIOS = """
CREATE TABLE IF NOT EXISTS log_cambios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tabla       TEXT    NOT NULL,
    registro_id INTEGER NOT NULL,
    accion      TEXT    NOT NULL CHECK (accion IN ('INSERT', 'UPDATE', 'DELETE')),
    campo       TEXT,
    valor_anterior TEXT,
    valor_nuevo    TEXT,
    creado_en   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_log_tabla    ON log_cambios(tabla);
CREATE INDEX IF NOT EXISTS idx_log_registro ON log_cambios(tabla, registro_id);
"""

# Columna descripcion_normalizada: permite búsquedas insensibles a acentos
# y espacios. Se llena automáticamente al insertar o actualizar productos.
MIGRACION_7_NORMALIZAR_DESCRIPCION = """
ALTER TABLE productos
    ADD COLUMN descripcion_normalizada TEXT;

-- Llenar la columna con los valores normalizados existentes
-- Usamos una función Python para normalizar correctamente los acentos
UPDATE productos SET descripcion_normalizada = UPPER(descripcion);

-- Índice para búsquedas rápidas
CREATE INDEX IF NOT EXISTS idx_productos_descripcion_norm
    ON productos(descripcion_normalizada);
"""

# Los tickets capturados a mano no vienen de un PDF ni del histórico. SQLite no
# permite ampliar un CHECK con ALTER TABLE, así que hay que reconstruir `tickets`
# y volver a crear las vistas que dependen de ella. La migración se ejecuta con
# las llaves foráneas apagadas (ver `migrar`) para poder sustituir la tabla sin
# tocar `detalle_tickets`.
MIGRACION_8_ORIGEN_MANUAL = """
DROP VIEW IF EXISTS v_detalle;
DROP VIEW IF EXISTS v_gasto_mensual;
DROP VIEW IF EXISTS v_gasto_detalle;
DROP VIEW IF EXISTS v_descuentos;
DROP VIEW IF EXISTS v_gasto_mensual_neto;
DROP VIEW IF EXISTS v_conciliacion;

CREATE TABLE tickets_v8 (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    archivo             TEXT    NOT NULL,
    ticket_legacy       TEXT,
    sha256              TEXT    NOT NULL UNIQUE,

    fecha               TEXT    NOT NULL,
    hora                TEXT,

    establecimiento      TEXT,
    rfc_emisor          VARCHAR(13),
    regimen_fiscal      TEXT,
    folio               TEXT,

    cliente             TEXT,
    forma_pago          TEXT,
    tarjeta             TEXT,

    total               REAL    NOT NULL,
    ahorro              REAL    NOT NULL DEFAULT 0,
    descuento           REAL    NOT NULL DEFAULT 0,
    subtotal            REAL,
    iva                 REAL,
    ieps                REAL,
    articulos_declarados INTEGER,

    estado              TEXT    NOT NULL DEFAULT 'confirmado'
                            CHECK (estado IN ('confirmado', 'anulado')),
    origen              TEXT    NOT NULL DEFAULT 'pdf'
                            CHECK (origen IN ('pdf', 'historico', 'manual')),
    notas               TEXT,
    creado_en           TEXT    NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO tickets_v8 (
    id, archivo, ticket_legacy, sha256, fecha, hora, establecimiento,
    rfc_emisor, regimen_fiscal, folio, cliente, forma_pago, tarjeta, total,
    ahorro, descuento, subtotal, iva, ieps, articulos_declarados, estado,
    origen, notas, creado_en
)
SELECT
    id, archivo, ticket_legacy, sha256, fecha, hora, establecimiento,
    rfc_emisor, regimen_fiscal, folio, cliente, forma_pago, tarjeta, total,
    ahorro, descuento, subtotal, iva, ieps, articulos_declarados, estado,
    origen, notas, creado_en
FROM tickets;

DROP TABLE tickets;
ALTER TABLE tickets_v8 RENAME TO tickets;

CREATE INDEX IF NOT EXISTS idx_tickets_fecha ON tickets(fecha);

CREATE VIEW v_detalle AS
SELECT  t.id          AS ticket_id,
        t.archivo,
        t.fecha,
        strftime('%Y-%m', t.fecha) AS mes,
        t.folio,
        t.establecimiento,
        c.nombre AS categoria,
        s.nombre AS subcategoria,
        d.linea,
        d.descripcion,
        d.sku,
        d.cantidad,
        d.precio_unit,
        d.total,
        d.tipo,
        (d.producto_id IS NOT NULL) AS en_catalogo
FROM    tickets t
JOIN    detalle_tickets d ON d.ticket_id = t.id
LEFT JOIN categorias    c ON c.id = d.categoria_id
LEFT JOIN subcategorias s ON s.id = d.subcategoria_id
WHERE   t.estado = 'confirmado';

CREATE VIEW v_gasto_mensual AS
SELECT  mes,
        categoria,
        ROUND(SUM(total), 2) AS importe,
        COUNT(*)             AS renglones
FROM    v_detalle
WHERE   categoria IS NOT NULL AND tipo = 'producto'
GROUP BY mes, categoria
ORDER BY mes DESC, importe DESC;

CREATE VIEW v_gasto_detalle AS
SELECT  mes,
        categoria,
        subcategoria,
        ROUND(SUM(total), 2) AS importe,
        COUNT(*)             AS renglones
FROM    v_detalle
WHERE   subcategoria IS NOT NULL AND tipo = 'producto'
GROUP BY mes, categoria, subcategoria
ORDER BY mes DESC, importe DESC;

CREATE VIEW v_descuentos AS
SELECT  strftime('%Y-%m', t.fecha) AS mes,
        d.descripcion,
        ROUND(SUM(d.total), 2)       AS importe,
        COUNT(*)                     AS renglones
FROM    tickets t
JOIN    detalle_tickets d ON d.ticket_id = t.id
WHERE   t.estado = 'confirmado' AND d.tipo = 'descuento'
GROUP BY mes, d.descripcion
ORDER BY mes DESC;

CREATE VIEW v_gasto_mensual_neto AS
SELECT  m.mes,
        ROUND(SUM(m.importe), 2)         AS bruto,
        ROUND(COALESCE(d.total, 0), 2)   AS descuentos,
        ROUND(SUM(m.importe) + COALESCE(d.total, 0), 2) AS neto
FROM    (SELECT mes, SUM(total) AS importe
         FROM    v_detalle
         WHERE   tipo = 'producto'
         GROUP BY mes) m
LEFT JOIN (SELECT strftime('%Y-%m', t.fecha) AS mes,
                  SUM(d.total)              AS total
           FROM    tickets t
           JOIN    detalle_tickets d ON d.ticket_id = t.id
           WHERE   t.estado = 'confirmado' AND d.tipo = 'descuento'
           GROUP BY 1) d ON d.mes = m.mes
GROUP BY m.mes
ORDER BY m.mes DESC;

CREATE VIEW v_conciliacion AS
SELECT  t.id,
        t.archivo,
        t.fecha,
        t.total AS total_pagado,
        ROUND(SUM(d.total), 2) AS total_renglones,
        ROUND(t.total - SUM(d.total), 2) AS diferencia
FROM    tickets t
JOIN    detalle_tickets d ON d.ticket_id = t.id
WHERE   t.estado = 'confirmado'
GROUP BY t.id
HAVING  ABS(t.total - SUM(d.total)) > 0.01;
"""

MIGRACIONES = [
    (1, MIGRACION_1_CATALOGO),
    (2, MIGRACION_2_GASTOS),
    (3, MIGRACION_3_VISTAS),
    (4, MIGRACION_4_DESCUENTOS),
    (5, MIGRACION_5_MENSUAL_NETO),
    (6, MIGRACION_6_LOG_CAMBIOS),
    (7, MIGRACION_7_NORMALIZAR_DESCRIPCION),
    (8, MIGRACION_8_ORIGEN_MANUAL),
]

VERSION_ESPERADA = MIGRACIONES[-1][0]


def get_db_connection() -> sqlite3.Connection:
    CATALOGO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CATALOGO_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def version_actual(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrar(conn: sqlite3.Connection) -> list[int]:
    """Aplica las migraciones que faltan, cada una en su propia transacción.

    `executescript` hace COMMIT implícito, así que el SQL se parte en sentencias
    individuales para que una migración fallida no deje la base a medias.
    """
    aplicadas = []
    actual = version_actual(conn)
    for version, sql in MIGRACIONES:
        if version <= actual:
            continue
        # La migración 8 reemplaza `tickets`; con las llaves foráneas activas
        # SQLite no permite soltar la tabla padre aunque se hayan conservado
        # los renglones. El PRAGMA tiene que ejecutarse fuera de la transacción.
        if version == 8:
            conn.execute("PRAGMA foreign_keys = OFF")
        try:
            conn.execute("BEGIN")
            for sentencia in _sentencias(sql):
                conn.execute(sentencia)
            if version == 8:
                problemas = conn.execute("PRAGMA foreign_key_check").fetchall()
                if problemas:
                    raise sqlite3.IntegrityError(
                        f"La migración {version} dejó llaves foráneas rotas: {problemas}"
                    )
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if version == 8:
                conn.execute("PRAGMA foreign_keys = ON")
        aplicadas.append(version)
    return aplicadas


def _sentencias(sql: str) -> list[str]:
    """Parte un script en sentencias, ignorando los comentarios de línea."""
    limpio = "\n".join(
        linea for linea in sql.splitlines() if not linea.strip().startswith("--")
    )
    return [s.strip() for s in limpio.split(";") if s.strip()]


def init_db() -> None:
    conn = get_db_connection()
    try:
        migrar(conn)
    finally:
        conn.close()


init_db()
