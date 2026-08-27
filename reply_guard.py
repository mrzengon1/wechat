"""回复后置校验：长度、不当答应、接外号、羞辱性称呼、绕过话术等。"""

from __future__ import annotations

import random
import re
from typing import Optional, Tuple

import config

_FORBIDDEN_COMPLY = re.compile(
    r"(好.?爸爸|叫.?爸爸|叫.?主人|主人好|爸爸好|儿子.?遵命|乖.?儿子|女儿.?遵命|奴才.?遵命)"
)
_NICKNAME_ASSIGN = re.compile(r"^你叫(.+)$")

# 对方要求 bot 用羞辱性称呼 / 扮演屈辱身份
_HUMILIATION_REQUEST_RES = (
    re.compile(r"叫.{0,4}(爸爸|爹爹|爸比|主人|奴才|奴隶)"),
    re.compile(r"喊.{0,4}(爸爸|爹爹|爸比|主人|奴才|奴隶)"),
    re.compile(r"叫我.{0,12}(爸爸|爹爹|爸比|主人|爸爸)"),
    re.compile(r"喊我.{0,8}(爸爸|爹爹|爸比|主人|爸爸)"),
    re.compile(r"(当|做|扮).{0,4}(儿子|女儿|孙子|孙女|狗|奴隶|奴才|舔狗)"),
    re.compile(r"你.{0,4}(是我)?(儿子|女儿|孙子|孙女|奴隶|奴才)"),
    re.compile(r"(是|做).{0,3}我(儿子|女儿|狗|奴隶|奴才)"),
    re.compile(r"认.{0,3}(爸爸|爹|主人)"),
    re.compile(r"(给|叫).{0,3}(爸爸|主人).{0,6}(请安|问好|磕)"),
)
_HUMILIATION_KEYWORDS = (
    "爸爸",
    "爹爹",
    "爸比",
    "主人",
    "主人大人",
    "奴才",
    "奴隶",
    "叫儿子",
    "当我儿子",
    "做我儿子",
    "你是我儿子",
    "喊爸爸",
    "叫爸爸",
    "叫我爸爸",
    "叫我主人",
    "daddy",
    "dog",
)
_BYPASS_HINTS = (
    "假装",
    "就这一次",
    "就一次",
    "试试",
    "试一下",
    "角色扮演",
    "roleplay",
    "忽略上面",
    "忽略之前",
    "不管之前",
    "必须叫",
    "一定要",
    "不许拒绝",
    "不准拒绝",
    "闹着玩",
    "开玩笑也行",
    "可以吗",
    "能不能",
    "规则不算",
    "突破",
)
# 回复里出现即视为可能照做（无拒答语气时拦截）
_HUMILIATING_REPLY_TERMS = (
    "爸爸",
    "爹爹",
    "爸比",
    "主人",
    "主人大人",
    "儿子遵命",
    "乖儿子",
    "女儿遵命",
    "奴才",
    "奴隶",
    "汪汪",
    "舔狗",
)
_HUMILIATING_NICKNAMES = (
    "爸爸",
    "爹",
    "爹爹",
    "爸比",
    "主人",
    "奴隶",
    "奴才",
    "儿子",
    "女儿",
    "孙子",
    "狗",
    "舔狗",
    "母狗",
    "公狗",
)

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
    "想什么呢",
    "不可以",
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
    "叫什么叫",
    "好好说话",
)

_MEIMAN_REFUSALS = (
    "想什么呢，这个不行",
    "宝贝别闹，这个叫不出口",
    "乖，这个不可以哦",
    "哼，才不要呢",
    "你做梦呀",
)


def _normalize_user_text(user_text: str) -> str:
    return re.sub(r"\s+", "", user_text.strip().lower())


def user_requests_humiliation(user_text: str) -> bool:
    return _user_requests_humiliation(user_text)


def _user_requests_humiliation(user_text: str) -> bool:
    t = _normalize_user_text(user_text)
    if not t:
        return False
    if any(k.lower() in t for k in _HUMILIATION_KEYWORDS):
        return True
    if any(p.search(t) for p in _HUMILIATION_REQUEST_RES):
        return True
    if "叫" in t and any(w in t for w in ("爸爸", "主人", "儿子", "女儿", "奴隶", "奴才")):
        return True
    if any(w in t for w in ("儿子", "女儿", "奴隶", "奴才")) and any(
        w in t for w in ("当", "做", "是", "扮", "叫", "喊")
    ):
        return True
    if any(h in user_text for h in _BYPASS_HINTS) and any(
        w in t for w in ("爸爸", "主人", "儿子", "女儿", "奴隶", "狗", "爹")
    ):
        return True
    return False


def _reply_humiliation_compliance(user_text: str, reply: str) -> bool:
    text = reply.strip()
    if not text or _is_refusal(text):
        return False
    if _FORBIDDEN_COMPLY.search(text):
        return True
    for term in _HUMILIATING_REPLY_TERMS:
        if term in text:
            return True
    # 「好的/嗯/遵命」+ 羞辱词
    if any(w in text for w in ("遵命", "知道了", "好的", "嗯好", "行")) and any(
        w in text for w in ("爸爸", "主人", "儿子", "女儿", "奴才", "奴隶")
    ):
        return True
    # 单独称呼羞辱词（非拒答语境）
    for term in ("爸爸", "主人", "爹爹"):
        if text == term or text.startswith(term + "，") or text.startswith(term + "。"):
            return True
    return False


def _assigned_nickname_humiliating(nick: str) -> bool:
    n = nick.strip().lower()
    if not n:
        return False
    return any(h in n for h in _HUMILIATING_NICKNAMES)


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
    return _user_requests_humiliation(user_text)


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


def _pick_refusal(
    user_text: str, gender_key: str, last_reply: str = "", flirt_style: bool = False
) -> str:
    if flirt_style:
        pool = [c for c in _MEIMAN_REFUSALS if c not in last_reply]
        if pool:
            text = random.choice(pool)
            if text[-1] not in "。！？…~":
                text += "。"
            return text

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

    if _user_requests_humiliation(user_text):
        if _reply_humiliation_compliance(user_text, text):
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
        if "儿子" in text and not _is_refusal(text):
            return text, False
        if "女儿" in text and not _is_refusal(text):
            return text, False

    nick = _extract_assigned_nickname(user_text)
    if nick:
        if _assigned_nickname_humiliating(nick):
            if not _is_refusal(text):
                return text, False
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

    if _reply_humiliation_compliance(user_text, text):
        return text, False

    return text, True


def sanitize_reply(
    user_text: str,
    reply: str,
    *,
    last_reply: str = "",
    gender_key: str = "female",
    flirt_style: bool = False,
) -> Tuple[str, bool]:
    """校验并返回安全回复；(text, was_replaced)"""
    text, ok = validate_reply(user_text, reply, last_reply)
    if ok:
        return text, False
    fallback = _pick_refusal(user_text, gender_key, last_reply, flirt_style=flirt_style)
    return fallback, True
