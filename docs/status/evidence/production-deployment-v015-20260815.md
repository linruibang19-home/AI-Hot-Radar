# v0.1.15 中文公共阅读门与教材生产发布（2026-08-15）

## 发布对象

- GitHub 合并提交：`709378cf4fcf46f9b23ddc545b5016f606a9dbc9`；
- Release 标签：`v0.1.15`；
- Release workflow：<https://github.com/linruibang19-home/AI-Hot-Radar/actions/runs/31834494935>；
- 生产地址：<https://aihotradar.online>；
- 目标环境：香港 Ubuntu 22.04.5、2C4G、Docker Compose、Caddy HTTPS。

这次发布不修改 RAG 检索策略、核心数据实体或数据库 schema。它给公共内容读取增加中文
结构化完成门，并补齐证据入库与切块、Redis 短期状态、90 题黄金集与质量页教材。

## 发布门禁

| 层 | 结果 |
|---|---|
| Python | 916 passed、2 skipped；mypy 87 个源文件；Ruff 与格式通过 |
| Java | Maven JDK 21 `85 / 85` 通过 |
| Web | typecheck、lint、Vitest `81 / 81`、Next production build 通过 |
| 数据库 | Flyway 空库应用与 pgvector/baseline table 验证通过 |
| 规格文档 | 140 个信源、9 个 profile；139 份 Markdown / 334 个本地链接通过 |
| Release | web、core-api、ai-service 三张 `sha-709378...` 镜像构建并推送成功 |

## 生产部署

服务器 `/opt/ai-hot-radar` 的 `production` 分支从 `2ba12225...` 严格 fast-forward 到
`709378cf...`，工作树保持干净；`.env` 只在目标机以 600 权限保存，部署过程未输出密钥。
`IMAGE_TAG` 与 checkout HEAD 对齐后执行 `infra/scripts/deploy-production.sh`：

1. preflight 校验不可变镜像、必需密钥、预算确认、TLS、Compose 与文件权限；
2. 拉取三张业务镜像并重建应用服务；
3. 等待 PostgreSQL、Redis、Java、Python、Web、调度、流水线、监控、备份与 Caddy；
4. 公网 smoke 验证 `/health`、`/`、`/items`、`/reports`、`/ask`、`/eval`、`/ops`、
   `/robots.txt`、`/sitemap.xml`、`/api/items`、安全头和私有管理边界。

部署脚本最终返回 `deploy OK: sha=709378cf4fcf46f9b23ddc545b5016f606a9dbc9`。

## 发布后事实快照

2026-08-15 从生产 PostgreSQL 只读查询：

| 指标 | 数值 |
|---|---:|
| 注册信源 | 140 |
| 内容 | 2415 |
| active chunk / 已向量化 | 9822 / 9822 |
| Story | 1967 |
| RAG 问答 / 引用 | 232 / 990 |
| 报告 | 18 |

公网 `/api/items?limit=20` 抽查的前 20 条均有非空 `zhTitle` 与 `summary`；英文原文仍保留在
`excerpt` 与 revision/chunk 证据层。这证明公共阅读门没有删除原始证据，也没有把摘要当成
最终 RAG 证据。

## 已知边界

- Chrome 扩展控制在本机初始化阶段失败，因此本记录只把真实 HTTP/容器/API 验收记为证据，
  不把它冒充为截图级浏览器验收；
- `/eval` 仍是版本化评测产物，不随每次页面访问重跑 90 题；`/ops` 才读取 30 秒 Redis 快照；
- 图片没有 OCR/视觉 embedding，PDF 当前只做文本提取；这些边界见 handbook 20；
- 质量指标中的自动支持度不能代替高风险数字和主体关系的人工复核。
