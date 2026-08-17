# 当前事实入口

本目录只保存判断“现在是什么”的少量活文档。历史发布、评测、压测和失败实验不在这里改写，
而是按日期保存在 `../delivery/`、`../product/`、`../eval/`、`../loadtest/` 和 `../history/`。

## 阅读顺序

1. [生产基线](production-baseline.md)：当前生产版本、服务、数据、质量与已知边界；
2. [当前任务](../../spec/08-roadmap-ai-ide.md)：只看最后一个状态为执行中的任务卡；
3. [累计开发日志](project-status.md)：只用于追溯历史，不用于判断实时生产状态。

## 事实优先级

```text
当前环境实时查询
  > 本目录带日期的生产基线
  > 日期化 status 验收证据
  > spec / ADR 中的目标与锁定决策
  > handbook / interview 中的讲解示例
```

动态数据必须注明日期、环境和测量方式。GitHub `main` 可能包含生产版本之后的文档提交，因此
仓库 HEAD、Release 标签和生产 `IMAGE_TAG` 是三个需要分别核对的概念。
