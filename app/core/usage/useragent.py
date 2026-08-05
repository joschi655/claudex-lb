"""Client user-agent fields recorded on request logs.

Shared by both proxies so a Claude request and a Codex request group the same
way in reports. ``useragent_group`` is the product token ahead of any version,
so ``claude-cli/2.1.0 (external, cli)`` groups as ``claude-cli``.
"""

from __future__ import annotations

from collections.abc import Mapping


def request_log_useragent_fields(headers: Mapping[str, str]) -> tuple[str | None, str | None]:
    raw_useragent = next((value for key, value in headers.items() if key.lower() == "user-agent"), None)
    if raw_useragent is None:
        return None, None
    useragent = raw_useragent.strip()
    if not useragent:
        return None, None
    first_token = useragent.split(maxsplit=1)[0]
    useragent_group = first_token.split("/", 1)[0].strip() or None
    return useragent, useragent_group
