# ADR-0038：RAG 发布门禁由 CI 执行，页面与 CI 共用一份门槛

- 状态：已接受
- 日期：2026-09-24
- 相关：ADR-0023、ADR-0037；`scripts/build_eval_summary.py`

## 背景

`/eval` 从 `apps/web/src/data/eval-summary.json` 算出「可发布 / 未达到发布门槛」，门槛是页面里的字面量。
CI 与部署脚本都不看它：快照不达标照样能发版（只是页面标红），手改一个数字也会显示为达标。
「以门禁约束上线」因此只是展示，不是约束。

## 决策

1. 门槛抽到 `apps/web/src/data/release-gate.json`：Recall@20 ≥ 0.85、事实句引用完整性 ≥ 0.95、
   段落支持 ≥ 0.90、诱导题错误断言 ≤ 0、可答题误拒 ≤ 5%、无流水线原因的拒答、中文专项召回通过。
   页面读它，CI 读它，两边不可能不一致。
2. `scripts/check_release_gate.py` 在 CI 的 Spec validation 任务里运行，两步：
   - **推导而非手写**：用 `build_eval_summary.build()` 从 `data/eval-runs/` 重建汇总，必须与提交的文件一致；
   - **达标**：发布快照逐项对照门槛，任一不过即失败。
3. `release.yml` 复用 `ci.yml`，所以门禁不过就不会构建发布镜像。

## 边界

CI 不重跑评测：一次生成评测要调用付费模型、约 40 分钟。评测在发版前手动运行
（`ahr rag-eval`），产物提交进 `data/eval-runs/`；CI 检查的是提交的快照。
因此「改了代码却没重跑评测」CI 拦不住——这仍靠发布流程（改模型、Prompt、切块或检索策略后必须重跑）。

## 验证

- 当前快照（GEN-20260924T075902Z / B9-20260924T080154Z / SPECIALIST-20260924T080157Z）通过全部 7 项；
- 手改汇总中的一个数字 → 「eval-summary.json is not what data/eval-runs produces」，退出码 1；
- 构造 Recall@20 0.80 且出现流水线拒答的快照 → 两项 FAIL，退出码 1。
