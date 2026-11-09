"""The video providers from the settings (Epic 31 D1): `VIDEO_PROVIDERS` lists the ones that are on (`youtube`,
`pixabay`; empty by default), each needing its key. Each place asks them in its own order (the epic's table): a
watched video wants YouTube first, a background loop or a seeded field Pixabay first."""

from src.configs import config

from .pixabay import PixabayVideos
from .port import IVideoProvider, Place
from .youtube import YouTubeVideos

ORDER: dict[str, tuple[str, ...]] = {
    "watch": ("youtube", "pixabay"),
    "background": ("pixabay",),  # YouTube's player always shows its controls and branding: never a backdrop
    "seed": ("pixabay", "youtube"),
}


def enabled_providers() -> list[str]:
    """The provider names that are on and have their key."""
    names = [name.strip() for name in (getattr(config, "video_providers", "") or "").split(",") if name.strip()]
    out = []
    for name in names:
        if name == "youtube" and getattr(config, "youtube_api_key", None):
            out.append(name)
        elif name == "pixabay" and getattr(config, "pixabay_api_key", None):
            out.append(name)
    return out


_instances: dict[str, IVideoProvider] = {}


def get_video_provider(name: str) -> IVideoProvider | None:
    """One instance per provider per process (its cache and counters live in files; the instance keeps the hour's
    exhaustion so a draft stops asking once a provider is out)."""
    if name not in enabled_providers():
        return None
    if name not in _instances:
        timeout = float(getattr(config, "image_timeout_seconds", 60))
        if name == "youtube":
            _instances[name] = YouTubeVideos(api_key=config.youtube_api_key, timeout=timeout)
        else:
            app_name = getattr(config, "unsplash_app_name", "fullstack_generation_agent")
            _instances[name] = PixabayVideos(
                api_key=config.pixabay_api_key,
                user_agent=f"{app_name}/{config.generator_version}",
                timeout=timeout,
            )
    return _instances[name]


def providers_for(place: Place) -> list[IVideoProvider]:
    """The enabled providers in the place's order."""
    out = []
    for name in ORDER[place]:
        provider = get_video_provider(name)
        if provider is not None:
            out.append(provider)
    return out


def videos_enabled() -> bool:
    return bool(enabled_providers())


def reset_providers() -> None:
    """Tests: forget the instances (a new key, a new cache dir)."""
    _instances.clear()
