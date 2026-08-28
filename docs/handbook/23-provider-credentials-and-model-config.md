# 23｜生成模型与供应商凭证：现在怎么配，为什么没有界面

> 2026-08-29 重写。此前这一章描述的是 `/admin/models` 控制台，那个页面已经删除
> （[ADR-0033](../adr/0033-generation-console-removed-model-stays-database-backed.md)）。
> 加密信封与中转站负结果的设计记录仍保留在
> [ADR-0032](../adr/0032-generation-provider-credentials-are-database-backed.md)。

## 1. 配置分成两半，来源不同

| 配的是什么 | 来源 | 怎么改 |
|---|---|---|
| **用哪个模型** | `generation_model_config` 单行 + `generation_model_catalog` 价目 | 改数据库（迁移或一条 SQL） |
| **发到哪、用哪把钥匙** | `LLM_BASE_URL` / `LLM_API_KEY` 环境变量 | 改 `infra/compose/.env` + 重启生成侧容器 |

这个分法不是设计出来的，是砍剩下的：模型那半在生产验证过（2026-08-11 从 `deepseek-chat`
切到 `deepseek-v4-flash`，此后一直是它），凭证那半的写入界面没验证通过，被删了。

`generation_provider_config` 表还在，行内容是 `env://LLM_BASE_URL` 占位符，密文为 NULL。
它现在只有回落语义：地址是占位符就用环境变量，密文是 NULL 就用环境变量。没有任何代码
往里写。

## 2. `.env` 里的 `LLM_MODEL` 不是运行中用的模型

这是本章最容易踩的一条，而且真的踩过。

[`build_client_from_env`](../../apps/ai-service/src/ahr/processing/llm.py) 只要能连上数据库，
就从 `generation_model_config` 读模型；`LLM_MODEL` 仅对没有 `DATABASE_URL` 的隔离测试和
命令行工具生效。所以生产 `.env` 长期写着 `deepseek-chat`，而实际跑的是 `deepseek-v4-flash`，
两者相差了 17 天和 4,867 次调用都没人发现。

约定：**两处保持一致**。`.env.example` 里已经写上了这条注释。

想确认线上究竟在跑什么，不要看 `.env`，查调用记录：

```sql
SELECT model, count(*), min(created_at)::date, max(created_at)::date
  FROM llm_usage GROUP BY 1 ORDER BY 2 DESC;
```

## 3. 换模型

1. 目标型号必须先在 `generation_model_catalog` 里且 `enabled`，带完整价目
   （`input/cached_input/output_cny_per_million`）—— 缺价目不会报错，只会让 `/ops` 的成本
   归因退回历史 fallback，静默失真；
2. 更新 `generation_model_config` 的 `model_id` 并递增 `version`；
3. 生成侧容器不需要重启：客户端每次构造时读库；
4. 验收看 `llm_usage.model` 是否出现新值，以及 `/ops` 的「调用时快照」行数是否在涨。

## 4. 换密钥或换供应商

SSH 到目标机，改 `infra/compose/.env` 的 `LLM_BASE_URL` / `LLM_API_KEY`，重启
`ai-service`、`pipeline`、`scheduler`。这是 ADR-0032 当初想消灭的流程，ADR-0033 明确接受了
它回来 —— 换密钥是低频动作，不值得一个常驻的写入面。

只接**官方 OpenAI 兼容端点**。中转站是记录在案的负结果，原因见 ADR-0032 的「备选」：
路径约定不统一，而填错地址的表现是 `200 text/html`，看起来像成功。

## 5. 推理模型：`<think>` 会被剥掉

切到推理模型（MiniMax-M3、DeepSeek-R1、QwQ、GLM-Z1 一类）时，正文可能长这样：

```
<think>The user wants a one-sentence summary...</think>

{"summary":"..."}
```

`response_format: {"type": "json_object"}` **压不住它**——2026-08-29 用 MiniMax 官方端点实测，
`finish_reason: stop`，正文仍带前缀。本仓库每个结构化调用点都以 `model_validate_json` 或
`json.loads` 收尾，所以这会让八个调用点全部失败。

`LlmClient` 因此在两处剥离：非流式在 `_complete` 的出口，流式在 `stream_summarize` 用一个
跨 delta 的状态机（开标签经常被切成 `<thi` + `nk>`）。剥离**锚定在响应开头**——一篇讲推理
模型的文章，其摘要里可以合法出现字面量 `<think>`，全局剥离会静默改坏字段。

未闭合的开标签（token 烧完了）返回空串而不是那段推理文本：响应里本来就没有答案，让调用方
按「模型没给出答案」降级，比给它一段过不了校验的散文更诚实。

## 6. `LLM_CREDENTIAL_MASTER_KEY`

它现在是一把**没有写入方**的密钥：AES-256-GCM 信封的解密路径还在，但没有代码再往
`credential_ciphertext` 写。保留声明与 preflight 长度检查，是因为该列理论上可能持有历史密文；
生产当前没有。

它缺失时**不影响运行**——生成侧走的是环境变量回落路径。这跟 ADR-0032 时代不一样，那时候
缺失会让保存按钮 503、pipeline 静默失败。

## 7. 排查入口

| 症状 | 先看哪里 |
|---|---|
| 不确定线上跑的什么模型 | `llm_usage` 的 `model` 列，不是 `.env` |
| 富集/报告静默不产出 | `llm_usage` 的 `succeeded = false` 行与 `attempts` |
| 换了模型但没生效 | `generation_model_config.model_id` 是否真的改了；`generation_model_catalog` 里该型号是否 `enabled` |
| `/ops` 成本突然全变「历史 fallback」 | 新型号在 catalog 里缺价目列 |
| 回答里出现 `<think>` | 剥离只处理响应开头；若模型把它放在中间，需要在 `llm.py` 补规则并加测试 |
| 401 / 403 | `LLM_API_KEY` 与 `LLM_BASE_URL` 是否属于同一家 |
