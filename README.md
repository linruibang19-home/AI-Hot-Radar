# AI Hot Radar

> 面向 AI 行业的可追溯时效情报平台：持续聚合公开信源，将分散资讯整理为可订阅的情报产品，并在同一份原文证据库上提供句级可回跳、可评测的 RAG 问答。

**Live Demo**: [https://aihotradar.online](https://aihotradar.online)

**Tech Stack**: Next.js 15.5 / React 19 / TypeScript · Spring Boot 3.4 / Java 21 · FastAPI / Python 3.12 · PostgreSQL 16 + pgvector · Redis 7 · DeepSeek / bge-m3 / bge-reranker-v2-m3 · Docker Compose / Caddy / GHCR / GitHub Actions

![精选首页：持续更新的 AI 情报、热点与推荐理由](docs/assets/screenshots/home.png)

![RAG 问答：回答中的事实可回跳到原始证据](docs/assets/screenshots/rag-answer.png)

**建议阅读顺序**：先用 [30 秒](#30-秒这个项目解决什么问题)了解价值，再用 [3 分钟](#3-分钟产品业务与技术全景)看清产品和架构；需要核验实现时进入 [30 分钟深度章节](#30-分钟核心链路与工程深度)，或直接使用[文档导航](#文档导航)。

<details>
<summary>当前生产与质量快照（2026-08-14，历史快照，非实时承诺）</summary>

- 生产版本：`v0.1.14@2ba1222`，香港 2C4G 单机，Docker Compose 编排，Caddy 提供 HTTPS。
- 分层回归：Python **916 passed / 2 skipped**，mypy 检查 87 个源文件无错误；Java `84 / 84` 通过。Web、契约、迁移、Compose smoke 与受影响 RAG 门禁由 CI 分层执行。
- 固定 RAG 发布评测：2026-08-11，90 题黄金集；主集 Recall@20 `0.8994`，句级引用覆盖率 `0.9881`，段落支持达标率 `0.9344`，可回答题误拒 `0 / 78`，诱导题错误断言 `0 / 12`。
- 上述生成评测产物记录的模型字段为 `deepseek-chat`；截至本快照，生产生成配置为 `deepseek-v4-flash` v3。检索使用 bge-m3，候选重排使用 bge-reranker-v2-m3。切换模型后必须重新跑门禁，不能沿用旧结论。
- 实时运行状态、告警、内容量与当前版本以 [`docs/status/current/`](docs/status/current/) 为准，不从 README 的历史数字反推。

</details>

---

## 30 秒：这个项目解决什么问题

- **及时发现**：统一轮询官方博客、文档、GitHub、论文与行业媒体，保留来源、抓取时间、正文版本和失败状态。
- **压缩噪声**：规范化 URL 与正文，跨来源去重并聚合为 Story，再通过规则和 LLM 结构化结果产出精选、热点、主题与事件视图。
- **稳定交付**：日报、周报、月报先生成不可变的 `PUBLISHED` 快照；网页与双确认邮件订阅读取同一份已发布事实，不在发送时临时生成另一版内容。
- **可核验问答**：RAG 只把原始 evidence chunk 作为证据；服务端绑定引用、原文 URL 和支持关系，证据不足时部分回答或拒答。

它不是“新闻页 + 聊天框”的拼接，而是一条从公开来源、正文版本、事件聚类、报告发布到证据检索和引用校验的可追溯数据链路。

---

## 3 分钟：产品、业务与技术全景

### 用户能做什么

| 用户任务 | 产品出口 | 关键约束 |
|---|---|---|
| 快速了解近期 AI 动态 | 精选、全部动态、热点、事件追踪 | 卡片来自已入库事实；可回到原始来源 |
| 按公司、模型或技术方向跟踪 | 主题地图与主题详情 | 区分核心命中、相关对比和顺带提及，避免关键词出现即归类 |
| 稳定阅读阶段性总结 | 日报、周报、月报 | 报告先发布快照；生成失败不阻断资讯入库与网站读取 |
| 定期接收报告 | 双确认邮件订阅 | 未确认地址不投递；邮件只发送 `PUBLISHED` 报告 |
| 对已采集语料提问 | 带句级引用的 RAG 问答 | 原始 chunk 才能成为证据；引用不可由模型自行伪造 |
| 查看工程质量 | RAG 质量、运行状态、模型配置、信源后台 | 指标带评测批次；管理写操作需要 RBAC 与审计 |

### 业务架构（数据链路）

```text
公开信源
  │  RSS / API / HTML / GitHub / arXiv
  ▼
发现与正文回源 ──► 全文门禁 ──► URL 与正文规范化 ──► 去重 / revision 版本化
                                                          │
                          ┌───────────────────────────────┴───────────────────────────────┐
                          ▼                                                               ▼
              LLM 结构化 / 实体识别                                             原始正文证据分块
                          │                                                               │
                          ▼                                                               ▼
                 Story 聚类与精选评分                                       bge-m3 向量 + 关键词索引
                          │                                                               │
             ┌────────────┼────────────┐                                                  ▼
             ▼            ▼            ▼                                      混合检索 / 融合 / 重排
       精选 / 热点     主题 / 事件   日 / 周 / 月报                                                │
             │                         │                                                         ▼
             └──────────────┬──────────┘                                        支持度校验 / 引用绑定
                            ▼                                                                    │
                        网站读者 ◄──────── 双确认邮件投递                              可核验 RAG 回答
```

所有出口读取同一份 PostgreSQL 已发布事实。RSS 或搜索摘要只用于发现，不能冒充正文；AI 生成的摘要用于阅读和结构化，不会替代原始 evidence chunk。

### 技术架构与服务边界

```text
Browser
  │ HTTPS
  ▼
Caddy :80/:443
  │
  ▼
Next.js 15.5 / React 19
  ├── 同源公共读请求 ─────────────► Spring Boot 3.4 / Java 21
  │                                  ├── 内容、报告、订阅、管理 API
  │                                  ├── RBAC、幂等、审计、缓存边界
  │                                  └── PostgreSQL 16 + pgvector / Redis 7 / SMTP
  │
  └── RAG 与工程读视图 ───────────► FastAPI / Python 3.12
                                     ├── 采集、正文抽取、结构化、Story 聚类
                                     ├── chunk / embedding / hybrid retrieval / rerank
                                     ├── DeepSeek 生成、引用校验与黄金集评测
                                     └── PostgreSQL 16 + pgvector / Redis 7

后台进程：Python Scheduler / Pipeline ──► PostgreSQL
交付链路：GitHub Actions ──► GHCR 不可变镜像 ──► Docker Compose ──► Caddy
恢复链路：PostgreSQL + 配置备份 ──► Restore Verify
```

| 层 | 技术 | 负责什么 | 明确不负责什么 |
|---|---|---|---|
| Web | Next.js 15.5、React 19、TypeScript、App Router、SSR | 内容页面、交互、同源代理、流式问答 UI | 直接查库、保存模型密钥或 OPERATOR 凭据 |
| Core API | Spring Boot 3.4、Java 21、Maven | 公共读 API、报告发布、订阅、管理 RBAC、幂等与审计 | 网页抽取、embedding、RAG 检索算法 |
| AI Service | FastAPI、Python 3.12、Pydantic、httpx | 采集、正文处理、结构化、聚类、报告生成、RAG 与评测 | 用户权限、订阅业务事实和邮件投递状态机 |
| Fact Store | PostgreSQL 16、pgvector、Flyway | 内容版本、证据块、Story、报告、订阅、审计与向量 | 把短期缓存状态当成业务真相 |
| Cache | Redis 7 | 查询缓存、速率限制、短期去重锁和短生命周期状态 | 持久业务事实、跨服务最终一致性的唯一依据 |
| Delivery | Docker Compose、Caddy、GHCR、GitHub Actions | 构建、门禁、不可变镜像、HTTPS、备份与恢复校验 | 在生产机现场修改源代码或手工拼装版本 |

Java 与 Python 的拆分按业务边界而不是语言偏好：Java 承担稳定事务、权限和交付语义；Python 承担变化更快的采集、模型与评测生态。两侧通过 OpenAPI、共享 schema 和 PostgreSQL 事实模型协作，避免把 Python 算法对象泄露为 Java 领域对象，也避免两套服务各自维护一份业务状态。

### 工程亮点

- **把引用做成服务端约束**：模型只返回候选声明；服务端根据实际召回的 chunk 绑定引用和 URL，校验支持关系，失败分支按 fail-closed 处理。
- **用混合检索解决不同召回问题**：dense 处理语义近似，PostgreSQL sparse 处理型号和专名，时间过滤处理“最近”语义；融合后再经 cross-encoder 重排，而不是只依赖向量相似度。
- **把负实验也留在发布证据里**：固定 90 题黄金集记录每轮改动、指标和结论；B2、B8 的退化没有被包装成优化，GEN-FIX 则定位并修复了解析出口问题。
- **分开事实、版本、证据与产品出口**：`content_item → content_revision → document/chunk_set/evidence_chunk → story/report` 逐层保存，使重抓取、重切块、重嵌入和报告重发可以独立追溯。
- **所有出口共用一个事实源**：网站、报告、邮件和 RAG 都从 PostgreSQL 的已发布事实出发；Redis 只做缓存和限流，邮件也不维护“邮件专用语料”。
- **用数据约束技术选型**：当前体量下 PostgreSQL + pgvector 已覆盖事务、稀疏与向量检索；没有证据收益时不引入 Kafka、独立向量库、Kubernetes 或 GraphRAG。
- **把交付和恢复纳入功能定义**：CI 同时检查代码、契约、Flyway、秘密扫描、Compose smoke 与受影响 RAG 门禁；生产使用不可变 GHCR 镜像，并保留备份、恢复演练、RBAC 和审计链路。

### 仓库地图：代码与证据如何组织

```text
AI-Hot-Radar/
├─ apps/
│  ├─ web/                 Next.js 页面、SSR、交互与同源代理
│  ├─ core-api/            Spring Boot 内容、报告、订阅和管理业务
│  └─ ai-service/          FastAPI 采集加工、RAG 与离线评测
├─ database/migrations/    Flyway V001–V026，数据库可执行演进历史
├─ api/ + schemas/         OpenAPI 与 Java/Python 共享结构契约
├─ config/                 信源、采集策略、站点覆盖、主题与模型配置
├─ infra/                  Docker Compose、Caddy、部署、备份和恢复脚本
├─ data/golden/            RAG 黄金集、fixture 与可复现实验输入
├─ docs/
│  ├─ handbook/            按业务主线理解系统
│  ├─ spec/                产品、架构、RAG、质量与任务规格
│  ├─ adr/                 技术决策、被否决方案与适用边界
│  ├─ status/              发布、评测、压测和事故证据
│  └─ interview/           项目讲解、代码走查与技术问答
├─ .github/                CI、镜像构建和发布门禁
├─ scripts/                文档校验、评测汇总与工作区维护
├─ AGENTS.md               仓库级工程约束的唯一来源
└─ DEVELOPMENT.md          本地开发、Docker Compose 与验证入口
```

这些目录不是展示层级：Flyway migration 是数据库演进事实，schema 是跨语言契约，CI 是发布门禁，infra 是可恢复交付路径。为了让根目录更短而删除它们，会同时删除项目的可验证性。

其余产品视图：

<details>
<summary>日报 / 周报 / 月报</summary>

![报告页面](docs/assets/screenshots/reports.png)

</details>

<details>
<summary>RAG 质量门禁</summary>

![RAG 质量页面](docs/assets/screenshots/rag-quality.png)

</details>

<details>
<summary>动态信源后台</summary>

![信源后台](docs/assets/screenshots/source-operations.png)

</details>

---

## 30 分钟：核心链路与工程深度

以下内容面向希望核验实现的人，可按需跳读。更完整的逐文件说明、ADR 和历史证据在 [`docs/`](docs/) 中维护。

### 从一个链接到一条可引用证据

1. **发现**：调度器按信源策略获取 RSS、API、站点列表、GitHub 或 arXiv 元数据，并保存来源、抓取时间和 trace id。
2. **正文回源**：adapter 访问 canonical URL，执行内容类型、长度、正文率和模板噪声门禁；RSS 摘要只能帮助发现，过不了全文门禁就不能进入 RAG 证据库。
3. **规范化与版本化**：统一 canonical URL、正文空白和内容哈希；重复正文复用内容，正文发生变化则新增 `content_revision`，不覆盖历史版本。
4. **结构化**：LLM 输出必须通过 Pydantic schema 校验，提取标题、摘要、类别、实体和事件候选；失败可重试或降级，但原始正文仍保留。
5. **证据分块**：对已通过全文门禁的原始正文按标题、段落和列表结构切分；chunk 保存原文字符区间、父段、revision 与 chunk-set 版本。
6. **索引与发布**：bge-m3 生成向量写入 pgvector，同时构建 PostgreSQL 关键词通道；只有完整、可追溯的 chunk-set 才能进入检索。

分块不是对 AI 摘要再次切片。当前策略以 400 token 为目标、120 token 为最小块、700 token 为软上限、60 token 为上下文重叠；超长结构块继续按句子或安全字符边界拆分，1200 token 为硬上限。具体常量、边界和降级分支见 [`docs/handbook/08-rag-indexing-and-retrieval.md`](docs/handbook/08-rag-indexing-and-retrieval.md) 与对应代码。

### 核心数据层级（为什么不能混）

| 层级 | 保存什么 | 为什么独立 |
|---|---|---|
| `source` / `crawl_run` | 信源配置、抓取批次、健康和失败 | 区分“来源失败”和“内容不存在”，支持限流、重放与审计 |
| `content_item` | 同一逻辑内容的稳定身份 | URL 或标题变化时仍可聚合同一内容 |
| `content_revision` | 某次正文事实、哈希和抓取时间 | 原文更新不能覆盖旧证据；回答和报告必须能回溯版本 |
| `document` / `chunk_set` | 一次切块策略、模型和版本 | 新 chunker 或 embedding 可重建，不污染旧索引 |
| `evidence_chunk` | 原始正文片段、位置、向量与父段 | RAG 引用的最小可核验单元，不能由摘要替代 |
| `story` / `story_member` | 跨来源同一事件及成员 | 去重后仍保留各家来源和不同表述 |
| `report` / `report_revision` | 日周月报草稿、审核与发布快照 | 邮件和网页只读取同一已发布版本，避免发送时漂移 |

PostgreSQL 同时承载这些事务关系、全文/稀疏检索和 pgvector 向量检索，当前数据量下减少了双写、索引同步和恢复复杂度。Redis 不参与这些事实的最终判定。

### RAG 全链路

```text
用户问题
  │
  ├─► 语义解析：问题类型 / 实体 / 型号 / 时间范围 / 是否要求最新
  │
  ├─► Dense：bge-m3 向量召回
  ├─► Sparse：PostgreSQL tsvector / 专名与型号召回
  └─► Temporal：发布时间与 freshness 约束
          │
          ▼
   候选归一化与 RRF / 加权融合
          │
          ▼
   bge-reranker-v2-m3 cross-encoder 重排
          │
          ▼
   父段扩展 + 来源去重 + token 预算
          │
          ▼
   DeepSeek 受约束生成：声明与 evidence id 分离
          │
          ▼
   服务端引用绑定 / 支持度校验 / 弱支持删除
          │
          ├─ 证据充分：回答 + 句级引用 + 原文 URL
          ├─ 部分充分：只回答有证据的部分
          └─ 不充分：明确拒答，不补常识、不猜测
```

关键点不是“把 Top-K 塞给模型”：

- 查询解析先识别时间语义和专名，避免纯向量检索把 `MXFP4`、版本号或“最近一周”模糊掉。
- dense、sparse、temporal 的候选先归一化，再融合；reranker 只处理有界候选，控制外部调用成本。
- 检索命中子块后可扩展父段，但最终引用仍绑定实际支持答案的原始 passage。
- 模型输出按 schema 解析；即使模型返回 Markdown 或错误 JSON，也不能绕过引用绑定和支持度检查。
- Redis 缓存键包含语料/索引新鲜度版本，内容更新后旧回答不会继续命中。

实现入口与约束见 [`docs/spec/04-rag-agent-design.md`](docs/spec/04-rag-agent-design.md)、[`docs/code-map.md`](docs/code-map.md) 和 [`docs/adr/`](docs/adr/)。

### RAG 如何评测

固定黄金集包含 90 题，覆盖最近动态、时间线、对比、事实核查、原理解释和不可回答六类问题。检索、生成、引用和拒答分别计量，避免用一个总分掩盖失败位置。

| 指标 | 2026-08-11 历史结果 | 样本 | 它回答的问题 |
|---|---:|---:|---|
| 主集 Recall@20 | `0.8994` | 90 题 | 正确证据是否进入前 20 个候选 |
| 中文厂商专项 Recall@20 | `0.9333` | 15 题 + 近邻噪声 | 专名、别名和中文分词下能否召回目标 |
| 句级引用覆盖率 | `0.9881` | 90 题生成评测 | 有事实主张的句子是否带引用 |
| 段落支持达标率 | `0.9344` | 90 题生成评测 | 引用 passage 是否达到自动支持门槛 |
| 可回答题误拒 | `0 / 78` | 78 题 | 有证据时是否错误拒绝 |
| 诱导题错误断言 | `0 / 12` | 12 题 | 无证据或错误前提下是否顺着用户编造 |

评测产物记录于 [`docs/status/eval/`](docs/status/eval/)；上述批次的生成模型字段为 `deepseek-chat`，检索和重排使用 bge-m3 / bge-reranker-v2-m3。自动 citation precision 是诊断指标，不等同于高风险事实的人审；任何模型、语料或检索策略变更都应产生新 run id，而不是修改旧快照。

### 三个最有价值的工程案例

| 实验 | 假设与改动 | 证据与结论 |
|---|---|---|
| B2：稠密 + 稀疏并集 | 加入 PostgreSQL 关键词通道，预期专名召回全面提升 | 局部专名题改善，但全局 MRR 从 `0.7630` 降至 `0.7480`；无条件并集引入噪声，记录为退化而非发布成果 |
| B8：融合权重扫描 | 扫描 42 组 dense / sparse / temporal 权重，预期找到更优全局组合 | 接入重排后差距收敛到约 `0.0004`，不足以支撑新增复杂度；结论是保持现状 |
| GEN-FIX：生成侧复测 | 初轮误拒率上升，最初怀疑语料竞争或检索退化 | 抓取原始模型响应后发现 Markdown/JSON 解析失败和引用编号写入错误；修复失败分支后误拒 `7.69% → 0.00%`，证明问题位于解析出口而非检索 |

完整逐轮判据和可复现产物见 [`docs/status/eval/`](docs/status/eval/) 与 [`docs/interview/03-rag-deep-dive.md`](docs/interview/03-rag-deep-dive.md)。

### 报告与邮件闭环

```text
已发布 Story / 精选内容
        │
        ▼
报告生成草稿 ──► 结构与引用校验 ──► PUBLISHED 不可变快照
                                           │
                         ┌─────────────────┴─────────────────┐
                         ▼                                   ▼
                    网站报告页                         到期订阅扫描
                                                             │
邮箱提交 ─► 确认邮件 ─► 双确认激活 ─► 按周期/时区 ─► 投递 PUBLISHED 快照
                                                             │
                                                   成功 / 重试 / 退订审计
```

日报、周报、月报共享报告版本模型，但时间窗口和模板不同。订阅先发送确认链接，未确认不投递；投递器只读取已经发布的报告 revision，不会为每个收件人重新调用模型。这样网页、邮件和后续 RAG 对同一时期事实的引用可以对齐，LLM 或 SMTP 暂时失败也不会阻断资讯采集。

### 生产交付、安全与恢复

- GitHub Actions 构建按 commit 固定的 GHCR 镜像；生产 Compose 拉取不可变 tag，不在服务器直接构建或手改代码。
- Caddy 终止 HTTPS；Core API、AI Service、PostgreSQL 与 Redis 只在 Compose 内网暴露。
- 管理接口使用角色凭据、幂等键和审计记录；模型密钥、SMTP 凭据与数据库密码只存在于运行环境，不进入镜像和 Git。
- PostgreSQL 是恢复主线；备份脚本之后必须执行 restore verify。Redis 可丢弃重建，不能成为恢复所需的唯一数据源。
- 当前 2C4G 的容器预算、JVM 参数、备份演练和迁移步骤不在 README 固化，详见 [`docs/handbook/14-deployment-security-ops.md`](docs/handbook/14-deployment-security-ops.md) 与 [`docs/status/current/`](docs/status/current/)。

---

## 本地运行

| 目标 | 推荐方式 | 需要什么 |
|---|---|---|
| 直接体验产品 | 打开 [Live Demo](https://aihotradar.online) | 无需本地环境 |
| 核验代码、迁移与测试 | 本地 Docker Compose + 各服务测试命令 | Docker、JDK 21、Python 3.12、Node.js |
| 完整运行采集、结构化和 RAG | 在本地 `.env` 配置自己的 provider key | DeepSeek 生成 key、SiliconFlow embedding/reranker key；禁止提交 `.env` |

仓库统一使用 Docker Compose，不要求本机直接安装 PostgreSQL 或 Redis：

```bash
cp .env.example .env
docker compose -f infra/compose/docker-compose.yml up -d --build
docker compose -f infra/compose/docker-compose.yml ps
```

默认入口与完整环境变量、Windows/PowerShell 命令、数据初始化和故障排查见 [`DEVELOPMENT.md`](DEVELOPMENT.md)。仅查看代码和运行离线测试不需要生产密钥；没有 provider key 时，外部模型调用相关能力会按配置关闭或失败，不应伪装为完整生产效果。

---

## 验证

Python / FastAPI：

```bash
cd apps/ai-service
python -m pytest -q
python -m mypy src
python -m ruff check .
```

Web / Next.js：

```bash
cd apps/web
npm run typecheck
npm run lint
npm test
npm run build
```

Java / Spring Boot：

```bash
cd apps/core-api
mvn -B verify
```

完整 CI 还覆盖 OpenAPI/共享契约生成差异、Flyway 空库与升级路径、依赖审计、秘密扫描、Docker Compose smoke、文档链接，以及改动影响到 RAG 时的固定黄金集发布门禁。测试通过说明对应门禁已满足，不代表第三方信源、模型或 SMTP 永久可用。

---

## 已知边界

- 自动引用覆盖率和支持度用于诊断，不能替代高风险数字、主体关系与结论的人审。
- 主题地图已按核心、相关和提及分层，但当前关系候选没有双盲人工标注，因此不发布“人工 precision / recall”。
- 极少数强时效、低词面重合问题仍可能安全拒答；系统不以扩大在线生成或猜测来强行覆盖。
- 信源后台当前是数据库健康快照，不是实时告警控制台；管理写 API 已有 RBAC、幂等和审计，但没有完整浏览器管理 UI。
- `outbox_event` 目前用于记录待处理事件，周期任务仍以数据库轮询编排；尚未把预留表包装成已完成的消息总线。
- 当前 Gmail SMTP 适合上线验证，不适合长期产品投递；正式规模化需要自有域名发信、SPF / DKIM / DMARC、退信和投诉处理。
- 在进入私有知识库或多租户前，不提前引入账号、ACL 和租户隔离；当前公开情报产品不声称具备企业级多租户能力。
- 实时状态以 [`docs/status/current/`](docs/status/current/) 为准；README 中的版本和指标只代表注明日期的历史证据。

---

## 文档导航

### 必读（5–15 分钟）

| 想了解什么 | 从这里开始 |
|---|---|
| 项目业务主线与阅读入口 | [`docs/handbook/README.md`](docs/handbook/README.md) |
| 模块、入口类、表与调用关系 | [`docs/code-map.md`](docs/code-map.md) |
| 当前生产、评测与交接事实 | [`docs/status/current/`](docs/status/current/) |
| 本地开发与验证 | [`DEVELOPMENT.md`](DEVELOPMENT.md) |

### 深入（按兴趣）

| 想了解什么 | 从这里开始 |
|---|---|
| 采集、正文门禁与数据模型 | [`docs/spec/09-source-registry-fulltext.md`](docs/spec/09-source-registry-fulltext.md)、[`docs/handbook/05-source-ingestion.md`](docs/handbook/05-source-ingestion.md) |
| 不同信源怎样入库并切成原文证据 | [`docs/handbook/20-ingestion-evidence-and-chunking.md`](docs/handbook/20-ingestion-evidence-and-chunking.md) |
| RAG 检索、生成、引用与评测 | [`docs/spec/04-rag-agent-design.md`](docs/spec/04-rag-agent-design.md)、[`docs/handbook/08-rag-indexing-and-retrieval.md`](docs/handbook/08-rag-indexing-and-retrieval.md)、[`docs/handbook/09-rag-generation-and-citations.md`](docs/handbook/09-rag-generation-and-citations.md)、[`docs/handbook/10-rag-evaluation.md`](docs/handbook/10-rag-evaluation.md) |
| Redis 的 key、TTL、失效与数据库兜底 | [`docs/handbook/21-redis-cache-and-short-lived-state.md`](docs/handbook/21-redis-cache-and-short-lived-state.md) |
| 90 题黄金集与 RAG 质量页 | [`docs/handbook/22-rag-golden-set-and-quality-page.md`](docs/handbook/22-rag-golden-set-and-quality-page.md) |
| 系统边界与为什么这样选型 | [`docs/spec/02-system-architecture.md`](docs/spec/02-system-architecture.md)、[`docs/adr/`](docs/adr/) |
| 报告、订阅和邮件投递 | [`docs/handbook/07-reports-and-email.md`](docs/handbook/07-reports-and-email.md) |
| 部署、安全、备份与恢复 | [`docs/handbook/14-deployment-security-ops.md`](docs/handbook/14-deployment-security-ops.md) |
| 压测方法与历史结果 | [`docs/status/loadtest/`](docs/status/loadtest/)、[`docs/handbook/18-performance-capacity-and-load-testing.md`](docs/handbook/18-performance-capacity-and-load-testing.md) |
| 逐轮 RAG 评测证据 | [`docs/status/eval/`](docs/status/eval/) |

### 面试专用

| 想了解什么 | 从这里开始 |
|---|---|
| 30 秒、2 分钟、5 分钟项目介绍 | [`docs/interview/00-project-one-pager.md`](docs/interview/00-project-one-pager.md) |
| 业务与架构完整讲解 | [`docs/interview/01-business-and-architecture.md`](docs/interview/01-business-and-architecture.md) |
| RAG 深挖与负实验 | [`docs/interview/03-rag-deep-dive.md`](docs/interview/03-rag-deep-dive.md) |
| Java / Python / 数据一致性 | [`docs/interview/04-backend-and-consistency.md`](docs/interview/04-backend-and-consistency.md) |
| 高频追问、反问与边界回答 | [`docs/interview/07-interview-question-bank.md`](docs/interview/07-interview-question-bank.md) |
| 简历表述与 STAR 工程案例 | [`docs/interview/08-resume-and-star-stories.md`](docs/interview/08-resume-and-star-stories.md) |
| 白板系统设计与现场演示 | [`docs/interview/09-system-design-whiteboard.md`](docs/interview/09-system-design-whiteboard.md)、[`docs/interview/10-demo-script.md`](docs/interview/10-demo-script.md) |

> 在简历、技术评审或对外材料中引用任何指标时，必须同时写明日期、样本量、模型/版本与测量环境；历史快照不是实时承诺。
