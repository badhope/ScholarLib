"""中图分类号（CLC）解析：从 Markdown front-matter 读 clc / clc_label。

正文以 YAML 风格 front-matter 开头时，例如：

    ---
    clc: TP3
    clc_label: 计算技术、计算机技术
    ---

    # 标题

校验口径：``^[A-Z]{1,2}\\d{0,3}(\\.\\d+)?$``（如 TP、TP3、TP311.13）。
非法值**不静默丢弃**——原样存入 ``clc_code`` 并把状态置为
``needs_correction``，详情接口据此提示"待校正"，由编辑部改口。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 中图法分类号：1-2 个大写字母 + 0-3 位数字 + 可选 .数字 子类。
# 示例：TP、TP3、TP311、TP311.13、F、F8、G25。
CLC_RE = re.compile(r"^[A-Z]{1,2}\d{0,3}(\.\d+)?$")


@dataclass(frozen=True)
class ClcInfo:
    """front-matter 解析结果。

    ``code`` 归一化后的值（大写）；``status`` 为 ``valid`` /
    ``needs_correction``；无 front-matter 或无 clc 时 code 为 None。
    """

    code: str | None
    label: str | None
    status: str  # "valid" | "needs_correction" | "absent"


def _parse_front_matter(markdown: str) -> dict[str, str]:
    """抽出最外层 ``---`` 包裹的 YAML 行，按 ``key: value`` 粗解析。

    只需要 clc / clc_label 两个标量，不引入完整 YAML 依赖（值里不会有
    嵌套结构）；解析失败返回空 dict，正文照常走。
    """
    text = markdown.lstrip("\ufeff").lstrip()
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return {}
    end: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return {}
    out: dict[str, str] = {}
    for line in lines[1:end]:
        m = re.match(r"^\s*([A-Za-z_][\w-]*)\s*:\s*(.*?)\s*$", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip().strip('"').strip("'")
        out[key] = value
    return out


def parse_clc(markdown: str) -> ClcInfo:
    """从 Markdown front-matter 提取并校验中图分类号。"""
    fm = _parse_front_matter(markdown or "")
    raw = fm.get("clc") or fm.get("CLC") or ""
    label = fm.get("clc_label") or fm.get("CLC_LABEL") or None
    raw = raw.strip()
    if not raw:
        return ClcInfo(code=None, label=None, status="absent")
    code = raw.upper()
    if CLC_RE.match(code):
        return ClcInfo(code=code, label=label, status="valid")
    # 非法：不丢弃，原样保留进库，标记待校正。
    return ClcInfo(code=code[:20], label=label, status="needs_correction")


def clc_status_of(code: str | None) -> str:
    """详情接口用：根据已存 code 反推校正状态（DB 无独立状态列）。"""
    if not code:
        return "absent"
    return "valid" if CLC_RE.match(code.strip()) else "needs_correction"


__all__ = ["CLC_RE", "ClcInfo", "clc_status_of", "parse_clc"]
