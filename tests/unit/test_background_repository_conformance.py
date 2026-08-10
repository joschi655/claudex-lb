"""The background scheduler's repository wrappers must match their Protocols.

The wrappers are handed to ``LimitWarmupService`` through ``cast(Any, ...)``, so a
Protocol that grows a method leaves them behind with nothing to complain: the
type checker sees ``Any``, the unit tests use fakes, and the scheduler's own loop
swallows the ``AttributeError`` into a log line. Warm-up then stops running with
no operator-visible signal.

That happened: ``latest_by_account_window`` was added to the Protocol and to the
real repository, and the background wrapper went out on a deploy without it.
"""

from __future__ import annotations

import inspect
from typing import Protocol, get_type_hints

import pytest

from app.core.usage.refresh_scheduler import (
    _BackgroundLimitWarmupRepository,
    _BackgroundRequestLogsRepository,
)
from app.modules.limit_warmup.service import (
    LimitWarmupAttemptsRepository,
    LimitWarmupRequestLogRepository,
)

pytestmark = pytest.mark.unit


def _protocol_members(protocol: type) -> list[str]:
    return sorted(
        name for name in dir(protocol) if not name.startswith("_") and callable(getattr(protocol, name, None))
    )


@pytest.mark.parametrize(
    ("protocol", "wrapper"),
    [
        (LimitWarmupAttemptsRepository, _BackgroundLimitWarmupRepository),
        (LimitWarmupRequestLogRepository, _BackgroundRequestLogsRepository),
    ],
    ids=["limit-warmup-attempts", "limit-warmup-request-logs"],
)
def test_background_wrapper_implements_every_protocol_method(protocol: type, wrapper: type) -> None:
    required = _protocol_members(protocol)
    assert required, "the protocol should declare at least one method"
    missing = [name for name in required if not callable(getattr(wrapper, name, None))]
    assert missing == [], f"{wrapper.__name__} is missing {missing}"


@pytest.mark.parametrize(
    ("protocol", "wrapper"),
    [
        (LimitWarmupAttemptsRepository, _BackgroundLimitWarmupRepository),
        (LimitWarmupRequestLogRepository, _BackgroundRequestLogsRepository),
    ],
    ids=["limit-warmup-attempts", "limit-warmup-request-logs"],
)
def test_background_wrapper_accepts_every_protocol_parameter(protocol: type, wrapper: type) -> None:
    """A wrapper that drops or renames a parameter fails at call time, not import."""
    for name in _protocol_members(protocol):
        expected = inspect.signature(getattr(protocol, name)).parameters
        actual = inspect.signature(getattr(wrapper, name)).parameters
        # A wrapper that forwards ``**kwargs`` accepts whatever the protocol names.
        if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in actual.values()):
            continue
        missing = [
            parameter
            for parameter in expected
            if parameter not in actual and expected[parameter].kind is not inspect.Parameter.VAR_KEYWORD
        ]
        assert missing == [], f"{wrapper.__name__}.{name} does not accept {missing}"


def test_the_protocols_are_still_protocols() -> None:
    """Guards the premise: these checks only matter while the contract is structural."""
    for protocol in (LimitWarmupAttemptsRepository, LimitWarmupRequestLogRepository):
        assert Protocol in protocol.__bases__
        # Resolves the annotations too, so a Protocol that stops importing cleanly
        # fails here rather than silently exempting itself from the checks above.
        assert get_type_hints(protocol) is not None
