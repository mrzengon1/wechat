# 微信 AI 自动回复

监听 PC 微信，调用大模型自动回复。基于 **wxauto4**，适配微信 **4.1.x**（推荐锁定 **4.1.8.107**）。

## 启动（弹窗版，默认）

```powershell
python main.py
```

或：

```powershell
python gui.py
```

窗口内选择风格（如高冷御姐 / 霸道总裁 / 模仿正常），点「开始监听」。日志在弹窗里查看。

## 命令行版

```powershell
python main.py --cli --no-select
```

## 依赖安装

```powershell
python -m pip install -r requirements.txt
```

可选：安装付费 **wxautox4**（Plus）后会自动启用子窗口监听、`SendEmotion` 等能力。

## 配置（.env）

```env
TARGET_NICKNAMES=好友A、工作群
REPLY_GROUP_CHATS=true
USE_CHAT_HISTORY=true
PERSONA=mimic
```

- **群聊**：把群名（与会话列表一致）写进 `TARGET_NICKNAMES`（默认开）
- **聊天历史**：`USE_CHAT_HISTORY=true`（默认开）
- **模仿正常**：选该风格时，读取与当前对方的历史，模仿你的语气回复
- **语音**：`ENABLE_VOICE=true` 时自动「语音转文字」后回复

## 风格

单一列表选择，例如：模仿正常、高冷御姐、温柔软妹、软萌萝莉、元气少女、霸道总裁、暖心暖男、痞帅少年、直球直男、沉稳大叔。

`.env` 可用 `PERSONA=mimic`（默认）或 `PERSONA=bazong` 等。

## 注意

- 需 **微信 PC 4.1.x** + **wxauto4**（免费版文档支持到约 **4.1.8.107**）
- 历史版本下载：[wechat4.0-windows-versions](https://github.com/SiverKing/wechat4.0-windows-versions/releases)
- 装好后尽量关闭自动更新，避免升到不受支持的小版本
- 免费版用轮询白名单（`ChatWith` + `GetAllMessage`）；收藏表情包发送需 Plus
- 自动化有封号风险，仅自用
