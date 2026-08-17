# 文档事实源与全仓一致性复核（2026-08-17）

任务卡：`TASK-M5-027`。本次只调整文档与文档校验，不改变 API、数据库结构、RAG 算法、
生产镜像或线上数据。

## 1. 审计范围

逐类检查了根入口、13 份 spec、21 份独立 ADR/索引、4 份 design、23 份 handbook、
18 份 interview、55 份 status、archive 与根开发指南，并与以下实现事实交叉核对：

- `apps/web/package.json`、Web 路由/代理/测试；
- `apps/core-api/pom.xml`、业务域包、缓存、订阅、管理与测试；
- `apps/ai-service/pyproject.toml`、采集/加工/RAG/评测模块及 CLI；
- `database/migrations/` 的完整 Flyway 链；
- `config/sources.yaml`、ingestion profiles、taxonomy 与 social watchlist；
- 本地/生产 Compose、Caddy、CI、备份、恢复、监控与发布脚本。

历史 status/eval 是不可再生证据，本轮没有把其中的旧数字“改成最新”。对这类文件只检查
入口是否明确标注历史，避免破坏当时的 run、失败假设和验收语境。

## 2. 发现的主要漂移

| 问题 | 风险 | 处理 |
|---|---|---|
| 多份文档各自声明“当前版本/数量” | main、Release、镜像和数据库数字互相冲突 | 新建 `status/current/production-baseline.md` 作为唯一 current 事实页 |
| 交付索引仍写 v0.1.7、V025 和旧测试数 | 读者把历史快照当线上现状 | 重写为能力/证据索引，动态数字全部链接 current |
| 08-14 handoff 与累计 project-status 位于 current | 容易误当持续更新页面 | 顶部冻结提示；current README 给出事实优先级 |
| 首次部署设计仍含 v0.1.5/V024 | 操作时可能使用旧镜像/迁移判断 | 标记 historical，执行只认 runbook + production baseline |
| Handbook/Interview 写死 140 个信源 | 配置已是 143，且 ACTIVE 本来就动态 | 改为配置化信源；具体值只在带日期快照中出现 |
| ADR-001～011 没有独立文件 | 看起来像 ADR 丢失 | 新建 ADR README，说明一级决策在 master spec、0012 起为独立 ADR |
| 开发指南仍写 Gradle 和旧测试数 | 与 Maven/JDK 21、当前测试集不符 | 改为 Maven/JDK，并以当次命令输出为准 |
| 文档校验只查 Markdown 链接 | 无法发现旧 current 路径和实现版本漂移 | 校验动态读取 source/Next/Spring/latest migration，并禁止旧 current 引用 |

## 3. 事实源优先级

```text
当前生产版本/容器/数据量
  -> docs/status/current/production-baseline.md

产品与架构约束
  -> docs/spec/00-master-spec.md + 领域 spec + 最新 ADR

当前代码行为
  -> migrations / config / Compose / package manifests / tests

历史评测与上线证据
  -> docs/status/{eval,product,operations,delivery,history}
```

发生冲突时不能凭 README 或面试稿选择一个数字。先判断是规范、代码、当前状态还是历史证据，
再按上面的层级处理。

## 4. 自动门禁

`scripts/validate_docs.py` 现在除链接和章节完整性外，还会：

- 从 `config/sources.yaml` 计算登记信源数并核对 current baseline；
- 从 `apps/web/package.json`、`apps/core-api/pom.xml` 核对 README 技术版本；
- 从 Flyway 文件名计算最新迁移并核对 current baseline；
- 禁止 canonical 入口重新引用已废弃的 `status/production/` 或 08-12 handoff；
- 要求 Handbook 01–22 与 Interview 00–16 的入口文件完整。

历史文档不受“最新数字”规则约束，否则每次发布都会篡改过去的实验上下文。

## 5. 验收口径

本任务完成时应至少满足：

```bash
python scripts/validate_docs.py
python scripts/validate_spec.py
python -m ruff check scripts/validate_docs.py
git diff --check
```

因为只修改文档和校验脚本，不触发生产部署。仓库 `main` 的文档更新也不意味着香港服务器的
三张业务镜像改变；生产版本仍以不可变 `IMAGE_TAG` 和 current baseline 为准。

## 6. 本次实测结果

| 范围 | 命令/环境 | 结果 |
|---|---|---|
| 文档 | `python scripts/validate_docs.py` | 通过：145 个 Markdown、383 个本地链接、Handbook 23 个入口、Interview 18 个入口 |
| 规格 | `python scripts/validate_spec.py` | 通过：143 个信源、9 类 profile、38 个 social id |
| 文档校验代码 | `python -m ruff check scripts/validate_docs.py` | 通过 |
| Python | `pytest -q`、`mypy src`、`ruff check .` | 935 passed、2 skipped；mypy 87 个源文件通过；ruff 通过 |
| Web | `typecheck`、`lint`、`test`、`build` | 全部通过；Vitest 9 个文件、81 项测试；Next.js 15.5.23 生产构建通过 |
| Java | JDK 21 Maven 容器 | 86 项测试全部通过；本机 JDK 低于 21，不能作为本项目 Java 验收环境 |

Java 容器随后在 Windows bind mount 的 fat JAR 写入收尾阶段长时间没有输出，人工中止了该次
`mvn verify`。因此本页只把 **86 项测试通过**记为证据，不把这一次命令记成完整 verify 成功；
正式打包是否可交付仍由 Linux CI 与 Docker 镜像构建门禁判定。这一限制不会反向写成产品缺陷。
