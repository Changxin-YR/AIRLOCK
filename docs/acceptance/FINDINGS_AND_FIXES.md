# 审查发现与修复记录

审查基线：`704b5035cf69f9a6c40c44eecd84c0d0741de849`。本轮修复与复验由同一执行者完成；独立反例指相对原测试新增的反例，不代表作者与评审者独立。

| ID | 严重度 | 最小复现与修复前证据 | 根因与修复 | 复验 |
|---|---|---|---|---|
| F001 | P1 | Windows 原生 Chrome 打开 `/`，body 为空；`baseline/blank-console.json`、`blank-console.png` | 主机 MIME 注册表将 `.js` 映射为 `text/plain`；`ConsoleAssets` 显式设置 JS/CSS/HTML 响应类型，保持 nosniff | `test_console_javascript_mime_survives_host_registry`；`fixes/browser-native.log` 的 10 项真实浏览器流程通过 |
| F002 | P1（验收门禁） | `baseline/evidence-counterexample.log`：含额外失败 JUnit、缺少截图、不完整逐例结果的合成包被校验器以 0 接受 | 只验证少数用例名字及汇总字段；改为检查全部失败/error/skip、必需截图、原始语料哈希及逐例重新计算阈值；显式异常在 `python -O` 下仍生效 | `tests/test_evidence_gate.py` 的故意失败、优化模式和伪造汇总反例 |
| F003 | P1（Windows 验收路径） | `baseline/pytest.log`：87 pass/1 fail，stdio 子进程 TLS 初始化失败 | 最小环境遗漏 Windows `SYSTEMROOT`；补系统变量白名单，不继承 reviewer/audit 凭据；MCP 显式 UTF-8 输入输出 | 原失败测试通过，并增加中文/emoji 跨进程往返 |

证据目录前缀：`evidence/full-audit-20261002/`。本轮 Docker 原状退出码 1：`auth.docker.io` 基础镜像认证连接超时，属于 `BLOCKED_ENV`，不是容器隔离通过。保留 Starlette/AnyIO 上游弃用 warning。

修复阶段 Python 95 项通过，原生浏览器 10 项通过；这些是中间工作树结果，最终验收必须重新绑定冻结提交。当前审查未复现未授权业务副作用；后续新适配器仍需单独反例和复验。
