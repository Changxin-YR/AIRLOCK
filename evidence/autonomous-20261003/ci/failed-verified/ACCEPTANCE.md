# 可复现验收记录

这份文件记录已验证的运行基线，不声称包含它自身的未来提交自动通过。最新main SHA和最终交付run由独立memory/progress/STATE.json锚定；任何后续代码变更都应重跑。

## 冻结运行基线

- commit：031489dab7405b8b0fbbb4cec98ad3fdd63dee5f
- root tree：72b33f35727f88ee263e47e2f71f4a39fc18a594
- GitHub Actions run：36964992992，conclusion success，2026-10-02 UTC
- artifact：11209193688（acceptance-evidence）
- 完整artifact SHA256：385d2eaa2607d0d06cf3ecedf094bfbb217d7898abe000cb35bcde9062ed9a1f
- run：https://github.com/Changxin-YR/AIRLOCK/actions/runs/36964992992

已下载原始artifact并核对SHA256；逐项核对manifest所列文件哈希和7份命令退出收据均为0。也比对了最终修复的service/api/app/browser/verify_evidence/队列测试源码与CI的source.zip一致，不只相信网页状态。

## 实际结果

| 项目 | 结果与证据 |
|---|---|
| Python | 88 passed，1条上游弃用warning；pytest.log + pytest.xml |
| 官方MCP Python SDK | 包含在88项内；初始化、发现、pending、独立审核、状态和余额读回 |
| JavaScript | 6项通过；frontend-tests.log，语法检查单独通过 |
| 原生浏览器 | native_browser_e2e，10项检查，无脚本错误；包含105条新只读历史后的pending可见性 |
| 真实Docker Compose | 命令exit_code=0；报告包含非root/只读/零能力、凭据与卷边界、不能伪造审批、网络与loopback端口、重启持久 |
| 数据断言 | 独立批准前1206行；批准演示删除并重启后0行，没有自动重播种；审计校验通过 |
| 合成回归 | dev120/test80；test三态80/80、只读误报0/30、支持写入影响20/20 |

运行环境：runner Python3.13.15、SQLite3.45.1；mcp1.26.0、Playwright1.57.0、pytest9.0.2。完整依赖版本在manifest.json。唯一pytest warning是Starlette引用AnyIO已弃用的BlockingPortal别名，未隐藏，也不是功能测试失败。

测试集内部评估p95本次为11.002ms，静态0.1ms、预演10.343ms，仅为当前1206行合成库与该runner上的内部计时；不包含最终持久化/提交、HTTP与人工等待，不能外推生产性能。

## 必须保留的失败与修复历史

1. 0433671 / run36963123248：GitHub曾显示success，但Docker原始日志启动超时，没有docker-report。tee管道掩盖子进程失败，因此这一轮不能视为整体通过。
2. 6544e63 / run36963919651：引入真实退出码收据与产物门禁后，正确显示failure。日志证实容器healthy而宿主PORTS为空。
3. 525ea8f / run36964267162：服务器改为ingress+protected，Agent仍仅protected；84项Python、原生浏览器和Docker受控隔离通过。
4. 031489d：修复只读历史挤掉pending，以及非有限JSON错误响应；新增测试后88项Python、10项native及其他严格门禁通过。

后续必须继续用run_logged返回真正退出码，不能为了日志显示方便改回可能吞错的管道。manifest不是验收证明，必须核对内容与状态。

## 未验证/未实现

真实LLM业务行为、真人A/B（n=0）、生产数据库/远端副作用、SSO/多人路由、多租户、学习型自动降级、外部审计锚定、提交后恢复和任意工具透明代理。官方SDK与容器smoke只证明所测子集，不是全面规范/安全认证。
