#!/usr/bin/env python3
"""Rubbish MCP server (stdio, stdlib only).

环境变量:
  RUBBISH_API_TOKEN  必填，站点「设置 → AI 投稿」创建的个人 Token
  RUBBISH_BASE_URL   默认 https://rubbish.argjiemi.cn

工具:
  submit_paper         以当前账号投稿（同一 Idempotency-Key 不重复入库）
  list_my_submissions  查看自己的投稿与站内相似度提示

用法（Claude Desktop / Cursor / 任意 MCP 客户端）:
  {
    "mcpServers": {
      "rubbish": {
        "command": "python3",
        "args": ["/abs/path/tools/rubbish-mcp/server.py"],
        "env": {"RUBBISH_API_TOKEN": "rbk_..."}
      }
    }
  }
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
BASE_URL = os.environ.get("RUBBISH_BASE_URL", "https://rubbish.argjiemi.cn").rstrip("/")
TOKEN = os.environ.get("RUBBISH_API_TOKEN", "").strip()

TOOLS: list[dict[str, Any]] = [
    {
        "name": "submit_paper",
        "description": "向 Rubbish 期刊投稿。需要个人 API Token；会自动跑敏感词与站内相似度，返回稿件 ID 与提示。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "maxLength": 1000},
                "abstract": {"type": "string", "maxLength": 20000},
                "authors": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "year": {"type": "integer"},
                "discipline": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["paper", "book", "dataset", "tutorial"],
                    "default": "paper",
                },
                "venue": {"type": "string"},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "doi": {"type": "string"},
                "external_url": {"type": "string"},
                "preview": {"type": "string"},
                "idempotency_key": {
                    "type": "string",
                    "description": "客户端生成唯一键；重试不会重复投稿",
                },
            },
            "required": ["title", "abstract", "authors", "year", "discipline"],
        },
    },
    {
        "name": "list_my_submissions",
        "description": "查看当前 Token 所属账号的投稿列表、状态和站内相似度分数。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status_filter": {"type": "string", "description": "如 pending / accepted"},
                "limit": {"type": "integer", "default": 20, "maximum": 50},
            },
        },
    },
]


def _request(method: str, path: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    if not TOKEN:
        raise RuntimeError("RUBBISH_API_TOKEN 未设置；请到站点设置页创建个人 Token")
    url = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-API-Key", TOKEN)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "rubbish-mcp/1.0")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _text_result(value: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}],
        "isError": False,
    }


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "submit_paper":
        key = str(arguments.pop("idempotency_key", "") or "")[:100]
        payload = {
            "title": arguments["title"],
            "abstract": arguments["abstract"],
            "authors": arguments["authors"],
            "year": arguments["year"],
            "discipline": arguments["discipline"],
            "type": arguments.get("type", "paper"),
            "venue": arguments.get("venue"),
            "keywords": arguments.get("keywords", []),
            "doi": arguments.get("doi"),
            "external_url": arguments.get("external_url") or None,
            "preview": arguments.get("preview"),
        }
        result = _request(
            "POST",
            "/api/ai/submissions",
            payload,
            {"Idempotency-Key": key} if key else None,
        )
        return _text_result(result)
    if name == "list_my_submissions":
        query = {}
        if arguments.get("status_filter"):
            query["status_filter"] = arguments["status_filter"]
        if arguments.get("limit"):
            query["limit"] = int(arguments["limit"])
        suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
        return _text_result(_request("GET", f"/api/ai/submissions{suffix}"))
    raise RuntimeError(f"未知工具: {name}")


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "rubbish-mcp", "version": "1.0.0"},
            },
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = call_tool(params.get("name", ""), params.get("arguments") or {})
        except Exception as exc:  # 工具失败要回给模型，而不是杀进程
            result = {
                "content": [{"type": "text", "text": f"调用失败：{exc}"}],
                "isError": True,
            }
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
