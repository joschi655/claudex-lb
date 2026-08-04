from __future__ import annotations

import json
from typing import cast

import pytest

from app.modules.accounts.repository import AccountsRepository
from app.modules.accounts.service import AccountsService, InvalidAuthJsonError

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_claude_oauth_backup_is_rejected_by_openai_import() -> None:
    payload = json.dumps(
        {
            "email": "user@example.com",
            "claudeAiOauth": {
                "accessToken": "sk-ant-oat01-consumer",
                "refreshToken": "sk-ant-ort01-consumer",
                "expiresAt": 1_752_900_000_000,
            },
        }
    ).encode()

    with pytest.raises(InvalidAuthJsonError):
        await AccountsService(repo=cast(AccountsRepository, None)).import_account(payload)
