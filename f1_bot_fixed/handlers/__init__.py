from aiogram import Router
from . import start, races, settings

# Корневой роутер, к которому подключаются все дочерние
root_router = Router()
root_router.include_router(start.router)
root_router.include_router(races.router)
root_router.include_router(settings.router)

__all__ = ["root_router"]
