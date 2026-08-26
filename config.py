"""运行配置。密钥请用环境变量或 .env，不要写进代码仓库。"""

import os
from pathlib import Path
from typing import Dict, List


ENV_PATH = Path(__file__).resolve().with_name(".env")


def _load_dotenv() -> None:
    """读取同目录 .env；文件中的键一律覆盖当前环境变量。"""
    env_path = ENV_PATH
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")


def _split_names(raw: str) -> List[str]:
    if not raw.strip():
        return []
    normalized = raw.replace("，", "、").replace(",", "、")
    normalized = normalized.replace("；", "、").replace(";", "、")
    normalized = normalized.replace("|", "、").replace("/", "、")
    parts = []
    for chunk in normalized.split("、"):
        name = chunk.strip()
        if name:
            parts.append(name)
    return parts


def join_names(names: List[str]) -> str:
    return "、".join(n for n in names if n and n.strip())


def normalize_names_input(raw: str) -> str:
    return join_names(_split_names(raw))


def _parse_indexes(raw: str) -> List[int]:
    if not raw.strip():
        return [0, 1, 2]
    out: List[int] = []
    for part in raw.replace("，", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out or [0, 1, 2]


def update_env_vars(updates: Dict[str, str]) -> None:
    """更新 .env 中的键值，保留注释与未改动的行。"""
    if not updates:
        return
    lines: List[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    for key, val in remaining.items():
        out.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def reload_listen_config() -> None:
    """从 .env 重新加载监听相关配置到模块变量。"""
    global LISTEN_MODE, TARGET_NICKNAMES, REPLY_GROUP_CHATS
    global GROUP_REPLY_INTERVAL, GROUP_SKIP_AT_OTHERS
    global USE_CHAT_HISTORY, HISTORY_TURNS, WECHAT_CONTEXT_LIMIT, WECHAT_CONTEXT_LIMIT_TECHNICAL
    global LEARN_MY_TONE, TONE_SAMPLE_LIMIT, TONE_MIN_SELF

    _load_dotenv()
    LISTEN_MODE = os.getenv("LISTEN_MODE", "selected").strip().lower()
    _targets = os.getenv("TARGET_NICKNAMES", "") or os.getenv("TARGET_NICKNAME", "")
    TARGET_NICKNAMES = _split_names(_targets)
    REPLY_GROUP_CHATS = os.getenv("REPLY_GROUP_CHATS", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    GROUP_REPLY_INTERVAL = int(os.getenv("GROUP_REPLY_INTERVAL", "45"))
    GROUP_SKIP_AT_OTHERS = os.getenv("GROUP_SKIP_AT_OTHERS", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    USE_CHAT_HISTORY = os.getenv("USE_CHAT_HISTORY", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    HISTORY_TURNS = 10 if USE_CHAT_HISTORY else 0
    WECHAT_CONTEXT_LIMIT = 0 if not USE_CHAT_HISTORY else int(
        os.getenv("WECHAT_CONTEXT_LIMIT", "24")
    )
    WECHAT_CONTEXT_LIMIT_TECHNICAL = int(
        os.getenv("WECHAT_CONTEXT_LIMIT_TECHNICAL", "48")
    )
    LEARN_MY_TONE = os.getenv("LEARN_MY_TONE", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    TONE_SAMPLE_LIMIT = int(os.getenv("TONE_SAMPLE_LIMIT", "12"))
    TONE_MIN_SELF = int(os.getenv("TONE_MIN_SELF", "3"))


_load_dotenv()

# —— 监听范围 ——
# selected: 只回复 TARGET_NICKNAMES 里的人
# all:      回复所有有新消息的会话（可用 IGNORE_NICKNAMES 排除）
LISTEN_MODE = os.getenv("LISTEN_MODE", "selected").strip().lower()  # selected | all

# 指定要自动回复的好友（备注名，与会话列表一致），顿号分隔
# 兼容旧变量 TARGET_NICKNAME（单人）
_targets = os.getenv("TARGET_NICKNAMES", "") or os.getenv("TARGET_NICKNAME", "")
TARGET_NICKNAMES: List[str] = _split_names(_targets)

# all 模式下忽略的会话（文件传输助手、公众号、不想回的人等）
IGNORE_NICKNAMES: List[str] = _split_names(
    os.getenv("IGNORE_NICKNAMES", "文件传输助手,微信团队")
)

# all / selected 均支持群聊；selected 时在 TARGET_NICKNAMES 里写群名即可
REPLY_GROUP_CHATS = os.getenv("REPLY_GROUP_CHATS", "true").lower() in (
    "1",
    "true",
    "yes",
)
# 群聊：未 @ 我时的回复冷却（秒），@ 我仍用 MIN_REPLY_INTERVAL
GROUP_REPLY_INTERVAL = int(os.getenv("GROUP_REPLY_INTERVAL", "45"))
# 群聊：消息仅 @ 别人（不含我）时不回复
GROUP_SKIP_AT_OTHERS = os.getenv("GROUP_SKIP_AT_OTHERS", "true").lower() in (
    "1",
    "true",
    "yes",
)

TEXT_ONLY = True

# 语音消息：调用 PC 微信「语音转文字」后按文字回复
ENABLE_VOICE = os.getenv("ENABLE_VOICE", "true").lower() in ("1", "true", "yes")
MIN_REPLY_INTERVAL = int(os.getenv("MIN_REPLY_INTERVAL", "5"))
# 全量轮询间隔（秒）
POLL_INTERVAL = 1.0
REPLY_DELAY_RANGE = (1.0, 3.0)

# —— 大模型（OpenAI 兼容 Chat Completions）——
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")

# DeepSeek V4：关闭 thinking，微信回复更快、更像普通聊天
LLM_DISABLE_THINKING = os.getenv("LLM_DISABLE_THINKING", "true").lower() in (
    "1",
    "true",
    "yes",
)

SYSTEM_PROMPT = """你是用户本人在微信里打字，像跟熟人聊天：短、口语、有温度。
禁止助手腔、模板话、套话；只输出一两句要发出的正文。"""

# 默认风格（单一列表：mimic模仿正常 / gaoleng_yujie高冷御姐 / bazong霸道总裁 等）
DEFAULT_PERSONA = os.getenv("PERSONA", "mimic").strip() or "mimic"
DEFAULT_GENDER = os.getenv("GENDER", "female").strip().lower() or "female"
if DEFAULT_GENDER in ("男", "男生", "m"):
    DEFAULT_GENDER = "male"
elif DEFAULT_GENDER in ("女", "女生", "f"):
    DEFAULT_GENDER = "female"

# 是否带入微信历史 / 多轮记忆（默认开）
USE_CHAT_HISTORY = os.getenv("USE_CHAT_HISTORY", "true").lower() in (
    "1",
    "true",
    "yes",
)

HISTORY_TURNS = 10 if USE_CHAT_HISTORY else 0
WECHAT_CONTEXT_LIMIT = 0 if not USE_CHAT_HISTORY else int(
    os.getenv("WECHAT_CONTEXT_LIMIT", "24")
)
WECHAT_CONTEXT_LIMIT_TECHNICAL = int(
    os.getenv("WECHAT_CONTEXT_LIMIT_TECHNICAL", "48")
)

# 从白名单会话里学习「我」的语气（优先当前会话；不足则借其他白名单）
LEARN_MY_TONE = os.getenv("LEARN_MY_TONE", "true").lower() in (
    "1",
    "true",
    "yes",
)
# 最多取多少条「我」的历史发言作语气参考
TONE_SAMPLE_LIMIT = int(os.getenv("TONE_SAMPLE_LIMIT", "12"))
# 当前会话「我」的发言少于该数时，补充其他白名单会话
TONE_MIN_SELF = int(os.getenv("TONE_MIN_SELF", "3"))
# 生成上限：闲聊与技术问题分开（技术类可写步骤、稍长）
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "256"))
MAX_TOKENS_TECHNICAL = int(os.getenv("MAX_TOKENS_TECHNICAL", "1024"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.92"))
# 单条回复最大字数；0 表示不截断
REPLY_MAX_CHARS = int(os.getenv("REPLY_MAX_CHARS", "0"))

FALLBACK_REPLY = "等会儿哈，刚忙一下"

# 可选：你的真实姓名/昵称，被问到名字时可回答；留空则岔开、不编造
BOT_REAL_NAME = os.getenv("BOT_REAL_NAME", "").strip()

# 文字回复里加微信表情（😂🙂👍 等，非收藏表情包）
ENABLE_EMOJI = os.getenv("ENABLE_EMOJI", "true").lower() in ("1", "true", "yes")
# 模型没加表情时，按概率补一个（0~1）
EMOJI_PROB = float(os.getenv("EMOJI_PROB", "0"))
# 单条回复最多保留几个 emoji
EMOJI_MAX = int(os.getenv("EMOJI_MAX", "1"))

# 微信「收藏表情」表情包（SendEmotion，下标从 0 起，对应添加的表情顺序）
ENABLE_STICKER = os.getenv("ENABLE_STICKER", "false").lower() in ("1", "true", "yes")
STICKER_INDEXES: List[int] = _parse_indexes(os.getenv("STICKER_INDEXES", "0,1,2,3,4"))
# 文字回复后再发一个表情包的概率
STICKER_AFTER_TEXT_PROB = float(os.getenv("STICKER_AFTER_TEXT_PROB", "0"))
# 对方发表情包时，用表情包回的概率
STICKER_REPLY_TO_EMOTION_PROB = float(os.getenv("STICKER_REPLY_TO_EMOTION_PROB", "0.6"))
# 短消息只发表情、不发文字的概率
STICKER_ONLY_PROB = float(os.getenv("STICKER_ONLY_PROB", "0.25"))

ENABLE_TICKLE = False
