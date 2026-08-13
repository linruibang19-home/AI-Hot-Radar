# 07｜面试问题库
回答结构统一为：**一句结论 → 本项目证据 → 为什么这样取舍 → 失效边界**。不要背成宣传稿。

## 业务与产品

### 1. 这和新闻聚合站有什么区别？

聚合只解决入口；本项目还做全文质量门、幂等版本、跨源 Story、发布快照、周期投递和原文证据 RAG。
同一事实层驱动所有出口，工程页公开失败实验和运行状态。

### 2. 核心用户链路是什么？

精选发现 → Story/主题理解 → 报告压缩 → RAG 追问并回原文核验 → 按周期邮件接收已发布报告。

### 3. 如何衡量产品而不只衡量模型？

内容看新鲜度、全文率、重复压缩、跨源 Story 和精选点击；RAG 看答案成功、引用点击、追问、误拒和
反馈；订阅看确认、送达、退订与投诉。Recall 和支持度只是质量门的一层。

### 4. 日报、周报、月报是不是每次打开现生成？

不是。批处理生成结构化报告并过引用/确定性门后保存为 PUBLISHED；页面和邮件都读取同一快照。

## 采集与数据

### 5. 为什么 RSS 摘要不能直接进 RAG？

RSS 常是截断的发现元数据，无法证明上下文与精确主张。系统回 canonical 正文，通过全文门后才切块引用。

### 6. 怎么保证重复采集不污染数据？

external id、规范 URL、内容 hash、唯一键和事务 upsert；处理结果再绑定 revision/input/pipeline version 做 CAS。

### 7. 文章去重和事件聚类有什么区别？

去重判断是否同一份内容或转载；Story 判断独立内容是否描述同一事件。前者压缩副本，后者保留多源证据。

### 8. 信源后台是实时的吗？

状态由每次 Scheduler 运行写 PostgreSQL，页面刷新读最新快照；它不是 websocket 监控，实时告警由 monitor 负责。

## 后端、数据库与一致性

### 9. 为什么 Java Core API 和 Python AI Service 分开？

Java 承担稳定事务、权限、订阅和 API；Python 承担采集、NLP、向量、重排和评测生态。代价是跨服务契约和接缝测试。

### 10. 为什么 PostgreSQL + pgvector，不上专用向量库？

当前八千级分块且检索强依赖状态、时间、实体和来源 join；同库保持事务过滤一致、运维更小。容量或并发压测越界再迁。

### 11. 为什么 Redis 不能是事实源？

Redis 被清空时，内容、报告、订阅和投递必须仍然正确；它只承载可重建缓存、限流和短锁。

### 12. 为什么没有 Kafka/RabbitMQ？

当前没有高 backlog、独立消费者扩缩或重放硬需求。`outbox_event` 只写不读，任务靠数据库轮询和幂等；不把预留说成完成。

### 13. 如何保证邮件不重复？

双确认建立 ACTIVE 订阅，调度只取 PUBLISHED；`subscription + report` 唯一事实、行锁和 delivery key 防重复，失败有限重试。

### 14. 数据库迁移失败怎么回滚？

Flyway 变更优先向前兼容；失败回应用 SHA，必要时从验证备份恢复。不可逆 DDL 不与普通代码一起冒险回滚。

## RAG

### 15. Dense、Sparse、Temporal 分别解决什么？

Dense 找语义改写，Sparse 保型号/版本精确词，Temporal/entity 在 SQL 层约束时间与主体。真实题正确证据 dense 14、sparse 1、融合 3。

### 16. 为什么用 RRF？

各通道分数不同量纲；RRF 只融合名次，再让统一 reranker 比 query-passage，减少手工分数标定脆弱性。

### 17. 为什么不是检索 top N 直接给模型？

top N 会被同篇/同事件占满。选证要覆盖子问题、来源多样性、一手来源和 token 预算，还要记录淘汰原因。

### 18. Parent/Child 如何避免引用过宽？

父块只补语境，最终 citation 仍绑定命中的最小原始 chunk；支持度按 claim-passage 检查。

### 19. 如何防模型伪造引用？

模型只输出临时证据编号；服务端从当前证据集绑定数据库 chunk 和 URL，越界剥离，弱支持/无引用事实删除，不变量失败就拒答。

