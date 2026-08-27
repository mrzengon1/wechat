"""
微信桌面版监听 + 大模型自动回复（wxauto4 / 微信 PC 4.1.x）。

LISTEN_MODE=selected → 只回复名单内联系人
LISTEN_MODE=all      → 回复所有新消息会话（可排除 IGNORE_NICKNAMES）

免费 wxauto4：用 open_separate_window 打开白名单独立子窗口并轮询；
安装已授权的 wxautox4（Plus）后优先用官方 AddListenChat。
"""

from __future__ import annotations

import random
import re
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple

import config
from llm import LLMReplier
from logger import log
from stickers import decide_sticker_action, pick_sticker_index, send_sticker
from subwindows import open_whitelist_subchats
from voice import voice_to_text
from wx_backend import (
    HAS_LISTEN,
    WeChat,
    WxResponse,
    backend_hint,
    create_wechat,
)


def _msg_attr(msg: Any) -> str:
    return str(getattr(msg, "attr", "") or "")


def _msg_type(msg: Any) -> str:
    return str(getattr(msg, "type", "") or "")


def _msg_content(msg: Any) -> str:
    return (getattr(msg, "content", None) or "").strip()


_HUMAN_ATTRS = ("self", "friend", "other")


def _is_from_friend(msg: Any) -> bool:
    return _msg_attr(msg).lower() in ("friend", "other", "")


def _get_chat_msgs(chat: Any) -> List[Any]:
    if chat is None:
        return []
    try:
        if hasattr(chat, "GetAllMessage"):
            return list(chat.GetAllMessage() or [])
        if hasattr(chat, "_api") and hasattr(chat._api, "get_msgs"):
            return list(chat._api.get_msgs() or [])
        if hasattr(chat, "_api") and hasattr(chat._api, "_chat_api"):
            return list(chat._api._chat_api.get_msgs() or [])
    except Exception:
        pass
    return []


def _is_usable_text_msg(msg: Any) -> bool:
    mtype = _msg_type(msg) or "text"
    if mtype not in ("text", "quote"):
        return False
    return bool(_msg_content(msg))


def _msgs_to_context(
    msgs: List[Any],
    limit: int,
    who: str = "",
    chat: Any = None,
    wx: Any = None,
) -> List[Dict[str, str]]:
    """把微信消息转成 LLM 对话上下文（对方=user，我=assistant）。"""
    pairs: List[Dict[str, str]] = []
    group = bool(who) and _is_group_chat(who, chat, wx)
    for msg in msgs:
        attr = _msg_attr(msg).lower()
        if attr not in _HUMAN_ATTRS:
            continue
        if not _is_usable_text_msg(msg):
            continue
        content = _msg_content(msg)
        if group and attr != "self":
            sender = _msg_sender(msg)
            if sender:
                content = f"[群·{sender}] {content}"
        role = "assistant" if attr == "self" else "user"
        pairs.append({"role": role, "content": content})
    if limit > 0:
        return pairs[-limit:]
    return pairs


def _normalize_ctx_compare(text: str) -> str:
    """去掉群前缀，便于比对「当前消息」与上下文最后一条。"""
    t = (text or "").strip()
    if t.startswith("[群·") and "]" in t:
        t = t.split("]", 1)[1].strip()
    if t.startswith("[群聊]"):
        t = t[5:].strip()
    return t


def _trim_context_for_reply(
    context: List[Dict[str, str]], user_text: str
) -> List[Dict[str, str]]:
    """去掉与当前待回复消息重复的最后一条 user。"""
    if not context:
        return []
    ctx = list(context)
    user_norm = _normalize_ctx_compare(user_text)
    while ctx:
        last = ctx[-1]
        if last.get("role") != "user":
            break
        last_norm = _normalize_ctx_compare(last.get("content", ""))
        if last_norm == user_norm or (user_norm and last_norm in user_norm):
            ctx.pop()
        else:
            break
    return ctx


def _self_samples_from_msgs(msgs: List[Any], limit: int) -> List[str]:
    """提取「我」发出的文字，用于学习语气。"""
    samples: List[str] = []
    for msg in msgs:
        if _msg_attr(msg).lower() != "self":
            continue
        if not _is_usable_text_msg(msg):
            continue
        text = _msg_content(msg)
        if text and text not in samples:
            samples.append(text)
    if limit > 0:
        return samples[-limit:]
    return samples


def _msg_key(msg: Any) -> str:
    mid = getattr(msg, "id", None)
    if mid:
        return f"id:{mid}"
    h = getattr(msg, "hash", None)
    if h:
        return f"h:{h}"
    return f"{_msg_attr(msg)}|{_msg_type(msg)}|{_msg_content(msg)}"


def _chat_for_name(wx: Any, name: str, current_chat: Any = None, current_who: str = "") -> Any:
    """取白名单会话：优先子窗口/listen，必要时 ChatWith（会切主窗口）。"""
    if current_chat is not None and name == current_who:
        return current_chat
    try:
        listen = getattr(wx, "listen", None) or {}
        if name in listen:
            chat = listen[name][0]
            if chat is not None:
                return chat
    except Exception:
        pass
    try:
        if hasattr(wx, "GetSubWindow"):
            sub = wx.GetSubWindow(name)
            if sub is not None:
                return sub
    except Exception:
        pass
    try:
        wx.ChatWith(name)
        time.sleep(0.25)
        return wx
    except Exception:
        return None


def _collect_chat_context(
    chat: Any,
    who: str = "",
    wx: Any = None,
    user_text: str = "",
) -> List[Dict[str, str]]:
    if not config.USE_CHAT_HISTORY:
        return []
    msgs = _get_chat_msgs(chat)
    if not msgs:
        return []
    from llm import _is_technical_question

    technical = _is_technical_question(user_text)
    limit = (
        config.WECHAT_CONTEXT_LIMIT_TECHNICAL
        if technical
        else config.WECHAT_CONTEXT_LIMIT
    )
    ctx = _msgs_to_context(msgs, limit, who=who, chat=chat, wx=wx)
    return _trim_context_for_reply(ctx, user_text)


def _collect_tone_samples(
    wx: Any,
    chat: Any,
    who: str,
    allowed_names: Optional[set] = None,
) -> Tuple[List[str], str]:
    """
    仅从【当前会话】提取「我」的历史发言，供「模仿正常」学习语气。
    不借用其他白名单。
    """
    del wx, allowed_names  # 仅当前会话
    limit = max(1, config.TONE_SAMPLE_LIMIT)
    current_msgs = _get_chat_msgs(chat)
    samples = _self_samples_from_msgs(current_msgs, limit)
    if not samples:
        return [], ""
    return samples[-limit:], "当前会话"


def _latest_human_msg(msgs: List[Any]) -> Any | None:
    for msg in reversed(msgs):
        if _msg_attr(msg).lower() in _HUMAN_ATTRS:
            return msg
    return None


