"""回复后置校验：长度、不当答应、接外号、重复话术等。"""

from __future__ import annotations

import random
import re
from typing import Optional, Tuple

import config

_FORBIDDEN_COMPLY = re.compile(r"(好.?爸爸|叫.?爸爸|叫.?主人|主人好|爸爸好)")
_NICKNAME_ASSIGN = re.compile(r"^你叫(.+)$")
_REFUSE_MARKERS = (
    "才不",
    "不要",
    "不想",
    "不行",
    "谁这么叫",
    "有病",
    "做梦",
    "想得美",
    "哼",
    "别闹",
    "少来",
    "凭啥",
    "为啥",
    "滚",
    "拉倒",
    "得了",
)

_FEMALE_NICK_REFUSALS = (
    "哼，才不要呢",
    "谁这么叫啊",
    "你起的外号自己留着吧",
    "有病吧你",
    "想得美",
    "才不呢",
)
_FEMALE_BAD_CALL_REFUSALS = (
    "想得美",
    "哼，别闹",
    "你做梦呢",
    "才不要",
    "有病吧",
)
_MALE_NICK_REFUSALS = (
    "谁这么叫",
    "起啥外号啊",
    "别闹",
    "你自己叫吧",
)
_MALE_BAD_CALL_REFUSALS = (
    "别想",
    "做梦呢",
    "别闹了",
    "有病？",
)


def _extract_assigned_nickname(user_text: str) -> Optional[str]:
    t = user_text.strip()
    if "吗" in t or "?" in t or "？" in t:
        return None
    m = _NICKNAME_ASSIGN.match(t)
    if not m:
        return None
    name = m.group(1).strip()
    return name or None


def _user_wants_bad_call(user_text: str) -> bool:
    t = user_text.strip()
    keys = (
        "叫我爸爸",
        "叫我主人",
        "叫爸爸",
        "叫主人",
        "你叫我爸爸",
        "你叫我主人",
        "可以叫我",
    )
    return any(k in t for k in keys)


def _is_refusal(text: str) -> bool:
    return any(m in text for m in _REFUSE_MARKERS)


def _trim_length(text: str) -> str:
    limit = config.REPLY_MAX_CHARS
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit].rstrip("，,、 ")
    for sep in ("。", "！", "？", "…", "~"):
        if sep in cut:
            cut = cut.rsplit(sep, 1)[0] + sep
            return cut
    return cut + "。"


def _pick_refusal(user_text: str, gender_key: str, last_reply: str = "") -> str:
    if gender_key == "female":
        if _extract_assigned_nickname(user_text) or user_text.strip().startswith("你叫"):
            pool = _FEMALE_NICK_REFUSALS
        elif _user_wants_bad_call(user_text):
            pool = _FEMALE_BAD_CALL_REFUSALS
        else:
            pool = _FEMALE_BAD_CALL_REFUSALS
    else:
        if _extract_assigned_nickname(user_text) or user_text.strip().startswith("你叫"):
            pool = _MALE_NICK_REFUSALS
        elif _user_wants_bad_call(user_text):
            pool = _MALE_BAD_CALL_REFUSALS
        else:
            pool = _MALE_BAD_CALL_REFUSALS

    choices = [c for c in pool if c not in last_reply]
    text = random.choice(choices or pool)
    if text[-1] not in "。！？…~":
        text += "。"
    return text


def validate_reply(
    user_text: str, reply: str, last_reply: str = ""
) -> Tuple[str, bool]:
    text = reply.strip()
    if not text:
        return text, False

    text = _trim_length(text)

    if last_reply and text == last_reply.strip():
        return text, False

    if _user_wants_bad_call(user_text) or (
        "爸爸" in user_text and "叫" in user_text
    ):
        if _FORBIDDEN_COMPLY.search(text) and not _is_refusal(text):
            return text, False
        if "爸爸" in text and not _is_refusal(text):
            return text, False
        if "主人" in text and not _is_refusal(text):
            return text, False

    nick = _extract_assigned_nickname(user_text)
    if nick:
        if nick in text and not _is_refusal(text):
            return text, False
        accept_words = ("知道了", "行啊", "随你", "可以", "好啊", "嗯好", "没问题")
        if any(w in text for w in accept_words) and not _is_refusal(text):
            return text, False

    if "备注" in text and not any(
        k in user_text for k in ("备注", "叫什么", "称呼", "名字", "是谁", "怎么叫")
    ):
        return text, False

    for bad in ("好的，", "收到，", "当然可以", "没问题，"):
        if text.startswith(bad):
            text = text[len(bad) :].lstrip()

    return text, True


def sanitize_reply(
    user_text: str,
    reply: str,
    *,
    last_reply: str = "",
    gender_key: str = "female",
) -> Tuple[str, bool]:
    """校验并返回安全回复；(text, was_replaced)"""
    text, ok = validate_reply(user_text, reply, last_reply)
    if ok:
        return text, False
    fallback = _pick_refusal(user_text, gender_key, last_reply)
    return fallback, True