### 20. `/eval` 为什么不随线上提问更新？

它是固定黄金集、语料 cutoff 和模型上的可复现发布实验。实时请求延迟/错误在 `/ops`；混在一起无法定位变化来源。

### 21. 为什么同时看拒答和误拒？

全拒答系统的“不可答拒答率”可以很高但没价值。必须同时保证 12 道诱导题不编造和 78 道可答题不误拒。

### 22. 最大的 RAG bug 是什么？

模型答案正确但未按 JSON/claims 契约，解析失败分支把答案清空，误拒到 7.69%。抓原始响应、做带守卫回退后回到 0%，并证伪了原先“语料竞争”假设。

### 23. 你保留了哪些负实验？

B2 并集退化；B8 权重扫描无实益；B13 中文分词对 RAG 零提升但站内搜索 10–32 倍。负结果决定组件边界。

### 24. 为什么自动 citation precision 不能代替人审？

稀疏标注会把未标但正确证据算错，交叉编码器也不擅长否定结论。发布门用自动诊断 + 高风险数字人工 P0 审计。

### 24A. 你真的完成了主题地图人工审核吗？

没有。工程上完成了真实快照分层抽样、revision/hash 绑定、盲审数据隔离、裁决结构、校验和加权
评估工具，但个人作品没有两位独立审核者和第三位裁决者，所以 1,995 条候选仍是待审核状态。
我宁可明确没有人工 precision/recall，也不把规则命中量包装成质量指标。

### 24B. 如果团队允许人审，你会怎样组织？

按关系层分层抽样，隐藏生产预测，双人独立标注，分歧由第三人裁决；样本固定 revision/hash，
最终按分层总体规模加权并报告 bootstrap 95% 置信区间。指标只用于冻结后的目标和独立保留集，
不能边看结果边改门槛。

### 24C. 你怎么证明 RAG 切的是原文而不是 AI 摘要？

迁移把 revision body、summary 和 chunk 分列；`chunk_revision` 只接 current revision body；
embedding backfill 读 chunk body，上下文前缀只用于向量输入；在线检索只 join current revision。
生产还检查非空正文覆盖、chunk/embedding 数、字符定位、摘要相等数和超限块，而不是只看一张架构图。

### 24D. 为什么仍然出现过 4,904-token chunk？

旧切分器能拆多行长表格，却把“没有换行的一整篇抽取正文”当一行保留。本轮生产审计发现当前
14 个超限块后，补了单行预算切分和回归测试，再用 `rechunk --oversized-only` 只重建受影响 revision，
随后只补这些新块的 embedding。这个案例展示了数据门禁比静态代码审查更重要。

### 24E. 已经被答案引用的 chunk 需要重切，怎么处理？

不能删除或原地改写。`rag_citation` 绑定的是回答当时看到的物理 passage；删除会破坏审计，原地
改写会让旧答案悄悄指向新证据。系统用 `chunk_set_id + is_active`：旧 set 退役但保留，新规则插入
新的 active set；在线检索和 embedding 只看 active，历史答案仍按主键读旧块，父块只能在同 set
扩展。这个约束由生产外键故障真实暴露，失败事务完整回滚。

### 24F. 为什么不复制一个 content revision 来承载新切块？

revision 表达“来源正文发生了变化”，chunk set 表达“同一正文被哪版处理规则切分”。正文没变却
复制 revision 会混淆来源历史和算法历史，也让 canonical hash 的含义失真。两个生命周期拆开后，
既能回答来源何时变化，也能回答哪版切块生成了当前索引。

### 24G. 没有执行真实人工审核，作品集还能怎么讲？

如实分三层：已经运行的是确定性关系规则、公共置信门和 90 题 RAG 自动回归；已经实现但未执行
的是分层抽样、隐藏预测、revision/hash 固定、双人标签结构、第三人裁决、严格校验和加权评估；
没有的结果就是人工 precision/recall。面试亮点是 fail-closed 和证据边界，不是假装多了两位审核员。

## 前端

### 25. 为什么使用 Next.js SSR？

