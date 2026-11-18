"""跨模块的小工具：脱敏、时间格式化、编号生成。"""
from __future__ import annotations

import re
import secrets
from datetime import datetime

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)(\d{6})(\d{8})(\d{3}[\dXx])(?!\d)")


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 7:
        return "****"
    return f"{phone[:3]}****{phone[-4:]}"


def mask_sensitive(text: str) -> str:
    """对话落库前脱敏：手机号、身份证号。"""
    if not text:
        return text
    text = _PHONE_RE.sub(lambda m: f"{m.group(1)}****{m.group(3)}", text)
    text = _ID_CARD_RE.sub(lambda m: f"{m.group(1)}********{m.group(3)}", text)
    return text


def fmt_dt(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M")


def gen_no(prefix: str, width: int = 4) -> str:
    """生成业务编号：TK20261118001 形式（随机后缀，冲突概率极低）。"""
    today = datetime.now().strftime("%Y%m%d")
    return f"{prefix}{today}{secrets.randbelow(10**width):0{width}d}"
