# TASK-M5-002 报告阅读体验与结构化只读模型

> 日期：2026-08-11
> 分支：`codex/rag-quality-gates`
> 状态：实现与自动化验收完成；Chrome 桌面/窄屏视觉门禁待补

## 1. 本卡做了什么

- 将日报、周报、月报统一为“周期档案栏 + 出版式正文”的只读阅读工作区；
- 保留全站侧栏、AI Hot Radar 品牌、字体与绿色强调色，不复制参考站点品牌、Logo、
  完整文案或像素布局；
- 报告列表入口直接打开该周期最新一期，详情 URL 仍可单独访问和分享；
- 章节目录、来源等级、Story 脉络、原文链接、统计、前后期导航均使用结构化字段；
- DRAFT、模型/提示版本、生成时间与“事实以原文为准”说明保持显式；
- 桌面为双栏阅读，窄屏降为单栏并将档案区变为可折叠区域。

本卡没有新增表、迁移、浏览器凭据或写接口，也没有实现审核、发布、下架和编辑。

## 2. 只读数据流

```text
report
  -> report_item（章节、位置）
  -> content_item（标题、摘要、原文 URL、内容类型）
  -> source（发布方、组织、来源等级）
  -> story（事件 slug、独立信源数）
  -> ReportDetail（sections / stats / navigation）
  -> Next.js Server Component
  -> 档案栏、刊头、主线、章节条目、原文与 Story 链接
```

生成 Markdown 仍作为向后兼容字段保留，但 Web 不再用它反解析标题、来源和链接。
PostgreSQL 仍是事实来源；Redis 职责、服务边界和公开 API 路径均未改变。

## 3. 实测数据与运行态

| 周期 | 最新 key | 状态 | 章节 | 条目 | 来源 | Story |
|---|---|---|---:|---:|---:|---:|
| 日报 | `2026-08-10` | DRAFT | 3 | 11 | 8 | 11 |
| 周报 | `2026-W33` | DRAFT | 4 | 22 | 12 | 22 |
| 月报 | `2026-08` | DRAFT | 7 | 88 | 23 | 88 |

`/reports`、两个周期查询入口及三种详情 URL 均返回 200；HTML 均包含刊头和“阅读原文”。
Core API、Web 替换后健康检查均为 `healthy`。

## 4. 验收证据

| 层 | 命令/检查 | 结果 |
|---|---|---|
| Java | Maven 容器 `mvn -B test` | 58/58；`ReportControllerTest` 5/5 |
| Python | Compose test image，`pytest tests/test_report.py tests/test_worker.py -q` | 55/55 |
| Web | Compose test image，typecheck + lint + Vitest + Next build | 62/62；零 lint 错误/警告；build 成功 |
| 镜像 | Compose Web build；Core build stage + 本地现有 runtime 等价封装 | 成功 |
| Runtime | Core/Web 健康检查、结构化 API、六个页面 URL | 全部通过 |

标准 Core API 多阶段镜像构建两次停在 Docker Hub 获取缺失
`eclipse-temurin:21-jre-jammy` token，均为远端连接重置。为完成本地实测，使用标准
Dockerfile 的 `build` stage 生成 JAR，再将 JAR 放入当前已验证的 Core runtime 镜像；
源码 Dockerfile 未改。网络恢复后，上线产物必须重新执行标准 Compose build。

## 5. 尚未通过的门禁与风险

ChromeCodex 在浏览器初始化前连续返回“failed to write kernel assets: 系统找不到指定的
路径”，重置控制会话后仍相同。错误发生在浏览器插件控制层，未导航到应用，因此：

- 不能宣称桌面和窄屏视觉验收通过；
- 不能用 HTTP 200、HTML 存在或 CSS 断点检查替代视觉判断；
- 下一次应优先在 ChromeCodex 恢复后检查 1440px 桌面、窄屏、周期切换、档案滚动、
  原文/Story 跳转及控制台错误。

月报当前有 88 条，HTML 约 267 KB；这是全量只读展示的直接结果。后续如真实浏览器证据
显示长文性能不足，应在独立任务卡比较分节折叠、分页或流式分段，不能在本卡静默改变
报告语义。

## 6. 下一张任务卡

先完成 `TASK-M5-002` 的 Chrome 视觉门禁。通过后再建立
`TASK-M5-003｜报告审核、发布/下架与公开可见性闭环`，先补 ADR/API 权限与审计设计，
再实现写操作；不得把当前 DRAFT 预览直接当正式发布。
