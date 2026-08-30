# ADR-0033：删除生成模型控制台，模型选择留在数据库层

- 状态：接受
- 日期：2026-08-29
- 关联：supersedes [ADR-0032](0032-generation-provider-credentials-are-database-backed.md) 的控制台部分；保留 [ADR-0027](0027-deepseek-generation-model-selection-is-database-backed.md)

## 背景

ADR-0032 把供应商地址和密钥做进了 `/admin/models`。之后还有一版没有写成 ADR 的尝试
（TASK-M5-033）：把这一页扩成多 Profile 管理器，一次可以存多套供应商配置。该版本写完了
迁移、四个 Java 类、两个 Python 模块、一个前端组件和八个测试类，本地三套件全绿，**但从未
在页面上验证通过，也从未提交**。生产一直跑在 v0.1.20（Flyway V027），页面上那块「模型
配置」对用户是坏的。

2026-08-29 实测又添了一条独立的坏消息。用 MiniMax 官方端点（标准 OpenAI 兼容，不是中转站）
测试切换：密钥有效、`/v1/models` 与 `/v1/chat/completions` 都返回 200，但 MiniMax-M3 是推理
模型，即使设了 `response_format: {"type": "json_object"}` 且 `finish_reason: stop`，正文仍然是

```
<think>The user wants a one-sentence summary...</think>\n\n{"summary":"..."}
```

这不是合法 JSON。本仓库每一个结构化调用点都以 `model_validate_json` 或 `json.loads` 收尾，
所以**即使配置管道修好了，切到任何推理模型仍然会全线失败**。控制台要真正可用，需要修的
不止是控制台。

## 决策

1. **删除控制台及其 HTTP 面**：Web 的 `app/admin/models/`、`app/api/admin/models/` 与侧边栏
   入口；Core API 的 `GenerationModelController/Service`、`GenerationProviderController/
   Service/Probe`、`GenerationCredentialCipher` 及其测试；`api/openapi.yaml` 里两个
   `/admin/models/generation*` 端点与三个 schema。
2. **保留数据库层**：`generation_model_config`（单行）、`generation_model_catalog`、
   `generation_provider_config` 三张表和 `build_client_from_env` 的读路径不动。理由有二：
   它在生产验证过 —— 2026-08-11 靠 V024 把生成模型从 `deepseek-chat` 切到
   `deepseek-v4-flash`，此后 17 天无事故；它还是 `/ops` 成本归因的唯一数据源，每次调用
   落库的价目快照就来自 `generation_model_catalog`。
3. **换模型 = 改数据库一行**，通过迁移或一条 SQL，不再有界面。这是一个一年发生零到两次的
   动作，不值得一个常驻的写入面。
4. **推理块剥离下沉到 `LlmClient`**，而不是留给控制台。它是客户端的健壮性问题：无论谁决定
   用哪个模型，`<think>` 前缀都不该到达八个调用点中的任何一个。非流式在 `_complete` 出口
   剥离，流式在 `stream_summarize` 用一个跨 delta 的状态机剥离（`/rag/ask/stream` 的增量
   直接渲染进浏览器）。剥离锚定在响应开头 —— 一篇讲推理模型的文章，其摘要里可以合法地
   出现字面量 `<think>`，全局剥离会静默改坏字段。

## 备选

- **修好控制台。** 需要同时解决：中转站路径推导（ADR-0032 已记录为负结果）、探测、加密
  写库、激活切换、草稿态。这些的总失败面远大于「换密钥不用 SSH」的收益，而换密钥是个
  低频动作。拒绝。
- **连表一起删，完全回到环境变量。** 两个具体代价，都是可量化的：
  - `.env` 里写的是 `LLM_MODEL=deepseek-chat`，而生产实际跑的是 `deepseek-v4-flash`。
    删掉数据库读路径会让生产**静默退回** `deepseek-chat`：输入 ¥1/M → ¥2/M，输出
    ¥2/M → ¥8/M。
  - `llm_usage` 的 `input/cached_input/output_cny_per_million` 三列会永久为 NULL，
    `/ops` 上「4,867 次使用调用时模型价目快照，3,352 次只能用历史 fallback」这个区分
    随之消失，成本页退化成一个用固定价目回算的估算。

  拒绝。要砍的是没跑通的东西，不是它下面跑通了的东西。

## 后果

- 换供应商地址或密钥回到「SSH + 改 `infra/compose/.env` + 重启生成侧容器」。这是 ADR-0032
  之前的状态，也是 ADR-0032 想解决的问题 —— 该问题重新存在，是本决策明确接受的代价。
- `LLM_CREDENTIAL_MASTER_KEY` 变成一把没有写入方的密钥。保留它的声明与 preflight 检查，
  因为 `generation_provider_config` 仍可能持有历史密文；生产当前是 `env://LLM_BASE_URL`
  占位符，实际没有密文，所以主密钥缺失不会影响运行。
- `.env.example` 补了说明：`LLM_MODEL` 不是运行中部署使用的模型，只对没有 `DATABASE_URL`
  的隔离测试生效，且必须与数据库那一行保持一致。这条注释存在的原因是它真的误导过人。
- 切换到推理模型现在只是配置问题，不是代码问题。

## 回滚

V027 时代的控制台代码在本提交之前的 git 历史里，`git show` 即可取回。

TASK-M5-033 的多 Profile 版本从未合入远端，因此不在远端历史中，它的验收记录也随之丢弃。
本 ADR 的背景段是它留下的唯一记录 —— 这是有意的：一份没有人能取回代码的验收报告，只会让
后来的人以为那个功能存在过并且可用。

数据库不需要回滚：本决策没有新增或删除任何迁移，生产仍是 Flyway V027。