内容和报告需要首屏 HTML、SEO、分享 URL；Next 服务端还隐藏内部 API 与 VIEWER 凭据。

### 26. 页面点击卡顿怎么排查？

分浏览器导航、Next route/data、Core/AI、DB/cache 和外部模型计时；内容路由预取与缓存，RAG 展示计划/阶段，不用 loading 动画掩盖根因。

### 27. 为什么管理写 UI 没有直接做？

写 API 已有 OPERATOR、二次确认和审计，但浏览器保存高权限 token 会扩大 XSS 面；先设计短会话/BFF/重新认证再实现。

## 安全、部署与运维

### 28. 生产怎样发布和回滚？

PR/CI → main → release 全量门 → GHCR SHA 镜像 → 服务器 preflight/deploy/smoke；失败回上一 IMAGE_TAG，数据库用兼容迁移或验证备份。

### 29. 2C4G 的瓶颈是什么？

模型外置后，优先关注内存、PostgreSQL/向量增长、镜像/日志/备份空间和外部 API P95，而非本地推理 CPU。

### 30. 如何迁移服务器且保持域名？

新机部署同 SHA、恢复校验数据、临时地址 smoke；大陆备案完成后改 A 记录，旧机保留 48–72 小时回退。域名与网站名不依赖机器。

### 31. 如果流量扩大 100 倍，先做什么？

先以 trace/RED/DB/队列/外部模型指标定位瓶颈，压测读缓存、连接池、向量召回与 Worker backlog；再按证据扩盘、扩 Worker、读优化、队列/搜索，不先画 Kubernetes。

### 32. 如果 Redis 全丢会怎样？

命中率下降、请求变慢、限流窗口重置，但已发布内容、报告、订阅、投递和 RAG 历史仍在 PostgreSQL，不应丢业务事实。

## 压力追问题库（33–120）

下面每题先用“一句结论”回答，再沿证据入口展开。`边界` 是主动承认何时当前结论会失效。

### 产品、业务与指标

| # | 问题 | 回答主线 | 证据与边界 |
|---:|---|---|---|
| 33 | 谁是第一目标用户？ | 需要低成本跟踪 AI 行业的开发者/求职者/研究者，而非企业私有知识库 | 公开语料、匿名阅读；私有语料需账号/ACL |
| 34 | 为什么要 Story？ | 把同一事件多篇文章组织为一个判断单元，又保留独立来源 | `story/story_item`；聚类纯度需持续抽检 |
| 35 | 精选和热榜有何不同？ | 精选重质量/多样性，热榜重窗口热度/衰减 | selection/heat 代码；都不是事实正确性 |
| 36 | 报告为什么需要状态机？ | 生成是候选，发布是业务承诺 | report publication + audit；不是多人工作流系统 |
| 37 | 用户为什么相信摘要？ | 不要求盲信，保留主来源、补充来源和原文跳转 | item/story/report DTO；摘要仍可能需纠错 |
| 38 | 如何衡量信源价值？ | 时效、全文率、一手性、独立增量、失败成本 | source health/crawl；不能只看内容数 |
| 39 | 如何衡量邮件价值？ | 确认率、送达、打开/点击、退订、投诉 | 当前先有 delivery 事实；用户行为分析未完整建设 |
| 40 | 为什么不做逐条推送？ | 高频噪声和成本高，当前承诺周期性已发布报告 | subscription period；未来需用户偏好/频控 |
| 41 | 内容数量越多越好吗？ | 否，重复、低质和单源集中会恶化检索与阅读 | fulltext/selection/RAG eval；数量只是快照 |
| 42 | 你的护城河是什么？ | 数据治理、可追溯证据、评测和运行闭环，不是模型 API | 代码/ADR/eval；个人项目没有商业网络效应 |

### 采集、正文与数据质量

