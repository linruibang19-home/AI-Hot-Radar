# 主题/厂商时间线顺序与导航感知性能（2026-08-13）

## 用户可见问题

厂商“相关与对比”页出现 `5 月 17 日 → 8 月 5 日 → 5 月 29 日 → 8 月 10 日`，主题地图和卡片
导航会用全屏骨架覆盖已加载内容，主观上明显卡顿。

## 根因

1. Core API 的厂商 feed 使用 `ORDER BY relation_score DESC, effective_time DESC`；它是关系排行，
   不是时间线。高分五月内容会排在低分八月内容之前，cursor 也沿用了错误 tuple。
2. Web 的 `groupByDay` 完全保留 API 插入顺序，没有守住“日期时间线必须倒序”的展示不变量。
3. 生产公开页和内部 Core API 的首字节实测约 0.16–0.20 秒与 0.13–0.16 秒；实际网络不是秒级，
   但 Sidebar 在这段短等待内覆盖整个阅读区，感知成本远大于真实请求时间。
4. 动态详情的 `generateMetadata` 和 page 都会读取 vendor/topic map；显式 request memoization 可避免
   同次 SSR 重复工作。

## 修改

- SQL 与 cursor 改为 effective publication/observation time DESC，再按 relation score、id 稳定排序；
- `groupByDay` 对副本按 effective time 与 id 倒序，后端退化时前端仍不乱；
- vendor/topic 查找使用 React `cache()` 做单请求去重；
- 删除全屏 `RouteLoading` portal，保留被点击 nav link 的即时 pending 状态和预取；
- 不引入额外缓存层，不改变内容新鲜度语义。

## 验收

- Java SQL 顺序/cursor 测试；
- Web 打乱输入的日期/日内顺序测试；
- Web 78 项、typecheck、lint、build；
- 部署后接口结果日期单调不增、公开页无全屏遮罩、Playwright/HTTP 冒烟与生产 TTFB 对比。

## 生产验收结果

- v0.1.9 起厂商 feed SQL 使用 `effective_time DESC, relation_score DESC, id DESC`，cursor 使用同一
  tuple；2026-08-13 生产 `related` 首页依次为 8 月 13、12、11、10、7、5、4、3 日，不再出现
  5 月/8 月交错；
- `/vendors/deepseek?relation=related` TTFB 约 0.42 秒，`primary` 约 0.35 秒；`/topics` 冷缓存
  一次约 3.24 秒，随后三次约 0.20–0.35 秒；
- 生产 Chrome 的主题地图无 console/page error；人为延迟 600ms 的 RSC 请求下，点击后侧栏立即
  `aria-busy`，已读正文保留，页面中不存在全屏 `.route-loading`；
- 全站浏览器回归 36 项中 32 项通过。日期计数失败经 API 复核为测试等待条件过早（生产标题与
  三页 API 都是 140 条）；3 个 RAG 失败由生产匿名限流返回 429，不能为了测试绕过真实限流。
  RAG 功能正确性继续由发布门和单查询 smoke 证明，批量浏览器 RAG 应在本地提高测试限额后运行。
