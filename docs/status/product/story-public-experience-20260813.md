# TASK-M3-REOPEN-001 验收记录：Story 公开入口有效性收口

日期：2026-08-13
分支：`codex/documentation-handbook`

## 结论

Story 的内部聚类、报告去重和 RAG 折叠能力保持不变；公开入口改名为“事件追踪”，并使用
比后台聚类更严格的读取门槛：至少两家独立来源、所有非主来源均有聚类评分且最低评分不低于
`0.67`。公开结果从 39 个多来源 Story 收敛到 7 个高置信度事件。

读者现在能在列表直接看到参与来源，在详情先读主来源摘要、再按时间线核验其他报道。内部
相似度不再展示，页面明确说明“多家来源”不等于每项主张均被独立证实。

## 数据验证

- 本地库共 1693 个 Story，其中 39 个拥有至少两家独立来源。
- 新公开 API 返回 7 个事件，0 个缺少两家来源或具体来源名称。
- 已确认的三个误合样本不再公开：NVIDIA/Ollama、Anthropic Fable/Claude Code、
  DeepSeek 发布/网易有道产品接入。
- 单来源 Story 与低置信度 Story 的详情路由返回 404。

## 自动化证据

- Java 21：`StoryControllerTest` 3 项通过；Core API production package 通过。
- Web：Vitest 全量 75 项通过；TypeScript、ESLint、Next.js production build 通过。
- Python：Story、Report、RAG folding/trace 回归 101 项通过。
- OpenAPI 3.1 YAML 可解析，`/stories` 响应契约与实际数组响应一致。
- Docker Compose：仅重建并替换 `core-api`、`web`；两者及原有依赖均健康。
- Chrome 桌面与 375px 窄屏目标流程通过：列表标题/来源可见，详情时间线可见，相似度不可见，
  控制台无错误，窄屏无水平溢出。

内置 Browser 运行时因无法写入本地资源路径未能连接；项目自带 Playwright 锁定版本也未安装
独立浏览器包。最终视觉回归复用本机 Chrome，未额外下载浏览器，避免增加 Docker/工具磁盘占用。

## 剩余风险与下一卡

`0.67` 是基于当前 39 个多来源样本做的保守公开门槛，不替代人工标注的聚类纯度评测；后台仍有
误合、漏合和 486 条待审核建议。下一卡应为 `TASK-M3-REOPEN-002`：建立 Story golden set，
分别评估事件同一性与“报道/采用/上下游动作”的关系，再决定是否升级聚类算法与稳定 Story 身份。
