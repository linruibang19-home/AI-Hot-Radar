# 主题地图关系黄金集

关联任务：`TASK-M5-016`。这里评测的是主题地图和厂商导航，不是 RAG 检索；二者使用同一批
内容事实，但回答不同问题，不能共用一个分数。

## 1. 为什么必须人工标注

生产规则已经是确定性的：厂商关系由 `item_entity` 投影成 `primary / related / mention`，主题
由 `item_topic` 取置信度不低于 `0.60` 的前三个。但“规则每次结果一致”不等于“结果正确”。
若把当前标签直接当答案，分类器只是在给自己判卷，页面即使关联错了也会得到 100%。

因此生成器只冻结候选、原文摘录、当前判断和总体分层规模，所有 `gold_label` 初始为空。
只有人工对照原文完成标签后，评测器才输出指标；存在任意待审核样本时，`evaluate` 以退出码
`2` 结束，也不会发布部分准确率。

## 2. 分层抽样

每个分层最多取 20 条，样本不足时全取且记录真实 `population_size`，绝不重复凑数：

- 厂商：每个厂商分别抽 `primary / related / mention / unmatched`；
- 主题：每个叶子主题分别抽 `public / suppressed / unmatched`；
- `unmatched` 是召回分母，没有它只能算精度，不能发现“该关联却完全没关联”的漏召回；
- 空分层仍写进 `strata`，避免“没有样本”被误读成“漏了抽样任务”。

抽样运行于 PostgreSQL `REPEATABLE READ READ ONLY` 事务，排序键为固定 seed 与内容 ID 的
哈希；同一语料视图、相同参数会得到相同样本。样本同时绑定 `content_item_id`、
`current_revision_id` 与 `content_sha256`，正文换版后必须重审。

## 3. 标签定义

### 厂商

| `gold_label` | 人工判断 |
|---|---|
| `primary` | 该厂商/模型族是文章主要对象；移除它会改变文章主旨 |
| `related` | 是重要比较方、合作方、收购对象或必要上下文，但不是唯一主角 |
| `mention` | 原文确实提到，但只是举例、列表项或顺带一句 |
| `unrelated` | 误抽取、同名误判，或原文不支持该关系 |

公开厂商页展示 `primary + related`，所以二分类指标以这两档为正例；同时单列
`primary precision`，防止“什么都算相关”掩盖核心列表污染。

### 主题

| `gold_label` | 人工判断 |
|---|---|
| `relevant` | 该主题是理解文章主旨所必需的一个内容维度 |
| `unrelated` | 只是术语出现、过宽标签，或原文并不支持 |

主题不是关键词匹配。一篇谈“某公司融资”的文章可以同时是 `funding` 与 `enterprise`，但仅仅
列出 GPU 型号不必然属于 `chips`。

## 4. 标注动作

1. 在本地、已迁移到 V025 的 Compose 数据库上生成复核队列：

   ```bash
   docker compose -f infra/compose/docker-compose.yml exec ai-service \
     python -m ahr.cli topic-quality sample \
       --per-stratum 20 --seed topic-map-golden-v1 \
       --output /tmp/topic-map-annotations.yaml
   New-Item -ItemType Directory -Force data/topic-map-review
   docker cp ai-hot-radar-ai-service-1:/tmp/topic-map-annotations.yaml \
     data/topic-map-review/annotations.yaml
   ```

后续命令继续使用 Compose，并为复核目录增加可写挂载；主服务中的 `/app/data` 默认只读，不能
在容器内直接覆盖黄金集。PowerShell 示例先设置：

```powershell
$compose = "infra/compose/docker-compose.yml"
$sourceMount = "${PWD}/apps/ai-service/src:/app/src:ro"
$reviewMount = "${PWD}/data/topic-map-review:/review"
```

2. 为两位不同复核人生成顺序不同、且不含 `predicted_label`、置信度和规则原因的盲审包：

   ```powershell
   docker compose -f $compose run --rm --no-deps -e PYTHONPATH=/app/src `
     -v $sourceMount -v $reviewMount ai-service python -m ahr.cli topic-quality review-init `
     --golden /review/annotations.yaml --reviewer reviewer-a --output /review/reviewer-a.yaml
   docker compose -f $compose run --rm --no-deps -e PYTHONPATH=/app/src `
     -v $sourceMount -v $reviewMount ai-service python -m ahr.cli topic-quality review-init `
     --golden /review/annotations.yaml --reviewer reviewer-b --output /review/reviewer-b.yaml
   ```

3. 两位复核人独立打开原文 URL 并核对 `original_excerpt`；填写 `gold_label` 和带明确时区的
   ISO-8601 `reviewed_at`，不交流标签，不修改正文、URL、revision 或 hash。
4. 对比两份结果并生成只含分歧项的第三人裁决包：

   ```powershell
   docker compose -f $compose run --rm --no-deps -e PYTHONPATH=/app/src `
     -v $sourceMount -v $reviewMount ai-service python -m ahr.cli topic-quality review-compare `
     --golden /review/annotations.yaml --review-a /review/reviewer-a.yaml `
     --review-b /review/reviewer-b.yaml --output /review/adjudication.yaml
   ```

   独立裁决人只填写分歧项的 `gold_label`、`reviewer`、`reviewed_at`。不得由原两位复核人之一
   充当裁决人。对比报告同时给出厂商/主题各自的一致率与 Cohen's κ；类别失衡时不能只看表面
   一致率。
5. 合并完整标注，并另行输出不含第三方正文摘录和复核人身份的可归档标签：

   ```powershell
   docker compose -f $compose run --rm --no-deps -e PYTHONPATH=/app/src `
     -v $sourceMount -v $reviewMount ai-service python -m ahr.cli topic-quality labels-finalize `
     --golden /review/annotations.yaml --review-a /review/reviewer-a.yaml `
     --review-b /review/reviewer-b.yaml --adjudication /review/adjudication.yaml `
     --output /review/final.yaml --labels-output /review/final-labels.yaml
   ```

6. 校验结构、分层覆盖和当前数据库版本绑定：

   ```bash
   docker compose -f infra/compose/docker-compose.yml exec ai-service \
     python -m ahr.cli topic-quality validate \
       --golden /app/data/topic-map-review/final.yaml
   ```

7. 全部完成后计算按分层总体规模加权的估计值及确定性分层 bootstrap 95% 置信区间：

   ```bash
   docker compose -f infra/compose/docker-compose.yml exec ai-service \
     python -m ahr.cli topic-quality evaluate \
       --golden /app/data/topic-map-review/final.yaml \
       --output /tmp/topic-map-quality.json
   ```

`data/topic-map-review/annotations.yaml` 默认不提交：候选队列包含第三方原文摘录且可从数据库重建。完成后的
人工标签应另存为去除原文正文、保留内容 hash 和 URL 的审计产物后再进入版本库；这一步属于
`TASK-M5-016` 第二阶段。

## 5. 指标与门禁

工程门禁检查：结构合法、所有目标与分层均声明、样本量等于 `min(20, population_size)`、
关系无重复、revision 可追溯、两位不同复核人均完成、盲审字段未被改写、分歧已由独立第三人
裁决。任何一步不完整都不得发布指标。

全部人工标签完成后输出：

- `vendor_primary_precision`；
- `vendor_public.precision / recall`（primary + related）；
- `topic_public.precision / recall`。

数值目标不能在看见结果后倒推。本阶段没有人工基线，因此不虚构 0.85 或 0.90 的“绿色门槛”；
第二阶段先冻结第一轮结果和置信区间，再在任务卡中预注册 v2 的目标，改规则后只用同一集合回归。
