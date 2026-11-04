"""Word 模板实现的转发层。

模板逻辑只有一份，放在 `apps/backend/app/modules/submission/docx_template.py`：
导出接口（线上「下载 Word」）和批处理脚本必须用同一份代码，否则线上导出的
Word 与编辑部离线生成的 Word 会长成两个样子——那是上一轮「电脑和手机两个
模样」的同类错误。

这里用文件路径加载而不是 `from app... import`：导入 `app` 包会连带初始化
数据库、structlog 等一整套运行时依赖，脚本在本地跑不动。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CANDIDATES = (
    Path(__file__).resolve().parents[2]
    / "apps" / "backend" / "app" / "modules" / "submission" / "docx_template.py",
    Path("/app/app/modules/submission/docx_template.py"),
)

_path = next((p for p in _CANDIDATES if p.exists()), None)
if _path is None:  # pragma: no cover
    raise ImportError("找不到 docx_template.py")

_spec = importlib.util.spec_from_file_location("paper_docx_template", _path)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
# 必须先注册进 sys.modules：@dataclass 在解析注解时会回查模块字典，
# 注册晚了会抛 AttributeError: 'NoneType' object has no attribute '__dict__'。
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

Meta = _mod.Meta
build = _mod.build
build_file = _mod.build_file
parse_meta = _mod.parse_meta
BODY_FONT = _mod.BODY_FONT
HEAD_FONT = _mod.HEAD_FONT
BODY_PT = _mod.BODY_PT

__all__ = ["Meta", "build", "build_file", "parse_meta", "BODY_FONT", "HEAD_FONT", "BODY_PT"]
