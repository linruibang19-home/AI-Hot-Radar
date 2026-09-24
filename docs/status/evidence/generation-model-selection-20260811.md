# DeepSeek 生成模型切换验收（2026-08-11）

## 结论

TASK-M5-007 已完成。PostgreSQL 是当前生成模型的事实源；页面可见
`deepseek-v4-flash` 与 `deepseek-v4-pro`，OPERATOR 可在不重启服务的情况下切换。
硅基流动 embedding/reranker、1024 维向量索引、分块和检索策略没有改动。

切换统一作用于之后创建的内容结构化、推荐理由、报告摘要和 RAG 生成客户端。历史内容、
历史回答和已有向量不会自动重算。DeepSeek API key 仍只存在于 AI Service 运行环境；模型页
输入的 OPERATOR 凭据仅用于单次同源请求，不进入 localStorage、数据库或响应。

## 关键实现

- ADR-0027 锁定 PostgreSQL 单例配置、模型白名单与检索模型边界。
- Flyway V024 建立模型目录/当前配置，并给 `llm_usage` 增加配置版本和调用时价目快照。
- Core API 增加受 VIEWER 保护的读取接口，以及带二次确认、持久化幂等、RBAC 和审计的切换接口。
- AI Service 在每次创建生成客户端时读取数据库；DeepSeek V4 显式关闭 thinking；报告摘要补齐
  之前缺失的 `llm_usage` 记录。
- Web 增加 `/admin/models`。页面说明模型作用范围、价目快照和固定的检索模型；切换不会暗中
  重算历史数据。
- OpenAPI 更新至 1.4.0。

## 自动化证据

- Python：Ruff 通过；mypy 86 个源码文件通过；pytest 878 passed、2 skipped。
- Java 21（Docker Maven）：74 tests，0 failure/error/skip。
- Web：typecheck、lint、71 tests、production build 全部通过。
- 规格：`python scripts/validate_spec.py` 通过。
- Flyway：现有 PostgreSQL 升级到 `024:true`，Core/AI/Web 健康。
- 本地真实管理闭环：Flash v1 → Pro v2 → Flash v3；`admin_audit` 产生 2 条 ALLOWED；
  AI Service 随后读取 `deepseek-v4-flash v3` 及 `1.0 / 0.02 / 2.0 CNY/M` 快照。
- 上述切换没有调用 DeepSeek 生成接口，没有产生模型 token 消耗。

## 未完成与边界

- Chrome 扩展桥仍在初始化阶段报本机路径错误，因此本轮没有把 HTTP 200 或 Next build 冒充
  Chrome 视觉验收；需要在浏览器连接修复后补桌面/窄屏点击检查。
- 模型价格是带生效日与官方链接的配置快照，不是供应商账单；价格变化需更新目录。
- thinking 与按工作负载分别选模型未开放，二者都需要独立质量/成本回归。