_ACK_EXACT = frozenset(
    {
        "收到",
        "好的",
        "好",
        "嗯",
        "嗯嗯",
        "哦",
        "噢",
        "喔",
        "行",
        "行吧",
        "好吧",
        "好啦",
        "ok",
        "okay",
        "k",
        "可以",
        "知道了",
        "明白",
        "懂了",
        "好哒",
        "好滴",
        "谢谢",
        "谢了",
        "3q",
        "thanks",
        "thx",
    }
)


def _normalize_ack_text(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("[群·") and "]" in t:
        t = t.split("]", 1)[1].strip()
    if t.startswith("[群聊]"):
        t = t[5:].strip()
    t = re.sub(r"[。！？!?,，~～…\.]+$", "", t)
    t = re.sub(r"\[.*?\]$", "", t).strip()
    return t.strip().lower()


def _is_ack_text(text: str) -> bool:
    t = _normalize_ack_text(text)
    if not t:
        return False
    if t in _ACK_EXACT:
        return True
    compact = t.replace(" ", "")
    return compact in _ACK_EXACT


def _is_ack_message(
    msg: Any, who: str = "", chat: Any = None, wx: Any = None
) -> bool:
    raw = _msg_content(msg)
    if _is_ack_text(raw):
        return True
    if who:
        resolved = _resolve_user_text(msg, who, chat, wx)
        return _is_ack_text(resolved)
    return False


def _should_reply_opening_message(
    msg: Any,
    who: str,
    chat: Any,
    wx: Any,
    aliases: Optional[Set[str]] = None,
    allowed_names: Optional[set] = None,
) -> bool:
    """打开白名单会话时，判断最新一条是否值得回复。"""
    if not _is_from_friend(msg):
        return False
    if _msg_attr(msg).lower() == "self":
        return False
    if not _should_handle_msg(msg, wx, who, chat, aliases):
        return False
    if _group_reply_skip_reason(msg, who, chat, wx, aliases, allowed_names):
        return False
    if _is_ack_message(msg, who, chat, wx):
        return False
    return True


def _same_msg(a: Any, b: Any) -> bool:
    if a is b:
        return True
    aid = getattr(a, "id", None)
    bid = getattr(b, "id", None)
    if aid and bid:
        return aid == bid
    ahash = getattr(a, "hash", None)
    bhash = getattr(b, "hash", None)
    if ahash and bhash:
        return ahash == bhash
    return _msg_content(a) == _msg_content(b) and _msg_attr(a) == _msg_attr(b)


def _should_reply_to_msg(
    msg: Any,
    chat: Any,
    who: str = "",
    wx: Any = None,
    allow_not_latest: bool = False,
) -> bool:
    """仅当最新一条有效消息是对方发的时才回复；自己发的 / 纯确认语跳过。"""
    if not _is_from_friend(msg):
        log(f"  跳过：自己/系统消息 attr={_msg_attr(msg)}")
        return False

    if _is_ack_message(msg, who, chat, wx):
        log("  跳过：确认语（收到/好的/ok 等），无需回复")
        return False

    if allow_not_latest:
        return True

    msgs = _get_chat_msgs(chat)
    if not msgs:
        return True

    latest = _latest_human_msg(msgs)
    if latest is None:
        return False

    if _msg_attr(latest).lower() == "self":
        log("  跳过：最新一条是自己发的，继续监听")
        return False

    if not _same_msg(msg, latest):
        log("  跳过：不是会话最新一条，继续监听")
        return False

    return True


def _should_handle_msg(
    msg: Any,
    wx: Any = None,
    who: str = "",
    chat: Any = None,
    aliases: Optional[Set[str]] = None,
) -> bool:
    attr = _msg_attr(msg)
    if attr in ("self", "system", "time", "tickle"):
        log(f"  跳过：attr={attr}")
        return False
    if attr and attr not in ("friend", "other", ""):
        log(f"  提示：非常见 attr={attr}，继续尝试")

    mtype = _msg_type(msg) or "text"
    if mtype == "emotion" and config.ENABLE_STICKER:
        return True
    if mtype == "voice" and config.ENABLE_VOICE:
        return True

    if wx is not None and _is_directed_at_me(msg, wx, chat, who, aliases):
        return True

    if config.TEXT_ONLY:
        if mtype not in ("text", "quote"):
            log(f"  跳过非文本：type={mtype}")
            return False

    if mtype == "emotion":
        return True
    return bool(_msg_content(msg))


def _resolve_user_text(msg: Any, who: str, chat: Any, wx: Any) -> str:
    """解析 incoming 文本；语音会先转文字。"""
    mtype = _msg_type(msg) or "text"
    if mtype == "voice" and config.ENABLE_VOICE:
        text = voice_to_text(msg, who)
        if not text:
            return ""
    else:
        text = _msg_content(msg)
        if mtype == "emotion" and not text:
            text = "[表情包]"

    if _is_group_chat(who, chat, wx):
        sender = _msg_sender(msg)
        if sender:
            return f"[群·{sender}] {text}"
        return f"[群聊] {text}"
    return text


def _is_group_chat(who: str, chat: Any, wx: Any) -> bool:
    try:
        if chat is not None and hasattr(chat, "ChatInfo"):
            if chat.ChatInfo().get("chat_type") == "group":
                return True
        if wx is not None and hasattr(wx, "ChatBox"):
            if wx.ChatBox.get_info().get("chat_type") == "group":
                return True
    except Exception:
        pass
    return _looks_like_group(who)


def _msg_sender(msg: Any) -> str:
    for attr in ("sender_remark", "sender"):
        val = getattr(msg, attr, None)
        if isinstance(val, str) and val.strip():
            s = val.strip()
            if s not in ("friend", "self", "system", "other"):
                return s
    return ""


_EMAIL_AT_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
# 微信 @ 后常有 \u2005 薄空格；也可能紧挨中文如 鹏@Fan
_AT_NAME_PATTERN = re.compile(
    r"\{@([^}]+)\}|@(?:[\u2005\u2006\u2009\s]*)([^\s@，,。！？!?：:;；\r\n]+)"
)


def _name_matches_alias(name: str, aliases: Set[str]) -> bool:
    n = (name or "").strip()
    if not n or not aliases:
        return False
    if n in aliases:
        return True
    n_low = n.lower()
    for alias in aliases:
        if alias in n or n in alias:
            return True
        if n_low == alias.lower():
            return True
    return False


def _extract_at_names(text: str) -> List[str]:
    if not text:
        return []
    scrubbed = _EMAIL_AT_PATTERN.sub(" ", text)
    names: List[str] = []
    for match in _AT_NAME_PATTERN.finditer(scrubbed):
        name = (match.group(1) or match.group(2) or "").strip()
        if name:
            names.append(name)
    return names


def _collect_at_names(msg: Any, aliases: Optional[Set[str]] = None) -> List[str]:
    names = _extract_at_names(_msg_text_blob(msg))
    for attr in ("at_list", "at_users", "at_user_list", "mention_list"):
        val = getattr(msg, attr, None)
        items: List[str] = []
        if isinstance(val, str):
            items = [val]
        elif isinstance(val, (list, tuple, set)):
            items = [str(x) for x in val if x]
        for item in items:
            name = str(item).strip()
            if name:
                names.append(name)
    seen: Set[str] = set()
    out: List[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _is_at_others_not_me(msg: Any, aliases: Optional[Set[str]]) -> bool:
    """消息里 @ 了别人且没有 @ 我。"""
    if not aliases:
        return False
    names = _collect_at_names(msg, aliases)
    if not names:
        return False
    if any(_name_matches_alias(n, aliases) for n in names):
        return False
    return True


_ASK_CONTACT_ME_RES = (
    re.compile(r"让.{0,18}(叫|联系|找|喊|@).{0,12}(我|咱|俺|你)"),
    re.compile(r"(叫|联系|找|喊).{0,6}(我|咱|俺|你)(?:吧|啊|呢|哈|嘛|呗|[，,。！？]|$)"),
    re.compile(r"(联系我|找我|叫我|喊我|联系你|找你|叫你|喊你)"),
    re.compile(r"让.{0,24}教.{0,4}你"),
    re.compile(r"教.{0,4}你(?:玩|一下|呗|吗)?"),
    re.compile(r"带你(?:玩|一起)"),
)
_BOT_ACTION_RES = (
    re.compile(r"^(你|您)(去|帮|让|问|找|联系|叫|喊)"),
    re.compile(r"[，,。！？\n](你|您)(去|帮|让|问|找|联系|叫|喊)"),
)
# @ 别人后紧跟「你+动作」通常是在跟被 @ 的人说，不是找 bot
_AT_THEN_YOU_ACTION = re.compile(
    r"@[^\s\u2005\u2006\u2009@，,。！？!?：:;；{}\[\]]+\s*你(去|帮|让|问|找|联系|叫|喊)"
)


def _strip_at_tokens(text: str) -> str:
    scrubbed = _EMAIL_AT_PATTERN.sub(" ", text or "")
    scrubbed = re.sub(r"\{@([^}]+)\}", " ", scrubbed)
    scrubbed = re.sub(
        r"@[^\s\u2005\u2006\u2009@，,。！？!?：:;；{}\[\]\r\n]+",
        " ",
        scrubbed,
    )
    return re.sub(r"\s+", " ", scrubbed).strip()


def _asks_others_contact_me(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(p.search(t) for p in _ASK_CONTACT_ME_RES)


def _addresses_bot_to_act(text: str, *, at_others_not_me: bool) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if at_others_not_me and _AT_THEN_YOU_ACTION.search(t):
        return False
    stripped = _strip_at_tokens(t)
    return any(p.search(stripped) for p in _BOT_ACTION_RES)


def _is_indirect_address_to_me(
    msg: Any, aliases: Optional[Set[str]] = None
) -> bool:
    """@ 了别人但实际在找 bot：让别人联系 bot / 让 bot 去找别人等。"""
    text = _msg_text_blob(msg).strip()
    if not text:
        return False
    at_others = _is_at_others_not_me(msg, aliases)
    if _asks_others_contact_me(text):
        return True
    return _addresses_bot_to_act(text, at_others_not_me=at_others)


def _is_directed_at_me(
    msg: Any,
    wx: Any,
    chat: Any,
    who: str,
    aliases: Optional[Set[str]] = None,
) -> bool:
    """@ 我，或语义上在找 bot（含间接）。"""
    if _is_at_me(msg, wx, chat, who, aliases):
        return True
    return _is_indirect_address_to_me(msg, aliases)


def _collect_self_aliases(wx: Any) -> Set[str]:
    """收集可用于识别 @ 我的昵称/备注。"""
    aliases: Set[str] = set()
    if config.BOT_REAL_NAME:
        aliases.add(config.BOT_REAL_NAME.strip())

    for name in config.AT_ALIASES:
        n = (name or "").strip()
        if n:
            aliases.add(n)

    for source in (
        getattr(wx, "nickname", None),
        getattr(wx, "NickName", None),
    ):
        if isinstance(source, str) and source.strip():
            aliases.add(source.strip())

    for info_src in (
        (lambda: wx.GetMyInfo() if hasattr(wx, "GetMyInfo") else None),
        (lambda: getattr(wx, "myinfo", None)),
    ):
        try:
            info = info_src()
        except Exception:
            info = None
        if isinstance(info, dict):
            for key in ("display_name", "nickname", "name", "id"):
                val = info.get(key)
                if isinstance(val, str) and val.strip():
                    aliases.add(val.strip())

    return {a for a in aliases if a}


def _msg_text_blob(msg: Any) -> str:
    parts: List[str] = []
    for attr in ("content", "hash_text"):
        val = getattr(msg, attr, None)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    for attr in ("quote_content", "quote_nickname"):
        val = getattr(msg, attr, None)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    for attr in ("at_list", "at_users", "at_user_list", "mention_list"):
        val = getattr(msg, attr, None)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
        elif isinstance(val, (list, tuple, set)):
            for item in val:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
    return "\n".join(parts)


def _text_mentions_alias(text: str, alias: str) -> bool:
    if not text or not alias:
        return False
    escaped = re.escape(alias)
    flags = re.IGNORECASE if alias.isascii() else 0
    patterns = (
        rf"@(?:[\u2005\u2006\u2009\s]*){escaped}(?:[\u2005\u2006\u2009\s，,。！？!?：:;；]|\r|\n|$)",
        rf"\{{@\s*{escaped}\s*}}",
        rf"[\u4e00-\u9fff]{escaped}(?:[\u2005\u2006\u2009\s，,。！？!?：:;；]|\r|\n|$)",
    )
    scrubbed = _EMAIL_AT_PATTERN.sub(" ", text)
    for pat in patterns:
        if re.search(pat, scrubbed, flags):
            return True
    return False


def _is_at_me(
    msg: Any,
    wx: Any,
    chat: Any,
    who: str,
    aliases: Optional[Set[str]] = None,
) -> bool:
    """判断群消息是否 @ 了我（排除邮箱里的 @）。"""
    if aliases is None:
        aliases = _collect_self_aliases(wx)

    blob = _msg_text_blob(msg)
    if blob and aliases:
        scrubbed = _EMAIL_AT_PATTERN.sub(" ", blob)
        for alias in sorted(aliases, key=len, reverse=True):
            if _text_mentions_alias(scrubbed, alias):
                return True

    for attr in ("at_list", "at_users", "at_user_list", "mention_list"):
        val = getattr(msg, attr, None)
        items: List[str] = []
        if isinstance(val, str):
            items = [val]
        elif isinstance(val, (list, tuple, set)):
            items = [str(x) for x in val if x]
        for item in items:
            name = str(item).strip()
            if not name:
                continue
            if aliases and _name_matches_alias(name, aliases):
                return True
    return False


def _group_reply_skip_reason(
    msg: Any,
    who: str,
    chat: Any,
    wx: Any,
    aliases: Optional[Set[str]] = None,
    allowed_names: Optional[set] = None,
) -> Optional[str]:
    """群聊过滤：返回跳过原因；None 表示可继续处理。"""
    if not _is_group_chat(who, chat, wx):
        return None
    if config.TARGET_NICKNAMES and not _allowed_who(who, allowed_names):
        return "群不在白名单"
    if config.GROUP_SKIP_AT_OTHERS and _is_at_others_not_me(msg, aliases):
        if not _is_indirect_address_to_me(msg, aliases):
            at_names = _collect_at_names(msg, aliases)
            return f"消息 @ 了别人（{','.join(at_names[:3])}）"
    return None


def _format_incoming(msg: Any, who: str, chat: Any, wx: Any) -> str:
    return _resolve_user_text(msg, who, chat, wx)


def _looks_like_group(who: str) -> bool:
    markers = ("群", "集团", "交流群", "粉丝群", "客户群")
    return any(m in who for m in markers)


def _allowed_who(who: str, allowed_names: Optional[set] = None) -> bool:
    if not who:
        return False
    who = who.strip()
    if who in config.IGNORE_NICKNAMES:
        return False
    if config.LISTEN_MODE == "selected":
        names = allowed_names if allowed_names is not None else set(config.TARGET_NICKNAMES)
        if who in names:
            return True
        # 备注名与会话显示名不完全一致时的宽松匹配
        for target in names:
            if who == target or who in target or target in who:
                return True
        return False
    if not config.REPLY_GROUP_CHATS and _looks_like_group(who):
        return False
    return True


def _chat_who(chat: Any, fallback: str = "") -> str:
    for attr in ("who", "nickname", "name", "Name"):
        val = getattr(chat, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip()
    if chat is not None and not isinstance(chat, (str, bytes)):
        s = str(chat).strip()
        if s and not s.startswith("<") and s not in ("None",):
            return s
    return fallback


def _send_ok(result: Any) -> bool:
    if result is None:
        return True
    if isinstance(result, WxResponse):
        return bool(result)
    if isinstance(result, dict) and "status" in result:
        return result.get("status") == "成功"
    return True


def _send_text(wx: WeChat, msg: Any, who: str, text: str, chat: Any = None) -> None:
    if chat is not None and hasattr(chat, "SendMsg"):
        result = chat.SendMsg(text)
        if _send_ok(result):
            return
    if hasattr(msg, "reply"):
        try:
            result = msg.reply(text)
            if _send_ok(result):
                return
        except Exception:
            pass
    result = wx.SendMsg(text, who=who)
    if not _send_ok(result):
        raise RuntimeError(f"发送失败：{result}")


def _normalize_new_messages(raw: Any) -> List[Tuple[str, List[Any]]]:
    if not raw:
        return []
    # wxauto 新版：{'chat_name': '...', 'msg': [...]}
    if isinstance(raw, dict) and "chat_name" in raw and "msg" in raw:
        msgs = raw["msg"]
        if not isinstance(msgs, list):
            msgs = [msgs] if msgs else []
        who = str(raw["chat_name"]).strip()
        return [(who, msgs)] if who and msgs else []
    if isinstance(raw, dict):
        out: List[Tuple[str, List[Any]]] = []
        for key, msgs in raw.items():
            if key in ("chat_type", "msg", "chat_name"):
                continue
            who = key if isinstance(key, str) else _chat_who(key)
            if not isinstance(msgs, list):
                msgs = [msgs] if msgs else []
            if who and msgs:
                out.append((who, msgs))
        return out
    return []


class Monitor:
    def __init__(
        self, persona_key: str = "default", gender_key: str = "male"
    ) -> None:
        from personas import (
            build_system_prompt,
            get_style_label,
            resolve_persona,
        )

        try:
            self.wx = create_wechat()
        except Exception as e:
            msg = str(e)
            hint = (
                "\n\n无法连接微信窗口。当前项目依赖 wxauto4，需【微信 PC 4.1.x】"
                "（推荐锁定 4.1.8.107）。\n"
                "请安装并登录对应版本，保持主窗口打开后再运行。\n"
                "下载参考：https://github.com/SiverKing/wechat4.0-windows-versions/releases\n"
            )
            raise SystemExit(f"{msg}{hint}") from e

        gender_key, persona_key = resolve_persona(gender_key, persona_key)
        display = get_style_label(persona_key)
        prompt = build_system_prompt(gender_key, persona_key)
        self.persona_key = persona_key
        self.gender_key = gender_key
        self.llm = LLMReplier(
            system_prompt=prompt,
            persona_name=display,
            gender_key=gender_key,
            persona_key=persona_key,
        )
        self._last_reply_at: Dict[str, float] = {}
        self._allowed_names: set = set()
        self._seen_keys: Dict[str, Set[str]] = {}
        self._primed_chats: Set[str] = set()
        self._sub_chats: Dict[str, Any] = {}
        self._free_subwindow_mode = False
        self._subwindow_fail_count: Dict[str, int] = {}
        self._subwindow_reopen_at: Dict[str, float] = {}
        self._sub_poll_cursor = 0
        self._sub_last_idle_poll = 0.0
        self._sub_last_read_at: Dict[str, float] = {}
        self._wl_sessions: List[Tuple[str, str, Any]] = []
        self._wl_sessions_at = 0.0
        self._wl_sessions_lock = threading.Lock()
        self._sub_monitor_threads: List[threading.Thread] = []
        self._self_aliases: Set[str] = _collect_self_aliases(self.wx)
        self._stop = False
        self._style_lock = threading.Lock()
        self._listen_mode = config.LISTEN_MODE
        mode = self._listen_mode
        log(f"微信已连接 | 模式：{mode} | {backend_hint()}")
        log(f"当前风格：{display}  [{persona_key}]")
        if mode == "selected":
            log(f"白名单：{config.TARGET_NICKNAMES}")
            if config.GROUP_SKIP_AT_OTHERS:
                log(
                    f"群聊：@ 我立即回；未 @ 降频（{config.GROUP_REPLY_INTERVAL}s）；"
                    "仅 @ 别人不回"
                )
                if self._self_aliases:
                    log(f"@ 识别别名：{sorted(self._self_aliases)}")
                elif any(_looks_like_group(n) for n in config.TARGET_NICKNAMES):
                    log(
                        "提示：群聊 @ 英文名/群名片请在 .env 设置 AT_ALIASES=Fan"
                        "（多个用顿号），否则 @Fan 可能识别不到"
                    )
            else:
                log("支持私聊与群聊（群名写入白名单即可）")
        else:
            log(f"全量监听 | 忽略：{config.IGNORE_NICKNAMES}")
            log(f"回复群聊：{config.REPLY_GROUP_CHATS}")
        log(
            f"连发多条逐条回复；单条仍等最新（历史={'开' if config.USE_CHAT_HISTORY else '关'}）"
        )
        if self.persona_key == "mimic":
            log("风格「模仿正常」：根据当前会话历史模仿你的语气")
        log(f"模型：{config.LLM_MODEL} @ {config.LLM_BASE_URL}")
        if config.ENABLE_VOICE:
            log("语音消息：自动转文字后回复")
        if config.ENABLE_STICKER:
            if hasattr(self.wx, "SendEmotion"):
                log(f"表情包下标：{config.STICKER_INDEXES}")
            else:
                log("表情包：当前免费版无 SendEmotion，收到表情时仅文字回复")

    def stop(self) -> None:
        self._stop = True
        if self._listen_mode == "selected":
            self._teardown_listeners()

    def apply_style(self, gender_key: str, persona_key: str) -> str:
        """运行中切换回复风格（线程安全）。"""
        from personas import (
            build_system_prompt,
            get_style_label,
            resolve_persona,
        )

        gender_key, persona_key = resolve_persona(gender_key, persona_key)
        display = get_style_label(persona_key)
        prompt = build_system_prompt(gender_key, persona_key)
        self.gender_key = gender_key
        self.persona_key = persona_key
        self.llm.apply_style(prompt, display, gender_key, persona_key)
        log(f"风格已切换 → {display}")
        return display

    def apply_listen_config(self) -> tuple[bool, str]:
        """运行中应用监听配置（白名单、群聊、历史）；模式变更需重启。"""
        config.reload_listen_config()
        notes: List[str] = []

        if config.LISTEN_MODE != self._listen_mode:
            notes.append("监听模式已保存，请停止后重新「开始监听」生效")

        with self._style_lock:
            self.llm.apply_history_setting()

        self._self_aliases = _collect_self_aliases(self.wx)
        if self._self_aliases:
            log(f"@ 识别别名：{sorted(self._self_aliases)}")

        if config.LISTEN_MODE == "selected" and self._listen_mode == "selected":
            self._allowed_names = set(config.TARGET_NICKNAMES)
            if HAS_LISTEN:
                self._setup_selected_listeners()
            else:
                # 运行中改白名单需重启监听，避免反复 open/搜索导致子窗口来回切
                notes.append(
                    "白名单已保存；请停止后重新「开始监听」以打开新子窗口"
                )
            notes.append(f"白名单：{sorted(self._allowed_names)}")
        elif config.LISTEN_MODE == "all" and self._listen_mode == "all":
            notes.append(
                f"群聊回复：{'开' if config.REPLY_GROUP_CHATS else '关'}"
            )

        notes.append(
            f"聊天历史：{'开' if config.USE_CHAT_HISTORY else '关'}"
        )
        msg = "；".join(notes)
        log(f"监听配置已应用 · {msg}")
        need_restart = config.LISTEN_MODE != self._listen_mode
        return need_restart, msg

    def _make_listen_callback(self, configured_name: str):
        def callback(msg: Any, chat: Any, _name: str = configured_name) -> None:
            if self._stop:
                return
            who = getattr(chat, "who", None) or _name
            if isinstance(who, str) and who.strip():
                self._allowed_names.add(who.strip())
            self.handle_one(msg, who, chat=chat)

        return callback

    def _setup_selected_listeners(self) -> None:
        """Plus：AddListenChat；免费版：open_separate_window 子窗口。"""
        if not HAS_LISTEN:
            self._setup_free_subwindows()
            return

        self._teardown_listeners()
        added: List[str] = []
        for name in config.TARGET_NICKNAMES:
            try:
                result = self.wx.AddListenChat(
                    name, self._make_listen_callback(name)
                )
                if isinstance(result, WxResponse):
                    log(f"无法监听 {name!r}：{result}")
                    continue
                chat_name = getattr(result, "who", name) or name
                self._allowed_names.add(name)
                self._allowed_names.add(chat_name)
                added.append(chat_name)
                log(f"已监听：{chat_name}")
            except Exception as e:
                log(f"无法监听 {name!r}：{e}")
        if not added:
            raise RuntimeError(
                "白名单监听均未建立，请检查 TARGET_NICKNAMES 是否与会话名一致"
            )
        if hasattr(self.wx, "StartListening"):
            self.wx.StartListening()
        log(f"仅监听 {len(added)} 个会话，不会查看其他聊天")

    def _setup_free_subwindows(self) -> None:
        """免费版：为白名单打开独立聊天子窗口。"""
        self._free_subwindow_mode = True
        self._subwindow_fail_count.clear()
        self._subwindow_reopen_at.clear()
        self._allowed_names = set(config.TARGET_NICKNAMES)
        self._sub_chats = open_whitelist_subchats(
            self.wx, list(config.TARGET_NICKNAMES)
        )
        if not self._sub_chats:
            raise RuntimeError(
                "未能打开任何白名单子窗口，请检查 TARGET_NICKNAMES 是否与会话名一致，"
                "并保持微信主窗口可见"
            )
        for name in config.TARGET_NICKNAMES:
            chat = self._resolve_sub_chat(name)
            if chat is None:
                continue
            self._allowed_names.add(chat.who)
            try:
                self._poll_one_chat(name, chat=chat)
                now = time.time()
                self._sub_last_read_at[name] = now
                self._sub_last_read_at[getattr(chat, "who", name) or name] = now
            except Exception:
                log(f"[{name}] 子窗口首次同步异常：\n{traceback.format_exc()}")
        uniq = {id(c): c.who for c in self._unique_sub_chats()}
        n = len(uniq)
        names = ", ".join(sorted({c.who for c in self._unique_sub_chats()}))
        want = len(config.TARGET_NICKNAMES)
        if n < want:
            log(
                f"警告：只打开了 {n}/{want} 个子窗口（{names}）；"
                "请确认白名单每项都是会话列表里的完整备注名，且互不重复"
            )
        mode = config.SUBWINDOW_MONITOR
        poll = config.SUBWINDOW_POLL_MODE
        if mode == "threads":
            log(
                f"已打开 {n} 个子窗口：{names}；threads 监控"
                f"（心跳 {config.SUBWINDOW_READ_INTERVAL}s）"
            )
        elif poll == "all":
            log(f"已打开 {n} 个子窗口：{names}；all 模式每 {config.POLL_INTERVAL}s 全读")
        else:
            log(
                f"已打开 {n} 个子窗口：{names}；{poll} 门控"
                f"（未读立即读 / 心跳 {config.SUBWINDOW_READ_INTERVAL}s）"
            )

    def _teardown_listeners(self) -> None:
        try:
            if HAS_LISTEN and hasattr(self.wx, "StopListening"):
                self.wx.StopListening(remove=True)
        except Exception:
            pass
        self._sub_chats.clear()

    def _build_whitelist(self) -> None:
        """仅解析白名单名称，不切换主窗口会话。"""
        self._allowed_names = set(config.TARGET_NICKNAMES)
        log(f"白名单：{sorted(self._allowed_names)}")

    def _allowed(self, who: str) -> bool:
        return _allowed_who(who, self._allowed_names)

    def _in_cooldown(
        self,
        who: str,
        chat: Any = None,
        at_me: bool = False,
        batch_mode: bool = False,
    ) -> bool:
        last = self._last_reply_at.get(who, 0.0)
        if batch_mode:
            interval = config.BATCH_REPLY_INTERVAL
        elif not at_me and _is_group_chat(who, chat, self.wx):
            interval = config.GROUP_REPLY_INTERVAL
        else:
            interval = config.MIN_REPLY_INTERVAL
        return time.time() - last < interval

    def _unique_sub_chats(self) -> List[Any]:
        seen: Set[int] = set()
        out: List[Any] = []
        for name in config.TARGET_NICKNAMES:
            chat = self._resolve_sub_chat(name)
            if chat is None:
                continue
            cid = id(chat)
            if cid in seen:
                continue
            seen.add(cid)
            out.append(chat)
        return out

    def _resolve_sub_chat(self, who: str) -> Any | None:
        if who in self._sub_chats:
            return self._sub_chats[who]
        for key, chat in self._sub_chats.items():
            if who == key or who in key or key in who:
                return chat
        return None

    def _poll_one_chat(self, who: str, chat: Any = None) -> None:
        """同步或处理新增消息；优先使用已打开的子窗口，避免切主窗口。"""
        if chat is None:
            chat = self._resolve_sub_chat(who)
            if chat is None and self._free_subwindow_mode:
                return
            if chat is None:
                chat = self._prepare_chat(who)
        if self._free_subwindow_mode and chat is self.wx:
            return
        msgs = _get_chat_msgs(chat)
        keys = [_msg_key(m) for m in msgs]

        if who not in self._primed_chats:
            self._seen_keys[who] = set(keys)
            self._primed_chats.add(who)
            latest = _latest_human_msg(msgs)
            if latest is not None and _should_reply_opening_message(
                latest,
                who,
                chat,
                self.wx,
                self._self_aliases,
                self._allowed_names,
            ):
                log(f"[{who}] 打开会话：最新一条待回复")
                self.handle_one(latest, who, chat=chat)
            elif latest is not None:
                if _msg_attr(latest).lower() == "self":
                    log(f"[{who}] 打开会话：最新一条是我发的，继续监听")
                elif _is_ack_message(latest, who, chat, self.wx):
                    log(f"[{who}] 打开会话：最新一条是确认语，跳过")
            log(f"[{who}] 已同步历史 {len(keys)} 条，开始盯新消息")
            return

        seen = self._seen_keys.setdefault(who, set())
        new_msgs = [m for m, k in zip(msgs, keys) if k not in seen]
        seen.update(keys)

        friend_new = [
            m
            for m in new_msgs
            if _is_from_friend(m)
            and _should_handle_msg(m, self.wx, who, chat, self._self_aliases)
            and not _group_reply_skip_reason(
                m, who, chat, self.wx, self._self_aliases, self._allowed_names
            )
        ]
        batch_mode = len(friend_new) > 1
        friend_new_set = set(id(m) for m in friend_new)

        for msg in new_msgs:
            if self._stop:
                break
            in_batch = batch_mode and id(msg) in friend_new_set
            self.handle_one(
                msg,
                who,
                chat=chat,
                allow_not_latest=in_batch,
                batch_mode=in_batch,
            )

    def _session_name(self, session: Any) -> str:
        for attr in ("name", "nickname", "who"):
            val = getattr(session, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
        info = getattr(session, "info", None)
        if isinstance(info, dict):
            for key in ("name", "nickname", "chat_name", "remark"):
                val = info.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
        return str(session).strip()

    def handle_one(
        self,
        msg: Any,
        who: str,
        chat: Any = None,
        *,
        allow_not_latest: bool = False,
        batch_mode: bool = False,
    ) -> None:
        if not self._allowed(who):
            log(f"[{who}] 不在白名单，跳过")
            return
        if not _should_handle_msg(
            msg, self.wx, who, chat, self._self_aliases
        ):
            return
        skip_reason = _group_reply_skip_reason(
            msg, who, chat, self.wx, self._self_aliases, self._allowed_names
        )
        if skip_reason:
            at_hint = _collect_at_names(msg, self._self_aliases)
            if at_hint and "别人" in skip_reason:
                log(
                    f"[{who}] 跳过：{skip_reason}；"
                    f"若 @ 的是你，请在 .env 加 AT_ALIASES={at_hint[0]}"
                )
            else:
                log(f"[{who}] 跳过：{skip_reason}")
            return
        if not _should_reply_to_msg(
            msg, chat, who, self.wx, allow_not_latest=allow_not_latest
        ):
            return

        is_group = _is_group_chat(who, chat, self.wx)
        at_me = (
            _is_directed_at_me(msg, self.wx, chat, who, self._self_aliases)
            if is_group
            else False
        )
        if self._in_cooldown(who, chat, at_me=at_me, batch_mode=batch_mode):
            kind = "@我/找我说" if at_me else ("群聊" if is_group else "私聊")
            log(f"[{who}] {kind}冷却中，跳过")
            return

        user_text = _resolve_user_text(msg, who, chat, self.wx)
        if not user_text:
            if _is_directed_at_me(msg, self.wx, chat, who, self._self_aliases):
                user_text = "[@我]"
            else:
                return

        mtype = _msg_type(msg) or "text"
        log(f"[{who}] 收到：{user_text!r}")

        sticker_action = decide_sticker_action(user_text, mtype)
        can_sticker = hasattr(self.wx, "SendEmotion") or (
            chat is not None and hasattr(chat, "SendEmotion")
        )
        if sticker_action != "none" and not can_sticker:
            sticker_action = "none"
        sticker_only = sticker_action == "only"

        reply = ""
        if not sticker_only:
            try:
                chat_context = _collect_chat_context(
                    chat, who, self.wx, user_text
                )
                tone_samples: List[str] = []
                tone_source = ""
                if self.persona_key == "mimic":
                    tone_samples, tone_source = _collect_tone_samples(
                        self.wx, chat, who, self._allowed_names
                    )
                    if tone_samples:
                        log(
                            f"[{who}] 模仿语气样本 {len(tone_samples)} 条 ← {tone_source}"
                        )
                    else:
                        log(f"[{who}] 当前会话暂无「我」的历史可模仿")
                if chat_context:
                    log(f"[{who}] 带入最近对话 {len(chat_context)} 条")
                reply = self.llm.reply(
                    user_text,
                    chat_id=who,
                    chat_context=chat_context or None,
                    tone_samples=tone_samples or None,
                    tone_source=tone_source,
                )
            except Exception:
                log(f"[{who}] 生成异常：\n{traceback.format_exc()}")
                reply = config.FALLBACK_REPLY
        else:
            log(f"[{who}] 只回表情包")

        if not reply and sticker_action == "none":
            return

        delay = random.uniform(*config.REPLY_DELAY_RANGE)
        if reply:
            log(f"[{who}] 将回复：{reply!r}（{delay:.1f}s 后）")
        time.sleep(delay)

        try:
            if reply:
                _send_text(self.wx, msg, who, reply, chat=chat)
                log(f"[{who}] 文字已发送")

            if sticker_action in ("only", "after_text"):
                time.sleep(random.uniform(0.3, 1.0))
                idx = pick_sticker_index(user_text, reply)
                if send_sticker(self.wx, who, chat, idx):
                    log(f"[{who}] 表情包已发 [index={idx}]")
                elif sticker_action == "only":
                    log(f"[{who}] 表情包发送失败")

            if reply or sticker_action != "none":
                self._last_reply_at[who] = time.time()
        except Exception:
            log(f"[{who}] 发送异常：\n{traceback.format_exc()}")

    def _session_unread(self, session: Any) -> bool:
        if session is None:
            return False
        try:
            if bool(getattr(session, "isnew", False)):
                return True
            if int(getattr(session, "new_count", 0) or 0) > 0:
                return True
        except Exception:
            pass
        info = getattr(session, "info", None)
        if isinstance(info, dict):
            if info.get("isnew"):
                return True
            try:
                if int(info.get("new_count") or 0) > 0:
                    return True
            except Exception:
                pass
        return False

    def _find_whitelist_sessions(self) -> List[Tuple[str, str, Any]]:
        """返回 [(配置白名单名, 会话显示名, session), ...]。"""
        sessions = self.wx.GetSession() or []
        found: List[Tuple[str, str, Any]] = []
        used = set()
        for target in config.TARGET_NICKNAMES:
            for s in sessions:
                who = self._session_name(s)
                if not who or who in used:
                    continue
                if who == target or target in who or who in target:
                    found.append((target, who, s))
                    used.add(who)
                    break
        return found

    def _poll_unread_whitelist(self) -> None:
        """只读会话列表；仅当白名单有未读时才切到该聊天处理。"""
        matched = self._find_whitelist_sessions()
        if not matched:
            # 列表里暂时找不到时，不狂切窗口；仅对未 priming 的做一次同步
            for name in config.TARGET_NICKNAMES:
                if self._stop:
                    break
                if name in self._primed_chats:
                    continue
                try:
                    self._poll_one_chat(name)
                except Exception:
                    log(f"[{name}] 首次同步异常：\n{traceback.format_exc()}")
            return

        for _target, who, sess in matched:
            if self._stop:
                break
            need = self._session_unread(sess) or who not in self._primed_chats
            if not need:
                continue
            try:
                if self._session_unread(sess):
                    log(f"[{who}] 会话列表有未读，打开聊天处理")
                self._poll_one_chat(who)
            except Exception:
                log(f"[{who}] 轮询异常：\n{traceback.format_exc()}")

    def _prepare_chat(self, who: str) -> Any:
        """优先复用独立子窗口；否则切主窗口会话。"""
        sub = self._resolve_sub_chat(who)
        if sub is not None:
            return sub
        if self._free_subwindow_mode:
            log(f"[{who}] 无可用子窗口，跳过（不切主窗口）")
            return self.wx
        try:
            if hasattr(self.wx, "GetSubWindow"):
                got = self.wx.GetSubWindow(who)
                if got is not None:
                    return got
        except Exception:
            pass
        try:
            self.wx.ChatWith(who, exact=False)
            time.sleep(0.25)
        except TypeError:
            try:
                self.wx.ChatWith(who)
                time.sleep(0.25)
            except Exception as e:
                log(f"[{who}] 切换会话失败：{e}")
        except Exception as e:
            log(f"[{who}] 切换会话失败：{e}")
        return self.wx

    def _chat_matches_name(self, chat_who: str, name: str) -> bool:
        if not chat_who or not name:
            return False
        if chat_who == name:
            return True
        return name in chat_who or chat_who in name

    def _chat_has_unread(self, chat: Any) -> bool:
        who = getattr(chat, "who", "") or ""
        if who and who not in self._primed_chats:
            return True
        for _target, session_who, sess in self._find_whitelist_sessions():
            if self._chat_matches_name(who, session_who) or self._chat_matches_name(
                who, _target
            ):
                if self._session_unread(sess):
                    return True
        for name in config.TARGET_NICKNAMES:
            if self._chat_matches_name(who, name) and name not in self._primed_chats:
                return True
        return False

    def _chat_needs_read(self, chat: Any) -> bool:
        """未读、未 priming、或心跳到期时才真正读子窗口消息。"""
        who = getattr(chat, "who", "") or ""
        if who and who not in self._primed_chats:
            return True
        if self._chat_has_unread(chat):
            return True
        last = self._sub_last_read_at.get(who, 0.0)
        interval = max(1.0, float(config.SUBWINDOW_READ_INTERVAL))
        return (time.time() - last) >= interval

    def _chats_to_poll_this_cycle(self) -> List[Any]:
        """serial：smart/lite=未读+心跳；all=每轮全读。"""
        chats = self._unique_sub_chats()
        if not chats:
            return []
        if config.SUBWINDOW_POLL_MODE == "all":
            return chats

        # smart：本轮读所有「需要读」的窗口（未读优先，心跳到期也读）
        if config.SUBWINDOW_POLL_MODE == "smart":
            due = [c for c in chats if self._chat_needs_read(c)]
            return due

        # lite：有未读就读热窗口；否则按 IDLE_ROTATE 轮流探一个
        hot = [c for c in chats if self._chat_has_unread(c)]
        if hot:
            return hot

        now = time.time()
        if now - self._sub_last_idle_poll < config.SUBWINDOW_IDLE_ROTATE:
            return []

        idx = self._sub_poll_cursor % len(chats)
        self._sub_poll_cursor += 1
        self._sub_last_idle_poll = now
        return [chats[idx]]

    def _poll_one_subwindow(self, chat: Any) -> None:
        from subwindows import rebind_sub_chat

        who = getattr(chat, "who", "") or ""
        alive = True
        if hasattr(chat, "exists"):
            alive = chat.exists()
        if not alive:
            fails = self._subwindow_fail_count.get(who, 0) + 1
            self._subwindow_fail_count[who] = fails
            if fails < 3:
                return
            now = time.time()
            last_try = self._subwindow_reopen_at.get(who, 0.0)
            if now - last_try < 60:
                return
            self._subwindow_reopen_at[who] = now
            log(f"[{who}] 子窗口不可用，尝试重新绑定…")
            rebuilt = rebind_sub_chat(self.wx, who)
            if rebuilt is None:
                from subwindows import open_sub_chat

                rebuilt = open_sub_chat(self.wx, who)
            if rebuilt is None:
                return
            with self._style_lock:
                for key in list(self._sub_chats.keys()):
                    if self._sub_chats.get(key) is chat:
                        self._sub_chats[key] = rebuilt
                self._sub_chats[who] = rebuilt
                self._sub_chats[rebuilt.who] = rebuilt
            chat = rebuilt
            self._subwindow_fail_count[who] = 0
        else:
            self._subwindow_fail_count[who] = 0
        self._poll_one_chat(chat.who, chat=chat)
        self._sub_last_read_at[chat.who] = time.time()
        if who and who != chat.who:
            self._sub_last_read_at[who] = time.time()

    def _poll_subwindows(self) -> None:
        """serial 模式：单线程轮询子窗口。"""
        chats = self._chats_to_poll_this_cycle()
        for i, chat in enumerate(chats):
            if self._stop:
                break
            who = getattr(chat, "who", "") or ""
            try:
                self._poll_one_subwindow(chat)
            except Exception:
                log(f"[{who}] 子窗口轮询异常：\n{traceback.format_exc()}")
            if i + 1 < len(chats) and config.SUBWINDOW_STAGGER > 0:
                time.sleep(config.SUBWINDOW_STAGGER)

    def _subwindow_monitor_loop(
        self, whitelist_name: str, phase_offset: float = 0.0
    ) -> None:
        """threads 模式：单窗口独立监控（仍受 smart 门控，避免空转闪窗）。"""
        if phase_offset > 0:
            time.sleep(phase_offset)
        while not self._stop:
            chat = self._resolve_sub_chat(whitelist_name)
            if chat is None:
                time.sleep(config.POLL_INTERVAL)
                continue
            who = getattr(chat, "who", "") or whitelist_name
            try:
                if (
                    config.SUBWINDOW_POLL_MODE != "all"
                    and not self._chat_needs_read(chat)
                ):
                    time.sleep(config.POLL_INTERVAL)
                    continue
                self._poll_one_subwindow(chat)
            except Exception:
                if not self._stop:
                    log(f"[{who}] 子窗口监控异常：\n{traceback.format_exc()}")
            time.sleep(config.POLL_INTERVAL)

    def _start_subwindow_monitors(self) -> None:
        """为每个白名单子窗口启动独立监控线程（错开相位，减轻抢焦点）。"""
        self._sub_monitor_threads.clear()
        targets = [
            n for n in config.TARGET_NICKNAMES if self._resolve_sub_chat(n) is not None
        ]
        if not targets:
            raise RuntimeError("没有可监控的子窗口")
        n = len(targets)
        step = config.POLL_INTERVAL / max(n, 1)
        for i, name in enumerate(targets):
            phase = step * i
            t = threading.Thread(
                target=self._subwindow_monitor_loop,
                args=(name, phase),
                name=f"wx-sub-{name}",
                daemon=True,
            )
            t.start()
            self._sub_monitor_threads.append(t)
            log(f"  └ 监控线程：{name}")
        log(f"共 {n} 个窗口同时监控中")

    def run_selected(self) -> None:
        if not config.TARGET_NICKNAMES:
            raise RuntimeError(
                "LISTEN_MODE=selected 时请在 .env 设置 TARGET_NICKNAMES"
            )

        self._build_whitelist()
        if HAS_LISTEN:
            self._setup_selected_listeners()
            log("白名单子窗口监听运行中（Plus）")
            try:
                while not self._stop:
                    time.sleep(0.3)
            finally:
                self._teardown_listeners()
        else:
            self._setup_free_subwindows()
            # 默认 serial+smart：有未读/心跳才读，减少 GetAllMessage 抢焦点闪窗
            if config.SUBWINDOW_MONITOR == "threads":
                self._start_subwindow_monitors()
                try:
                    while not self._stop:
                        time.sleep(0.3)
                finally:
                    self._teardown_listeners()
            else:
                log(
                    f"单线程监控（serial/{config.SUBWINDOW_POLL_MODE}）："
                    f"心跳 {config.SUBWINDOW_READ_INTERVAL}s"
                )
                try:
                    while not self._stop:
                        try:
                            self._poll_subwindows()
                        except Exception:
                            if not self._stop:
                                log(f"轮询异常：\n{traceback.format_exc()}")
                        time.sleep(config.POLL_INTERVAL)
                finally:
                    self._teardown_listeners()
        log("监听循环已结束")

    def run_all(self) -> None:
        if HAS_LISTEN and hasattr(self.wx, "GetNextNewMessage"):
            log("开始全量轮询（GetNextNewMessage）")
            while not self._stop:
                try:
                    raw = self.wx.GetNextNewMessage()
                    for who, msgs in _normalize_new_messages(raw):
                        if not self._allowed(who):
                            continue
                        chat = self._prepare_chat(who)
                        for msg in msgs:
                            if self._stop:
                                break
                            self.handle_one(msg, who, chat=chat)
                except Exception:
                    if not self._stop:
                        log(f"轮询异常：\n{traceback.format_exc()}")
                time.sleep(config.POLL_INTERVAL)
        else:
            log("开始全量轮询：盯会话未读，有新消息才打开聊天（免费版）")
            while not self._stop:
                try:
                    sessions = self.wx.GetSession() or []
                    for s in sessions:
                        if self._stop:
                            break
                        who = self._session_name(s)
                        if not who or not self._allowed(who):
                            continue
                        if not self._session_unread(s) and who in self._primed_chats:
                            continue
                        try:
                            if self._session_unread(s):
                                log(f"[{who}] 有未读，打开聊天处理")
                            self._poll_one_chat(who)
                        except Exception:
                            log(f"[{who}] 轮询异常：\n{traceback.format_exc()}")
                except Exception:
                    if not self._stop:
                        log(f"轮询异常：\n{traceback.format_exc()}")
                time.sleep(config.POLL_INTERVAL)
        log("监听循环已结束")

    def run(self) -> None:
        if config.LISTEN_MODE == "all":
            self.run_all()
        else:
            self.run_selected()


if __name__ == "__main__":
    import sys

    if "--cli" in sys.argv:
        _run_cli()
    else:
        from gui import main as gui_main

        gui_main()


def _run_cli() -> None:
    import argparse

    from logger import log as cli_log, subscribe
    from personas import choose_style_interactive, get_style_label, resolve_persona

    subscribe(lambda m: print(m))

    parser = argparse.ArgumentParser(description="微信 AI 自动回复（CLI）")
    parser.add_argument("--persona", "-p", "--style", default=None, help="风格代号，如 mimic / bazong")
    parser.add_argument("--gender", "-g", default=None, help="已弃用，可忽略")
    parser.add_argument("--no-select", action="store_true")
    args = parser.parse_args([a for a in sys.argv[1:] if a != "--cli"])

    if args.persona:
        persona = args.persona.strip()
    elif args.no_select:
        persona = config.DEFAULT_PERSONA
    else:
        persona = choose_style_interactive(config.DEFAULT_PERSONA)

    gender, persona = resolve_persona(config.DEFAULT_GENDER, persona)
    cli_log(f"已选择：{get_style_label(persona)}")
    Monitor(persona_key=persona, gender_key=gender).run()
