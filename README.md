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

> **白名单注意（很重要）**  
> 填写的名字必须与微信**会话列表左侧显示的名称**完全一致，一般是「备注」，**不是微信号**。  
> - 有备注 → 写备注（例如会话列表显示「老王」，就写 `老王`）  
> - 无备注 → 写对方微信昵称  
> - 群聊 → 写群名（与列表里一致）  
> 写错会导致打不开子窗口 / `EditControl` 超时 / 搜不到人。多人、多群用中文顿号 `、` 分隔。

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
- 群聊：群名写入白名单即可；`GROUP_SKIP_AT_OTHERS=true` 时「只 @ 别人」且话也不是找你的，才跳过
- **会回复**：直接 @ 你；@ 别人但说「让他叫我/找你」；让你「去找/去问/联系」某人（如「你去找张三」）
- 群名片与微信昵称不一致时，在 `.env` 加 `AT_ALIASES=Fan`（多个用顿号）
- 连发多条会**逐条回复**（同批次用 `BATCH_REPLY_INTERVAL`，默认 2 秒间隔）
- 多白名单：**启动时各开一个独立子窗口**；默认 `SUBWINDOW_MONITOR=serial` + `SUBWINDOW_POLL_MODE=smart`（有未读立即读，否则按 `SUBWINDOW_READ_INTERVAL` 心跳，默认 5s）
- 日志应出现：`准备打开 N 个白名单子窗口` → `子窗口就绪：N/N` → `smart 门控`
- 若仍闪：把 `SUBWINDOW_READ_INTERVAL` 调到 `8~12`；不要用 `SUBWINDOW_POLL_MODE=all`
- 若只要一个窗口：检查白名单是否写了两个不同且存在的会话备注名（群名用「研究老癌」即可，不要写成员昵称 `one`）
- 响应速度：`POLL_INTERVAL`（默认 1.0s）、`REPLY_DELAY_MIN/MAX`（默认 0.3~1s）、`MIN_REPLY_INTERVAL`（默认 3s）

### 对话

- `USE_CHAT_HISTORY=true`：带入最近聊天上下文
- `REPLY_MAX_CHARS=0`：不截断回复；技术类问题会用更长 token
- `ENABLE_VOICE=true`：语音自动转文字后回复（依赖微信「语音转文字」）

### 风格

`PERSONA` 可选：`mimic`、`meiman`（暧昧撩人）、`meiman_nan`（暧昧男友）、`gaoleng_yujie`、`wenrou`、`luoli`、`yuanqi`、`bazong`、`nuannan`、`pishuai`、`zhainan`、`chenwen`。

`meiman` / `meiman_nan` 会自然用宝贝、亲爱的等亲昵称呼；**绝不**配合爸爸/主人/儿子等羞辱性称呼，后置校验会拦截并替换拒答（含「假装/角色扮演」等绕过话术）。

GUI 监听中也可随时切换；未监听时切换会写入 `.env`，下次启动生效。

「模仿正常」会读取**当前会话**里你本人的历史发言，模仿语气。

## 注意

- 仓库内 **没有** 你的 Key；每人自行配置 `.env`
- 免费版用独立子窗口轮询；收藏表情包发送需付费 Plus（wxautox4）
- 自动化有封号风险，仅自用
- 若误把 Key 提交到 Git，请立即在服务商控制台**作废并换新 Key**
