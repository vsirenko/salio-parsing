"""Proxies behind the admin panel: /api/admin/proxies

Made once and chosen by any channel (`proxy_id` on the channel). The addresses carry their
credentials and are shown masked; sending `urls` replaces the whole list.
"""

from fastapi import APIRouter, Response, status

from app.api.deps import ProxyServiceDep
from app.features.proxies.schemas import ProxyCheck, ProxyCreate, ProxyRead, ProxyUpdate
from app.schemas.common import ErrorResponse

router = APIRouter(prefix="/proxies", tags=["admin: proxies"])


@router.get("", response_model=list[ProxyRead], summary="List proxies")
async def list_proxies(service: ProxyServiceDep) -> list[ProxyRead]:
    return await service.list_proxies()


@router.post(
    "",
    response_model=ProxyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a proxy",
    responses={409: {"model": ErrorResponse, "description": "The name is taken"}},
)
async def create_proxy(payload: ProxyCreate, service: ProxyServiceDep) -> ProxyRead:
    """`urls` like `http://user:pass@host:port` or `socks5://…`, taken in turn by a run."""
    return await service.create_proxy(payload)


@router.get(
    "/{proxy_id}",
    response_model=ProxyRead,
    summary="Get a proxy",
    responses={404: {"model": ErrorResponse, "description": "Proxy not found"}},
)
async def get_proxy(proxy_id: int, service: ProxyServiceDep) -> ProxyRead:
    return await service.get_proxy(proxy_id)


@router.patch(
    "/{proxy_id}",
    response_model=ProxyRead,
    summary="Update a proxy",
    responses={
        404: {"model": ErrorResponse, "description": "Proxy not found"},
        409: {"model": ErrorResponse, "description": "The name is taken"},
    },
)
async def update_proxy(proxy_id: int, payload: ProxyUpdate, service: ProxyServiceDep) -> ProxyRead:
    """Switching it off sends its channels out direct from the next run; nothing else to edit."""
    return await service.update_proxy(proxy_id, payload)


@router.delete(
    "/{proxy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a proxy no channel uses",
    responses={
        404: {"model": ErrorResponse, "description": "Proxy not found"},
        409: {"model": ErrorResponse, "description": "Channels still go out through it"},
    },
)
async def remove_proxy(proxy_id: int, service: ProxyServiceDep) -> Response:
    await service.remove_proxy(proxy_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{proxy_id}/check",
    response_model=ProxyCheck,
    summary="Try every address of a proxy",
    responses={404: {"model": ErrorResponse, "description": "Proxy not found"}},
)
async def check_proxy(proxy_id: int, service: ProxyServiceDep) -> ProxyCheck:
    """One request for `PROXY_CHECK_URL` through each address: whether it answered, how fast,
    and the address the far side saw."""
    return await service.check_proxy(proxy_id)
