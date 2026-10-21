"""Tests para el servicio de panel."""

import pytest
from backend.services import panel


def test_normalizar_todo():
    assert panel.normalizar(None) == "todo"
    assert panel.normalizar("") == "todo"
    assert panel.normalizar("invalido") == "todo"


def test_normalizar_anio():
    assert panel.normalizar("2026") == "2026"


def test_normalizar_mes():
    assert panel.normalizar("2026-09") == "2026-09"


def test_es_anio():
    assert panel.es_anio("2026") is True
    assert panel.es_anio("2026-09") is False
    assert panel.es_anio(None) is False


def test_es_mes():
    assert panel.es_mes("2026-09") is True
    assert panel.es_mes("2026") is False
    # "2026-13" tiene formato válido de mes, aunque el mes 13 no exista.
    # La validación del rango se hace en normalizar(), no en es_mes().
    assert panel.es_mes("2026-13") is True
    assert panel.normalizar("2026-13") == "todo"


def test_periodo_info_todo():
    info = panel.periodo_info(None)
    assert info["valor"] == "todo"
    assert info["granularidad"] == "mes"


def test_periodo_info_mes():
    info = panel.periodo_info("2026-09")
    assert info["granularidad"] == "dia"
    assert "Septiembre" in info["etiqueta"]


def test_porcentaje():
    assert panel._pct(50, 200) == 25.0
    assert panel._pct(0, 0) == 0.0
