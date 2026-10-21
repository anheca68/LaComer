# Mejoras Implementadas - Octubre 2026

## 1. Tickets 

**Seccion Tickets Procesados**
- [x] Agregada funcionalidad para ocultar/mostrar el detalle de los tickets procesados
- [x] Botón toggle (▼/▶) en el extremo derecho del encabezado
- [x] Preferencia guardada en localStorage para persistir entre sesiones

**Seccion Tickets Descartados**
- [x] Agregada funcionalidad para ocultar/mostrar el detalle de los tickets descartados
- [x] Botón toggle (▼/▶) en el extremo derecho del encabezado
- [x] Preferencia guardada en localStorage para persistir entre sesiones

**Archivos modificados**:
- `frontend/templates/index.html` - Botones toggle en secciones 4 y 5
- `frontend/static/js/toggle.js` - Lógica de mostrar/ocultar
- `frontend/static/css/tickets.css` - Estilos para el toggle

---

## 2. Consultas/Por Articulo

### Búsqueda insensible a acentos
- [x] Migración 7: agregada columna `descripcion_normalizada` a la tabla `productos`
- [x] Búsqueda actualizada para usar la columna normalizada
- [x] Los productos ahora se guardan con su descripción normalizada
- [x] La búsqueda de "cafe" ahora encuentra "Café", "CAFE", etc.

**Archivos modificados**:
- `backend/database.py` - Migración 7
- `backend/services/consultas.py` - Búsqueda con columna normalizada
- `backend/services/catalogo.py` - Mantener columna actualizada
- `tests/test_consultas.py` - Tests actualizados

### Normalización de productos duplicados
- [x] Módulo de autenticación simple (`backend/auth.py`)
- [x] Servicio de normalización (`backend/services/admin_normalizacion.py`)
- [x] Router de administración (`backend/routers/admin.py`)
- [x] Interfaz de login (`frontend/templates/admin_login.html`)
- [x] Interfaz de normalización (`frontend/templates/admin_normalizar.html`)
- [x] Estilos CSS (`frontend/static/css/admin.css`)
- [x] Copia automática de seguridad antes de cada operación
- [x] Botón "Deshacer" para restaurar desde copia de seguridad
- [x] Detección de duplicados con vista previa antes de ejecutar

**Acceso**: `/admin/normalizar-productos` (requiere contraseña de administrador)

**Configuración**: Variable de entorno `ADMIN_PASSWORD`

**Archivos nuevos**:
- `backend/auth.py`
- `backend/services/admin_normalizacion.py`
- `backend/routers/admin.py`
- `frontend/templates/admin_login.html`
- `frontend/templates/admin_normalizar.html`
- `frontend/static/css/admin.css`

**Archivos modificados**:
- `backend/main.py` - Registro del router admin
- `frontend/templates/base.html` - Enlace al panel admin

---

## Resumen de mejoras

| Mejora | Estado | Impacto |
|--------|--------|---------|
| Toggle tickets procesados/descartados | ✅ Completada | Medio |
| Búsqueda insensible a acentos | ✅ Completada | Alto |
| Normalización de duplicados (admin) | ✅ Completada | Alto |

---

## Tests

- **Total**: 20 tests
- **Estado**: Todos pasan ✅
- **Ejecución**: `python -m pytest tests/ -v`

---

## Configuración requerida

Agregar al archivo `.env` o variables de entorno:
```bash
ADMIN_PASSWORD=tu_contraseña_segura
```
