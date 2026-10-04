# Codex 独立验收入口

你是独立验收者，不是README润色者。先fetch main和memory/progress，读PROGRESS.md、STATE.json并核对实际main SHA。不要再次清空仓库，不要删测试/降断言来变绿，不接生产数据，不读取其他项目密钥。

## 环境

推荐Python3.13、Node22、Docker Compose；安装requirements-dev.txt。确定性审批无需真实 LLM key；Next.js 审批台需要 npm ci 与 npm run build。记录实际版本与提交。上游Starlette/AnyIO弃用警告应如实记录，不能当作测试失败或偷偷忽略所有警告。

SQLite先执行 `python -m airlock.sqlite_runtime --pin-file configs/sqlite-runtime.json`，正式CI/Docker必须实际加载固定3.53.1/source ID。Linux构建与链接命令以`.github/workflows/ci.yml`为准；完整CI证据包还必须包含`sqlite-runtime-build.log`、`sqlite-runtime-linked.log`及各自JSON/真实退出收据。未确认运行时在打开持久WAL前拒绝；不得为运行旧环境删库或降级同步。

## 基础检查

```bash
python -m pip install -r requirements-dev.txt
npm ci
python scripts/run_logged.py evidence/next-build.log -- npm run build
python scripts/run_logged.py evidence/npm-audit.log -- npm audit --omit=dev
python scripts/run_logged.py evidence/pytest.log -- python -m pytest -q --junitxml=evidence/pytest.xml
python scripts/run_logged.py evidence/acceptance-matrix.log -- python docs/acceptance/validate_matrix.py
python scripts/run_logged.py evidence/frontend-check.log -- npm run check
python scripts/run_logged.py evidence/frontend-tests.log -- npm test
python -m benchmark.generate
python scripts/run_logged.py evidence/benchmark-dev.log -- python -m benchmark.evaluate --split dev --tuning --output evidence/benchmark-dev.json
python scripts/run_logged.py evidence/benchmark-test.log -- python -m benchmark.evaluate --split test --output evidence/benchmark-test.json
python -m playwright install chromium
python scripts/run_logged.py evidence/browser-native.log -- python scripts/browser_smoke.py
python scripts/run_logged.py evidence/browser-edges.log -- python scripts/browser_edges.py
python scripts/run_logged.py evidence/pilot-browser.log -- python scripts/pilot_browser.py
python scripts/run_logged.py evidence/docker-smoke.log -- python scripts/docker_smoke.py
python scripts/run_logged.py evidence/container-integrations.log -- python scripts/container_integrations.py
python scripts/run_logged.py evidence/dependency-audit.log -- python -m pip_audit -r requirements.txt --format json --output evidence/dependency-audit.json
python scripts/run_logged.py evidence/latency.log -- python scripts/measure_latency.py --samples 60 --output evidence/latency.json
python scripts/run_logged.py evidence/ablation.log -- python -m benchmark.ablation --split test --output evidence/ablation.json
python scripts/run_logged.py evidence/study-analysis.log -- python -m benchmark.research --output evidence/study-analysis.json study evidence/study-automation.json
python scripts/run_logged.py evidence/comparison.log -- python scripts/demo_comparison.py --output evidence/comparison.json
python scripts/verify_evidence.py
python scripts/evidence_manifest.py
```

原生浏览器必须不加--bridge。缺少Docker或浏览器时标记环境受限，不能以静态配置/DOM替代品算通过。官方mcp SDK测试属于pytest必需项，不得改成skip。

## 需要独立构造的反例

未批准写、agent凭据审批、伪造approved/risk/principal、替换请求或摘要、同键不同负载、并发与重复审批、过期与重启、审批前数据/策略漂移、审计失败、执行后提交前进程退出、响应丢失后查询重试。

检查命中行与变化行不同、RETURNING、大整数、NaN/Infinity、二进制、重复列名、CTE/注释/大小写、系统表/ATTACH/扩展。验证错误响应本身可序列化且不暴露输入。

提交一个pending后产生超过100条新只读记录，确认pending仍出现在服务器筛选后的队列，不被页面本地过滤隐藏。测试切换视图的并发刷新、表单状态、错误信息和移动端。

必须检查目标数据、动作终态与原始审计三者，而不是只有HTTP状态码。验证 HMAC 的 seq/action 归属、key-id 轮换与检查点之前的截尾；检查点之后的尾部和全部密钥失陷边界保留。

## 部署与接口

Docker脚本只操作新建的唯一项目和测试卷。确认服务器有入口与内部网络，Agent只在内部网络；发布端口仅loopback，Agent无服务器卷、reviewer/audit环境变量、宿主文件或Docker socket。验证非root、只读根、能力位为零、无批准不写、重启后pending不自执行、批准后不自动重新播种。

官方 SDK 验证所用的 stdio 与无会话 Streamable HTTP 工具子集，不是规范认证或真实模型行为评估。真实模型/具体MCP host需要操作者另行授权配置，不能找其他项目的密钥来跑。收到pending必须查询状态，拒绝后不能换键盲重试。

## 结论格式

逐条列出PASS / FAIL / NOT RUN / ENVIRONMENT BLOCKED，附命令、真实退出码、原始日志、提交和复现方法。P0：未授权执行/绑定可替换/业务与审计提交不一致；P1：核心启动、交互或可复现流程失败。先给最小复现，再修复并增加回归，最终重新跑全套。

逐项检查剩余缺口：真人 A/B、真实多来源金标、生产连接器、SSO/OAuth、多租户、外部 WORM 和任意工具透明代理。范围路由、真实 DeepSeek 合成实验、独立补偿审批、检查点与安全 shadow 治理已实现；任何恢复/预算/模型建议均不能自动批准。不得将合成样本100%写成真实危险召回率。验收完成更新memory/progress，不把本清单的期望结果当已发生事实。
