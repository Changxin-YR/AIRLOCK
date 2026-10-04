# 独立反例与诊断

这些脚本、JSON与退出收据保留原始运行状态。`tracked_source_dirty=true`表示提交前实验，不替代最终冻结提交的CI。

- GitHub探针：24个并发申请只有一次send；错误回读不能完成收敛。
- `profile_read_connections`：固定种子、每臂60例，本机Windows诊断；旧两连接与诊断连接复用均保留两次FULL提交。它用于定位可避免的连接/checkpoint成本，不能证明所有Linux尾延迟异常由同一原因造成。
- `guard_before_database_probe`：用安全SQLite3.53.1覆盖版本查询来触发“旧版本”拒绝，观察旧顺序先打开现存WAL再关闭，会使其checkpoint。没有复现数据损坏。
- `guard_before_database_fixed_probe`：Store/GitHub各自对现存WAL及全新路径共4例；仅打开内存连接，持久文件的存在性及全部字节不变。

原始收据中的命令从`var/security-review-20261003/`执行。重放时把所需脚本复制到新的`var/<独立目录>/`再运行，保留相同目录深度，并使用新输出；原文件相对路径由此可解析项目根。不要覆盖这些已归档结果。最终可直接运行的回归在`tests/test_connection_lifecycle.py`和`tests/test_sqlite_runtime.py`。
