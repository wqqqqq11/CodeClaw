# CodeClaw

CodeClaw 是一个轻量级的 Python 代码库，具有长期记忆、多提供商 LLM 路由、技能系统和本地多智能体委派功能。

<div align="center">
  <img src="logo.png" alt="CodeClaw logo" width="420">
</div>


## 核心功能

- 支持多个 LLM 提供商：OpenAI、Anthropic、Gemini、DeepSeek。
- Telegram 优先体验，命令驱动的工作流。
- 本地终端聊天模式（`CodeClaw chat`），使用相同的运行时栈。
- 技能系统（Hub + 本地技能）。
- 本地代理委派（`codex`、`claude`），用于大型编码任务。
- 智能多代理编排，支持自动规划、依赖关系和确认流程。
- 工作区原生代码生成/编辑，附带紧凑的增量报告。

## 快速开始

### 1) 一键安装（推荐）

```bash
git clone https://github.com/wqqqqq11/CodeClaw.git && cd CodeClaw && bash setup.sh
```

`setup.sh` 自动完成所有操作：

- 在 `~/.local/bin/CodeClaw` 安装 `CodeClaw` 命令
- 将配置写入 `~/.env`
- 在 `~/.CodeClaw` 创建运行时文件

然后运行：

```bash
CodeClaw run
```

如果你的 shell 尚未重新加载 `PATH`，请使用：

```bash
~/.local/bin/CodeClaw run
```

### 2) 手动安装

```bash
git clone https://github.com/wqqqqq11/CodeClaw.git
cd CodeClaw
pip install -r requirements.txt
./CodeClaw onboard
```

然后编辑 `~/.env` 并启动：

```bash
./CodeClaw run
```

## CLI 命令

```bash
CodeClaw onboard
CodeClaw onboard --reset-env
CodeClaw onboard --configure
CodeClaw run
CodeClaw run --provider deepseek --model deepseek-chat
CodeClaw chat
```

## Telegram / 聊天命令

| 命令 | 用途 |
|---|---|
| `/help` | 显示命令帮助 |
| `/memory` | 记忆统计 |
| `/recall <query>` | 语义记忆搜索 |
| `/skills ...` | 搜索/安装/激活技能 |
| `/agent` | 本地代理委派控制 |
| `/agent doctor` | 代理安装/认证诊断 |
| `/agent multi <goal>` | 自动规划多代理运行 |
| `/agent multi @claude @codex <goal>` | 优先使用特定代理 |
| `/agent multi --agent backend=codex --agent qa=claude <goal>` | 显式工作分配 |
| `/agent multi confirm` | 执行待处理计划 |
| `/agent multi edit <feedback>` | 重新生成待处理计划 |
| `/agent multi cancel` | 取消待处理计划 |
| `/show` | 当前运行时/提供商/模型状态 |
| `/clear` | 重置当前聊天历史 |
| `/wipe_memory` | 清除所有保存的记忆（需要确认） |

## 智能多代理模式

`/agent multi` 支持三种定义工作分配的方式：

1. 自动模式：

```text
/agent multi 构建一个全栈待办应用
```

2. 优先代理（无标签）：

```text
/agent multi @claude @codex 构建一个全栈待办应用
```

3. 显式分配覆盖（向后兼容）：

```text
/agent multi --agent backend=codex --agent frontend=claude --agent docs=codex 构建一个全栈待办应用
```

你也可以在 DAG 中声明显式依赖关系：

```text
/agent multi --agent backend=codex --agent frontend=claude --agent integration=claude --depends-on integration=backend,frontend 构建应用
```

使用显式分配时，当你不传递 `--depends-on` 时，目标中的依赖提示仍然会被遵守。示例：

```text
/agent multi --agent backend=codex --agent frontend=claude --agent integration=claude 构建应用，保持后端和前端并行，并让集成等待后端和前端完成
```

运行方式：

- 首先生成并显示计划。
- 默认需要确认（`confirm`、`yes`），除非设置了 `LOCAL_AGENT_MULTI_AUTO_CONTINUE=yes`。
- `edit` 允许你在执行前迭代计划。
- `cancel` 或 `no` 清除待处理计划。
- 执行现在遵循真正的 DAG 调度，因此下游通道可以在其依赖完成后立即启动。
- 每个工作线程获得专属路径，必须写入 `handoff/<lane>.md` 和 `handoff/<lane>.json`，并根据轻量级验收规则进行检查。
- 同一合约系统现在也处理非编码通道，包括研究、分析、编写和审查/验证角色。
- 当通道声明 `command_succeeds` 时，验收现在可以运行小型受限的仓库本地命令。
- 后端/前端通道还会自动检查 handoff JSON 字段，因此 `outputs.endpoints` 和 `outputs.api_calls` 必须实际填充。
- 文档/编写通道现在通过 `outputs.deliverables` 获得相同的处理，因此非代码产物也以机器可读的方式被跟踪。
- 研究/审查和文档/编写运行现在在最终报告中也会进行轻量级跨通道发现/交付物审计。
- 后端/前端运行还会从 handoff JSON 进行轻量级跨通道 API 审计，因此方法/路径不匹配会在最终报告中显示。
- 失败的通道可以获得由 `LOCAL_AGENT_MULTI_REPAIR_ATTEMPTS` 控制的小型自我修复通道（限制在 `0..2` 范围内）。

## 支持的提供商

| 提供商 | 设置 `LLM_PROVIDER` | 示例模型 |
|---|---|---|
| OpenAI | `openai` | `gpt-5.2`, `gpt-5.2-mini` |
| Claude | `claude` | `claude-opus-4-5`, `claude-sonnet-4-5` |
| Gemini | `gemini` | `gemini-3-flash-preview`, `gemini-2.5-flash` |
| DeepSeek | `deepseek` | `deepseek-chat`, `deepseek-reasoner` |

快速提供商检查：

```bash
python scripts/provider_smoke_test.py
```

## 技能（Hub + 本地）

示例：

```text
/skills search sonos
/skills add sonoscli
/skills use sonoscli
/skills off sonoscli
/skills create my_custom_skill "我的私有工作流"
```

路径：

- Hub 技能：`~/.CodeClaw/skills/hub/<slug>/SKILL.md`
- 本地技能：`~/.CodeClaw/skills/local/<name>/SKILL.md`

## 架构（简述）

```text
Telegram 或终端聊天
  -> 记忆召回（SQLite + 语义搜索）
  -> 提供商路由（OpenAI/xAI/Claude/Gemini/DeepSeek/Z-AI）
  -> 响应 + 可选的文件操作在 ~/.CodeClaw/workspace
  -> 可选的本地委派代理（单线程或多线程）
```

## 环境要求

- Python 3.10+
- 至少一个支持的 LLM 提供商的 API 凭证

## 许可证

MIT

---

