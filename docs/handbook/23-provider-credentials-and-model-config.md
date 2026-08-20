# 23｜模型配置：供应商凭证怎样入库、怎样回落

这一篇讲 `/admin/models` 背后的东西：生成模型怎么选、供应商地址和 API Key 怎么存、
主密钥丢了会怎样，以及为什么这一页**不支持第三方中转站**。

对应决策：[ADR-0027](../adr/0027-deepseek-generation-model-selection-is-database-backed.md)（模型选择）、
[ADR-0032](../adr/0032-generation-provider-credentials-are-database-backed.md)（供应商凭证）。

## 1. 两件事，两张表

页面上是两块，背后也是两条独立的路径：

| 页面区块 | 存在哪 | 迁移 | 改了影响谁 |
|---|---|---|---|
| 生成模型（Flash / Pro 切换） | `generation_model` 白名单 + 当前配置行 | V0xx（ADR-0027） | 之后的富化、报告、问答 |
| 供应商（请求地址 + API Key） | `generation_provider_config` 单行表 | V027 | 同上，但决定能不能连通 |

拆开是因为它们的失败模式不同：模型选错了会得到一个能跑但更贵/更差的结果，供应商填错了是
整条生成链断掉。前者需要价目快照，后者需要**写入前先验证**。

## 2. 供应商这张表为什么是单行

```sql
CREATE TABLE generation_provider_config (
    singleton_key      SMALLINT PRIMARY KEY DEFAULT 1 CHECK (singleton_key = 1),
    base_url           TEXT NOT NULL,
    api_key_ciphertext TEXT,
    key_fingerprint    VARCHAR(16),
    version            BIGINT NOT NULL DEFAULT 1,
    updated_by         UUID REFERENCES admin_principal(id),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_generation_provider_secret_shape CHECK (
        (api_key_ciphertext IS NULL AND key_fingerprint IS NULL)
        OR (api_key_ciphertext IS NOT NULL AND key_fingerprint IS NOT NULL)
    )
);
```

`CHECK (singleton_key = 1)` 让"一个部署一套生成配置"成为数据库层面的约束，而不是靠应用
代码自觉。多供应商、多环境不同配置都不在这张表的范围内 —— 真要做需要新 ADR，因为那会
改变上面这个前提。

`ck_generation_provider_secret_shape` 保证密文和指纹要么都在、要么都不在。少了这条约束，
"有密文没指纹"这种半截状态会让控制台显示不出任何东西，却又不会回落到环境变量。

## 3. 密钥的存法：AES-256-GCM 信封

密文格式是 `v1.<nonce>.<ciphertext>`，nonce 12 字节、认证 tag 128 位，两段都用**无填充
base64url** 编码。前缀 `v1.` 是为了将来换算法时能识别旧格式。

**为什么是 GCM 不是 CBC**：这把密钥读出来是要发给供应商的。CBC 下密文被改坏，解出来是
一段乱码，程序会拿着乱码去请求，对方返回 401 —— 你会以为是密钥过期，往完全错误的方向排查。
GCM 在解密那一步就失败，错误出现在正确的位置。

**指纹**是明文 SHA-256 的前 12 个十六进制字符。它的唯一用途是让控制台显示"现在装的是哪
一把"，不必解密。这也是排查时的对照手段：

```bash
docker compose -f docker-compose.prod.yml exec pipeline sh -c \
  'printf %s "$LLM_API_KEY" | sha256sum | cut -c1-12'
```

拿这个输出和页面上显示的指纹比，一眼看出容器实际在用的是环境变量那把还是库里那把。

### 跨语言的坑

Java 侧用 `Base64.getUrlEncoder().withoutPadding()` 编码，Python 侧 `urlsafe_b64decode`
**要求补齐 padding**。这是加解密跨语言时最容易踩的一处：Java 写出来的字符串 Python 直接
解会抛 `binascii.Error`。实现里 Python 侧显式补 `=` 之后再解。

## 4. 写入前先验证

`POST /api/v1/admin/models/provider` 的顺序是：**先拿这对地址和密钥去请求一次供应商，
通了才落库**。

探测发的是 `GET {base}/models` 带 Bearer，不是发一次补全 —— 它同样能证明地址可达、密钥有效，
但不花钱。错误映射成固定的码，上游响应体一律不透传：

