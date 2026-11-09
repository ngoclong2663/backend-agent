"""Epic 31: a quick check of the video providers' keys (`make video-keys`), as Epic 27's for Unsplash: one cheap call
each: YouTube `videos.list` (1 unit) and one Pixabay search (1 of the minute's 100 requests). Prints what each
answered and the limits it reported. Dev tool, never part of generation."""

import asyncio
import sys

import httpx

from src.configs import config
from src.videos.factory import enabled_providers
from src.videos.pixabay import API as PIXABAY_API
from src.videos.youtube import API as YOUTUBE_API


async def check_youtube(key: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{YOUTUBE_API}/videos", params={"part": "status,contentDetails", "id": "aqz-KE-bpKQ", "key": key}
        )
    if response.status_code != 200:
        return f"youtube: {response.status_code} {response.text[:200]}"
    item = (response.json().get("items") or [{}])[0]
    return (
        f"youtube: ok (1 unit): embeddable={item.get('status', {}).get('embeddable')}, "
        f"duration={item.get('contentDetails', {}).get('duration')}"
    )


async def check_pixabay(key: str) -> str:
    headers = {"User-Agent": f"{config.unsplash_app_name}/{config.generator_version}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            PIXABAY_API,
            params={"key": key, "q": "ocean waves", "video_type": "film", "safesearch": "true", "per_page": 3},
            headers=headers,
        )
    limits = {k: response.headers.get(k) for k in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset")}
    if response.status_code != 200:
        return f"pixabay: {response.status_code} {response.text[:200]} {limits}"
    data = response.json()
    sizes = sorted((data.get("hits") or [{}])[0].get("videos", {}).keys())
    return f"pixabay: ok ({data.get('totalHits')} hits, sizes {sizes}) limits {limits}"


async def main() -> int:
    names = enabled_providers()
    print(f"VIDEO_PROVIDERS={config.video_providers!r} → enabled with a key: {names or 'none'}")
    if not names:
        return 1
    if "youtube" in names:
        print(await check_youtube(config.youtube_api_key or ""))
    if "pixabay" in names:
        print(await check_pixabay(config.pixabay_api_key or ""))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
