# Codex 独立验收入口

你是独立验收者，不是README润色者。先fetch main和memory/progress，读PROGRESS.md、STATE.json并核对实际main SHA。不要再次清空仓库，不要删测试/降断言来变绿，不接生产数据，不读取其他项目密钥。

## 环境

推荐Python3.13、Node22、Docker Compose；安装requirements-dev.txt。程序无需真实LLM key，前端不需要npm依赖或构建。记录实际版本与提交。上游Starlette/AnyIO弃用警告应如实记录，不能当作测试失败或偷偷忽略所有警告。

## 基础检查

```bash
python -m pip install -r requirements-dev.txt
python scripts/run_logged.py evidence/pytest.log -- python -m pytest -q --junitxml=evidence/pytest.xml
python scripts/run_logged.py evidence/frontend-check.log -- npm run check
python scripts/run_logged.py evidence/frontend-tests.log -- npm test
python -m benchmark.generate
python scripts/run_logged.py evidence/benchmark-dev.log -- python -m benchmark.evaluate --split dev --tuning --output evidence/benchmark-dev.json
python scripts/run_logged.py evidence/benchmark-test.log -- python -m benchmark.evaluate --split test --output evidence/benchmark-test.json
python -m playwright install chromium
python scripts/run_logged.py evidence/browser-native.log -- python scripts/browser_smoke.py
python scripts/run_logged.py evidence/docker-smoke.log -- python scripts/docker_smoke.py
python scripts/verify_evidence.py
python scripts/evidence_manifest.py
```

原生浏览器必须不加--bridge。缺少Docker或浏览器时标记环境受限，不能以静态配置/DOM替代品算通过。官方mcp SDK测试属于pytest必需项，不得改成skip。

## 需要独立构造的反例

未批准写、agent凭据审批、伪造approved/risk/principal、替换请求或摘要、同键不同负载、并发与重复审批、过期与重启、审批前数据/策略漂移、审计失败、执行后提交前进程退出、响应丢失后查询重试。

检查命中行与变化行不同、RETURNING、大整数、NaN/Infinity、二进制、重复列名、CTE/注释/大小写、系统表/ATTACH/扩展。验证错误响应本身可序列化且不暴露输入。

提交一个pending后产生超过100条新只读记录，确认pending仍出现在服务器筛选后的队列，不被页面本地过滤隐藏。测试切换视图的并发刷新、表单状态、错误信息和移动端。

必须检查目标数据、动作终态与原始审计三者，而不是只有HTTP状态码。验证HMAC包含seq/action归属，并保留无外部锚点无法检测尾部截断的限制。

## 部署与接口

Docker脚本只操作新建的唯一项目和测试卷。确认服务器有入口与内部网络，Agent只在内部网络；发布端口仅loopback，Agent无服务器卷、reviewer/audit环境变量、宿主文件或Docker socket。验证非root、只读根、能力位为零、无批准不写、重启后pending不自执行、批准后不自动重新播种。

官方SDK只验证所用的stdio工具子集，不是规范认证或真实模型行为评估。真实模型/具体MCP host需要操作者另行授权配置，不能找其他项目的密钥来跑。收到pending必须查询状态，拒绝后不能换键盲重试。

## 结论格式

逐条列出PASS / FAIL / NOT RUN / ENVIRONMENT BLOCKED，附命令、真实退出码、原始日志、提交和复现方法。P0：未授权执行/绑定可替换/业务与审计提交不一致；P1：核心启动、交互或可复现流程失败。先给最小复现，再修复并增加回归，最终重新跑全套。

保留未实现项：真实LLM语义评估、真人A/B、生产连接器、SSO/多人路由、多租户、学习降级、外部审计锚定、提交后自动恢复与任意工具透明代理。不得将合成样本100%写成真实危险召回率。验收完成更新memory/progress，不把本清单的期望结果当已发生事实。
