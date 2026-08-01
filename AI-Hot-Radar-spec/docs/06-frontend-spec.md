# 06｜前端规格

文档 ID：`AHR-FE-600`

## 1. 设计目标

风格为“高信息密度但不拥挤的技术情报雷达”。可以借鉴 AIHOT 的功能布局，但不得复制其品牌、Logo、插图、完整文案和像素级视觉实现。

## 2. App Router 结构

```text
app/
├── (public)/
│   ├── page.tsx
│   ├── items/[slug]/page.tsx
│   ├── stories/[slug]/page.tsx
│   ├── topics/[slug]/page.tsx
│   ├── reports/[period]/[key]/page.tsx
│   └── search/page.tsx
├── radar/page.tsx
├── favorites/page.tsx
└── admin/
```

内容首屏优先 Server Component；筛选器、收藏、流式回答和管理操作使用 Client Component。不得把整页变成 client-only。

## 3. 公共组件

- `StoryCard`：事件标题、摘要、热度、来源数、时间；
- `ItemCard`：标题、来源、时间、分类、摘要、精选理由；
- `SourceBadge`：一手/权威二手/社区；
- `EntityChip`、`TopicChip`；
- `FilterBar`：URL search params 是唯一筛选状态；
- `CursorList`：加载、重试和保留滚动位置；
- `Timeline`：事件时间而非页面抓取时间；
- `CitationPopover`：来源、日期、证据节选、原文入口；
- `RagPlanSummary`：解释识别的实体与时间范围；
- `EmptyState`、`ErrorState`、`Skeleton`；
- `AdminJobTrace`：任务阶段、尝试、错误和 request ID。

## 4. 页面验收要点

### 首页

- 桌面两栏：主精选流 + 热点/主题侧栏；移动端单栏；
- 日期分组 sticky heading；
- 分类筛选可分享 URL；
- 新内容提示不强制打断阅读；
- 卡片不展示无解释的“神秘分数”。

### Story 详情

- 顶部显示 event time、first report、latest update；
- 主摘要和“为什么重要”；
- 一手来源优先的报道列表；
- 时间线区分事实更新、观点、纠正；
- 同一来源转载不得伪装为多个独立信源。

### Radar

- 输入框提供示例问题；
- 回答开始前展示识别的实体/时间，可一键修改；
- 流式文本中引用编号出现时即可点击；
- 右侧/底部证据面板按 Story 分组；
- 显示“检索至某时刻”，不得写成永久事实；
- 降级、部分证据、不确定和拒答有独立视觉状态。

## 5. SEO 与元数据

- item/story/topic/report 生成 canonical、OpenGraph、JSON-LD；
- 搜索和参数化过滤页默认 `noindex,follow`，防止重复索引；
- sitemap 只包含公开已发布内容；
- 删除内容返回 410；临时不可用返回 503，不用 404 掩盖；
- 标题与描述由已保存内容生成，不在请求时调用 LLM。

## 6. 可访问性与性能

- WCAG 2.2 AA；键盘可操作、清晰 focus、语义 heading；
- 热度不只用颜色表达；
- 尊重 `prefers-reduced-motion`；
- 图片使用明确尺寸和懒加载，首屏 hero 除外；
- 目标 Core Web Vitals：LCP < 2.5s、INP < 200ms、CLS < 0.1；
- Bundle 分析阻止把管理/Markdown 重组件打入首页首包。

## 7. 状态与数据访问

- 服务端通过 Core API 获取公共数据；
- 客户端 mutation 使用生成的 typed client；
- 筛选状态在 URL，不另存全局 store；
- 收藏 MVP 用 localStorage，必须支持导出；登录同步后采用服务器版本和可解释冲突策略；
- 禁止在浏览器暴露内部 service token、LLM key 和管理 API 密钥。