| # | 问题 | 回答主线 | 证据与边界 |
|---:|---|---|---|
| 43 | 140 个源是否都实时正常？ | 140 是登记配置，ACTIVE/PROBING/隔离是动态运行状态 | `/admin/sources`；必须带时间 |
| 44 | 如何新增一个信源？ | 注册 profile/源，准备 fixture，probe，全文门通过后 ACTIVE | spec09/10；不能仅加 URL |
| 45 | 为什么保存 raw response？ | 解析回归、审计、重新处理，不依赖第三方页面仍存在 | raw_document；受版权/保留期约束 |
| 46 | ETag 有什么价值？ | 304 降带宽且避免重复解析 | cursor/HTTP tests；站点不支持则 hash/cursor |
| 47 | canonical 错了会怎样？ | 错合并或重复，需要站点规则、页面声明和最终 URL 共同判断 | URL tests；业务 query 不可随意删 |
| 48 | 如何防 SSRF？ | scheme/host/DNS/IP/每跳重定向检查，限制大小和超时 | ingestion HTTP；DNS rebinding 仍需谨慎 |
| 49 | 为什么不默认 Playwright？ | 资源重、失败面大、可能触碰访问政策 | 当前无生产 browser 容器；allowlist 才评估 |
| 50 | PDF 怎么处理？ | 论文 HTML 优先，PDF 降级并保存页/段定位 | arXiv adapter；复杂表格/OCR 非当前范围 |
| 51 | 发布时间缺失怎么办？ | 保持空并记录 observed/fetched，UI 不伪造精确时间 | ADR/精选时间修复；会降低时间查询确定性 |
| 52 | Source 隔离如何恢复？ | 修 fixture/adapter 后 probe，满足阶梯再转状态 | source state audit；不手工掩盖失败 |
| 53 | 同一批重放如何不重复？ | external id/canonical/hash/唯一键/upsert | migrations/repository tests；第三方 ID 变化仍需近重 |
| 54 | Cursor 与内容怎么保证一致？ | batch 入库提交后才推进 cursor | ingestion transaction；不是跨源全局事务 |
| 55 | 页面变更如何发现？ | 解析失败率/全文门/fixture/canary | monitor + source backend；不是自动修 selector |
| 56 | 采集是否合法？ | 只读公开/授权入口，尊重限制，受限源元数据化 | policy/profile；不是法律意见替代 |

### 数据库、状态与一致性

| # | 问题 | 回答主线 | 证据与边界 |
|---:|---|---|---|
| 57 | item 和 revision 为什么分开？ | 稳定身份与变化正文分离，引用可追溯旧输入 | V001；revision 增长需保留策略 |
| 58 | `evidence_passage` 表在哪？ | 是领域术语，物理实现是 `content_chunk` | ADR-0029/Flyway；不能按旧文档找表 |
| 59 | embedding 为什么与 chunk 同行？ | 当前单模型减少 join/同步 | ADR-0029；多模型需拆表/双索引 |
| 60 | PostgreSQL 同时搜索会不会慢？ | 当前规模/SLO 可接受，先索引/查询优化 | explain/eval；量级增长触发拆分 |
| 61 | HNSW 为什么而非 IVFFlat？ | 当前在线召回和较小规模偏向免训练、高 recall | migration/config；需用实际压测验证参数 |
| 62 | advisory lock 崩溃会死锁吗？ | session 结束自动释放 | processing worker；长任务需监控连接 |
| 63 | `SKIP LOCKED` 会饿死任务吗？ | 排序/next attempt + 短领取降低风险 | SQL；持续失败靠 backoff/dead state |
| 64 | CAS 如何防旧结果？ | 输出绑定 input hash/revision/version，提交时比较 | processing tests；外部副作用另处理 |
| 65 | Outbox 为什么存在却没消费？ | 早期预留和事件审计，当前轮询更简单 | ADR-0028；需要有界清理 |
| 66 | `processed_event` 有何用？ | 未来消费者幂等预留，不证明消费已实现 | Flyway/无 reader；不要包装 |
| 67 | 数据删除如何传播？ | tombstone/status、公共查询过滤、向量/缓存清理 | spec；完整权利人流程仍需产品化 |
| 68 | 如何迁移大表？ | expand/dual read-write/backfill/contract | Flyway 规则；当前尚未经历超大表在线迁移 |
| 69 | 数据库挂了会怎样？ | read/processing ready 失败，Caddy/Web 可给受控错误 | health/runbook；单机无自动 DB HA |
| 70 | 连接池怎么定？ | 所有容器池总和小于 DB 上限并留迁移/运维余量 | Compose/config；按真实并发调 |

