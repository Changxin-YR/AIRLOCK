# 启动配置与项目维护验证（2026-10-04）

F043：显式指定的配置路径不存在时，旧启动器会继续使用环境配置。launcher/missing-config.log记录原行为；这是原实现可复现的缺陷，exit0表示复现脚本完成，不是修复通过。

新增启动回归涵盖显式路径、默认环境兼容、环境优先级、BOM、格式/类型/读取错误脱敏与init防覆盖。launcher-final为16项通过。launcher-fixed-tests的11失败/5通过源于测试夹具全局环境被pytest写入自身标记，后改为只替换模块OS视图；失败完整保留。

independent/launcher-countercheck.log通过真实子进程验证6类错误均exit2且未创建数据库，help正常exit0；independent/targeted.log记录52项启动、证据门禁和矩阵定点检查通过。所有身份和路径为隔离合成夹具，没有真实环境凭据或已有数据库访问。IMPORT_INDEX保留原命令路径、退出码、SHA和dirty状态。

当前源冻结与完整CI结果将分别由CI_FINAL.json、源码归档和实际日志标识。原始126目标与外部条件继续按原标准验收。
