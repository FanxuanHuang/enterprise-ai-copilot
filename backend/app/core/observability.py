import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator


_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(request_id: str) -> Token[str]:
    return _request_id.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)


@contextmanager
def log_latency(
    logger: logging.Logger,
    *,
    event: str,
    details: str = "",
) -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        latency_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "request_id=%s event=%s latency_ms=%.2f %s",
            get_request_id(),
            event,
            latency_ms,
            details,
        )
