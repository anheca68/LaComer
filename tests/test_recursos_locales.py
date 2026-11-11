"""La app tiene que funcionar sin internet: nada de scripts ni estilos externos."""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PLANTILLAS = sorted(
    list((RAIZ / "frontend" / "templates").glob("*.html"))
    + list((RAIZ / "carga_inicial" / "templates").glob("*.html"))
)

# src="http..." o href="http..." en <script> o <link>, también con //cdn...
EXTERNO = re.compile(
    r"<(?:script|link)\b[^>]*\b(?:src|href)\s*=\s*[\"'](?:https?:)?//", re.IGNORECASE
)


@pytest.mark.parametrize("plantilla", PLANTILLAS, ids=lambda p: p.name)
def test_plantilla_sin_recursos_externos(plantilla):
    externos = [
        linea.strip()
        for linea in plantilla.read_text(encoding="utf-8").splitlines()
        if EXTERNO.search(linea)
    ]
    assert not externos, f"{plantilla.name} carga recursos de internet: {externos}"


def test_articulo_usa_chart_local(bd_temporal, iniciar_sesion):
    cliente = iniciar_sesion("consulta")
    html = cliente.get("/articulo").text
    assert 'src="/static/js/chart.umd.min.js"' in html
    assert cliente.get("/static/js/chart.umd.min.js").status_code == 200
