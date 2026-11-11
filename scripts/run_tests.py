#!/usr/bin/env python3
"""Ejecuta todos los tests del proyecto, desde cualquier carpeta."""

import subprocess
import sys
from pathlib import Path

# Raíz del repositorio: la carpeta que contiene a scripts/.
RAIZ = Path(__file__).resolve().parents[1]


def main():
    resultado = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=RAIZ,
    )
    return resultado.returncode


if __name__ == "__main__":
    sys.exit(main())
