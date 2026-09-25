"""Proxies: named ways out, chosen by channels, their credentials never shown."""

import asyncio
import time

import httpx2
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models import Proxy, Source
from app.features.proxies.schemas import (
    AddressCheck,
    ProxyCheck,
    ProxyCreate,
    ProxyRead,
    ProxyUpdate,
    mask,
)


class ProxyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_proxies(self) -> list[ProxyRead]:
        rows = (await self.session.scalars(select(Proxy).order_by(Proxy.name))).all()
        return [await self._read(proxy) for proxy in rows]

    async def get_proxy(self, proxy_id: int) -> ProxyRead:
        return await self._read(await self._row(proxy_id))

    async def create_proxy(self, payload: ProxyCreate) -> ProxyRead:
        proxy = Proxy(**payload.model_dump())
        self.session.add(proxy)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"A proxy named '{payload.name}' exists") from exc
        await self.session.refresh(proxy)
        audit.set_target("proxy", proxy.id)
        # Masked: the trail is read by everyone who can read the panel, and a password in it
        # would outlive every rotation of it.
        audit.record_changes(
            name=payload.name,
            urls=[mask(url) for url in payload.urls],
            is_enabled=payload.is_enabled,
            note=payload.note,
        )
        return await self._read(proxy)

    async def update_proxy(self, proxy_id: int, payload: ProxyUpdate) -> ProxyRead:
        proxy = await self._row(proxy_id)
        audit.set_target("proxy", proxy.id)
        sent = payload.model_dump(exclude_unset=True)
        if payload.name is not None:
            proxy.name = payload.name
        if payload.urls is not None:
            proxy.urls = payload.urls
        if payload.is_enabled is not None:
            proxy.is_enabled = payload.is_enabled
        if "note" in sent:
            proxy.note = payload.note
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"A proxy named '{payload.name}' exists") from exc
        # `updated_at` is set by the database, so the row is read back before it is shown.
        await self.session.refresh(proxy)
        if "urls" in sent:
            sent["urls"] = [mask(url) for url in payload.urls or []]
        audit.record_changes(**sent)
        return await self._read(proxy)

    async def remove_proxy(self, proxy_id: int) -> None:
        """Only one no channel uses: taking it away would send them out direct, unasked."""
        proxy = await self._row(proxy_id)
        audit.set_target("proxy", proxy.id)
        users = await self._sources(proxy.id)
        if users:
            raise ConflictError(
                f"'{proxy.name}' is used by {', '.join(users)}",
                code="proxy_in_use",
                details={"sources": users},
            )
        await self.session.delete(proxy)
        await self.session.flush()
        audit.record_changes(removed=proxy.name)

    async def check_proxy(self, proxy_id: int) -> ProxyCheck:
        """Every address asked for the probe page once, side by side.

        Answers what a run would otherwise find out the slow way — a password that changed,
        an address the provider took away — and which address the shop would see.
        """
        proxy = await self._row(proxy_id)
        probe = settings.proxy_check_url
        checks = await asyncio.gather(*(check_address(url, probe) for url in proxy.urls))
        return ProxyCheck(proxy_id=proxy.id, probe=probe, addresses=list(checks))

    async def _row(self, proxy_id: int) -> Proxy:
        proxy = await self.session.get(Proxy, proxy_id)
        if proxy is None:
            raise NotFoundError(f"Proxy {proxy_id} not found")
        return proxy

    async def _sources(self, proxy_id: int) -> list[str]:
        rows = await self.session.scalars(
            select(Source.slug).where(Source.proxy_id == proxy_id).order_by(Source.slug)
        )
        return list(rows.all())

    async def _read(self, proxy: Proxy) -> ProxyRead:
        return ProxyRead(
            id=proxy.id,
            name=proxy.name,
            urls=[mask(url) for url in proxy.urls],
            is_enabled=proxy.is_enabled,
            note=proxy.note,
            sources=await self._sources(proxy.id),
            created_at=proxy.created_at,
            updated_at=proxy.updated_at,
        )


async def check_address(url: str, probe: str) -> AddressCheck:
    """One request for the probe page through one address."""
    started = time.monotonic()
    try:
        async with httpx2.AsyncClient(
            proxy=url, timeout=settings.proxy_check_timeout_seconds
        ) as client:
            response = await client.get(probe)
    except httpx2.HTTPError as error:
        return AddressCheck(
            url=mask(url),
            ok=False,
            ms=int((time.monotonic() - started) * 1000),
            error=f"{type(error).__name__}: {error}"[:300],
        )
    ms = int((time.monotonic() - started) * 1000)
    ip = None
    try:
        ip = str(response.json().get("ip") or "") or None
    except ValueError:
        ip = response.text.strip()[:64] or None
    return AddressCheck(
        url=mask(url), ok=response.status_code < 400, status=response.status_code, ip=ip, ms=ms
    )