### RAG 检索、生成与评测

| # | 问题 | 回答主线 | 证据与边界 |
|---:|---|---|---|
| 71 | 为什么 embedding 固定？ | 不同向量空间不可混查，切换需全量回填与回归 | ADR-0027；生成模型可独立切 |
| 72 | Dense 漏型号怎么办？ | sparse/CJK/identifier 通道补精确词，再统一重排 | NVFP4 示例；不能保证所有新词 |
| 73 | Sparse 中文为什么难？ | simple tokenizer 缺中文词边界，用 CJK bigram 改通道 | ADR-0018；不是通用分词器 |
| 74 | 时间过滤放哪？ | 计划解析为绝对范围，SQL 前置过滤，重排再用 freshness | temporal trace；元数据缺失会影响 |
| 75 | RRF 常数 60 怎么定？ | 稳定常用基线，重点由端到端评测验证而非神化常数 | fusion/eval；规模变化可重评 |
| 76 | Reranker 挂了怎么办？ | 降级到融合排序并标 trace，不返回部分 provider 垃圾 | timeout/degrade tests；质量会下降 |
| 77 | 为什么不把 top100 都给模型？ | token/延迟、冗余和噪声，选证需多样性 | context budget；太少也会漏召回 |
| 78 | 如何处理比较题？ | planner 拆对象，证据预算平衡，避免一方占满 | query types/eval；实体解析要准确 |
| 79 | 如何处理“最近”？ | asked_at + timezone → 绝对时间窗 | temporal tests；用户未给时区用产品默认 |
| 80 | 多轮会不会传播幻觉？ | 改写只读用户问题，不读旧答案作事实 | conversation tests；错误实体仍可能需澄清 |
| 81 | 模型直接写 URL 怎么办？ | 忽略，URL 从绑定 chunk 反查 | answer/citation tests |
| 82 | 支持度阈值如何定？ | 黄金集/人工抽检校准，按高风险关系加审计 | ADR-0021/23；不是绝对真值 |
| 83 | 缓存怎样知道语料变了？ | corpus fingerprint + query type freshness 粒度 | ADR-0017/tests；指纹设计需随业务复核 |
| 84 | 为什么拒答不缓存？ | 新语料到来后可能可答，且拒答价值低 | cache tests；可做很短负缓存防攻击 |
| 85 | 黄金集会不会过拟合？ | 分类/专项/负样本/人工审计和新题保留集 | 90 题仍偏小，需持续扩展 |
| 86 | Recall 89.9% 是否够？ | 达当前门但仍有约 10% 相关项漏召回，需按风险看失败题 | `/eval`；不能称行业 SOTA |
| 87 | 引用覆盖 98.8% 等于正确吗？ | 否，只说明有引用；支持率/人工 entailment 另测 | ADR-0021 |
| 88 | 自动评测何时刷新？ | 模型/语料/策略变化后主动重跑并版本化 | eval docs；不是页面定时更新 |
| 89 | 在线反馈如何闭环？ | 应记录有用/无用、引用点击和失败类型进入标注队列 | 当前尚不完整，是后续 P2 |
| 90 | Prompt injection 怎么测？ | 原文不可信边界、恶意 fixture、禁止泄密/指令覆盖 | safety tests；持续增加攻击集 |

### Java、Python、前端与跨服务