| 上游情况 | 返回码 | 页面提示 |
|---|---|---|
| 401 / 403 | `provider_auth_failed` | 密钥不被接受 |
| 404 | `provider_endpoint_not_found` | 地址不对 |
| `Content-Type: text/html` | `provider_returned_html` | 这不是 API 地址 |
| 连接失败 / 超时 | `provider_unreachable` | 连不上 |

第三行是从一次真实的失败里长出来的，见第 6 节。

地址本身也校验：必须 http(s)、必须有 host、**不允许带 userInfo**（`https://user:pass@host`
这种会把凭据写进日志）、长度不超过 500。

## 5. 回落：为什么迁移上线时是 no-op

种子行写的是占位符 `env://LLM_BASE_URL`，密文为 `NULL`。生成侧读配置时**逐字段判断**：

```python
stored_url, ciphertext = str(row[0] or ""), row[1]
base_url = env_base_url if stored_url == _ENVIRONMENT_MARKER or not stored_url else stored_url
api_key  = env_api_key  if ciphertext is None else _decrypt_credential(str(ciphertext))
```

两个字段各判各的，所以可以只覆盖地址、或只覆盖密钥。而因为种子值就是占位符，**V027 应用
的那一刻，生产行为一个字节都没变** —— 迁移上线和功能启用被拆成了两件事。

这是给数据库迁移做的一种常规保险：结构先上，行为由数据触发。出问题时回滚的是那一行数据，
不是回滚迁移。

## 6. 为什么不支持中转站

这一页曾经想做成通用连接管理器，接任意 OpenAI 兼容的第三方中转站。做完了，删掉了。

实测发现的问题是：**中转站之间没有统一的路径约定**。测的那家只有 `/v1/messages` 和
`/v1/chat/completions` 是 API，`/` 和 `/chat/completions` 都返回 `200 text/html`。于是：

- "用户填的是根地址还是完整端点"做成开关，两个答案都可能是错的；
- 按供应商类型推导路径的规则，第一条（OpenAI）就写错了；
- 最麻烦的是失败长成 `200` + 一个 HTML 页面 —— **看起来像成功**。

判断是收益（省模型费用）撑不起成本（一套无法离线验证的路径推导，外加连接启停、模型列表
拉取、thinking 开关一串配套状态），整套删除。

保留下来的是 HTML 响应检测：它在官方端点上同样能挡住"地址填错却返回 200"。

## 7. 主密钥

`LLM_CREDENTIAL_MASTER_KEY`，`openssl rand -base64 32`，解码必须恰好 32 字节。

它缺失时的失败是**分裂的**，这一点值得记住：

- core-api 和 ai-service 会回答"本站不能保存密钥"，保存按钮返回 503 —— 明显；
- pipeline 会**正常启动**，然后每一轮富化静默失败 —— 不明显。

所以它在三处被检查：Compose 里用 `${VAR:?}` 声明（缺了容器起不来）、`preflight.sh` 检查
长度（缺了在任何容器启动前就点名）、还有一条静态断言要求三个服务都带上它：

```python
# apps/ai-service/tests/test_prod_compose.py
def test_every_generation_worker_can_decrypt_a_stored_credential(compose):
    for name in ("core-api", "ai-service", "pipeline"):
        assert "LLM_CREDENTIAL_MASTER_KEY" in compose["services"][name]["environment"]
```

最后这条是补上去的：第一次提交只把变量加进了本地 compose，所有门禁全绿，而功能上线后会
"看起来存在但不工作"。那条断言就是本来该拦下它的。

**主密钥丢失 = 已入库的密钥全部不可解，没有恢复路径**，只能用重置接口回到环境变量再重填
一次。所以它必须离机备份。

## 8. 排查入口

| 现象 | 先看 |
|---|---|
| 保存按钮返回 503 | 主密钥有没有到达 core-api：`GET /api/v1/admin/models/provider` 的 `credentialStorageReady` |
| 页面显示"来自环境变量"但你以为改过了 | 库里那行的 `api_key_ciphertext` 是不是还是 NULL、`version` 是不是还是 1 |
| 改完不生效 | 生成侧每次建客户端都读库，不缓存；先比对指纹再怀疑代码 |
| 富化静默失败 | `docker compose logs pipeline`，看有没有解密相关异常 |

具体命令见 [`../spec/11-end-to-end-runbook.md`](../spec/11-end-to-end-runbook.md)。
