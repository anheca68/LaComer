#!/usr/bin/env python3
"""Script para corregir la normalización de descripciones en productos.

Este script actualiza la columna descripcion_normalizada usando la función
normalizar() correcta que elimina acentos y normaliza espacios.
"""

import sys
from pathlib import Path

# Agregar el directorio raíz al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database import get_db_connection
from backend.services.catalogo import normalizar


def main():
    conn = get_db_connection()
    try:
        # Obtener todos los productos
        productos = conn.execute(
            "SELECT id, descripcion FROM productos"
        ).fetchall()

        print(f"Corrigiendo {len(productos)} productos...")

        for p in productos:
            descripcion_norm = normalizar(p["descripcion"])
            conn.execute(
                "UPDATE productos SET descripcion_normalizada = ? WHERE id = ?",
                (descripcion_norm, p["id"])
            )

        conn.commit()
        print("¡Normalización corregida exitosamente!")

        # Verificar algunos ejemplos
        print("\nEjemplos de normalización:")
        ejemplos = conn.execute(
            "SELECT descripcion, descripcion_normalizada FROM productos LIMIT 5"
        ).fetchall()
        for e in ejemplos:
            print(f"  {e[0]} -> {e[1]}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
