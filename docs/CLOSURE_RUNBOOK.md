# 受控接入、归档与研究闭环

当前路径是 Agent → AIRLOCK → 已注册且提供 preview/execute/receipt 契约的上游。写入必须由独立 reviewer 对原始快照批准；恢复、预算和模型建议不产生批准权限。操作步骤与反例由 `scripts/upstream_isolation.py`、`tests/test_mcp_streamable.py` 和 `scripts/live_upstream.py` 复验。研究验收另需真实参与者和授权数据。

## 身份与域名

传输响应的总截止时间覆盖 DNS、TLS、响应头和正文；慢速逐字节发送不能不断重置总时限。受控 HTTP/MCP 响应拒绝重复 JSON 字段、非有限数、无效 Unicode、过深嵌套和压缩正文。Streamable HTTP 的 SSE 支持 LF、CRLF、CR 及跨字节分段。未知结果仍查询原动作，不换键重发。

`AIRLOCK_OIDC_FILE` 指向 `configs/oidc.example.json` 的本机副本。管理员从可信身份系统取得公开 RSA JWKS（至少 2048 位），保存到 `jwks_file`；服务不跟随令牌的 jku/x5u，也不联网动态信任新签名密钥。令牌须符合 RFC 9068 access-token profile：RS256、typ=at+jwt、精确 issuer/audience、sub/exp/iat/jti/client_id、有效期不超过配置上限。支持公共签名密钥轮换和 jti/主体撤销；每次请求重读配置。身份系统颁发令牌、交互式登录及生产部署尚需项目真实 IdP 配置。

主体只映射 `agent:demo` 或已配置 reviewer。`AIRLOCK_REVIEWER_FILE` 中审核账户的 `credential_env` 可省略以只允许 OIDC；工具、资源、风险、active 路由仍由服务端指定。令牌 claims 中的 role/scope 不能扩大权限，OIDC 不映射 operator；独立 operator token 继续掌管策略、审计密钥与运维接口。浏览器现有凭据输入支持 access token，token 只留页面内存。

上游域名必须配置 `pinned_addresses`。连接前核对所有 DNS 回答均在管理员批准集合内；实际连接使用验证后的 IP，同时保持原始 Host、TLS SNI 和证书域名校验。`tls_ca_file` 可指定组织 CA。重定向、环境代理、混合 metadata 地址或 DNS 越界均失败关闭。公网只允许 HTTPS；隔离测试私网 HTTP 需显式 `allow_private_network=true` 和精确私网 pin，生产非可信网络应使用 TLS。Agent 不得得到上游凭据或进入目标网络。

## MCP 与恢复

`transport=mcp_streamable` 支持已协商的 2025-06-18/2025-11-25 版本、初始化会话、SSE 分片、进度通知、固定工具发现和结构化收据。`mcp_json` 保留无会话 JSON 模式。每次受控阶段会话独立建立，终止会话为 best effort，终止失败不重发写入。每响应上限 16 KiB、阶段总预算 10 秒；未知结果读取原 action 收据。服务端主动请求、session 替换、错误 id、缺失工具或缺少契约均阻断。入站 AIRLOCK `/mcp` 仍是声明的无会话协议子集，不宣称完整 MCP host 认证。

```sh
python scripts/docker_smoke.py
python scripts/upstream_isolation.py
python scripts/live_upstream.py --provider-config configs/deepseek-flash.example.json --ledger var/deepseek-continuation-ledger --output evidence/live-upstream.json
```

最后一个命令会使用模型预算，只能在明确授权后运行；复用同一个持久 ledger。网络检查使用一次性容器：Agent 单独内网、上游单独内网且无宿主公开端口，AIRLOCK 跨两网；从 Agent 实测上游 DNS 与直接 IP 都不可达。脚本中的 reviewer 是测试自动化。

## 审计独立保存与运维

先用 `scripts/audit_checkpoint.py` 从 operator 接口取检查点，再由独立保管者运行归档 CLI。保管者只读取 `AIRLOCK_ARCHIVE_ACCESS_KEY`、`AIRLOCK_ARCHIVE_SECRET_KEY`，不回退 AWS 默认配置。归档需安装 `requirements-archive.txt`；服务器基础运行依赖不包含 boto3。

