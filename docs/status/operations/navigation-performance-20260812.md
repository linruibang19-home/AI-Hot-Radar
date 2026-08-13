# 导航点击性能与即时反馈（2026-08-12）

任务：TASK-M5-006 上线维护项
状态：✅ 已随 `v0.1.5@d58e639` 发布并通过公网浏览器回归

## 1. 根因与基线

生产环境逐路由三次 `curl` 表明，热请求 TTFB 大多为 0.10–0.30 秒；真实 Chrome 通过
侧边栏切换 11 个页面时，URL 与目标首屏可见耗时为 0.47–0.96 秒且控制台无错误。后端
Redis/Core API 没有形成秒级瓶颈，主要问题是动态 App Router 等待 RSC 期间旧页面完全
不变，用户无法判断点击是否生效。

曾验证把 `loading.tsx` 放到根路由，但它会令主题页屏幕中的大量动态详情链接自动预取，
一次产生几十个 RSC 请求并出现导航竞态，因此该方案已撤回，没有把副作用留进提交。

## 2. 最终改动

- 侧边栏点击非当前路由后立即设置 `aria-busy=true` 与低干扰脉冲状态；
- 桌面端通过 body portal 显示与原页面色彩、圆角一致的骨架屏，移动端保留按钮反馈而不
  用固定遮罩覆盖全宽导航；
- 只在鼠标悬停或键盘聚焦某一个侧边栏目标时调用 `router.prefetch`，避免全页批量预取；
- 不启用 Next 数据缓存，不改变 Core API Redis TTL、内容时效或任何后端接口；
- Playwright 新增“延迟 RSC 时点击必须即时反馈”的确定性回归，并修正报告页已经过时的
  DOM 选择器。

## 3. 验收证据

| 检查 | 结果 |
|---|---|
| Next 15.5.23 production build | 编译、Lint、类型检查、静态页面生成通过 |
| Compose Web health | healthy |
| Playwright navigation | 16/16，通过桌面路由、详情、原文、返回、移动端无横向溢出 |
| 慢 RSC 回归 | 600ms 人工延迟期间 `aria-busy=true` 且骨架可见；完成后状态清除 |
| 定向预取 | 本地 Chrome 悬停预取完成后，热点榜点击到 URL 切换 214ms |
| 浏览器控制台 | 0 error |

## 4. 生产发布复测

- PR [#6](https://github.com/linruibang19-home/AI-Hot-Radar/pull/6) 五项 CI 全绿后合并；
- Release [31524206135](https://github.com/linruibang19-home/AI-Hot-Radar/actions/runs/31524206135)
  在 `d58e63942c5cfff4c8a134fd77914ccf6893de1a` 重跑五项门禁并发布三张 SHA 镜像；
- 服务器 preflight、镜像 pull、10 服务 `up --wait` 与公网 smoke 全部通过，0 unhealthy；
- 生产 Chrome 实测目标路由悬停预取 434ms，随后点击到目标首屏 219ms，控制台 0 error；
- 官方 Playwright 容器直接对 `https://aihotradar.online` 跑导航回归 16/16，通过桌面、
  详情、原文、慢 RSC、返回和 375px 移动端场景。

ChromeCodex 插件仍在启动内核前报 `failed to write kernel assets ... (os error 3)`；本次采用
本机已安装 Chrome 的 Playwright 通道与官方 Playwright 容器完成真实浏览器验收，插件故障
不再被误写为“没有浏览器证据”。
