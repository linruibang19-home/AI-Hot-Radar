# GitHub Actions Node 24 运行时升级证据（2026-08-17）

## 结论

`TASK-M5-029` 只升级 GitHub 官方 Action 的运行时主版本，不改变应用运行时、依赖、业务代码、
发布标签或生产镜像。PR #35 首轮五路 CI 全部通过，旧 Action 的 Node 20 弃用与强制 Node 24
兼容告警已消失。

## 变更矩阵

| Action | 原版本 | 新版本 | 保持不变的应用语义 |
|---|---:|---:|---|
| `actions/checkout` | v4 | v7 | 默认深度、凭据和工作目录未另行配置 |
| `actions/setup-python` | v5 | v7 | Python 仍为 3.12 |
| `actions/setup-java` | v4 | v5 | Temurin Java 仍为 21，Maven cache 保留 |
| `actions/setup-node` | v4 | v7 | Node 仍为 22；显式 `package-manager-cache: false`，不引入新缓存信任边界 |

Docker 的 buildx、login、metadata 与 build-push Action 没有出现本次 Node 20 告警，因此没有借机升级。
release workflow 只把 checkout 升到 v7；没有创建版本 tag，也没有推送镜像。

## 可复现验证

### 本地静态门禁

```text
workflow YAML parse             PASS (ci.yml, release.yml)
python scripts/validate_docs.py PASS
python scripts/validate_spec.py PASS
git diff --check               PASS
```

### Pull request 实际运行

- PR：[#35](https://github.com/linruibang19-home/AI-Hot-Radar/pull/35)
- 首轮 run：[`32025546259`](https://github.com/linruibang19-home/AI-Hot-Radar/actions/runs/32025546259)
- Spec validation：8 秒，PASS
- Flyway from empty database：20 秒，PASS
- Core API：23 秒，PASS
- AI service：38 秒，PASS
- Web：61 秒，PASS

合并后的 `main` push run 在 PR 合并后补记；它验证默认分支使用的就是相同工作流，而不是只验证
临时分支。

## 仍然存在但不属于本任务的提示

- Python 测试日志有 Starlette `TestClient` 关于未来 `httpx2` 的弃用提示；当前 935 项测试仍通过，
  应单独升级依赖并做契约回归，不能在 CI Action 升级中混改。
- Java 编译提示 `CacheConfig.java` 使用弃用 API；应以 `-Xlint:deprecation` 定位后单独修复，当前
  Maven verify 与 86 项测试通过。

这两个提示是应用依赖/API 生命周期问题，不是 GitHub Action Node 运行时问题。本任务保留告警，
避免把五条构建链同时变化后失去故障归因能力。
