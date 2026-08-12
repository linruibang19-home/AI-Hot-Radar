# 11｜Java Core API 实现走读

## 1. 技术栈与定位

Core API 使用 Java 21、Spring Boot 3.4、Spring Web、JDBC/Flyway 兼容数据库访问、Bean Validation、
Actuator 和邮件组件。它不是 ORM 主导的领域模型项目：查询和状态迁移多用显式 SQL，便于控制
窗口、锁、JSON 聚合和 PostgreSQL 特性。

## 2. 包结构

| 包 | 责任 |
|---|---|
| `content` | 资讯、Story、报告公开读模型 |
| `subscription` | 申请、确认、退订、SMTP、投递调度 |
| `admin` | Source、模型、报告发布、审计、幂等 |
| `health` | live/ready 和依赖状态 |

## 3. Controller 到 SQL

Controller 负责 HTTP 语义、输入校验和 DTO；Service 负责事务/状态；NamedParameterJdbcTemplate
执行参数化 SQL。公开读只返回页面需要的摘要、来源和导航，不把内部原文或管理字段泄露。

学习 `ReportController` 时沿这条线：period/key 解析 → 查询报告主记录 → 加载 report entries →
分组 section → 计算阅读统计 → 查询前后导航 → 组装 immutable record DTO。

## 4. 管理安全

当前管理认证是环境变量 Bearer Token，不是完整 Spring Security 用户体系。读操作需要 VIEWER，
写操作需要 OPERATOR，并额外要求：

- 显式目标确认，降低误点；
- idempotency key，重试不重复执行；
- `admin_audit` 保存动作、before/after 和 trace；
- token 不入数据库、不返回页面、不写日志。

这是单运营者场景的受控取舍，不等价于多租户 RBAC。

## 5. 报告发布

`ReportPublicationService` 查询当前状态，验证允许迁移，再事务更新。不能直接从 DRAFT 跳到任意
状态；页面按钮只是发出意图，数据库状态才是事实。重复请求由幂等组件复用结果。

## 6. 订阅和邮件

申请服务规范化邮箱、period 和 timezone，生成带版本 token。确认事务创建 ACTIVE subscription
并替换周期偏好。投递 `@Scheduled` 循环查询 due candidates、插入唯一 delivery、领取重试、调用
mailer、更新 SENT/FAILED。SMTP 是外部副作用，不能和数据库事务假装原子；delivery 状态负责
补偿和重试。

## 7. 错误契约

无效 token、邮件未配置、参数错误和资源不存在映射为确定 Problem/HTTP 状态。不要把数据库异常
栈直接返给浏览器。健康检查区分 live 与 ready：进程活着不代表数据库可用。

## 8. 测试

- 纯单元：token、period、渲染、状态迁移；
- MVC/Controller：请求、权限、错误格式；
- PostgreSQL 集成：Flyway、SQL、锁、唯一约束；
- Compose/CI 使用 Java 21，不能以本地 JDK 17 失败误判代码。

## 9. 面试追问

**为什么不用 JPA？** 不是否定 JPA，而是本项目有大量 PostgreSQL 窗口、`SKIP LOCKED`、JSON、
pgvector 和精确 DTO 查询；显式 SQL 更透明。若普通 CRUD 增长，可局部使用而非全面迁移。

**如何处理 SMTP 与数据库双写？** 不声称分布式事务。先创建 delivery，再发送，成功/失败落状态；
唯一键防重复，重试补偿。极端“供应商已收但本地未记成功”仍需 provider id/幂等能力才能完全
消除，是剩余边界。