```sh
python scripts/archive_checkpoint_s3.py --help
python scripts/build_archive_fixture.py --output evidence/archive-image.json
python scripts/archive_integration.py --output evidence/archive-integration.json
python scripts/operational_check.py --url http://127.0.0.1:8000 --output evidence/operations.json
```

归档CLI在联网前排他预留并同步输出文件。已有输出路径会在上传前拒绝；若中断后留下reserved/unknown_if_interrupted，应先检查远端版本并保留预留文件，不能直接重传。

归档验证同时绑定桶、精确版本、对象路径、SHA256、数据库实例和序号，并检查当前保留期仍有效。过期收据不能证明当前不可变保管：验证报错且不会自动续期、重传或修改对象。真实保管者应在到期前安排另行授权的续期或新归档，并保留历史收据；checkpoint 的 HMAC 仍须用独立保留密钥核对。

S3 桶必须启用版本控制与 Object Lock；写入 COMPLIANCE 保留期并回读版本、hash、retention。收据绑定具体版本；新版本不替代原收据。取回检查点后以独立保留密钥与 `AIRLOCK_AUDIT_ANCHOR_FILE` 验证数据库链。测试从 MinIO 官方归档仓库固定提交 7aac2a2c5b7c882e68c1ce017d8256be2feea27f 构建一次性镜像（需 Go 1.24.8），记录源码/二进制/image hash；[官方仓库](https://github.com/minio/minio)已转源码分发，旧 DockerHub 镜像不可公开拉取。删除、缩短保留、降级锁定均必须被服务实际拒绝；它证明 API 契约，临时容器删除后不提供永久归档。真实云账户、独立保管权限、长期保留和灾难恢复仍需实际部署。重复上传相同检查点若返回条件冲突，保留原收据再执行 verify，不绕过条件写入。

`GET /v1/operations/health` 和 `/v1/operations/prometheus` 仅 operator 可访问，返回审计损坏、待处理过期积压、远端长期未知、遥测队列压力/丢弃；检查为只读。CLI 有告警退出 2，正常退出 0，通知失败退出 3，身份/网络/响应未知退出 4；未知不发送恢复通知，适合现有运维调度器接入。检查本身不重试效果或批准请求。

`GET /v1/audit/export?after=0` 先按 reviewer 路由过滤，再用固定白名单产生摘要；支持分页，不导出 SQL、样本、原始身份或自由文本。每次导出随机化 action 代号，原审计不变。序号、状态和数量仍可见；分享前需核对用途。脱敏摘要不能单独验证被省略内容的 HMAC 链，须另存原始审计与检查点。

## 研究数据到验收

```sh
python scripts/research_pipeline.py --output evidence/research-pipeline
python -m benchmark.closure --output evidence/annotation-pack prepare cases.jsonl
python -m benchmark.closure --output evidence/evaluation.json evaluate cases.jsonl --predictions predictions.jsonl --annotations labels.jsonl --adjudications adjudications.json
python -m benchmark.closure --output evidence/study.json study --tasks tasks.json session-a.json session-b.json
python -m benchmark.closure --output evidence/governance.json governance authorized-records.json
```

首次命令是完整工具演练：两个合成族、一个 GitLab 第一方事故启发的受限重构，均为作者候选标签；source notes 保存在 Git。真实标签模板留空，不能把模板算作人。prepare 冻结家族与来源 hash；evaluate 要求预测精确覆盖、恰好两位独立标注者、四类分歧仲裁，κ 在仲裁前计算。test/holdout 禁用于 tuning。身份/授权声明仍需研究者核实。

危险识别指标只使用独立 `predicted_dangerous`；安全闸门送审/阻断另报保护率和额外审批率。合法写入被送审不再算模型危险识别；未知语义预测明确列覆盖率。影响 ±5% 报告保留覆盖率、零影响反例和分母。缺标签时 acceptance_metrics=null，不能靠工具运行成功宣布科研达标。

研究任务可包含 `check={"question":"…","options":["…","…"],"answer":"…"}`。审批决定后单独显示理解题，决定耗时不包含回答理解题的时间。导出绑定任务文件 SHA；分析器依据任务文件重算正确率和理解率，automation 排除。真实任务金标保密、受控研究环境与参与者独立性需研究者安排，前端文件无法防参与者主动阅读答案。治理指标只接收声明授权的真实日志，按参与者/日期/任务去重，单列任务质量差异、零分母、日均审批与归并率。
