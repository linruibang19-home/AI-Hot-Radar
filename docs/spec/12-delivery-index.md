# 12｜完整交付索引

文档 ID：`AHR-INDEX-1200`  
版本：`v1.2.0`

## 1. 这是“开发规格包”，不是已经写完的产品源码

该包提供产品、架构、数据、接口、采集、RAG、前端、安全、测试、部署和 AI IDE 任务边界；`database/`、`api/`、`schemas/`、`config/` 是可执行契约。真正的 Next.js/Spring Boot/FastAPI 项目由 TASK-M0 起逐卡创建。

## 2. 文件清单

| 路径 | 内容 | 状态 |
|---|---|---|
| `README.md` | 总入口、优先级、导航 | 完成 |
| `AGENTS.md` / `CLAUDE.md` / `.cursor/rules/*` | 三类 AI IDE 统一约束 | 完成 |
| `00-master-spec.md` | 锁定技术与范围 | 完成 |
| `01-product-requirements.md` | 页面、角色、产品验收 | 完成 |
| `02-system-architecture.md` | Java/Python/Next.js 边界 | 完成 |
| `03-data-ingestion.md` | 核心实体、去重、Story | 完成 |
| `04-rag-agent-design.md` | 时间/事件感知混合 RAG | 完成 |
| `05-api-contract.md` | API 语义 | 完成 |
| `06-frontend-spec.md` | 页面与组件状态 | 完成 |
| `07-quality-security-ops.md` | 测试、安全、版权、运维 | 完成 |
| `08-roadmap-ai-ide.md` | M0–M5 与任务卡 | 完成 |
| `09-source-registry-fulltext.md` | 信源分层与全文标准 | 完成 |
| `10-source-adapter-implementation.md` | RSS/API/HTML/PDF 实现 | 完成 |
| `11-end-to-end-runbook.md` | 联调、日报、RAG、恢复 | 完成 |
| `config/sources.yaml` | 140 个入口 | 完成；运行时仍需 probe |
| `config/social-watchlist.yaml` | 30 X + 8 公众号 | 完成；默认关闭 |
| `config/taxonomy.yaml` | 主题分类 | 完成 |
| `config/ingestion-profiles.yaml` | Adapter 机器契约 | 完成 |
| `config/site-overrides.yaml` | 特殊站点规则 | 候选规则；fixture 后激活 |
| `schemas/source-registry.schema.json` | 单来源 JSON Schema | 完成 |
| `schemas/ingestion-event.schema.json` | 任务事件 Schema | 完成 |
| `database/migrations/V001__baseline.sql` | 基线数据库（Flyway 唯一入口） | 完成 |
| `api/openapi.yaml` | API 基线 | 完成 |
| `.env.example` | 环境变量 | 完成 |
| `scripts/validate_spec.py` | 离线规格校验 | 完成 |

## 3. 推荐交付给 AI IDE 的顺序

```text
先解压完整目录
→ 阅读 README + 00 + 08
→ 执行 TASK-M0-001
→ TASK-M1-001（RSS/模型/任务）
→ TASK-M1-002（全文与健康门禁）
→ 新增 TASK-M1-003（GitHub/Changelog/arXiv/API）
→ Wave A 真实 canary
→ M2 内容网站
→ M3 Story
→ M4 RAG
→ M5 上线
```

不要把整包粘贴进聊天窗口要求“一次生成完整产品”。让 IDE 在仓库中逐文件读取，并一次只执行一张任务卡。

