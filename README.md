# 微信 AI 自动回复

监听 PC 微信，调用大模型自动回复。基于 **wxauto4**，适配微信 **4.1.x**（推荐锁定 **4.1.8.107**）。

> **隐私**：仓库不包含任何 API Key。密钥只写在本地 `.env`（已被 `.gitignore` 忽略），切勿提交到 Git。

## 快速开始

### 1. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 2. 配置密钥与白名单

```powershell
copy .env.example .env
```

用记事本或编辑器打开 `.env`，至少填写：

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `LLM_API_KEY` | **必填**。大模型 API Key | DeepSeek 控制台创建后粘贴 |
| `LLM_BASE_URL` | API 地址 | `https://api.deepseek.com`（默认） |
| `LLM_MODEL` | 模型名 | `deepseek-v4-flash`（默认） |
| `TARGET_NICKNAMES` | 白名单：好友备注名 / 群名，顿号分隔 | `张三、工作群` |
| `LISTEN_MODE` | `selected` 只回白名单；`all` 回所有人 | `selected` |
| `PERSONA` | 默认风格代号 | `mimic`（模仿正常） |

**DeepSeek Key**：打开 [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 创建，复制到：

```env
LLM_API_KEY=sk-xxxxxxxx
```

也可改用 OpenAI 或本地 Ollama，见 `.env.example` 底部注释。

**白名单注意**：名字须与微信**会话列表显示名**一致（通常是备注，不是微信号）。例如备注是「马帅」、昵称是 Hahah，白名单请写 `马帅`（或写昵称，程序会尽量搜索匹配）。

### 3. 准备微信

1. 安装并登录 **微信 PC 4.1.x**（推荐 **4.1.8.107**）
2. 历史版本：[wechat4.0-windows-versions](https://github.com/SiverKing/wechat4.0-windows-versions/releases)
3. 尽量关闭自动更新，避免升到不受支持的版本
4. 保持微信主窗口可见（不要最小化到托盘）

### 4. 启动

弹窗版（推荐）：

```powershell
python gui.py
```

或：

```powershell
python main.py
```

在窗口中：

1. 选择风格（如「模仿正常」「霸道总裁」）
2. 确认白名单 →「保存配置」
3. 点「开始监听」

命令行版：

```powershell
python main.py --cli --no-select
```

## 配置说明（常用）

完整项见 `.env.example`。

### 监听

- `LISTEN_MODE=selected`：只回复 `TARGET_NICKNAMES` 里的人/群
- `LISTEN_MODE=all`：回复有新消息的会话，可用 `IGNORE_NICKNAMES` 排除
- 群聊：群名写入白名单即可；`GROUP_SKIP_AT_OTHERS=true` 时「只 @ 别人」不回；未 @ 我时有冷却（`GROUP_REPLY_INTERVAL`）

### 对话

- `USE_CHAT_HISTORY=true`：带入最近聊天上下文
- `REPLY_MAX_CHARS=0`：不截断回复；技术类问题会用更长 token
- `ENABLE_VOICE=true`：语音自动转文字后回复（依赖微信「语音转文字」）

### 风格

`PERSONA` 可选：`mimic`、`gaoleng_yujie`、`wenrou`、`luoli`、`yuanqi`、`bazong`、`nuannan`、`pishuai`、`zhainan`、`chenwen`。

GUI 监听中也可随时切换；未监听时切换会写入 `.env`，下次启动生效。

「模仿正常」会读取**当前会话**里你本人的历史发言，模仿语气。

## 注意

- 仓库内 **没有** 你的 Key；每人自行配置 `.env`
- 免费版用独立子窗口轮询；收藏表情包发送需付费 Plus（wxautox4）
- 自动化有封号风险，仅自用
- 若误把 Key 提交到 Git，请立即在服务商控制台**作废并换新 Key**
