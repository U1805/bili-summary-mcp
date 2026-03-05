import logging

from colorlog import ColoredFormatter


class _ExcludeLoggerFilter(logging.Filter):
    def __init__(self, prefixes: tuple[str, ...]) -> None:
        super().__init__()
        self._prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return not any(record.name.startswith(prefix) for prefix in self._prefixes)


def _build_colored_handler(formatter: logging.Formatter) -> logging.Handler:
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(formatter)
    return handler


def _build_level_colored_formatter(info_color: str = "white") -> ColoredFormatter:
    return ColoredFormatter(
        "%(log_color)s%(message)s%(reset)s",
        log_colors={
            "DEBUG": "cyan",
            "INFO": info_color,
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    )


def setup_logging() -> None:
    if getattr(setup_logging, "_configured", False):
        return

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    default_formatter = _build_level_colored_formatter("white")
    default_handler = _build_colored_handler(default_formatter)
    default_handler.addFilter(_ExcludeLoggerFilter(("app.mcp.server", "httpx", "uvicorn.access")))
    root_logger.addHandler(default_handler)

    mcp_logger = logging.getLogger("app.mcp.server")
    mcp_logger.setLevel(logging.INFO)
    mcp_logger.handlers.clear()
    mcp_logger.addHandler(
        _build_colored_handler(
            _build_level_colored_formatter("blue"),
        )
    )
    mcp_logger.propagate = False

    httpx_logger = logging.getLogger("httpx")
    httpx_logger.setLevel(logging.INFO)
    httpx_logger.handlers.clear()
    httpx_logger.addHandler(
        _build_colored_handler(
            _build_level_colored_formatter("purple"),
        )
    )
    httpx_logger.propagate = False

    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.setLevel(logging.INFO)
    uvicorn_access_logger.handlers.clear()
    uvicorn_access_logger.addHandler(
        _build_colored_handler(
            _build_level_colored_formatter("green"),
        )
    )
    uvicorn_access_logger.propagate = False

    setup_logging._configured = True
