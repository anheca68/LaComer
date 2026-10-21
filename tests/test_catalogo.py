"""Tests para el servicio de catálogo."""

import pytest
from backend.services.catalogo import (
    normalizar,
    _similitud,
    SIN_CATEGORIA,
    SIN_SUBCATEGORIA,
)


def test_normalizar_mayusculas():
    assert normalizar("café") == "CAFE"


def test_normalizar_espacios():
    assert normalizar("  hello   world  ") == "HELLO WORLD"


def test_normalizar_acentos():
    assert normalizar("áéíóú") == "AEIOU"


def test_similitud_identicos():
    assert _similitud("Cafe", "cafe") == 1.0


def test_similitud_diferentes():
    assert _similitud("Cafe", "Refresco") < 0.5


def test_similitud_parecidos():
    assert _similitud("Cafe con leche", "Cafe con leche") == 1.0
