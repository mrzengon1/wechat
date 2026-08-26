"""微信客户端后端：免费 wxauto4（独立子窗口轮询）。"""

from __future__ import annotations

from typing import Any, Type

from wxauto4 import WeChat as _WeChat
from wxauto4.param import WxResponse as _WxResponse

WeChat: Type[Any] = _WeChat
WxResponse: Type[Any] = _WxResponse
BACKEND = "wxauto4"
# 免费版无官方 AddListenChat，用 open_separate_window + 子窗口轮询
HAS_LISTEN = False


def create_wechat(**kwargs: Any) -> Any:
    """创建微信实例。"""
    try:
        return WeChat(ads=False, **kwargs)
    except TypeError:
        return WeChat(**kwargs)


def backend_hint() -> str:
    return f"后端：{BACKEND} | 独立子窗口轮询（无需 Plus）"
