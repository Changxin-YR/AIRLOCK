# 启动前诊断与数据保护验收（2026-10-04）

本轮源码 `7dcea8ab94b60753391e0d90a73179684fc39fe1`，修改前基线 `f27b447e268209a8b8f480111e55a3f6bb1bedce`。新增本地 `doctor` 预检，修复 F044—F046；原始 126 项目标、服务端批准下限和外部验证条件保留。

## 原始复现与反例

- `local/independent/`：从 Git 基线导出的源码及隔离复现。非法 TTL / Origin 端口的子进程 exit1 且异常含合成输入；非法 CSP 报错前已创建并播种 1206 行新库。外层 exit0 表示预期问题被复现，不表示应用通过。缺控制台但 `/healthz` 为 200 是存活与就绪的区别，API-only 行为继续支持。
- `local/author-diagnostics/`：预检作者测试。最后 59 项通过，exit0；此前版本记录保留。
- `local/independent-retest/`：另一实现者的真实子进程、库访问保护、静态路径和原生浏览器反例。`first` 为 5 failed / 21 passed / 3 环境受限，其中一项来自浏览器测试调用方式；修正夹具后 `first-corrected` 仍为 4 failed / 24 passed / 1 环境受限，确认 CRLF/CR 哈希问题。修复后 `repaired` 为 28 passed / 1 Windows 文件符号链接环境受限，exit0。未降低原业务断言；目录链接与根目录链接已通过。Linux CI 的三个真实符号链接测试另行强制验收。
- 浏览器原始 `browser-crlf.json` 记录：原文 CRLF 哈希下内联脚本被 CSP 拦截；按浏览器归一化 LF 计算哈希后脚本实际执行。预检随后采用同一解释，并拒绝 NUL。
- `local/full-preflight.*`：修改中全量 793 passed、exit0；`local/final-targeted.*` 为最终未提交定点 142 passed / 3 Windows 环境受限。源码/dirty 状态保持原值。
- `local/continuation/frozen-targeted.*`：冻结源码的定点复验 142 passed / 3 Windows 符号链接环境受限、exit0。修复后独立应用快照中的 82 个文件另已与冻结工作区逐哈希比对一致。

## 证据边界

`IMPORT_INDEX.json` 将 120 份原文件映射到公开副本，保留字节、SHA256 和原路径。完整冻结 CI 与下载后复核见 `CI_FINAL.json`、`ci/`；最新 126 项记录位于 `docs/acceptance/COMPLETION_MATRIX.json`。`DOCUMENT_BINDINGS.json` 绑定交付文档；`ARCHIVE_MANIFEST.json` 绑定本目录载荷。

doctor 不启动服务、不修改环境、不打开持久数据库、不读取可选集成文件或请求网络；本地 PASS 不证明真实身份、远端服务、已有业务库或生产就绪。应用启动时，只要已安装控制台入口或 CSP，就在 Gate 初始化前校验；完全未安装仍可 API-only 启动。

本轮模型 API 新调用 0、真人研究完成 0。所有本地验证均使用合成配置及一次性测试数据。个人日志、真实凭据、数据库和本机临时目录不打包。Git 副本无自动到期，依赖仓库历史和备份，不是 WORM；Actions 副本有独立到期时间，详见元数据及 `docs/acceptance/EVIDENCE_RETENTION.md`。
