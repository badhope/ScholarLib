"""P2 收尾：/reader/{int} 服务端 301 重定向。"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_reader_int_redirects_301_to_catalog(client: AsyncClient) -> None:
    """GET /reader/301 → 301 Location: /catalog/301#article。"""
    resp = await client.get("/reader/301", follow_redirects=False)
    assert resp.status_code == 301, resp.status_code
    assert resp.headers["location"] == "/catalog/301#article"


@pytest.mark.asyncio
async def test_reader_non_int_not_caught(client: AsyncClient) -> None:
    """GET /reader/assets/xxx 不应被 int 路由吞掉（应落到 SPA/404）。"""
    # 非整数 id 不匹配 /reader/{int}，交由后续处理；这里只断言不返回 301。
    resp = await client.get("/reader/assets/main.js", follow_redirects=False)
    assert resp.status_code != 301
