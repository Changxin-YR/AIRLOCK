# 审查发现与修复记录

审查基线：`704b5035cf69f9a6c40c44eecd84c0d0741de849`。本轮修复与复验由同一执行者完成；独立反例指相对原测试新增的反例，不代表作者与评审者独立。

| ID | 严重度 | 最小复现与修复前证据 | 根因与修复 | 复验 |
|---|---|---|---|---|
| F001 | P1 | Windows 原生 Chrome 打开 `/`，body 为空；`baseline/blank-console.json`、`blank-console.png` | 主机 MIME 注册表将 `.js` 映射为 `text/plain`；`ConsoleAssets` 显式设置 JS/CSS/HTML 响应类型，保持 nosniff | `test_console_javascript_mime_survives_host_registry`；`fixes/browser-native.log` 的 10 项真实浏览器流程通过 |
| F002 | P1（验收门禁） | `baseline/evidence-counterexample.log`：含额外失败 JUnit、缺少截图、不完整逐例结果的合成包被校验器以 0 接受 | 只验证少数用例名字及汇总字段；改为检查全部失败/error/skip、必需截图、原始语料哈希及逐例重新计算阈值；显式异常在 `python -O` 下仍生效 | `tests/test_evidence_gate.py` 的故意失败、优化模式和伪造汇总反例 |
| F003 | P1（Windows 验收路径） | `baseline/pytest.log`：87 pass/1 fail，stdio 子进程 TLS 初始化失败 | 最小环境遗漏 Windows `SYSTEMROOT`；补系统变量白名单，不继承 reviewer/audit 凭据；MCP 显式 UTF-8 输入输出 | 原失败测试通过，并增加中文/emoji 跨进程往返 |

| F004 | P1（受影响依赖与 Windows 静态文件边界） | 增量阶段 `fixes/dependency-audit-before-upgrade.json` 发现 Starlette 0.50.0 已知问题，包括 UNC 解析前外连风险 CVE-2026-48818；报告存在同一漏洞的别名重复，不能按条目数声称已复现等量攻击 | 固定 FastAPI 0.142.2 / Starlette 1.7.0 / Pydantic 2.13.5；`ConsoleAssets.lookup_path` 在 filesystem resolution 前拒绝 UNC/反斜杠 | `test_static_unc_path_rejected_before_filesystem_resolution` 验证没有进入危险解析；最终 `dependency-audit.log.status.json` 为 0。未向真实 SMB 主机发送凭据 |
| F005 | P2（新增 UI 移动布局） | 新增五个导航项后 390px 视口横向溢出 | 小屏导航换行、按钮保持可点击宽度 | `final/browser-report.json` mobile no-overflow；原生移动截图已人工查看 |
| F006 | P1（新功能审批绑定的防回归） | 独立改写 pending TTL 的反例要求拒绝；旧摘要字段不充分覆盖过期时间和自身版本 | `Gate._digest` 纳入 action ID、expires_at 和版本，执行前重算 | `test_new_boundaries.py` 的 TTL 替换反例；151 项全套通过 |
| F007 | P2（指标可读性） | `final/console-metrics.png` 中静态规则等名称受到通用 45px 首列样式影响而断裂 | `governance.js` 为指标表设独立 class，CSS 自适应首列并保留阶段名称 | `final-ui/` 原生浏览器复验，修复提交 `b9de71085e9b3027b8127c4da6d7193d8f19ba88` |

证据目录前缀：`evidence/full-audit-20261002/`。本机 Docker 原状及最终退出码均为 1：`auth.docker.io` 基础镜像认证连接超时，属于 `BLOCKED_ENV`，不是本机容器隔离通过。Linux CI run 36986102382 在相同核心代码 SHA 上真实运行 Docker 与最终证据门禁并成功。最终 pytest 保留 Starlette TestClient 的 httpx 弃用 warning，未统一屏蔽。

修复阶段 Python 95 项通过、原生浏览器 10 项通过，是中间工作树结果。冻结核心提交 `266ad9e9daedcbfd5183f0402d1d5227f4a2a0b4` 后，Python 151 项、JS 6 项、原生浏览器 14 项通过。最终 UI 样式提交另有 `final-ui/` 收据，不能将中间结果改称最终运行。

本轮增量补齐了 C1—C12 对应的受控 HTTP 上游、CEL/YAML、独立补偿审批、模型建议 provider、路由、预算/批量、shadow 建议、研究工具和指标。新增独立反例覆盖路由撤销、预算并发、新组成员、时钟倒退、模型非法 schema、远端已生效但响应/审计失败后重启对账等，详见逐项矩阵的 test_ids。新功能的加固项与历史基线缺陷分开描述。

CI run 36986618577 的 `intentional-negative-control` 子进程退出 23，GitHub 作业及整次 run 为 failure，正常 verify 作业 success。该临时作业在 `90bbbfb` 删除，历史日志保留。这证明实际失败传播路径，没有跳过原有检查来恢复正常状态。

当前已测边界内未发现仍未修复、可复现的 P0/P1；这不是对未实现适配器、生产部署或真实模型行为的安全认证。未完成的原目标仍列为 PARTIAL/受阻，不因本结论关闭。
