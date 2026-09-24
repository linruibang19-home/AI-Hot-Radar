# RAG 问答界面精修验收（2026-08-11）

## 范围

本次只执行 `TASK-M4-004`。保留 `/ask` 的侧栏、标题、对话头、多轮记录、答案卡、
证据质量和引用结构，只精修首次进入时的空状态、示例问题与底部输入区。

## 已完成

- 用“基于站内原始资讯 / 从一个具体问题开始”建立空状态视觉层级，缩短无意义留白；
- 首屏明确展示“原文引用、时间范围可修正、证据不足会拒答”三项真实能力边界；
- 示例问题在桌面端使用两列、移动端使用单列，保留每个问题所验证的能力说明；
- 输入区增加半透明分隔、主按钮层级及键盘 `focus-visible`，不引入新组件库；
- 新增源代码结构回归，固定三项可信提示与示例问题语义标签。

## 验收证据

全部命令均通过 Docker Compose 测试覆盖运行：

```text
npm run typecheck                         PASS
npm run lint                              PASS
npm test -- --run                         PASS (4 files, 55 tests)
npm run build                             PASS (Next.js 15.5.23)
```

随后重建并启动实际 `web` 镜像：

```text
container health                          healthy
GET http://localhost:3000/ask             200
HTML contains 基于站内原始资讯             true
HTML contains 问答能力边界                 true
HTML contains 证据不足会拒答               true
```

## 尚未替代的验收

本记录证明代码、构建和实际运行态正确，不代替人工视觉审美判断。Chrome 插件会话在本轮
前一阶段已经按插件规则结束，因此改后桌面/移动端交互截图应在下一次浏览器验收任务中执行，
无需为此阻塞当前可部署代码。
