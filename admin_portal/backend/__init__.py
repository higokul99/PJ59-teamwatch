"""Register the complete admin portal with the main FastAPI application."""
from .dispatch import RoomDispatch
from .routes import create_admin_router
from .service import Manager


def install(root):
    manager = Manager(root)
    root.app.include_router(create_admin_router(manager))
    root.app.add_middleware(RoomDispatch, manager=manager)
    return manager
