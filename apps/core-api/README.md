# Core API（Spring Boot）

Core API 是稳定业务边界：公开内容/Story/报告读取、报告发布、邮件订阅与投递、管理鉴权、
幂等和审计。它不负责采集、正文抽取、Embedding、Rerank 或答案生成。

本模块采用**按业务域分包 + 域内分层**，而不是把全项目拆成巨大的 `controller/service/dao/entity`
四个目录：

```text
com.aihotradar.coreapi
├── content/       Controller → Service → Repository → PostgreSQL read model
├── subscription/  Controller → Service → JDBC/SMTP adapter
├── admin/         Controller → Service/Repository + security/audit/idempotency
├── cache/         Redis CacheManager 与 TTL
├── health/        liveness/readiness
└── observability/ request id 与结构化日志
```

- `Controller` 只处理 HTTP 参数、状态码和响应；ArchUnit 禁止其依赖 Spring JDBC。
- `Service` 保存业务阈值、状态转换、分页/聚合和幂等编排。
- `Repository` 保存 SQL、RowMapper 和 PostgreSQL 投影。
- 没有使用 JPA `@Entity`：核心读取是带窗口、聚合、来源/Story 连接和游标的查询，Spring JDBC
  更直接；Java `record` 是 API/read model，表结构由 Flyway 管理，不把数据库行伪装成领域对象。

验证：

```bash
mvn -B verify
```
