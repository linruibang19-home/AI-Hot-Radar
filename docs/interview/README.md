# AI Hot Radar 面试准备导航

本目录不是第二套规格。规格仍以 [`../spec/00-master-spec.md`](../spec/00-master-spec.md)
为准；这里把已经实现且有证据的内容重排成适合复习、讲解和追问的顺序。

## 推荐学习顺序

1. [`01-system-map.md`](01-system-map.md)：先把业务、服务边界和数据流画在一张图上。
2. [`02-data-and-rag.md`](02-data-and-rag.md)：掌握采集、结构化、混合检索、生成与评测。
3. [`03-production-operations.md`](03-production-operations.md)：理解部署、安全、邮件、备份与迁移。
4. [`04-interview-question-bank.md`](04-interview-question-bank.md)：按产品、后端、RAG、数据库、前端和运维练追问。
5. [`05-resume-and-demo.md`](05-resume-and-demo.md)：把项目压缩成简历 bullet、30 秒介绍和 5 分钟演示。
6. [`../interview-guide.md`](../interview-guide.md)：复习最有区分度的真实案例与反例。

## 三条讲解纪律

- **动态数据和发布快照分开讲。** 首页、运行状态、信源后台读实时数据库；`/eval`
  展示固定语料与固定模型上的发布评测，只有重新跑评测并生成快照才会改变。
- **事实和判断分开讲。** “做了 HNSW”是事实；“规模足够所以没上 Milvus”是有边界的判断。
- **不要把预留表说成已经工作的链路。** 例如 `outbox_event` 当前只写不读，就应当明确说
  一致性仍由轮询保证。

## 一页证据索引

| 要证明什么 | 可展示的证据 |
|---|---|
| 产品能使用 | 线上站点、[`../../README.md`](../../README.md) 截图 |
| 内容持续更新 | `/`、`/ops`、`/admin/sources` 的读取时间与最近成功时间 |
| RAG 有质量门 | `/eval`、`../status/eval/`、90 题黄金集 |
| 引用可追溯 | `/ask/{id}` 的句级编号、来源卡与检索轨迹 |
| 生产可恢复 | `../status/production/`、备份清单、隔离恢复记录 |
| 取舍有依据 | `../adr/` 与保留的负实验轮次 |

所有面试数字都应说明**数据截止时间、样本量和测量环境**。页面上实时变化的计数，
答辩前重新查看，不要背 README 中的历史快照。