| # | 问题 | 回答主线 | 证据与边界 |
|---:|---|---|---|
| 91 | 为什么 Java 用 JDBC 不用 JPA？ | PostgreSQL 特性、显式 SQL、DTO 查询更透明 | code；普通 CRUD 可局部 JPA |
| 92 | FastAPI 负责哪些 HTTP？ | RAG/health，不拥有订阅和管理事实 | routes/Compose |
| 93 | Python 三角色如何发布一致？ | 同 SHA 镜像不同 command | Compose；故障域仍独立容器 |
| 94 | 跨语言契约如何防漂移？ | OpenAPI/schema、类型、CI 与接缝测试 | contracts/tests；手写 SQL 仍需审查 |
| 95 | 为什么 Next 不直连数据库？ | 安全、边界、缓存、DTO 和演进 | architecture；避免浏览器凭据 |
| 96 | SSR 与 CSR 怎么选？ | 内容首屏/SEO SSR，交互和流式 Client | web code；重页面需测 hydration |
| 97 | 如何隐藏内部 token？ | server-only env/BFF，同源代理 | Compose/Web；浏览器不持 OPERATOR |
| 98 | SSE 断开怎么处理？ | 取消后台、未提交不缓存、持久化完整结果才可复用 | incremental/API tests |
| 99 | 前端怎样展示 stale？ | last-known-good/更新时间/错误状态分离 | UI；不是所有页都自动轮询 |
| 100 | 导航慢是前端问题吗？ | 分层计时，可能是 SSR/API/DB/外部模型 | navigation evidence；动画不算修复 |
| 101 | 邮件 HTML 如何防注入？ | 转义第三方标题、受控 Markdown、内联样式 | mailer tests |
| 102 | 时区在哪转换？ | DB/服务保存 IANA，查询/展示按边界转换 | subscription/temporal tests |

### 安全、部署、运维与扩展

| # | 问题 | 回答主线 | 证据与边界 |
|---:|---|---|---|
| 103 | main 合并会自动更新生产吗？ | 不会；需构建 SHA 镜像并显式部署/验收 | release workflow/runbook |
| 104 | 怎么证明服务器跑哪个版本？ | IMAGE_TAG/OCI revision + Compose，而非目录 HEAD | deployment evidence |
| 105 | 为什么只有 Caddy 暴露？ | 缩小攻击面、统一 TLS/代理 | prod Compose static tests |
| 106 | Bearer Token 足够安全吗？ | 单运营者最小实现，高熵/角色/审计；非多租户认证 | ADR-0019 |
| 107 | 密钥泄露怎么办？ | 立即撤销轮换、查日志/历史、更新服务器 secret、验证 | 运维流程；“忘记”不能撤销泄露 |
| 108 | 备份如何证明可用？ | checksum + 异机 + 隔离 restore + smoke | status evidence；每日 dump RPO 24h |
| 109 | 迁移新服务器会换网站名吗？ | 不会，域名/DNS 与主机解耦 | migration runbook |
| 110 | Ubuntu 24.04 兼容吗？ | 应用容器化，宿主只需受支持 Docker/Compose/内核 | preflight；仍要实际 smoke |
| 111 | 2C4G OOM 怎么办？ | 先看容器/DB/pool，限并发/内存/swap，再升级 | ops；不能承诺高并发 |
| 112 | 磁盘增长在哪里？ | DB正文/索引/备份、镜像/build cache、日志 | bounded logs/maintenance；不自动删卷 |
| 113 | 如何做零停机？ | 当前不承诺；可双机/兼容迁移/Caddy 切换 | 单机边界；业务允许短窗口 |
| 114 | 何时上消息队列？ | backlog/SLO/独立消费者/轮询成本证据 | ADR-0028 trigger |
| 115 | 何时上 Elasticsearch？ | FTS 质量/吞吐经优化仍不达标 | ADR-0015；不是简历装饰 |
| 116 | 何时上 Kubernetes？ | 多节点、故障域、滚动/扩缩和团队收益超过成本 | 当前不需要 |
| 117 | 如何支持百万文档？ | 分区/归档、异步索引、专用检索评测、对象存储、容量规划 | 这是设计演进，未实测百万 |
| 118 | 如何支持企业私有语料？ | 账号/租户/ACL 前置过滤、审计和独立索引/密钥 | 当前公开单租户，不可声称已支持 |
| 119 | 最大技术债是什么？ | 信源持续维护、自动支持度校准、Outbox 预留、单机恢复窗口 | roadmap；按风险排序 |
| 120 | 如果重做会先改什么？ | 更早建立实现事实/规格校验、原始模型响应观测和用户反馈标注 | 本轮 ADR/GEN-FIX 经验 |

## 反问练习

- 一手源与媒体冲突时，产品应如何展示，而不是让模型偷偷裁决？
- DeepSeek 输出契约变化，schema、解析、不变量、指标和告警哪一层最先发现？
- 独立向量库的迁移门槛怎样用数据定义？
- 私有语料进入后，权限过滤应该在召回前、重排前还是生成前？为什么必须前置？
