# Mejoras Implementadas - Octubre 2026

## 1. Seguridad

### Validación de ticket_id en rutas dinámicas
- **Archivo**: `backend/routers/tickets.py`
- **Cambio**: Agregada función `_validar_ticket_id()` que valida que el ID del ticket solo contenga caracteres alfanuméricos, guiones y guiones bajos
- **Rutas protegidas**: `/descargar-csv/{ticket_id}` y `/reporte/{ticket_id}`
- **Beneficio**: Previene ataques de path traversal

## 2. Panel de Control - Nuevos KPIs

### Tendencia de gasto
- **Archivo**: `backend/services/panel.py`
- **Cambio**: Nuevo KPI "Tendencia 3 meses" que compara los últimos 3 meses contra los 3 anteriores
- **Beneficio**: Permite ver si el gasto está subiendo o bajando

### Día de mayor gasto
- **Archivo**: `backend/services/panel.py`
- **Cambio**: Nuevo KPI "Día de mayor gasto" que muestra qué día de la semana tiene más gasto
- **Beneficio**: Ayuda a identificar patrones de compra

### Archivos actualizados
- `backend/services/panel.py` - Nuevos cálculos en `indicadores()`
- `frontend/templates/panel.html` - Nuevas tarjetas KPI

## 3. Consulta por Artículo - Gráfico de Evolución

### Nuevo endpoint AJAX
- **Archivo**: `backend/routers/consultas.py`
- **Ruta**: `/api/articulos/precios/{articulo_id}`
- **Beneficio**: Alimenta el gráfico de evolución de precios

### Nueva función de servicio
- **Archivo**: `backend/services/consultas.py`
- **Función**: `precios_articulo_serie()`
- **Beneficio**: Obtiene serie mensual de precios (min/prom/max) para Chart.js

### Interfaz de usuario
- **Archivo**: `frontend/templates/articulo.html`
- **Cambio**: Agregado gráfico de línea con evolución de precios usando Chart.js
- **Beneficio**: Visualización clara de cómo varían los precios mes a mes

## 4. Tests Unitarios

### Estructura creada
```
tests/
├── __init__.py
├── test_panel.py      # 8 tests
├── test_catalogo.py   # 6 tests
└── test_consultas.py  # 4 tests
```

### Configuración
- `pytest.ini` - Configuración de pytest
- `scripts/run_tests.py` - Script para ejecutar todos los tests

### Ejecución
```bash
source venv/bin/activate
python -m pytest tests/ -v
```

**Resultado**: 18/18 tests pasan

## 5. Archivos Modificados

| Archivo | Cambio |
|---------|--------|
| `backend/routers/tickets.py` | Validación de ticket_id |
| `backend/routers/consultas.py` | Nuevo endpoint de precios |
| `backend/routers/panel.py` | Optimización de datos |
| `backend/services/panel.py` | Nuevos KPIs |
| `backend/services/consultas.py` | Nueva función de precios |
| `frontend/templates/panel.html` | Nuevas tarjetas KPI |
| `frontend/templates/articulo.html` | Gráfico de precios |

## 6. Pendientes de Mejoras Anteriores

### mejoras_01.md
- [ ] Categorización manual con creación de nuevas categorías/subcategorías
- [ ] Validación de mayúsculas en categorías

### mejoras_02.md
- [x] Estructura Backend/Frontend (ya existía)
- [x] Consulta por artículo con coincidencia parcial (implementado)
- [x] Consulta por número de ticket (implementado)
