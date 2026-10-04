# 双向复验原始证据

应用源码：`096b9bbbf9c113471eda1a713f9d0c860c95a348`。历史基线：`4e512df4c65e9b94b7f210ed5483e612efb5eec1`。全部新输入为隔离合成数据；新增真人记录和付费模型调用均为0。

- `independent/execution/`：GitHub收据竞态的旧版失败、修复结果、发送前后真实进程骤停与不重发。
- `independent/research/`：未修改基线、严格来源/金标/日历反例、修复后128项定点与旧报告重放。
- `independent/operations/`：通知状态、退出码、库保护、120项最终回归和独立真实loopback链。
- `independent/ops-review/`：第二方向找到的schema和高水位缺陷；`retest/`和`OPS_REVIEW_FINAL.json`是修复后复验。
- `independent/cross-review/`：另一作者对GitHub/研究修复的56项交叉探针。
- `independent/evidence-gate/`：原矩阵假关闭及原始慢样本被摘要掩盖的复现、作者回归。
- `independent/gate-review/`：第二方向找到的浮点阈值和未归档收据漏洞；`counterchecks-repaired.log`为相同14项探针修复后结果。
- `local/`：588项Windows全量预检、45项冻结门禁复验、Node检查与6测试。实际版本、SHA和dirty按相邻收据读取。

每份旧报告只描述它自己的源hash与当时结果。中间PASS不覆盖后来发现的反例；最终冻结CI和最新独立复验优先。日志中的exit0也可能表示“探针成功记录了漏洞”，必须同时读取其accepted/expected/result字段。

`IMPORT_INDEX.json`将本机来源映射到公开副本并绑定字节/hash。原始命令可能引用忽略的var路径；在全新隔离checkout中，把对应公开副本恢复到索引中的`var/bidirectional-20261003/`路径后可按收据重放，勿覆盖已有证据。常规回归直接运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe docs/acceptance/validate_matrix.py
```

当前commit的完整复验包位于`ci/`，下载元数据与实测退出码见`CI_FINAL.json`。下载包里的source.zip只含相应提交的源码/文档；历史证据另外保存在Git，避免递归打包。

两份早期Windows错误文件可能含环境片段，仅在本机保留，公开索引只列hash/字节数/原因，不声称原文进入Git。所有数据库、运行时凭据和个人日志均不在本包。Git副本无自动到期，依赖仓库历史/备份，不是云端WORM。
