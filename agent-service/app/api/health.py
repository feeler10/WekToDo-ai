from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=['health'])


class HealthResponse(BaseModel):
    status: Literal['ok'] = 'ok'


@router.get('/health', response_model=HealthResponse)
async def get_health() -> HealthResponse:
    return HealthResponse()
