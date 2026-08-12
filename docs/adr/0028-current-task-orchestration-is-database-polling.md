# ADR-0028：当前后台任务编排采用 PostgreSQL 轮询，不把 Outbox 预留表描述为消息队列

- 状态：接受
- 日期：2026-08-12
- 关联：AHR-SPEC-000 §3/§8、AHR-ARCH-200、AHR-INGEST-1000、AHR-RUNBOOK-1100、ADR-0005、TASK-M5-014

## 背景

早期规格为未来的异步消费者预留了 `outbox_event` 和 `processed_event`，并写下“Core API
发布 Outbox、AI Worker 消费”的目标拓扑。当前生产实现并没有该消费者：`outbox_event`
随内容写入并按保留期清理，但没有进程读取其未发布行，`published_at` 也没有被推进。

真正承担无人值守工作的，是两个 Python 常驻进程：采集调度器从 `source.next_poll_at`
领取到期信源；处理流水线从 PostgreSQL 读取尚未完成的内容状态。前者使用
`FOR UPDATE SKIP LOCKED`，后者使用 PostgreSQL advisory lock、输入版本与幂等写来避免重复
执行。Java Core API 负责公开读 API、报告发布、订阅、邮件投递和管理审计，不负责采集调度。

如果继续把目标拓扑写成当前事实，面试讲解、故障恢复和扩容判断都会建立在不存在的消费者上。

## 决策

1. 当前后台编排事实源是 PostgreSQL。Python `scheduler` 按 `source.next_poll_at` 领取信源，
   Python `pipeline` 按内容状态推进结构化、聚类、选择、报告和索引工作。
2. `outbox_event` 当前定义为**同事务事件日志与未来传输预留点**，不是已启用的任务总线；
   `processed_event` 是预留的消费幂等表，不代表已有消费者。
3. 文档、监控和恢复手册不得用 `published_at`、表行数或表名推断“Outbox 正在投递”。只有
   可定位的生产者、消费者、积压 SLO、重放命令和消费测试同时存在时，才可这样描述。
4. Java Core API 仍拥有报告订阅的 `@Scheduled` 邮件投递器；这与采集/处理调度是两条独立
   链路，不得笼统称为“Java Scheduler”。
5. 当前规模不引入 RabbitMQ/Kafka。出现持续 backlog、数据库轮询影响业务查询、消费者需
   独立扩缩容或需要可证明的跨服务事件交付时，另立 ADR、迁移与回滚方案。

## 备选

- **立即补 Outbox Publisher**：没有容量或可靠性证据，反而新增失败面与运维负担。
- **删除 Outbox 表**：会丢失事务事件审计与未来演进落点，也属于无必要的破坏性迁移。
- **继续保持文档模糊**：会让“数据库轮询的一致性”被错误包装成“消息投递的一致性”。

## 后果

- 当前运行图、故障排查和面试叙述与代码一致；轮询、锁和幂等是必须解释的核心机制。
- Outbox 是明确的技术债/演进接口，而不是简历上的已完成能力。
- 若将来启用消费者，需要为积压、死信、顺序、幂等、重放和切换窗口提供独立验收。

## 回滚

本 ADR 只纠正文档语义，不改变运行代码。若未来完成真正的 Outbox 消费链路，以新 ADR
取代本决策，并在同一发布中更新规格、拓扑、监控和恢复手册。
