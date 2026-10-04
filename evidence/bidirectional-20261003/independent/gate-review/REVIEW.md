# 证据门禁跨作者复验

范围：只读复验 `docs/acceptance/validate_matrix.py`、`scripts/verify_evidence.py` 中新增 `verify_latency`，以及两份作者测试。未编辑这些文件。所有反例在内存或本目录下的临时私有目录构造，没有修改任何原始交付证据。

## 发现

1. **数值阈值仍读取摘要。** 原始 p95 恰好为 100ms/300ms/5000ms 时，将相应摘要 p95 改成 `math.nextafter(limit, 0)`，摘要与原始值的容差比较通过，旧阈值读取摘要会将本该失败的原始数据放行。三个独立手算边界均复现。
2. **未归档收据可伪装冻结依据。** G1 可替换为仓库其他目录内的伪造 `.log` 和复制 clean/SHA 字段的 `.log.status.json`，并同步 commands/evidence，旧校验通过。此时从未执行新 command，也没有 manifest hash 绑定。保持文件在仓库内，确认不是路径越界问题。

第一轮 `counterchecks.log` / `.status.json`：exit 1，14 个探针中 10 个符合预期，4 个反例错误放行。作者原 36 项测试在此状态通过（`author-tests.log` exit 0），因此以上两类遗漏由跨作者反例新增发现。

主代理修复：严格阈值从原始数据重新计算 p95；当前冻结 PASS 依据要求收据和原始日志同时命中当前 CI manifest 并通过 hash。历史/异目录支持证据不能单独建立冻结 PASS。

## 原脚本复验

`counterchecks-repaired.log` / `.status.json`：exit 0，原 14 个探针全部符合预期。

- 两个正常对照：原始完整矩阵、原始 latency 报告均通过，没有误拒。
- 12 个负向探针：原始样本缺失、摘要缺失、样本改值、NaN、诚实报告的超限样本、三个严格边界、矩阵原始日志缺失、command 错配、receipt 缺失、异目录伪造冻结依据全部拒绝。
- 修后作者 36 项测试通过，`author-tests-repaired.log` exit 0。
- 新增建议回归草稿 `test_gate_regressions_draft.py` 独立运行 4 passed，`draft-tests.log` exit 0。草稿包含 3 个自足手算边界及 1 个异目录伪造收据，可由主代理采用至原测试归属文件。

基线 HEAD `4e512df4c65e9b94b7f210ed5483e612efb5eec1`，所有检测发生在并发 dirty 工作区，不能声称旧 HEAD 已包含修复。每次独立探针日志记载 HEAD、dirty 文件清单和四份源文件 SHA256。修后 validator hash：`48b05970c450b7ad28c32acc0552f89271bcdec8b9edebd77ecec445c274ca02`；verifier hash：`e01c034b4e50786cd4f88799ed9f97b090c5002948491d549e4660f55164e4be`。

本结果是 **结构、来源绑定与数值一致性 PASS**，不构成真实功能、模型、业务、双人标注或真人 A/B 验收。对被授权修改 manifest 和全部证据的人，hash 自洽本身也不是独立真实性证明；主流程仍需冻结 source SHA、实际运行并核验 CI/归档来源。正式外部实验未运行，不能因门禁通过关闭外部条件。

所有证据仍只在本机 Git 忽略目录，无永久保留承诺；未执行任何付费 API、外部任务或 Git 提交。
