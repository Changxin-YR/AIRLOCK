# Verification ledger

此页记录验证边界，原始日志优先。初版核验时间2026-09-30。

## 本地已执行

- Python真实SQLite集成、授权/审批/事务/漂移/重启/响应丢失测试；具体数量由`Evidence/*/pytest.xml`确定。
- 实际MCP1.30.0 stdio客户端服务端、网关与执行器HTTP进程：工具列举、读取、待审批、独立批准、6条记录修改。
- 子进程目标提交后立即退出；新进程查回执恢复，目标回执一条，无二次效果。
- Vue TypeScript检查与Vite生产构建。
- 200合成策略案例，150个可预检案例与独立逻辑参考结果比较。禁止把这些称为真实安全准确率。

## 独立CI门禁

`.github/workflows/verify.yml` 会运行上述全部、本机安装Chromium的Playwright端到端、Docker实际网络/卷/权限隔离、依赖审计。以对应提交的Actions完成结果为准。截图必须从运行应用产生，并人工检查桌面和390×844移动屏；不能以构建成功替代视觉验收。

当前开发工具的浏览器访问本地地址返回 `ERR_BLOCKED_BY_ADMINISTRATOR`；未修改浏览器安全策略绕过，改在独立GitHub runner验证。开发容器未安装Docker，Compose门禁同样通过独立runner执行。

## 明确未测/未做

- 真实DeepSeek模型API：NOT_TESTABLE，没有提供API key；fixture/provider模拟测试不计live。
- 用户对照实验：NOT_CONDUCTED，真实参与者0；没有决策耗时改善结论。
- 公网生产部署、TLS终止与灾备恢复、更多数据库或MCP客户端、独立红队与第三方审计：未验收。
- 压力下吞吐/大规模任务公平性：未测；当前是小数据集顺序执行的个人作品。

Codex应重新运行而不是照抄本页。后续补齐结果时保留提交SHA、运行URL、原始数据及已知失败，不掩盖历史问题。
