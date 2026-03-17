from aiogram import Router
from . import start, races, settings, standings, drivers, admin

root_router = Router()
root_router.include_router(start.router)
root_router.include_router(races.router)
root_router.include_router(standings.router)
root_router.include_router(drivers.router)
root_router.include_router(settings.router)
root_router.include_router(admin.router)

__all__ = ["root_router"]