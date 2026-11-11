"""Diseño: tema claro/oscuro y gráficas.

Los colores viven en variables de base.css; el tema oscuro solo las redefine.
Si una hoja vuelve a fijar un fondo a mano, en tema oscuro queda una tarjeta
blanca con texto claro: estas pruebas lo detectan.
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CSS = RAIZ / "frontend" / "static" / "css"
JS = RAIZ / "frontend" / "static" / "js"
PLANTILLAS = RAIZ / "frontend" / "templates"


def test_base_ofrece_cambio_de_tema(bd_temporal, iniciar_sesion):
    html = iniciar_sesion("consulta").get("/").text
    assert 'id="cambiar-tema"' in html
    assert "/static/js/tema.js" in html
    # El tema guardado se aplica antes de pintar, en el <head>.
    cabeza = html.split("</head>", 1)[0]
    assert 'localStorage.getItem("tema")' in cabeza


def test_tema_oscuro_definido():
    base = (CSS / "base.css").read_text(encoding="utf-8")
    assert ':root[data-tema="oscuro"]' in base
    # Al imprimir se vuelve a los colores claros.
    assert re.search(r'@media print\s*{\s*:root\[data-tema="oscuro"\]', base)


def test_barras_con_esquinas_discretas():
    panel = (JS / "panel.js").read_text(encoding="utf-8")
    assert re.search(r"const RADIO_BARRA = 4;", panel)
    radios = re.findall(r"borderRadius:\s*([^,\n]+)", panel)
    assert radios and all(r.strip() == "RADIO_BARRA" for r in radios), radios


def test_graficas_toman_colores_del_tema():
    panel = (JS / "panel.js").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{6}\b", panel.replace("#0f172a", "").replace("#f8fafc", "").replace("#e2e8f0", "")), \
        "panel.js no debe fijar colores de serie: deben salir de las variables --grafica-*"
    assert "tema-cambiado" in panel


HOJAS = sorted(p for p in CSS.glob("*.css") if p.name != "base.css")


@pytest.mark.parametrize("hoja", HOJAS, ids=lambda p: p.name)
def test_hojas_sin_fondos_fijos(hoja):
    fijos = [
        linea.strip()
        for linea in hoja.read_text(encoding="utf-8").splitlines()
        if re.search(r"background(-color)?\s*:\s*[^;]*(#[0-9a-fA-F]{3,8}\b|\bwhite\b)", linea)
    ]
    assert not fijos, f"{hoja.name} fija fondos que no cambian con el tema: {fijos}"


@pytest.mark.parametrize("plantilla", ["reportes.html", "reporte.html", "log.html"])
def test_plantillas_sin_fondos_fijos_fuera_de_impresion(plantilla):
    texto = (PLANTILLAS / plantilla).read_text(encoding="utf-8").split("@media print", 1)[0]
    fijos = re.findall(r"background\s*:\s*(#[0-9a-fA-F]{3,6}\b|white)", texto)
    assert not fijos, f"{plantilla} fija fondos: {fijos}"
