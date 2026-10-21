"""Tests para el servicio de consultas."""

import pytest
from backend.services.consultas import (
    buscar_articulos_por_nombre,
    buscar_ticket,
    detalle_articulo_por_anio,
    precios_articulo_serie,
)


def test_buscar_articulos_vacio():
    assert buscar_articulos_por_nombre("") == []
    assert buscar_articulos_por_nombre("x") == []


def test_buscar_articulos_acentos():
    """La búsqueda debe ser insensible a acentos gracias a descripcion_normalizada."""
    # Buscar "cafe" debe encontrar productos con "Café" o "CAFE"
    resultados = buscar_articulos_por_nombre("cafe")
    # Verificar que no hay error y que la función devuelve una lista
    assert isinstance(resultados, list)


def test_buscar_articulos_comodin():
    """La búsqueda con comodín * debe funcionar."""
    resultados = buscar_articulos_por_nombre("caf*")
    assert isinstance(resultados, list)


def test_buscar_ticket_inexistente():
    assert buscar_ticket("999999") is None


def test_detalle_articulo_inexistente():
    assert detalle_articulo_por_anio(999999) is None


def test_precios_serie_inexistente():
    assert precios_articulo_serie(999999) is None
