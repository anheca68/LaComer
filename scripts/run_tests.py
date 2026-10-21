#!/usr/bin/env python3
"""Ejecuta todos los tests del proyecto."""

import subprocess
import sys


def main():
    resultado = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd="/Users/anheca/Desktop/cursos/py/LaComer"
    )
    return resultado.returncode


if __name__ == "__main__":
    sys.exit(main())
