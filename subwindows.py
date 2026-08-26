"""免费 wxauto4：用 SessionBox.open_separate_window 打开独立聊天窗并封装为可轮询对象。"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from wxauto4 import uia

from logger import log


def _walk_chat_single_windows(root: Any = None) -> List[Any]:
    if root is None:
        root = uia.GetRootControl()
    found: List[Any] = []

    def walk(c: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        try:
            if getattr(c, "ClassName", None) == "mmui::ChatSingleWindow":
                found.append(c)
        except Exception:
            pass
        try:
            for ch in c.GetChildren():
                walk(ch, depth + 1)
        except Exception:
            pass

    walk(root)
    return found


def find_single_window(nickname: str) -> Any | None:
    """按窗口标题查找独立聊天窗。"""
    nick = (nickname or "").strip()
    if not nick:
        return None
    exact = None
    fuzzy = None
    for w in _walk_chat_single_windows():
        try:
            name = (w.Name or "").strip()
        except Exception:
            continue
        if not name:
            continue
        if name == nick:
            exact = w
            break
        if fuzzy is None and (nick in name or name in nick):
            fuzzy = w
    return exact or fuzzy


def _session_names(wx: Any) -> List[str]:
    try:
        sessions = wx.GetSession() or []
    except Exception:
        return []
    names: List[str] = []
    for s in sessions:
        try:
            n = (getattr(s, "name", None) or "").strip()
        except Exception:
            n = ""
        if n:
            names.append(n)
    return names


def _clear_search_box(wx: Any) -> None:
    """清空搜索框（不要 ESC，ESC 会关掉独立子窗口）。"""
    try:
        box = wx.SessionBox.searchbox
        if box is None:
            return
        box.Click()
        time.sleep(0.1)
        uia.SendKeys("{Ctrl}a")
        time.sleep(0.05)
        uia.SendKeys("{DELETE}")
        time.sleep(0.15)
    except Exception:
        pass


def _prepare_main_chat(wx: Any) -> None:
    """切回主窗口聊天页，便于搜索/切换会话。"""
    try:
        if hasattr(wx, "SwitchToChat"):
            wx.SwitchToChat()
            time.sleep(0.35)
    except Exception:
        pass


def _pick_search_candidate(query: str, candidates: List[str]) -> str:
    """从搜索结果里选出最可能的会话显示名。"""
    q = (query or "").strip()
    if not candidates:
        return q

    def _valid(name: str) -> bool:
        n = (name or "").strip()
        if len(n) < 2:
            return False
        if n in {".", "…", "-", "—"}:
            return False
        return True

    usable = [c for c in candidates if _valid(c)]
    if not usable:
        return q

    for c in usable:
        if c == q or c.lower() == q.lower():
            return c
    for c in usable:
        if q in c or c in q:
            return c

    # 昵称搜备注：微信通常把最相关联系人排在最前（如 Hahah → 马帅）
    return usable[0]


def _search_contact_name(wx: Any, query: str) -> Optional[str]:
    session_box = getattr(wx, "SessionBox", None)
    if session_box is None or not hasattr(session_box, "search"):
        return None

    results: List[Any] = []
    for attempt in range(3):
        _prepare_main_chat(wx)
        _clear_search_box(wx)
        time.sleep(0.3 + attempt * 0.25)
        try:
            results = session_box.search(query) or []
            break
        except Exception as e:
            if attempt >= 2:
                log(f"[{query}] 搜索联系人失败：{e}")
            else:
                time.sleep(0.35)

    candidates: List[str] = []
    skip_headers = {"联系人", "群聊", "公众号", "聊天记录", "搜一搜"}
    for el in results:
        try:
            content = (getattr(el, "content", None) or "").strip()
        except Exception:
            content = ""
        if not content or content in skip_headers or content.startswith("查看全部"):
            continue
        candidates.append(content)

    _clear_search_box(wx)
    if not candidates:
        return None
    picked = _pick_search_candidate(query, candidates)
    if picked != query:
        log(f"[{query}] 搜索匹配会话名：{picked}")
    return picked


def _resolve_display_name(wx: Any, nickname: str) -> str:
    """把白名单名字解析成会话列表里的真实显示名（备注优先）。"""
    nick = (nickname or "").strip()
    if not nick:
        return nick

    def _match_session(names: List[str]) -> str | None:
        for n in names:
            if n == nick:
                return n
        for n in names:
            if nick.lower() == n.lower():
                return n
        for n in names:
            if nick in n or n in nick:
                return n
        return None

    sessions = _session_names(wx)
    hit = _match_session(sessions)
    if hit:
        return hit

    # 优先搜索（昵称→备注），避免 ChatWith 触发 EditControl 超时
    searched = _search_contact_name(wx, nick)
    if searched:
        hit = _match_session(_session_names(wx))
        if hit:
            return hit
        return searched

    # 最后才 ChatWith
    try:
        if hasattr(wx, "ChatWith"):
            _prepare_main_chat(wx)
            wx.ChatWith(nick, exact=False, force=False)
            time.sleep(0.55)
            hit = _match_session(_session_names(wx))
            if hit:
                _clear_search_box(wx)
                return hit
    except Exception as e:
        log(f"[{nick}] ChatWith 解析名失败：{e}（将尝试直接打开）")

    _clear_search_box(wx)
    return nick


def _ensure_in_session_list(wx: Any, nickname: str) -> None:
    """先切到该会话，让 open_separate_window 能在会话列表里找到。"""
    _prepare_main_chat(wx)
    try:
        sb = wx.SessionBox
        if hasattr(sb, "switch_chat"):
            sb.switch_chat(nickname, exact=False)
            time.sleep(0.45)
            return
    except Exception as e:
        log(f"[{nickname}] switch_chat 失败：{e}")
    try:
        if hasattr(wx, "ChatWith"):
            wx.ChatWith(nickname, exact=False, force=False)
            time.sleep(0.45)
    except Exception as e:
        log(f"[{nickname}] ChatWith 失败：{e}")


def _bind_sub_chat(wx: Any, nickname: str, control: Any) -> Optional[SubChat]:
    api = getattr(wx, "_api", None)
    if api is None or not hasattr(api, "_get_chatbox"):
        return None
    try:
        hwnd = int(control.NativeWindowHandle)
        box = api._get_chatbox(hwnd)
        if box is None:
            return None
        name = nickname
        try:
            info = box.get_info() or {}
            if isinstance(info, dict) and info.get("chat_name"):
                name = str(info["chat_name"]).strip() or nickname
        except Exception:
            pass
        try:
            title = (control.Name or "").strip()
            if title:
                name = title
        except Exception:
            pass
        return SubChat(name, box, control)
    except Exception:
        return None


class SubChat:
    """独立聊天窗包装：兼容 GetAllMessage / SendMsg / ChatInfo / who。"""

    def __init__(self, nickname: str, box: Any, control: Any) -> None:
        self.who = nickname
        self._box = box
        self._control = control

    def ChatInfo(self) -> dict:
        try:
            info = self._box.get_info() or {}
            if isinstance(info, dict):
                return info
        except Exception:
            pass
        return {"chat_name": self.who, "chat_type": "friend"}

    def GetAllMessage(self) -> list:
        try:
            return list(self._box.get_msgs() or [])
        except Exception:
            return []

    def SendMsg(self, msg: str, who: str = None, **kwargs) -> Any:
        del who, kwargs
        if hasattr(self._box, "send_msg"):
            return self._box.send_msg(msg)
        if hasattr(self._box, "send_text"):
            return self._box.send_text(msg)
        raise RuntimeError("子窗口不支持发送")

    def exists(self) -> bool:
        try:
            return bool(self._control.Exists(0))
        except Exception:
            return False


def open_sub_chat(wx: Any, nickname: str, retries: int = 2) -> Optional[SubChat]:
    """打开独立窗口并绑定 ChatBox。"""
    session_box = getattr(wx, "SessionBox", None)
    if session_box is None or not hasattr(session_box, "open_separate_window"):
        log(f"[{nickname}] 当前后端无 open_separate_window")
        return None

    api = getattr(wx, "_api", None)
    if api is None or not hasattr(api, "_get_chatbox"):
        log(f"[{nickname}] 无法获取 _get_chatbox")
        return None

    # 已有子窗口则直接绑定，避免重复 open 触发 EditControl 超时
    existing = find_single_window(nickname)
    if existing is not None:
        bound = _bind_sub_chat(wx, nickname, existing)
        if bound is not None:
            return bound

    display = _resolve_display_name(wx, nickname)
    open_names = [display]
    if nickname not in open_names:
        open_names.append(nickname)
    if display != nickname:
        log(f"[{nickname}] 解析为会话名：{display}")

    for dn in open_names:
        existing = find_single_window(dn)
        if existing is not None:
            bound = _bind_sub_chat(wx, dn, existing)
            if bound is not None:
                return bound

    last_err = ""
    for attempt in range(retries + 1):
        for dn in open_names:
            _ensure_in_session_list(wx, dn)

            try:
                result = session_box.open_separate_window(dn)
                if result is not None and hasattr(result, "is_success") and not result:
                    last_err = str(result)
                    if attempt == 0:
                        log(f"[{dn}] open_separate_window：{result}")
            except Exception as e:
                last_err = str(e)
                log(f"[{dn}] 打开独立窗口异常：{e}")

            time.sleep(0.8 + attempt * 0.4)
            control = find_single_window(dn) or find_single_window(nickname)
            if control is None:
                last_err = last_err or "未找到独立窗口"
                continue

            bound = _bind_sub_chat(wx, dn, control)
            if bound is not None:
                return bound
            last_err = "ChatBox 绑定失败"
            break

    log(f"[{nickname}] 建立子窗口失败：{last_err}")
    return None


def open_whitelist_subchats(wx: Any, names: List[str]) -> Dict[str, SubChat]:
    """为白名单打开独立子窗口，返回 {会话名: SubChat}。"""
    out: Dict[str, SubChat] = {}
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        chat = open_sub_chat(wx, name)
        if chat is None:
            log(f"跳过未打开的白名单：{name}")
            continue
        out[chat.who] = chat
        out[name] = chat
        log(f"已打开子窗口：{chat.who}")
        time.sleep(0.7)
    return out
