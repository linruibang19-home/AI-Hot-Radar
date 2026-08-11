# RAG 质量与运行页面收口（2026-08-11）

对应 `TASK-M5-008`。本卡只改变工程信息的解释层与价目展示口径，不修改检索、生成、
黄金集、SLO 或数据库事实。

## 1. 结果

- `/eval` 更名为「RAG 质量」，首屏直接给出当前发布判定、门槛、run ID 与剩余风险；
  十轮检索演进、负结果、逐轮明细、RAGAS 映射和生成实验完整保留。
- `scripts/build_eval_summary.py` 增加 08-11 最终发布轮，页面不再把 B13 / GEN-FIX
  历史实验快照冒充当前结果。
- 当前发布卡展示：主集 Recall@20 0.8994、引用完整性 0.9881、段落支持达标率
  0.9344、可答题误拒 0/78、诱导题错误断言 0/12；15 题专项加入真实近邻噪声后
  Recall@20 保持 0.9333。
- `/ops` 更名为「运行状态」，首屏给出 p95 SLO、外部 API 延迟占比、最大成本操作、
  价目快照覆盖与建议动作。
- V024 之后的调用逐行标为「调用时快照」；旧记录逐行标为「历史 fallback」。金额明确是
  价目估算而非供应商账单，token 与延迟仍来自真实调用记录。
- 侧栏只改工程项名称，不改变路由、整体布局、颜色或页面信息密度语言。

## 2. 数据边界

- 自动 citation precision 依赖稀疏黄金标注，只作诊断；发布判定使用段落支持门和人工
  P0 审计，不能互相替代。
- 噪声 A/B 是 15 题专项小样本，不冒充完整 90 题噪声回归。
- 本地当前 3403 次历史调用均早于 V024，没有价目快照，因此金额仍使用 legacy fallback；
  新调用才会开始积累可追溯的模型价目快照。
- 切换 DeepSeek 生成模型后必须重跑生成回归。SiliconFlow embedding/reranker 本卡不动。

## 3. 验收证据

```text
python scripts/build_eval_summary.py
  PASS：10 retrieval rounds, 3 extra runs，并写入最终发布快照

apps/web: npm run typecheck
  PASS
apps/web: npm run lint
  PASS
apps/web: npm test
  PASS：8 files / 71 tests
apps/web: npm run build
  PASS：/eval static、/ops dynamic production build

docker compose -f infra/compose/docker-compose.yml build web
  PASS
docker compose -f infra/compose/docker-compose.yml up -d --no-deps web
  PASS：web healthy

HTTP smoke
  GET http://localhost:3000/eval  -> 200，含 CURRENT RELEASE GATE、0.9881 与最终 run ID
  GET http://localhost:3000/ops   -> 200，含历史 fallback 与模型配置入口
  GET http://localhost:8000/rag/stats?days=30 -> 200
```

## 4. 视觉验收阻塞

按用户要求再次连接 Chrome 检查实际页面，但 Chrome 插件在建立浏览器连接前失败：

```text
failed to write kernel assets: 系统找不到指定的路径。 (os error 3)
```

因此本卡没有把 Chrome 截图或交互验收写成已通过。服务端渲染、生产构建、Docker 健康和
HTTP 内容已通过；浏览器视觉回归仍需在插件资产路径恢复后补验。

## 5. 下一张任务卡

继续 `TASK-M5-005` 的全量预发布门禁与文档快照，随后才进入 `TASK-M5-006` 首次生产部署。
