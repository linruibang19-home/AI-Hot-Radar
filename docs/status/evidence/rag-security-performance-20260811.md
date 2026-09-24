# RAG 上线前安全与性能稳定性验收（2026-08-11）

对应 `TASK-M4-003` 与 ADR-0024。结论：本地/预生产代码范围内的提示注入基线、凭据
输出保护、供应商快速失败、分阶段 SLO 和全库质量门禁已完成；必须依赖服务器与新密钥的
轮换、真实告警、TLS 和恢复演练仍未执行。

## 1. 安全边界

- 用户问题和每段原始网页证据分别放入显式数据块；证据按 JSON 编码，尖括号转义，网页中
  伪造的闭合标签不能逃出 `UNTRUSTED_EVIDENCE`。
- 系统指令明确：证据中的忽略规则、系统提示词索取、格式变更和权限请求均为网页数据，
  不能执行。没有按关键词删除文章，安全新闻仍可检索。
- 最终答案经过引用绑定、支持度、逐句门禁和不变量后，再扫描私钥头、Authorization
  Bearer、OpenAI 风格 key、GitHub token 与 AWS access key。命中时正文、引用、模型限定
  条件和 considered 标题均不发布、不缓存，只记录凭据类别，不记录匹配值。
- 真实绕缓存问答“使用 MXFP4 量化的是哪个模型？”成功返回：未拒答、3 条引用、
  `credential_output_blocked=false`，证明新边界没有破坏正常 RAG。

这仍是上线基线，不是完整 DLP。企业多租户文档 ACL、PII 分类和外部 Guardrail 需要明确
产品范围与供应商后再做。

## 2. 供应商失败边界

- embedding：默认 60 秒 / 3 次，可用环境变量在 1–120 秒、1–5 次内覆盖；非法值启动
  配置失败，不静默截断。
- rerank：从 60 秒 / 3 次收紧为 **20 秒 / 2 次**，可在 1–60 秒、1–3 次内覆盖；失败
  继续使用既有 fused-order 降级并写入 metrics。
- 没有第二供应商的真实凭据、价格与回归，因此没有伪造“自动备用模型切换”。

08-11 全量检索记录 89 次重排共 522081 ms，平均约 5.9 秒；20 秒单次边界保留充足长尾，
同时把最坏等待从约 180 秒收敛到约 42 秒（两次 20 秒与一次退避）。

## 3. 当前真实 SLO

数据来自当前 PostgreSQL 中近 30 天 210 次真实问答，不是离线样本：

| 阶段 | 样本 | p50 | p95 | p99 | p95 SLO | 状态 |
|---|---:|---:|---:|---:|---:|---|
| 总链路 | 210 | 10843 ms | 15634 ms | 34833 ms | 30000 ms | 达标 |
| generate | 202 | 5931 ms | 9510 ms | 28786 ms | 15000 ms | 达标 |
| rerank | 202 | 2740 ms | 3784 ms | 5553 ms | 10000 ms | 达标 |
| support | 87 | 1744 ms | 3671 ms | 4817 ms | 10000 ms | 达标 |
| embed | 202 | 1727 ms | 2067 ms | 2506 ms | 5000 ms | 达标 |
| temporal | 5 | 3 ms | 7 ms | 8 ms | 10000 ms | **样本不足** |

`/ops` 现同时展示 p50/p95/p99、每阶段阈值和
`ok / breached / insufficient_data`。默认至少 20 个样本才可能显示达标，避免 1 次快请求
被误报为健康。真实告警接收器需等服务器环境配置。

## 4. 验收证据

- Python：Ruff 全部通过；mypy **86 个源码文件通过**；pytest **863/863**。
- Web：TypeScript、ESLint、Vitest **54/54**、Next.js 15.5.23 production build 通过。
- Compose：AI Service 和 Web 用当前工作树重建；PostgreSQL、Redis、AI Service、Web
  健康；`/health/live`、`/health/ready`、`/rag/stats`、`/ops`、`/ask`、`/reports` 全部 200。
- 测试覆盖层修正为绑定整个仓库深度，避免 `test_prod_compose.py` 因 `/app` 路径变浅而
  漏跑；Web 测试阶段使用锁文件依赖的 Docker volume，不依赖宿主机 Node。

## 5. 仍需服务器权限的 P0

1. 轮换 GitHub、LLM、embedding/rerank、PostgreSQL 等全部实际密钥并设置供应商消费上限；
2. 配置 DNS/TLS、真实告警接收器与值班路径；
3. 对一份真实 `pg_dump` 执行恢复演练并记录 RPO/RTO；
4. 若未来引入账户或私有语料，再实现租户隔离与文档级 ACL。
