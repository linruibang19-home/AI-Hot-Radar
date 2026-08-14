# AI Service（FastAPI + Worker）

Python 侧使用 FastAPI，但 HTTP 只是三个运行形态之一：同一镜像还运行 Scheduler 和 Pipeline。
它负责采集、全文抽取、LLM 结构化、去重/Story、切块/Embedding、混合检索、Rerank、生成和评测；
订阅、权限和投递事实属于 Java Core API。

本模块采用**按能力域分包 + 显式层次职责**：

```text
ahr/
├── main.py, health.py, rag/api.py       # Transport / composition
├── ingestion/pipeline.py, scheduler.py  # Application orchestration
├── processing/pipeline.py, worker.py    # Application orchestration
├── rag/service.py                       # RAG use case orchestration
├── */models.py, schemas.py, planner.py,
│   fusion.py, chunking.py, safety.py    # Domain policy / pure rules
└── adapters/, repository.py, http.py,
    llm.py, embeddings.py, cache.py      # Infrastructure adapters
```

不是每个函数都包一层类：纯排序、切块、时间解析和安全规则保持可组合函数；数据库、HTTP、模型和
Redis 才是需要隔离的 I/O 边界。AST 架构测试禁止 ingestion 反向依赖 processing/RAG、禁止 RAG
调用采集适配器，并把 FastAPI 限制在传输模块。

验证：

```bash
python -m pytest -q
python -m mypy src
python -m ruff check .
```
