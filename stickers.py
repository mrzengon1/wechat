"""微信收藏表情包（SendEmotion）选择与发送。"""

from __future__ import annotations

import random
from typing import Any, List, Optional

import config
from logger import log


def parse_indexes(raw: str) -> List[int]:
    if not raw.strip():
        return [0, 1, 2]
    out: List[int] = []
    for part in raw.replace("，", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out or [0, 1, 2]


def _send_ok(result: Any) -> bool:
    if result is None:
        return True
    if hasattr(result, "is_success"):
        return bool(result)
    if isinstance(result, dict) and "status" in result:
        return result.get("status") == "成功"
    return True


def pick_sticker_index(user_text: str, reply: str = "") -> int:
    indexes = config.STICKER_INDEXES
    blob = f"{user_text}{reply}"
    if any(k in blob for k in ("哈哈", "笑", "搞笑", "hh", "xswl", "乐", "逗")):
        pool = indexes[: max(1, len(indexes) // 2)] or indexes
    else:
        pool = indexes
    return random.choice(pool)


def decide_sticker_action(user_text: str, msg_type: str = "text") -> str:
    """
    返回：none | only | after_text
    对方发收藏表情包时，用收藏表情回（可附带文字）。
    """
    if not config.ENABLE_STICKER or not config.STICKER_INDEXES:
        return "none"

    if msg_type != "emotion":
        return "none"

    if random.random() < config.STICKER_ONLY_PROB:
        return "only"
    return "after_text"


def should_send_sticker(user_text: str, msg_type: str = "text") -> bool:
    return decide_sticker_action(user_text, msg_type) != "none"


def send_sticker(wx: Any, who: str, chat: Any, index: Optional[int] = None) -> bool:
    idx = index if index is not None else random.choice(config.STICKER_INDEXES)
    try:
        if chat is not None and hasattr(chat, "SendEmotion"):
            result = chat.SendEmotion(idx)
        elif hasattr(wx, "SendEmotion"):
            result = wx.SendEmotion(idx, who=who)
        else:
            log("  当前后端不支持 SendEmotion（免费 wxauto4 无此接口，需 Plus）")
            return False
        log(f"  SendEmotion(index={idx}) => {result}")
        return _send_ok(result)
    except Exception as e:
        log(f"  发送表情包失败：{e}")
        return False
