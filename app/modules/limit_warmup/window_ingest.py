"""Record the window a Claude warmup just opened.

A warmup response carries the same ``anthropic-ratelimit-unified-*`` headers a
relayed response does, so the newly opened window is written through the relay's
own ingest path. Without this the reset timestamp would still describe the
window the ping replaced, and the next evaluation would warm the account again.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from app.core.anthropic.usage_headers import parse_unified_usage
from app.core.anthropic.usage_ingest import persist_usage_snapshot
from app.db.session import get_background_session
from app.modules.proxy.account_cache import get_account_selection_cache
from app.modules.usage.repository import UsageRepository

logger = logging.getLogger(__name__)


async def ingest_warmup_window(account_id: str, headers: Mapping[str, str]) -> None:
    """Persist whatever window state the warmup response reported.

    Never raises: a warmup that landed has already done its job, and losing the
    bookkeeping must not turn a successful ping into a failed attempt.
    """
    snapshot = parse_unified_usage(headers)
    if not snapshot.has_any:
        return
    try:
        async with get_background_session() as session:
            await persist_usage_snapshot(UsageRepository(session), account_id, snapshot)
        get_account_selection_cache().invalidate()
    except Exception:
        logger.warning(
            "Failed to ingest warm-up window for account_id=%s",
            account_id,
            exc_info=True,
        )
