"""Nada se actualiza solo: todas las dependencias tienen versión fija.

Las actualizaciones se hacen a mano (ver "Actualizar dependencias" en el
README). Estas pruebas fallan si una versión queda abierta.
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
FIJA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[0-9][^\s;]*$")


def _paquetes(archivo: Path):
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if linea and not linea.startswith("-r "):
            yield linea


@pytest.mark.parametrize("archivo", ["requirements.txt", "requirements-dev.txt"])
def test_requirements_con_version_exacta(archivo):
    abiertas = [p for p in _paquetes(RAIZ / archivo) if not FIJA.match(p)]
    assert not abiertas, f"{archivo} tiene versiones sin fijar con ==: {abiertas}"


def test_imagen_base_fijada_por_digest():
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    bases = re.findall(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE)
    assert bases, "El Dockerfile no tiene FROM"
    for base in bases:
        assert re.search(r":\d+\.\d+\.\d+[^@]*@sha256:[0-9a-f]{64}$", base), (
            f"La imagen base {base} debe llevar versión exacta y @sha256:<digest>"
        )


def test_pip_en_docker_no_instala_dependencias_por_su_cuenta():
    dockerfile = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
    instalaciones = re.findall(r"pip install[^\n]*", dockerfile)
    assert instalaciones
    for linea in instalaciones:
        assert "--no-deps" in linea and "-r requirements.txt" in linea, linea
    assert "pip check" in dockerfile
