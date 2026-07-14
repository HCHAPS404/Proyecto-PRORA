from fastapi import APIRouter

from app.api.dependencies import CurrentUser, SessionDep
from app.schemas.users import PreferencesResponse, PreferencesUpdate

router = APIRouter(tags=["preferences"])


def _normalized(preferences: dict) -> PreferencesResponse:
    supported = set(PreferencesResponse.model_fields)
    values = {key: value for key, value in preferences.items() if key in supported}
    return PreferencesResponse(**values)


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(user: CurrentUser) -> PreferencesResponse:
    return _normalized(user.preferences or {})


@router.patch("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    payload: PreferencesUpdate, user: CurrentUser, session: SessionDep
) -> PreferencesResponse:
    current = _normalized(user.preferences or {}).model_dump()
    current.update(payload.model_dump(exclude_unset=True))
    normalized = PreferencesResponse(**current)
    user.preferences = normalized.model_dump()
    await session.commit()
    return normalized
