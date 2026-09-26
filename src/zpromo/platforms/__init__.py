"""Platform publishers. Each exposes: publish(post, product, category, copy) -> (remote_id, remote_url)
and metrics(posts) -> {post_id: {metric: value}}."""
from .base import AuthError, PlatformError, RateLimited  # noqa: F401


def get(name: str, settings: dict):
    if name == "pinterest":
        from .pinterest import Pinterest
        return Pinterest(settings)
    if name == "tumblr":
        from .tumblr import Tumblr
        return Tumblr(settings)
    if name == "bluesky":
        from .bluesky import Bluesky
        return Bluesky(settings)
    if name == "threads":
        from .threads import Threads
        return Threads(settings)
    raise KeyError(name)
