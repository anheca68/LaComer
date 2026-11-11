# Carga inicial del histórico

Herramienta separada de la aplicación principal. Se usó una sola vez para
importar las transacciones históricas (Excel `DESPENSA.xlsx`, hoja `DATA`, y
los PDFs de `procesados/` que no estaban en la base). La aplicación principal
ya no expone `/importar` ni lee el Excel.

## Contenido

| Archivo | Qué hace |
|---------|----------|
| `servicio.py` | Arma el plan de importación desde el Excel y los PDFs y lo aplica en una sola transacción |
| `router.py` | Rutas `/importar/*` (solo `admin`, y solo con la tabla `tickets` vacía) |
| `templates/importar.html` | Pantalla de revisión del plan |
| `app.py` | La aplicación completa más las rutas de carga inicial |
| `migrar_catalogo.py` | Script de consola: pasa la hoja `catalogo` del Excel a categorías, subcategorías y productos |

## Uso

Desde la raíz del repositorio, con el mismo entorno y la misma base que la app:

```bash
# Pantalla web en http://127.0.0.1:8002/importar (inicia sesión como admin)
.venv/bin/python -m carga_inicial

# Solo el catálogo, por consola (idempotente)
.venv/bin/python -m carga_inicial.migrar_catalogo [ruta_excel]
```

- El Excel se busca en `DATA_DIR/DESPENSA.xlsx`; se puede indicar otra ruta con
  `CATALOGO_EXCEL`.
- La pantalla solo funciona mientras la tabla `tickets` esté vacía; con tickets
  registrados redirige a `/tickets`.
- Respalda `despensa.db` antes de usarla.

## Docker

La carpeta `carga_inicial/` no entra en la imagen (está en `.dockerignore`).
Para usarla contra los datos del NAS, lo más simple es copiar `data/` a una
máquina con el repositorio y correrla ahí con `DATA_DIR` apuntando a la copia.
