"""轻量内容风控：可解释的关键词/正则扫描。

定位：先挡「高置信度垃圾广告、引流、辱骂」，不假装是 AI 内容审核。
规则保守，宁可漏过让后台举报补位，也不把正常学术讨论（例如讨论“代写
现象”）误杀。需要扩展时用环境变量 ``RUBBISH_MODERATION_BLOCKLIST``
追加逗号分隔的词，重启生效。
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

# 高置信度引流/诈骗：命中即拦。避免单字“微信”“QQ”误伤正常讨论，
# 必须和“加/扫/群/私聊”等动作词同现。
_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "广告引流",
        "疑似广告引流：请去掉加微信/扫码进群/私聊等联系方式",
        re.compile(
            r"(?:加|扫|搜|私聊|私信|联系)\s*(?:微信|wechat|vx|v信|薇信|qq|群|飞机|telegram)"
            r"|(?:扫码|长按二维码)\s*(?:进群|加群|咨询|领取)"
            r"|(?:刷单|返利|博彩|网赌|赌球|六合彩|贷款秒批|代开发票|办证|内部渠道|稳赚不赔)",
            re.IGNORECASE,
        ),
    ),
    (
        "辱骂攻击",
        "内容包含人身攻击或侮辱性表达，请改为就事论事",
        re.compile(r"傻逼|脑残|去死|畜生|贱人|废物东西", re.IGNORECASE),
    ),
)


@dataclass(frozen=True)
class ModerationHit:
    category: str
    message: str
    term: str


def _normalize(text: str) -> str:
    # NFKC 折叠全角/兼容字符；去掉零宽字符，防止“微​信”拆字绕过。
    normalized = unicodedata.normalize("NFKC", text or "").lower()
    normalized = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", normalized)
    return normalized


def _extra_terms() -> list[str]:
    raw = os.getenv("RUBBISH_MODERATION_BLOCKLIST", "")
    return [term.strip() for term in raw.split(",") if term.strip()]


def scan_text(text: str, *, max_hits: int = 3) -> list[ModerationHit]:
    """返回命中项；空列表表示通过。只做确定性规则，不调用外部服务。"""
    normalized = _normalize(text)
    hits: list[ModerationHit] = []
    for category, message, pattern in _PATTERNS:
        match = pattern.search(normalized)
        if match:
            hits.append(ModerationHit(category=category, message=message, term=match.group(0)[:40]))
        if len(hits) >= max_hits:
            break
    for term in _extra_terms():
        if term.lower() in normalized:
            hits.append(
                ModerationHit(
                    category="站规词",
                    message="内容包含站点禁止的词，请修改后再提交",
                    term=term[:40],
                )
            )
        if len(hits) >= max_hits:
            break
    return hits


def rejection_detail(text: str) -> dict[str, object] | None:
    """路由层统一返回体：命中时给 code + 可读原因，不把原文回显给用户。"""
    hits = scan_text(text)
    if not hits:
        return None
    return {
        "code": "content_blocked",
        "message": hits[0].message,
        "categories": sorted({hit.category for hit in hits}),
    }


__all__ = ["ModerationHit", "rejection_detail", "scan_text"]
