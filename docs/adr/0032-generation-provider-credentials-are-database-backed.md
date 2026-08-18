# ADR-0032：生成供应商地址与密钥入库，只接官方兼容端点

- 状态：接受
- 日期：2026-08-19
- 关联：ADR-0005、ADR-0027、TASK-M5-030

## 背景

`/admin/models` 原本只能在预置的 DeepSeek 模型之间切换（ADR-0027）。供应商地址和 API Key
只存在于 `LLM_BASE_URL` / `LLM_API_KEY` 两个环境变量里，换一把 Key 需要 SSH 上目标机、改
`infra/compose/.env`、重启三个生成侧容器。页面上有一整块「模型配置」，却唯独改不了真正决定
能不能调通的两个值。

在此之前先尝试过一版更大的方案：把这一页做成通用的连接管理器，可以接任意 OpenAI 兼容的
中转站，像 CC Switch 或 Cline 那样。该方案已实现并被放弃，负结果记录在下面的「备选」。

## 决策

1. **V027 建单行表 `generation_provider_config`**（`singleton_key SMALLINT PRIMARY KEY
   CHECK (singleton_key = 1)`），保存 `base_url`、`api_key_ciphertext`、`key_fingerprint`、
   `version` 与审计列。密文与指纹要么同时为空、要么同时存在，由 CHECK 约束保证。
2. **密钥以 AES-256-GCM 信封存储**，格式 `v1.<nonce>.<ciphertext>`，nonce 12 字节、tag 128
   位，编码为无填充 base64url。主密钥来自 `LLM_CREDENTIAL_MASTER_KEY`，必须解码为恰好 32
   字节。选 GCM 而不是 CBC：这把密钥读出来是要发给供应商的，静默损坏会表现成对方的鉴权
   失败，排查方向完全错误；GCM 在解密时就会失败。
   指纹是 SHA-256 的前 12 个十六进制字符，只用于让控制台显示「现在装的是哪一把」而不必
   解密。
3. **写库前先验证**：`GET {base}/models` 带 Bearer。401/403 → `provider_auth_failed`，
   404 → `provider_endpoint_not_found`，返回 HTML → `provider_returned_html`，连不上 →
   `provider_unreachable`。验证不通过就不落库，上游响应体一律不透传。
   用 `/models` 而不是发一次补全：它能同时证明地址可达和密钥有效，且不花钱。
4. **逐字段回落环境变量**。种子行写的是 `env://LLM_BASE_URL` 占位符，因此 V027 上线时是
   no-op —— 迁移跑完，生产行为一个字节都没变。地址是占位符就用 `LLM_BASE_URL`，密文为
   NULL 就用 `LLM_API_KEY`；两者独立判断，可以只覆盖其中一个。
5. **只接官方兼容端点**。不猜测路径、不做端点探测、不提供「地址已是完整端点」这类开关。
6. **保留撤销路径**：`POST /api/v1/admin/models/provider/reset` 把该行写回占位符状态，
   不需要知道原来的环境变量值。

## 备选

- **继续只用环境变量。** 零新增攻击面，但换 Key 要 SSH 加重启，且页面上会一直有一个改不了
  真正配置的「模型配置」。拒绝。
- **明文存库。** 数据库备份会离机，明文密钥随之离机。拒绝。
- **存 Redis。** 违反 ADR-0005：Redis 只放可重建数据，凭证不可重建。拒绝。
- **接入任意 OpenAI 兼容中转站（已实现后放弃）。** 这是一条负结果，值得写下来：
  - 中转站之间没有统一的路径约定。实测的那家只有 `/v1/messages` 与 `/v1/chat/completions`
    是 API，`/` 与 `/chat/completions` 返回 `200 text/html`。「用户填的是根地址还是完整
    端点」做成开关后，两个答案都可能是错的，而错误表现是 200 + HTML，看起来像成功。
  - 为此写的按供应商类型推导路径的规则，第一条（OpenAI）就是错的。
  - 收益是「可以接便宜的中转」，成本是一套无法在不联网的情况下验证的路径推导逻辑，外加
    连接启停、模型列表拉取、thinking 开关等一串配套状态。对一个自用的内容站不成比例。
  - 本次改回官方端点后，`resolve_endpoint`、连接表、模型列表拉取全部删除。HTML 响应检测
    保留下来了 —— 它在官方端点上同样能挡住「填错地址却返回 200」这一类。

## 后果

- 换供应商密钥从「SSH + 改 .env + 重启三个容器」变成页面上两个输入框，且改完立刻生效，
  不重启。
- 新增一个必须存在的环境变量 `LLM_CREDENTIAL_MASTER_KEY`。它缺失时的失败是分裂的：
  core-api 与 ai-service 会回答「本站不能保存密钥」（保存按钮 503），而 pipeline 会正常
  启动、然后每一轮富化静默失败。因此它在 compose 里用 `${VAR:?}` 声明、在 preflight 里
  检查长度、并有一条静态断言要求三个服务都带上它。
  第一次提交只加进了本地 compose，所有门禁全绿，功能会「看起来存在但不工作」；那条静态
  断言就是为了拦住这个而补的。
- **主密钥丢失 = 已入库的密钥全部不可解**。没有恢复路径，只能用第 6 条重置回环境变量再
  重新填一次。主密钥必须离机备份。
- `generation_provider_config` 只有一行。多供应商、多环境不同配置都不在本 ADR 范围内；
  真要做需要新 ADR，因为那会改变「一个部署一套生成配置」这个前提。

## 回滚

1. `POST /api/v1/admin/models/provider/reset` 回到环境变量，行为立即等价于 V027 之前。
2. 需要彻底移除时，`DROP TABLE generation_provider_config`：该表没有任何外键指向它，
   生成侧在读不到行时本来就走环境变量。
3. 表存在但主密钥不可用时，系统按第 4 条回落，站点继续用环境变量里的密钥运行 —— 不会
   因为解不开密文而停摆。

## 日期

2026-08-19（V027 于 2026-08-18 随 v0.1.19 部署，部署时为 no-op）
