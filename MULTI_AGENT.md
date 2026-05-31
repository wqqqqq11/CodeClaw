# 多代理指南

`/agent multi` 是 CodeClaw 的轻量级编排模式，用于将一个目标拆分为多个工作通道。

简而言之：

- 你提出一个目标。
- CodeClaw 提出一个多工作线程计划。
- 你确认、编辑或取消它。
- 工作线程在安全的条件下并行运行。
- 每个工作线程编写交接文件。
- CodeClaw 通过轻量级验收和跨通道审计检查输出。

这不是一个重量级框架。
它保持本地化、基于文件且实用。

## 核心命令

启动计划：

```text
/agent multi <目标>
```

优先使用代理：

```text
/agent multi @claude @codex <目标>
```

强制显式通道分配：

```text
/agent multi --agent backend=claude --agent frontend=codex --agent docs=claude <目标>
```

当你需要保证执行顺序时，添加显式 DAG 依赖：

```text
/agent multi --agent backend=codex --agent frontend=claude --agent integration=claude --depends-on integration=backend,frontend 构建应用
```

`--depends-on` 也可以写作 `--depends-on=integration=backend,frontend`。

当你不传递 `--depends-on` 时，显式分配仍会在目标文本中接受依赖提示，例如：

```text
/agent multi --agent backend=codex --agent frontend=claude --agent integration=claude 构建应用，保持后端和前端并行，并让集成等待后端和前端完成
```

运行提议的计划：

```text
/agent multi confirm
```

根据反馈重新生成计划：

```text
/agent multi edit 将文档设为最终通道并保持后端/前端并行
```

取消计划：

```text
/agent multi cancel
```

## 工作原理

`/agent multi` 通常创建：

- 编码通道用于实现、验证、文档或集成
- 研究通道用于发现和综合
- 编写通道用于文章、报告和交付物
- 审查通道用于评论、差距检测和建议

每个通道获得：

- 职责
- 预期输入
- 预期输出
- 相关时获得专属路径
- 验收检查
- `handoff/<lane>.md`
- `handoff/<lane>.json`

## 优势所在

- 真正的 DAG 调度：下游通道在其自身依赖完成后立即启动
- 机器可读的交接文件
- 轻量级修复尝试
- 合约感知检查，如 `outputs.endpoints`、`outputs.api_calls`、`outputs.findings`、`outputs.deliverables`
- 针对 API、发现流程和交付物的全局审计

## 最佳使用场景

- 全栈应用构建
- 后端/前端/文档拆分
- 研究 + 审查工作流
- 文章/报告流水线
- 迁移规划
- 错误分类和修复
- 实现 + 质量保证
- 架构 + 执行
