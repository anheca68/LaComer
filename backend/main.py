from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import STATIC_DIR, TEMPLATES_DIR
from backend.routers.admin import router as admin_router
from backend.routers.consultas import router as consultas_router
from backend.routers.importar import router as importar_router
from backend.routers.panel import router as panel_router
from backend.routers.productos import router as productos_router
from backend.routers.tickets import router as tickets_router

app = FastAPI(title="Procesador de Tickets PDF", version="2.0")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
# Los routers se registran de más específico a menos: /tickets declara "/tickets"
# y "/", así que el panel tiene que declararse después para ganar la raíz.
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(tickets_router)
app.include_router(panel_router)
app.include_router(productos_router)
app.include_router(importar_router)
app.include_router(consultas_router)
app.include_router(admin_router)
