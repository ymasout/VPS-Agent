import re
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from .config import get_settings

router = APIRouter(prefix="/agent-downloads", tags=["agent-releases"])
allowed_assets = {
    "install-agent.sh",
    "SHA256SUMS",
    "vps-agent-linux-amd64",
    "vps-agent-linux-arm64",
}
release_pattern = re.compile(r"^v\d+\.\d+\.\d+$")


def release_asset_url(release: str, asset: str) -> str | None:
    if asset not in allowed_assets:
        return None
    repository = get_settings().agent_release_repository
    if release == "latest":
        return f"https://github.com/{repository}/releases/latest/download/{asset}"
    if release_pattern.fullmatch(release):
        return f"https://github.com/{repository}/releases/download/{release}/{asset}"
    return None


@router.get("/{release}/{asset}")
async def download_release_asset(release: str, asset: str) -> StreamingResponse:
    url = release_asset_url(release, asset)
    if url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="release asset not found")

    client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, connect=10))
    try:
        response = await client.send(client.build_request("GET", url), stream=True)
    except httpx.HTTPError as error:
        await client.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="release upstream unavailable"
        ) from error
    if response.status_code != status.HTTP_200_OK:
        await response.aclose()
        await client.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="release upstream rejected request"
        )

    async def content() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    headers = {
        "cache-control": "public, max-age=300",
        "content-disposition": f'attachment; filename="{asset}"',
    }
    return StreamingResponse(
        content(),
        media_type=response.headers.get("content-type", "application/octet-stream"),
        headers=headers,
    )
