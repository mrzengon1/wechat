"""微信语音 → 文字（调用 PC 微信「语音转文字」）。"""

from __future__ import annotations

from typing import Any

from wx_backend import WxResponse

import config
from logger import log


def voice_to_text(msg: Any, who: str = "") -> str:
    """将语音消息转为文字；失败返回空串。"""
    if not config.ENABLE_VOICE:
        return ""
    if not hasattr(msg, "to_text"):
        log(f"[{who}] 语音无法转文字（消息类型不支持）")
        return ""

    try:
        log(f"[{who}] 语音转文字中…")
        result = msg.to_text()
        if isinstance(result, WxResponse):
            log(f"[{who}] 语音转文字失败：{result}")
            return ""
        text = str(result).strip()
        if not text or text.startswith("[语音]"):
            log(f"[{who}] 语音转文字无有效内容")
            return ""
        log(f"[{who}] 语音内容：{text!r}")
        return text
    except Exception as e:
        log(f"[{who}] 语音转文字异常：{e}")
        return ""
