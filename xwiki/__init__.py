"""Service-first package for xWiki.

The package exposes a compact facade from :mod:`xwiki.service` so callers can
import and run the knowledge flow without any CLI layer.
"""

from .config import XWikiConfig as XWikiSettings
from .config import XWikiConfig
from .service import XWikiService

__all__ = [
    "XWikiConfig",
    "XWikiSettings",
    "XWikiService",
]
