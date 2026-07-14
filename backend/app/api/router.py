from fastapi import APIRouter

from app.api.routes import (
    agent,
    alerts,
    auth,
    health,
    notifications,
    preferences,
    risk,
    sources,
    subscriptions,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(preferences.router)
api_router.include_router(alerts.router)
api_router.include_router(subscriptions.router)
api_router.include_router(notifications.router)
api_router.include_router(sources.router)
api_router.include_router(risk.router)
api_router.include_router(agent.router)
