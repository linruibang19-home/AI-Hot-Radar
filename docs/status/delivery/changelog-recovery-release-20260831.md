# v0.1.21 发布与部署验收 · 2026-08-31

`v0.1.21@be31bd0c54da4c7e034da58b558980ae99b411ac`，香港 2C4G 生产。
标签构建在提交上重跑了五路门禁，三张镜像推 GHCR，
`deploy-production.sh` 走 preflight → pull → `up -d --wait` → 公网 smoke。

## 部署过程

| 步骤 | 结果 |
|---|---|
| 部署前备份 | `ai_hot_radar-20260830T110131Z.dump`（337M，含校验和） |
| 回滚点 | `IMAGE_TAG=sha-0914ae9bef2ef2cc60d116ee0262d52ee63192cb` |
| 标签构建 | 5 路门禁全过 + 3 张镜像（ai-service / core-api / web） |
| Flyway | 停留 V027，本次无迁移 |
| 容器 | 10 个全部 healthy |
| 公网 smoke | `/health` `/` `/items` `/reports` `/ask` `/eval` `/ops` `/robots.txt` `/sitemap.xml` `/api/items` 全过 |

部署脚本第一次拒绝执行，原因是我把 `.env` 备份文件放在了仓库里，工作树不干净——
脚本要求干净工作树是对的，备份移到 `~/ahr-env-backups/` 后通过。

## 代码上线不等于数据恢复

`docs_changelog` 的修复改的是「以后不再丢」，**生产已有的数据不会自己回来**：
游标里存着 381 个段落哈希，声称它们都见过，而库里只有 11 条内容。
必须做一次性修复。

```
sync-sources                     # 配置变更：智谱换 .md 地址、qwen-research 停用
清 section_hashes + etag         # 12 个游标，声称已见 381 段
ingest --profile docs_changelog  # 256 条入库
```

### 入库同样不等于可检索

入库后立即查：**250 条内容，只有 11 条切了块**。新内容对 RAG 完全不可见。
这是本项目反复出现的形状，所以查了而不是假设。

```
process --no-enrich --limit 400  # 切块 249 条，写入 274 个分块，不花 LLM 的钱
embed --limit 500                # 274 个分块全部向量化，0 失败，43089 token
```

补齐后 **250 / 250 可检索**。富化（中文标题、摘要）留给 pipeline 定时任务自己追，
它每 15 分钟一轮、每轮 60 条。

## 恢复结果

| 信源 | 部署前 | 部署后 |
|---|---:|---:|
| gemini-api-changelog | 1 | 60 |
| anthropic-app-release-notes | 1 | 53 |
| mistral-changelog | 1 | 50 |
| glm-new-releases | 1 | 27 |
| kimi-platform-changelog | 1 | 23 |
| baidu-qianfan-changelog | 1 | 19 |
| deepseek-api-changelog | 1 | 14 |
| **合计** | **11** | **250** |

全库内容 2816 → 4113。

## 端到端验收

拿当初触发整条调查的那个问题实测线上：

**「智谱最近有什么模型发布？」**

- 修复前：拒答
- 修复后：正常回答，`retrieval_confidence` 0.1887，10 条证据 1 条引用

答案内容正确（GLM-5.3-Flash、320B 总参 / 18B 激活、1M 上下文），与官方
changelog 条目一致。但它引的是 Latent Space 的周报，**不是智谱官方那条**——
恢复的 changelog 内容确实进了证据集（DeepSeek API Changelog 有两条在里面），
排序上还是三方综述占先。这是排序问题，不是采集问题，记在待办里。

## 部署顺带暴露的问题

三个 OpenAI 信源 `QUARANTINED`，`ACCESS_RESTRICTED (403)`，
**连续失败 71–73 次**——`developers.openai.com` 拒绝这个香港 IP，
远早于本次部署。此前被「每个 changelog 信源恰好 1 条」的假象盖住了：
1 条和 1 条看不出区别，一个是被唯一索引挡的，一个是根本连不上。

| 信源 | 状态 | 连续失败 |
|---|---|---:|
| openai-deprecations | QUARANTINED | 73 |
| openai-api-changelog | QUARANTINED | 71 |
| openai-codex-changelog | QUARANTINED | 71 |

`anthropic-api-release-notes` 仍是 1 条、`anthropic-claude-code-changelog` 仍是 0 条，
是另一种原因，待查。

## 待办

1. **三个 OpenAI 信源需要出口方案**（代理或换源），香港 IP 直连被 403
2. `anthropic-api-release-notes` / `anthropic-claude-code-changelog` 抽不出内容
3. 「连续多次 discovered 0 不该算健康」的信号还没做——本次两个缺陷都被它掩盖
4. 智谱那题重跑后引的是三方综述而非官方源，排序待看
5. HTML 列表档位 99.8% 内容无发布日期，见
   [listing-articles-undated-20260831](../eval/listing-articles-undated-20260830.md)
