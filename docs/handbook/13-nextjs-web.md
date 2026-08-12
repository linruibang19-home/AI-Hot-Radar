# 13｜Next.js Web 与产品体验

## 1. Web 的职责

Next.js 15/React 19/TypeScript 提供 SSR 内容页面、客户端筛选和导航、报告阅读、RAG 流式交互、
邮件订阅弹窗与工程后台。它不直接访问数据库，也不持有 provider/admin 密钥。

## 2. 页面族

| 页面 | 主要数据 | 体验重点 |
|---|---|---|
| 精选/全部/热点 | Core API 内容 DTO | 快速扫描、筛选、时间语义 |
| Story/主题 | story/entity/topic | 来源关系和演进 |
| 日/周/月报 | report detail | 长文阅读、章节、历史导航 |
| AI 问答 | AI Service stream + citations | 进度、证据、拒答、历史对话 |
| RAG 质量 | 版本化评测摘要 | 门槛、负结果、非实时声明 |
| 运行状态 | 动态 usage/latency | SLO、成本口径、动作建议 |
| 模型/信源后台 | 受保护 API | 只读默认、高风险操作确认 |

## 3. 数据获取边界

服务端页面优先通过内部 API 取得首屏，提高 SEO 和稳定性；客户端交互使用同源 `/api` route
代理，避免在浏览器暴露 Compose 地址。环境变量区分 server-only 与 `NEXT_PUBLIC_*`，任何密钥
都不能被打包进浏览器。

## 4. 导航性能

左侧导航使用 Next Link/prefetch 和 pending 反馈。慢感常来自新路由等待 SSR/API，而不是按钮
本身。优化顺序是：保留布局、即时 active/pending、预取常用路由、缩小首屏请求、并行独立数据、
缓存稳定读模型；不能用假数据让页面瞬间出现。

## 5. RAG UI

- 空态给真实问题建议，而不是装饰性卡片；
- 提交后立即显示用户问题和检索阶段；
- 流式文本保留段落、列表、加粗和 citation marker；
- 引用卡展示来源、发布时间、原文段落和跳转；
- 证据不足明确拒答；
- 历史对话是持久化记录，多轮重写不把旧答案当事实；
- 移动端输入固定但不遮挡引用。

## 6. 报告 UI

保留原有编辑部风格：左侧周期历史、顶部日/周/月切换、主栏刊头、摘要指标、主题章节、原文条目、
前后期导航和邮件订阅。增强层次但不大改视觉语言。

## 7. 状态和错误

每个数据区分 loading、empty、error、stale/last known good。管理操作失败保留用户输入并显示 trace，
不能乐观地把未提交状态显示为成功。订阅弹窗明确“先确认、发送什么、何时发送、如何退订”。

## 8. 可访问性与安全

- 键盘焦点和对话框 focus trap；
- 表单 label、错误关联、按钮 pending/disabled；
- 颜色不是唯一状态信号；
- 外链 `rel` 安全；
- Markdown/HTML 渲染白名单；
- 不把第三方正文作为 `dangerouslySetInnerHTML` 原样注入。

## 9. 测试

Vitest/Testing Library 覆盖组件和数据转换；typecheck/lint 阻止类型和规则退化；Next production
build 验证 server/client 边界；浏览器桌面/移动端走读验证视觉、导航、RAG、报告和订阅完整流程。

## 10. 代码入口

- 路由：`apps/web/app/`
- 组件：`apps/web/components/`
- 数据客户端/类型：`apps/web/lib/`
- API 代理：`apps/web/app/api/`
- 样式：`apps/web/app/globals.css`

