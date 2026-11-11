from contextlib import asynccontextmanager
from typing import Iterable

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from backend.auth import MiddlewareSesion, crear_admin_inicial
from backend.config import STATIC_DIR
from backend.routers.admin import router as admin_router
from backend.routers.consultas import router as consultas_router
from backend.routers.panel import router as panel_router
from backend.routers.productos import router as productos_router
from backend.routers.sesion import router as sesion_router
from backend.routers.tickets import router as tickets_router
from backend.routers.usuarios import router as usuarios_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sin usuarios nadie podría entrar: el primer admin sale de las variables
    # ADMIN_USUARIO y ADMIN_PASSWORD.
    crear_admin_inicial()
    yield


def crear_app(routers_extra: Iterable[APIRouter] = ()) -> FastAPI:
    """Arma la aplicación.

    `routers_extra` permite que una herramienta aparte (por ejemplo
    `carga_inicial`) levante su propia instancia con rutas adicionales sin
    tocar la aplicación principal.
    """
    app = FastAPI(title="Procesador de Tickets PDF", version="2.0", lifespan=lifespan)

    # Toda la aplicación exige sesión salvo /login, /health y /static.
    app.add_middleware(MiddlewareSesion)

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    # Los routers se registran de más específico a menos: /tickets declara
    # "/tickets" y "/", así que el panel tiene que declararse después para
    # ganar la raíz.
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(sesion_router)
    app.include_router(tickets_router)
    app.include_router(panel_router)
    app.include_router(productos_router)
    app.include_router(consultas_router)
    app.include_router(admin_router)
    app.include_router(usuarios_router)
    for router in routers_extra:
        app.include_router(router)
    return app


app = crear_app()
