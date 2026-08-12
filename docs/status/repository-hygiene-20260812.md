# 仓库卫生与知识归档（2026-08-12）

任务卡：`TASK-M5-013`。

## 盘点范围

- 482 个受 Git 管理文件；
- Python 149、Java 47、TypeScript/TSX 64、SQL 25、Markdown 91；
- 25 个 Flyway 文件（含 V017.1），140 个信源和 90 题黄金集；
- `docs/status/` 中当前入口、历史快照与不可再生评测证据；
- 本地构建缓存、工具 worktree、恢复演练备份和 Windows 异机备份任务。

## 实际处理

| 项目 | 处理 | 安全证据 |
|---|---|---|
| 已合并 Claude worktree | 用 `git worktree remove` 移除，约 625MB | 工作区干净且提交已是 `main` 祖先 |
| 旧 RAG 审查 worktree | 未提交的三份文档先保存到 `stash@{0}`，再移除登记 | stash 对象 `83857e5...`，不覆盖当前生产后文档 |
| Python/Java/Web 构建缓存 | 删除约 248MB 可再生产物 | 只指定 `.gitignore` 覆盖路径，依赖、密钥与数据未动 |
| 工作区恢复备份 | 删除约 99MB 副本 | `D:\Backups\AI Hot Radar` 存在同名、同大小、同 SHA-256 副本；计划任务最近结果 0 |
| 空临时/挂载目录 | 删除 | `.codex-tmp`、service-local `config/`/`data/` 无文件且非规范入口 |
| Git 跟踪文件 | 不删除 | 无临时名、编辑器残留、重复内容或异常大文件 |
| 黄金集与 `docs/status/eval/*.json` | 完整保留 | 不可再生的版本化实验与负结果证据，不是缓存 |

`.env`、`node_modules`、PostgreSQL/Redis 数据卷、异机备份、测试 fixture、迁移和生产配置均未删除。

## 长期入口

- `docs/code-map.md`：按业务链路阅读全部代码；
- `docs/status/README.md`：区分当前状态、历史快照与实验事实；
- `docs/README.md`：规格、ADR、设计、状态和面试材料总导航；
- `.gitignore`：阻止工具临时目录和错误 service-local 挂载目录重新出现。

## 尚未自动处理

1. `stash@{0}` 是 2026-08-09 的上线前 RAG 审查笔记。后续应逐条与当前代码和发布门核对，
   只摘取仍成立且当前文档缺失的洞察；在核对前不合入也不删除。
2. `AI Hot Radar Docker Maintenance` 已登记为每日 03:15，首次计划运行尚未发生；运行后检查
   `LastTaskResult`，失败时修计划任务环境而不是扩大脚本权限。
3. 生产仍运行 `v0.1.7@c1c6918`；本轮文档/本地卫生不触发部署。TASK-M5-012 的日志驱动
   需要在下一次受控生产维护窗口随容器重建生效。

## 回归证据与环境差异

- 规格：140 个信源、9 个 Profile、38 个 social id，验证通过；
- 文档：91 份 Markdown 相对链接与图片存在性通过；敏感串扫描通过；
- Python：Ruff 通过，pytest **884 passed / 2 skipped**；
- Compose：本地与生产两份配置均可渲染；
- Java：本机只有 JDK 17，而项目锁定 JDK 21，不以本机 Maven 失败判定源码；由 PR 的 JDK 21
  CI 重新验证；
- Web：清理前依赖目录已不完整，`npm ci` 又受本机网络中断，不保留半安装结果；由 PR 的
  锁文件干净安装、typecheck、lint、unit 和 build 验证；
- mypy：当前全局环境解析到 mypy 1.20.2 + redis 5.3.1 后，`health.py` 出现一个
  `no-untyped-call`；项目现有 `mypy>=1.13,<2.0` 仍过宽，CI 是否复现以 PR 为准。若 CI 也失败，
  下一张独立任务应固定工具/Redis 类型组合或增加有依据的第三方库 override，不能在归档任务中
  静默放宽类型规则。

这些环境差异不改变生产运行；它们说明“缓存可删”与“依赖必须由锁定环境重建”是两件事。
