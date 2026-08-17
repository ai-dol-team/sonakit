import logging
import sys

from sonakit.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s level=%(levelname)s logger=%(name)s message=%(message)s",
        stream=sys.stdout,
        force=True,
    )

