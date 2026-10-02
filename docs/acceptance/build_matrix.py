"""Rebuild the review ledger from explicit per-target judgments and raw receipts.
PASS is restricted to each row's scope; an external dependency is never inferred
from successful tooling. This is bookkeeping, not an autonomous semantic audit.
"""
from pathlib import Path
import json
import xml.etree.ElementTree as ET
from collections import Counter

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'evidence/full-audit-20261002'
FINAL=BASE/'final'
SHA=(FINAL/'commit.txt').read_text(encoding='utf-8-sig').strip()
INDEX=json.loads((ROOT/'docs/acceptance/AIRLOCK-acceptance-targets.json').read_text(encoding='utf-8'))
JUNIT=list(ET.parse(FINAL/'pytest.xml').iter('testcase'))
RECORDS={}


def row(id,implementation,verification,scope,missing,files,tests='',logs='pytest',result=None):
    RECORDS[id]=dict(implementation_status=implementation,verification_status=verification,scope=scope,
        uncovered_scope=missing,code_references=files.split(),test_modules=tests.split(),log_names=logs.split(),
        actual_result=result or scope)


I='IMPLEMENTED';P='PARTIAL';M='MISSING';PASS='PASS';EXT='BLOCKED_EXTERNAL';NOT='NOT_RUN'
row('G1',I,PASS,'本地个人项目可运行；Linux CI 真实容器，成本/依赖边界已写明。','不代表生产部署或实际付费模型成本。','README.md docs/OPERATIONS.md','test_sdk_interop test_gate', 'pytest browser-native dependency-audit')
row('G2',I,PASS,'简历描述绑定实际代码路径和合成证据。','用户本人是否能独立复现需实际演示。','docs/INTERVIEW.md README.md','test_gate test_upstream','pytest comparison')
row('G3',I,PASS,'创新定位为服务端绑定、影响证据与治理组合；核对现有 HITL/审批实现。','没有性能横评、行业首创或外部采用结论。','docs/RESEARCH.md docs/INTERVIEW.md',logs='')
row('G4',I,EXT,'已交付 17 组问答、追问、运行命令和限制。','用户现场讲解、答辩与独立操作能力未验证。','docs/INTERVIEW.md docs/OPERATIONS.md',logs='')
row('A1',I,PASS,'本地失败回滚；远端授权执行后失联为 unknown；模型/预演失败阻断。','受信上游必须履行 CAS/收据契约；无任意外部工具保证。','airlock/service.py airlock/upstream.py airlock/semantic.py','test_gate test_new_boundaries test_semantic')
row('A2',P,PASS,'服务端身份、绑定和独立 reviewer；Linux Compose 无目标卷/审核密钥。','真实第三方上游的专有网络隔离/生产 OAuth 未验；开发 shell 不在敌对边界。','airlock/api.py compose.yaml scripts/docker_smoke.py','test_api test_routing test_gate')
row('A3',P,PASS,'request/action/trace 关联、阶段时延、原始错误与有权限的审计指标。','尚无跨上游分布式 trace collector、生产告警和真实账单对账。','airlock/observability.py airlock/service.py airlock/upstream.py','test_observability','pytest latency')
row('A4',I,PASS,'本地 exact 与上游声明值区分；备份/远端恢复未知；失败不会猜测后执行。','未实现通用估算适配器，未知受控操作阻断。','airlock/sql.py airlock/recovery.py airlock/static/review.js','test_gate test_recovery test_upstream')

row('C1.1',I,PASS,'Gate/Invocation/Decision 与框架无关；HTTP 与 stdio MCP 共用授权核心。','不含任意 Agent 框架的专用插件。','airlock/service.py airlock/models.py airlock/api.py airlock/mcp.py','test_mcp test_api test_sdk_interop')
row('C1.2',P,PASS,'官方 MCP SDK 1.26.0 实跑初始化/发现/调用/pending/批准/读回及独立 HTTP 上游；直接协议测试覆盖拒绝和错误。','官方 SDK 下的所有拒绝/错误组合和真实第三方 host 未穷尽。','airlock/mcp.py tests/test_sdk_interop.py tests/test_live_transport.py','test_sdk_interop test_live_transport test_mcp')
row('C1.3',P,EXT,'配置 allowlist 的独立 HTTP counter 服务已完成官方 SDK 至上游真实调用和收据对账。','需改连接配置并适配 pending；尚无真实第三方/模型 host 轨迹，非通用 MCP 上游代理。','airlock/upstream.py scripts/fixture_upstream.py docs/OPERATIONS.md','test_upstream test_sdk_interop')
row('C1.4',I,PASS,'协商 2025-06-18/2025-11-25；明确 Tasks 已存在，当前使用有文档的回执/查询。','没有 Tasks capability 或 MCP Streamable HTTP 服务端。','airlock/mcp.py docs/RESEARCH.md docs/OPERATIONS.md','test_mcp test_sdk_interop')
row('C1.5',P,PASS,'只允许操作者注册 literal-IP origin；拒绝私网/重定向等；入站和上游凭据分离，发现按主体过滤。','仅合成适配器，未实现域名/DNS rebinding 管理、OAuth audience 及生产第三方授权。','airlock/upstream.py airlock/access.py','test_upstream test_routing')
row('C2.1',I,PASS,'block 优先、错误阻断、支持写入审批下限不能被 pass/模型覆盖。','','airlock/policy.py airlock/service.py','test_policy test_semantic test_gate')
row('C2.2',I,PASS,'真实 cel-python 0.4.0＋安全 YAML；schema、重复键/alias 拒绝、类型及 AST/字数/规则上限。','仅文档定义的有限布尔/比较子集。','airlock/policy.py policies/example.yaml requirements.txt','test_policy')
row('C2.3',I,PASS,'内容摘要绑定；无效激活/审计失败恢复旧策略；旧 pending 随有效版本变化 stale。','','airlock/policy.py airlock/service.py airlock/api.py','test_policy test_new_boundaries')
row('C2.4',P,PASS,'规则冲突、恶意 YAML、类型/字段/表达式限制及原子重载失败反例通过。','未单独压力测试跨进程热重载；当前活跃策略为各进程内配置快照。','airlock/policy.py tests/test_policy.py tests/test_new_boundaries.py','test_policy test_new_boundaries')
row('C2.5',P,EXT,'可运行受限 CEL/YAML 示例，声明与 Envoy 的变量/函数/优先级差异。','没有 Envoy 实例/兼容测试，不宣称完全对齐。','policies/example.yaml docs/OPERATIONS.md','test_policy')
row('C3.1',I,PASS,'私有克隆预演与真实目标分离，失败/资源上限阻断；真实表无 pending 效果。','','airlock/sql.py tests/test_gate.py','test_gate test_recovery')
row('C3.2',I,PASS,'匹配/变化/返回分开；零变化、RETURNING、NULL/二进制/触发器等受限语义验证。','固定 STRICT schema，不支持的 SQL 模式拒绝。','airlock/sql.py tests/test_gate.py','test_gate','pytest benchmark-dev benchmark-test')
row('C3.3',I,PASS,'本地来源/时间/目标/schema hash/前后指纹/5 条样本和截断；上游另标声明值。','上游声明值依赖适配器事实，不是本地独立验证。','airlock/service.py airlock/upstream.py airlock/static/review.js','test_gate test_upstream','pytest browser-native')
row('C3.4',I,PASS,'摘要绑定 ID/TTL/版本/请求/策略/目标/影响；锁内复核与上游 CAS。','','airlock/service.py airlock/upstream.py','test_gate test_new_boundaries test_upstream')
row('C3.5',I,PASS,'逐适配器说明精确克隆、受信 CAS 预演与未支持执行边界。','无 Shell/通用外部服务沙箱。','docs/OPERATIONS.md airlock/sql.py airlock/upstream.py','test_gate test_upstream')
row('C4.1',P,PASS,'区分预演回滚、事务回滚、提交后补偿和独立授权；UI 说明。','尚无通用技术可逆性/业务恢复分类器，仅两个适配器的证据字段。','airlock/recovery.py airlock/static/review.js docs/OPERATIONS.md','test_recovery','pytest browser-native')
row('C4.2',I,PASS,'没有实际备份依据时保持 null/unknown；本地完整补偿快照与外部备份分开。','','airlock/sql.py airlock/recovery.py airlock/static/review.js','test_recovery test_gate')
row('C4.3',I,PASS,'删除/更新/插入后的完整合成快照补偿在独立副本演练并核对哈希/约束。','范围为固定 SQLite 合成表，不含第三方灾备。','airlock/recovery.py tests/test_recovery.py','test_recovery')
row('C4.4',I,PASS,'restore 是新动作，独立路由/审批/幂等/版本/审计；后续漂移不覆盖。','','airlock/recovery.py airlock/service.py','test_recovery test_routing','pytest browser-native')
row('C4.5',I,PASS,'可逆性、预算、模型建议均不取消写审批；硬 block 不能人工覆盖。','','airlock/policy.py airlock/service.py','test_policy test_recovery test_semantic test_governance')
row('C5.1',I,EXT,'实现可选真实 OpenAI Responses provider、strict schema、超时、持久调用/并发/估算预算限制。','无本项目授权的 key/model/价格与预算，未进行真实 API 调用；美元预占不是账单硬封顶。','airlock/semantic.py docs/OPERATIONS.md','test_semantic')
row('C5.2',I,PASS,'模型建议只可加严；不能自批或持有目标/审核权限；无效输出阻断。','','airlock/semantic.py airlock/service.py','test_semantic test_gate')
row('C5.3',P,PASS,'离线验证伪系统注释、无效 schema、缺字段、NaN/越界、超时、预算耗尽。','真实供应商限流/拒答/模型提示注入成功率未验证。','airlock/semantic.py tests/test_semantic.py','test_semantic test_gate')
row('C5.4',I,PASS,'应用结果缓存绑定主体/工具参数/模型/提示/策略/目标快照；provider cached_tokens 独立统计。','缓存失效路径依据实现及离线 scope 反例；未测真实 provider cache。','airlock/semantic.py airlock/service.py airlock/observability.py','test_semantic test_observability')
row('C5.5',I,EXT,'离线契约与真实调用分账；live=未运行、费用 null，工具不会默认联网花费。','需本项目明确授权 provider/model/key/budget 和真实 usage。','airlock/semantic.py scripts/live_agent.py benchmark/ablation.py','test_semantic','pytest ablation')
row('C6.1',I,PASS,'持久 pending/rejected/expired/stale/failed/executed/executing/unknown；批准与远端效果分开。','','airlock/service.py airlock/upstream.py airlock/store.py','test_gate test_upstream test_new_boundaries')
row('C6.2',I,PASS,'两个独立 reviewer 配置/范围路由、缺路由阻断、越权读/批拒绝、即时撤销。','非真实 SSO 或两人 quorum。','airlock/access.py airlock/api.py tests/test_routing.py','test_routing')
row('C6.3',I,PASS,'服务端 TTL、重启、时钟回退阻断；SSE 持久游标重连，客户端通知不授权。','','airlock/service.py airlock/api.py airlock/static/lib.js','test_gate test_live_transport test_new_boundaries','pytest frontend-tests browser-native')
row('C6.4',I,PASS,'同键同内容返回原收据，冲突拒绝；本地并发只执行一次；失联保留原 action。','','airlock/service.py airlock/upstream.py','test_gate test_governance test_upstream')
row('C6.5',I,PASS,'本地进程退出和审计失败原子回滚；远端租约/丢响应/审计失败后重启对账，不重发。','信任上游原子 CAS/幂等，不是分布式 exactly-once。','airlock/upstream.py tests/test_new_boundaries.py tests/test_gate.py','test_gate test_upstream test_new_boundaries')
row('C7.1',I,PASS,'影响数量/可恢复依据/主体资源优先，再命令和原 JSON；exact/上游声明/截断明确。','','airlock/static/review.js airlock/static/governance.js','test_api','browser-native')
row('C7.2',P,PASS,'实际浏览器完成登录、pending、拒绝、批准、历史/审计、批量、补偿、指标和退出。','expired/stale/failed/unknown 有真实后端测试和渲染分支，但尚未逐状态完成原生浏览器端到端复验。','airlock/static/app.js airlock/static/review.js scripts/browser_smoke.py','test_gate test_upstream','pytest browser-native')
row('C7.3',I,PASS,'真实 API 数据，草稿按 action 保存；服务端 pending 过滤、105 条历史反例。','','airlock/static/app.js airlock/api.py','test_pending_queue','pytest browser-native')
row('C7.4',P,PASS,'桌面/390px 移动原生截图，文本节点、Origin/Host/CSP、内存凭据与退出；新导航溢出已修。','未覆盖所有长文本、键盘/辅助技术及全部失败状态的原生交互。','airlock/static/style.css airlock/static/lib.js airlock/api.py scripts/browser_smoke.py','test_api test_static_paths','pytest browser-native frontend-tests')
row('C7.5',I,PASS,'首次可见＋页面可见性＋单调时钟，离开动作/指标页暂停；遥测不授权。','','airlock/static/lib.js airlock/static/app.js airlock/static/study.js','test_api','frontend-tests browser-native')
row('C7.6',I,PASS,'无 key 确定性路径可运行；角色/合成数据/未知成本提示和使用手册。','没有三秒决策或全面可访问性认证。','README.md docs/OPERATIONS.md airlock/static/app.js',logs='browser-native')
row('C8.1',I,PASS,'主体/工具/资源/策略/风险/reviewer/时间窗分组，成员明示，累计影响。','','airlock/governance.py airlock/static/governance.js','test_governance','pytest browser-native')
row('C8.2',I,PASS,'组摘要和精确成员集合/版本/TTL 绑定；新成员拒绝；累计高风险再查路由，逐成员收据。','不提供全组事务原子性；先执行项可使后续 stale。','airlock/governance.py airlock/service.py','test_governance','pytest browser-native')
row('C8.3',I,PASS,'主体/资源固定窗预算；原子预占/结算/释放，重启及并发不重置，新 ID 不免限额。','单位不是事故概率界限；固定窗不等同滑动窗。','airlock/governance.py airlock/store.py','test_governance')
row('C8.4',I,PASS,'历史生成仅显示分组窗口的 shadow 建议；operator 明确激活/期限/CAS/撤回，永不授权写。','安全修正替代原自动降级设想；没有训练授权模型。','airlock/service.py airlock/api.py','test_observability test_new_boundaries')
row('C8.5',P,EXT,'区分只读 pass、幂等收据、当前 eligible 分组折叠和实际 batch 审阅比例，未知错误/用户日为 null。','缺真实同任务质量工作负载、审批错误金标与日常使用数据。','airlock/observability.py airlock/governance.py','test_observability','pytest browser-native')
row('C9.1',I,PASS,'稳定 reason_code/action/trace、execution_occurred/重试说明及有界替代方向；错误不回显原始输入。','','airlock/service.py airlock/api.py','test_api test_mcp')
row('C9.2',I,PASS,'合成删除被真实拒绝后仍 1206 行；安全 SELECT 返回真实 1206，另路明确批准后为 0。','','scripts/demo_comparison.py scripts/demo_agent.py','test_gate','comparison')
row('C9.3',I,EXT,'有真实 provider 的有界 Agent 驱动，仅固定工具、一次写建议、无 reviewer 权限。','未获本项目授权真实模型/host；没有真实工具轨迹或真人批准继续。','scripts/live_agent.py airlock/semantic.py','test_live_agent_contract')
row('C9.4',I,PASS,'拒绝后禁止重复写；pending 查询，unknown 原收据对账；Agent 最多 8 步和单个写建议。','','scripts/live_agent.py scripts/demo_agent.py airlock/upstream.py','test_live_agent_contract test_upstream')
row('C10.1',I,PASS,'原始 evaluated 快照含模板/策略/路由/影响/相关 ID，决定与收据另记签名事件。','','airlock/store.py airlock/service.py airlock/upstream.py','test_gate test_observability test_upstream')
row('C10.2',P,PASS,'HMAC seq/action/前序绑定和篡改归属测试；当前范围审计权限。','无自动 key-id 轮换、外部截尾锚点；插入/重排全组合仍有验证缺口，离线轮换策略已说明。','airlock/store.py docs/OPERATIONS.md','test_gate test_routing')
row('C10.3',I,PASS,'本地审计失败回滚，远端已授权效果后审计失败保留 executing 可对账；按 reviewer 限制样本查看。','仅合成数据，非生产 PII/字段级脱敏系统。','airlock/store.py airlock/service.py airlock/access.py','test_gate test_new_boundaries test_routing')
row('C10.4',I,PASS,'回放原始快照而非重执行；明确没有外部不可变存证。','','airlock/static/app.js airlock/store.py','test_gate','pytest browser-native')
row('C11.1',I,PASS,'151 Python、6 JS、14 原生浏览器场景、官方 SDK、本地/远端实际效果及 Linux CI 真 Docker。','Windows Docker 镜像网络失败保留；不等同所有部署环境。','tests scripts/browser_smoke.py scripts/docker_smoke.py','test_gate test_sdk_interop test_upstream','pytest frontend-tests browser-native docker-smoke')
row('C11.2',P,EXT,'冻结旧合成回归、独立关键词、四臂/κ/研究导入和逐例工具已交付。','真实多来源数据、真实双人标签、live 三臂尚缺。','benchmark/research.py benchmark/ablation.py benchmark/evaluate.py','test_research test_benchmark','pytest benchmark-dev benchmark-test ablation')
row('C11.3',I,PASS,'真实 exit receipt、全部 JUnit 无失败/skip、图片/逐例重算/commit 绑定、完整 CI gate；独立 CI exit23 对照另存。','Actions 压缩包保存期限为 90 天，Git 原始日志与本地截图另存。','scripts/run_logged.py scripts/verify_evidence.py .github/workflows/ci.yml','test_logged_runner test_evidence_gate','pytest')
row('C11.4',I,PASS,'固定回归阈值和时延阈值在 CI 执行，151 安全/行为测试零失败；失败资料保留。','真实危险识别和真人阈值缺数据，未宣称通过。','scripts/verify_evidence.py benchmark/evaluate.py','test_evidence_gate','pytest benchmark-dev benchmark-test latency')
row('C12.1',P,PASS,'HTTP request_id、action_id、trace_id 保存至审核/执行/恢复审计，上游以 action/request hash 关联。','未向外部 collector 输出跨进程 OpenTelemetry spans。','airlock/observability.py airlock/service.py airlock/upstream.py','test_observability')
row('C12.2',P,PASS,'真实授权范围内三态、阶段分位数、队列/失败、预演、模型 usage/缓存/治理指标。','缺真实模型数据和主动 cache invalidation 计数；默认窗折叠率与可激活窗明确区分。','airlock/observability.py airlock/static/governance.js','test_observability test_semantic','pytest browser-native')
row('C12.3',I,EXT,'provider usage 与按操作者价格估算分开；模型/币种/来源/生效日、cache-read/write unknown。','没有本项目真实 usage/账单和当前授权价格表，不能做真实费用结论。','airlock/semantic.py airlock/observability.py','test_semantic','pytest ablation')
row('C12.4',P,PASS,'指标按身份范围保护、固定 labels；真实 HTTP 与直接调用配对测开销，审计故障 fail-closed。','没有外部指标 exporter 故障注入或跨上游开销测量。','airlock/observability.py airlock/api.py scripts/measure_latency.py','test_routing test_new_boundaries','pytest latency')

row('L0-1',P,EXT,'SDK、独立进程和模拟器已实测；真实 Agent 工具已实现。','真实模型/host 授权缺失。','tests/test_sdk_interop.py scripts/live_agent.py','test_sdk_interop test_live_transport')
row('L0-2',I,PASS,'pending 本地和独立远端真实目标不变，原快照持久，浏览器不授予权限。','','tests/test_gate.py tests/test_upstream.py','test_gate test_upstream')
row('L0-3',I,PASS,'独立 reviewer 批准绑定对象，官方 SDK 读取真实结果；并发/重复不双执行。','','tests/test_sdk_interop.py tests/test_gate.py','test_sdk_interop test_gate')
row('L0-4',I,PASS,'服务端到期不执行，远端响应丢失 unknown 对账，不换键盲重试。','','airlock/service.py airlock/upstream.py','test_gate test_upstream test_new_boundaries')
row('L0-5',I,PASS,'本地提交前进程死亡回滚；重启不重播种；远端已提交失联只查原收据。','','tests/test_gate.py tests/test_upstream.py','test_gate test_upstream test_new_boundaries')
row('L0-6',P,EXT,'合成拒绝和 SELECT 真替代通过，有界模型驱动无自批权。','真实模型拒绝后自主改道尚未运行。','scripts/demo_comparison.py scripts/live_agent.py','test_live_agent_contract','comparison pytest')
row('L0-7',P,PASS,'evaluated/决定/远端收据包含主体、时间、参数、策略、摘要、模板、相关 ID。','未做覆盖所有状态的正式字段完整率统计，不能直接宣称 100%。','airlock/service.py airlock/store.py','test_gate test_observability test_upstream')
row('T1',P,EXT,'合成保护覆盖和三态一致率单独报告；有真实危险标签 schema 和计算函数。','缺独立业务危险金标，≥90% 语义召回未知。','benchmark/research.py benchmark/evaluate.py','test_research','pytest benchmark-dev benchmark-test')
row('T2',P,EXT,'同一合成集支持 pass 额外拦截率 0/60，三态混淆原始行已保存。','非危险独立业务金标缺失，真实风险 FPR≤10% 未验证。','benchmark/research.py benchmark/evaluate.py','test_research','pytest benchmark-dev benchmark-test')
row('T3',I,PASS,'固定合成环境的静态分类阶段及真实 HTTP 延迟分开记录，30 写样本 p95 <300ms。','并发1与首次请求/热态；未测冷 OS 缓存和生产并发。','scripts/measure_latency.py airlock/sql.py',logs='latency')
row('T4',I,PASS,'1206行克隆/执行/差异阶段30次写样本 p95 <5s，保留所有样本与极值。','尚未覆盖每种上游/规模的性能分布。','scripts/measure_latency.py airlock/sql.py',logs='latency benchmark-dev benchmark-test')
row('T5',P,PASS,'旧冻结合成60个可预演写入按独立手工期望计数全部一致，零变化样例保留。','只有本地 exact 模式；没有估算适配器/真实多来源±5% 验证。','benchmark/generate.py benchmark/evaluate.py','test_gate','benchmark-dev benchmark-test')
row('T6',I,PASS,'同目标相同只读请求，60对随机交替，逐对增量 p95 <100ms 且另报均值。','只测本机 SQLite/HTTP，非第三方模型/网络。','scripts/measure_latency.py',logs='latency')
row('B1',P,EXT,'200例/40族合成回归完整；真实来源导入保留 source_reference/version/授权局限。','缺获授权日常 Agent 日志、可独立复现的真实事故集合；不能把报道重复计例。','benchmark/generate.py benchmark/research.py docs/RESEARCH.md','test_research test_benchmark','pytest benchmark-dev benchmark-test')
row('B2',P,EXT,'新 Case/Annotation schema 包含决策、风险、影响依据、可逆性、意图、来源、适配器、快照和 split，未知保留。','旧200条只有作者策略金标，四类真实标注和相应数据快照尚未取得。','benchmark/research.py','test_research')
row('B3',I,EXT,'双独立人标注导入、去重/两人验证、分歧和仲裁前 κ 函数及手算例通过。','真实标注者0；κ=null，无≥0.75结论。','benchmark/research.py tests/test_research.py','test_research','pytest study-analysis')
row('B4',P,EXT,'旧集按族6:4冻结，tuning拒读test；新导入拒跨split同族/重复请求，冻结不可静默替换。','旧test已公开；尚无全新独立保留集，近语义重复仍需人工核查。','benchmark/generate.py benchmark/evaluate.py benchmark/research.py','test_benchmark test_research')
row('B5',I,EXT,'四组管线已实现，朴素关键词独立；模型组无权限执行写，必须显式授权持久预算账本。','无真实模型授权，三模型组 n=0 / BLOCKED_EXTERNAL。','benchmark/ablation.py airlock/semantic.py','test_new_boundaries','pytest ablation')
row('B6',P,EXT,'旧集逐例/按族指标和四臂输出已交付，缺失模型指标保持无数据。','真实按来源/工具分层、独立危险金标、模型成本/时延及完整四臂错误分析未完成。','benchmark/ablation.py benchmark/research.py benchmark/evaluate.py','test_research','pytest ablation benchmark-test')
row('B7',I,PASS,'公式手算、空集/零分母、退化 κ、重复标注/泄漏、固定seed；原计数期望为手工构造。','工具可复现不代表来源独立性已验证。','tests/test_research.py tests/test_benchmark.py benchmark/generate.py','test_research test_benchmark','pytest latency')
row('B8',I,PASS,'保存关键词弱项、合成限制、未运行模型、人为失败与本机Docker失败；不推断普适结果。','','docs/EVALUATION.md docs/acceptance/FINDINGS_AND_FIXES.md',logs='benchmark-dev benchmark-test ablation')
for id,text in [('H1','≤5秒均值、3秒理解、p95/CI'),('H2','≥90%真实业务决策正确率'),('H3','<1秒快速批准代理指标<5%与理解核验'),('H4','eligible只读归并≥80%且相同任务质量'),('H5','活跃用户日均审批<20次')]:
    row(id,P,EXT,'研究导入/可见计时/手动导出/配对分析工具可运行；'+text+'的真人/真实工作负载结果未产生。','真实参与者0，无授权真实日志和活跃用户日；自动化导出已排除。','airlock/static/study.js benchmark/research.py benchmark/study-example.json','test_research','pytest browser-native study-analysis')
row('R1',P,PASS,'Linux真实Compose验证非root/只读根/零cap、无DB卷/审核密钥/socket、受限网络与独立审批。','本机Docker网络受阻；未运行注册上游专用生产网络隔离，宿主root不在边界。','compose.yaml scripts/docker_smoke.py','test_api','pytest docker-smoke')
row('R2',I,PASS,'方言编译授权、堆叠/注释/CTE/RETURNING/DDL/系统表/非有限/大整数/二进制/资源耗尽反例。','','airlock/sql.py airlock/models.py tests/test_gate.py','test_gate test_api test_audit_regressions')
row('R3',P,PASS,'SQL伪系统指令、恶意模型schema/越权建议不改变权限；UI按文本渲染。','没有真实模型跨工具描述/资源/拒绝建议的系统性攻击成功率测量。','airlock/semantic.py airlock/static/lib.js tests/test_semantic.py','test_semantic test_gate')
row('R4',I,PASS,'独立角色、请求/摘要/TTL替换、并发、路由撤销、SSE只通知、跨主体/恢复授权。','','airlock/access.py airlock/service.py','test_api test_gate test_routing test_new_boundaries test_recovery')
row('R5',I,PASS,'预算并发/重启/换ID、组新成员、模型异常、路由缺失、shadow激活不能免审。','','airlock/governance.py airlock/policy.py airlock/service.py','test_governance test_semantic test_routing test_observability')
row('R6',P,PASS,'错误输入不回显、UTF8/NaN稳定、审计/指标范围过滤、凭据隔离、UNC前置拒绝与SSRF origin约束。','生产PII脱敏/导出系统、完整外网SSRF渗透不在已测范围。','airlock/api.py airlock/access.py airlock/upstream.py','test_api test_routing test_upstream test_static_paths')
row('E1',P,PASS,'2026-10-02 GitHub API：AIRLOCK stars=0/forks=0，无外部采用证据；main历史为作者与自动化提交。','贡献者集合API不被connector支持，不宣称已证明没有其他外部贡献。','docs/RESEARCH.md evidence/full-audit-20261002/source-facts.json',logs='')
row('E2',I,PASS,'准确核对theagentrouter/agent-router#2073状态/日期/正文/作者权限；仓库内保留未发送讨论草稿。','未向第三方发帖、未被采纳、未实现Envoy部署。','docs/RESEARCH.md docs/UPSTREAM_PROPOSAL_DRAFT.md',logs='')
row('E3',I,PASS,'独立一次性数据库1206→0；有代理pending/拒绝保持1206，安全SELECT后明确批准才0。','受事故启发的合成演示；不是Replit精确复原。','scripts/demo_comparison.py docs/RESEARCH.md',logs='comparison')
row('E4',P,PASS,'读取官方LlamaFirewall/MCPGuard-Dynamic/AgentTrust/agentgateway/mcp-firewall/Cloudflare/Docker资料与AIID汇编，注明边界。','MCPGuard/AgentTrust同名歧义；无Replit完整第一方日志或竞品全量复现，数字因果不做强断言。','docs/RESEARCH.md',logs='')
row('D1',P,NOT,'当前FastAPI＋原生JS/CSS，偏差及迁移影响已单列。','Next.js未实现，未获用户接受偏差，保持未关闭。','README.md docs/OPERATIONS.md package.json',logs='frontend-check browser-native')
row('D2',I,PASS,'README、架构/状态机、API/数据/策略/启动/版本、故障/测试/研究手册已同步。','通用生产部署/SSO等不在当前实现。','README.md docs/OPERATIONS.md docs/SPEC.md docs/PLAN.md docs/THREAT_MODEL.md',logs='pytest browser-native dependency-audit')
row('D3',I,PASS,'17组问答覆盖CEL/LLM/远端未知/批量/实验/修复，简历不写未验指标。','用户本人讲解能力还需真实演示。','docs/INTERVIEW.md',logs='pytest comparison')
row('D4',I,PASS,'独立工作分支/草稿PR、Git原始证据/本地截图/126矩阵/进度更新；Actions临时包另列期限。','未合并main；没有release或外部不可变永久归档。','docs/acceptance/FINAL_REPORT.md docs/acceptance/EVIDENCE_RETENTION.md',logs='')
for id,text in [('K1','危险语义召回反复调优<80%'),('K2','真实FPR>25%'),('K3','真人决策耗时>15秒'),('K4','快速批准>20%并需结合理解/正确率')]:
    row(id,P,EXT,'失败触发条件保留：'+text+'；不删原目标、不自动放宽写审批。','真实金标/真人结果缺失，触发条件未知，不能宣称未触发或达标。','docs/CODEX_FULL_AUDIT_BRIEF.md docs/EVALUATION.md',logs='study-analysis ablation')
row('K5',I,PASS,'声明边界内已测无未授权效果；P1界面/门禁/依赖故障修复并复验，外部范围没有扩张保证。','测试不证明全域不可绕过；Docker本机和生产上游局限单列。','docs/acceptance/FINDINGS_AND_FIXES.md','test_gate test_new_boundaries test_static_paths','pytest docker-smoke')
row('K6',P,EXT,'当前可支持合成SQL预演精确，未知模式阻断；缺少全工具真实工作负载覆盖分母。','无法判断通用dry-run覆盖率是否<30%；不允许模型猜测后执行。','airlock/sql.py airlock/upstream.py docs/EVALUATION.md','test_gate','pytest benchmark-dev benchmark-test')
row('W1',I,PASS,'改动前保存完整目标矩阵和失败基线，早期登记真实来源/标注/模型缺口。','','docs/acceptance/BASELINE_MATRIX.json docs/acceptance/EXECUTION_PLAN.md',logs='')
row('W2',I,PASS,'按基线→P1→增量功能→独立反例→冻结提交复验推进；独立进程、SDK、浏览器、CI容器实际运行。','','docs/acceptance/FINDINGS_AND_FIXES.md tests','test_sdk_interop test_upstream','pytest browser-native comparison')
row('W3',I,PASS,'保留基线空白页、中间修复、最终桌面/移动/批量/指标/研究截图及原始报告；memory/progress同步。','本轮等价截图/轨迹证据，不伪造历史周录屏。','docs/acceptance/EVIDENCE_RETENTION.md',logs='browser-native')


def build():
    targets=[]
    for original in INDEX['targets']:
        id=original['id']
        if id in RECORDS:
            r=dict(RECORDS[id]);modules=r.pop('test_modules');names=r.pop('log_names')
            receipts=[(name,json.loads((FINAL/(name+'.log.status.json')).read_text())) for name in names]
            r.update(id=id,parent_id=original.get('parent_id'),criterion=original.get('criterion') or original.get('title'),
                requirement_origin='docs/CODEX_FULL_AUDIT_BRIEF.md and original acceptance index; no goals removed',
                tested_commit_sha=SHA,test_ids=[c.get('classname','')+'::'+c.get('name','') for c in JUNIT if any(c.get('classname','').endswith(m) for m in modules)],
                commands=[{'command':s['command'],'tested_commit_sha':s['tested_commit_sha'],'receipt':str((FINAL/(name+'.log.status.json')).relative_to(ROOT)).replace('\\','/')} for name,s in receipts],
                exit_codes=[{'command':name,'exit_code':s['exit_code'],'environment':'Windows local'} for name,s in receipts],
                evidence=[str((FINAL/(name+'.log')).relative_to(ROOT)).replace('\\','/') for name,s in receipts],
                fixes=['See FINDINGS_AND_FIXES.md for baseline fixes and incremental implementation evidence'],
                remaining_work=r['uncovered_scope'] or 'Within the stated scope, no further implementation gap identified.',
                blocker=r['uncovered_scope'] if r['verification_status'] in {EXT,'BLOCKED_ENV',NOT} else None,
                unblock_input=r['uncovered_scope'] if r['verification_status']==EXT else None,
                retest_command=receipts[0][1]['command'] if receipts else ['manual source and provenance review'],
                deviation_or_safety_amendment='All supported writes still require independent approval; budgets, models, reversibility and learning do not grant permissions.',
                versions=json.loads((FINAL/'manifest.json').read_text())['packages'])
            if not receipts:
                r['commands']=[{'command':'manual source/provenance review','receipt':'evidence/full-audit-20261002/source-facts.json','process_exit_code_applicable':False}]
                r['exit_codes']=[{'command':'manual review','exit_code':None,'reason':'no subprocess; not an invented zero'}]
                r['evidence']=['evidence/full-audit-20261002/source-facts.json']
            if 'browser-native' in names:
                extra=BASE/'final-ui/browser-native.log.status.json'
                status=json.loads(extra.read_text())
                r['supplemental_verified_commit_sha']=status['tested_commit_sha']
                r['commands'].append({'command':status['command'],'receipt':extra.relative_to(ROOT).as_posix(),'tested_commit_sha':status['tested_commit_sha']})
                r['exit_codes'].append({'command':'browser-native after metric-column fix','exit_code':status['exit_code'],'environment':'Windows local'})
                r['evidence']+=['evidence/full-audit-20261002/final-ui/browser-native.log','evidence/full-audit-20261002/final-ui/browser-report.json']
            if id=='C11.3':
                r['evidence']+=['evidence/full-audit-20261002/ci-negative-control-job.log','evidence/full-audit-20261002/ci-negative-control.json']
                r['commands'].append({'command':['python','scripts/run_logged.py','evidence/negative-control.log','--','python','-c','raise SystemExit(23)'],'tested_commit_sha':'89c32625a49f7744389efe6284e942eee5a82332','run_url':'https://github.com/Changxin-YR/AIRLOCK/actions/runs/36986618577'})
                r['exit_codes'].append({'command':'intentional-negative-control','exit_code':23,'environment':'Ubuntu runner','expected_failure':True})
            if id in {'A2','C11.1','C11.3','C11.4','R1','K5','G1'}:
                r['evidence']+=['evidence/full-audit-20261002/ci-266ad9e-job.log','evidence/full-audit-20261002/ci-266ad9e-artifacts.json']
                r['commands'].append({'command':'GitHub Actions verify job (including Docker and verify_evidence.py)','run_url':'https://github.com/Changxin-YR/AIRLOCK/actions/runs/36986102382','tested_commit_sha':SHA})
                r['exit_codes'].append({'command':'GitHub Actions verify job','exit_code':0,'environment':'Ubuntu runner','basis':'job/steps success and verifier checked actual child receipts'})
            targets.append(r)
        else:
            # Only parent C rows may be derived; every child above has its own judgment.
            assert id.startswith('C') and '.' not in id,id
            targets.append({'id':id,'parent_id':None,'criterion':original.get('title'),'derived_parent':True})
    by_id={r['id']:r for r in targets}
    for parent in [r for r in targets if r.get('derived_parent')]:
        children=[r for r in targets if r['id'].startswith(parent['id']+'.')]
        all_done=all(r['implementation_status']==I for r in children)
        all_pass=all(r['verification_status']==PASS and r['implementation_status']==I for r in children)
        parent.update(implementation_status=I if all_done else P,verification_status=PASS if all_pass else EXT if any(r['verification_status']==EXT for r in children) else NOT,
            requirement_origin='Original parent goal; aggregation requires all children',scope='; '.join(r['id']+': '+r['scope'] for r in children),
            uncovered_scope='; '.join(r['id']+': '+r['uncovered_scope'] for r in children if r['uncovered_scope']),
            code_references=sorted({f for r in children for f in r['code_references']}),test_ids=sorted({t for r in children for t in r['test_ids']}),
            commands=[{'child_id':r['id'],'commands':r['commands']} for r in children],exit_codes=[{'child_id':r['id'],'exit_codes':r['exit_codes']} for r in children],
            evidence=sorted({e for r in children for e in r['evidence']}),tested_commit_sha=SHA,
            actual_result='All children complete/pass' if all_pass else 'Parent not fully accepted; inspect every child. Limited-scope PASS does not close uncovered child scope.',
            fixes=['Aggregated child fixes; no substitute parent test'],remaining_work='Review listed child gaps',blocker=None,unblock_input=None,
            retest_command=['Re-run each child evidence command'],deviation_or_safety_amendment='Preserve all original children and safety floor.',versions=children[0]['versions'])
    assert len(targets)==126 and set(by_id)=={x['id'] for x in INDEX['targets']}
    required=set(INDEX['required_result_fields'])
    for r in targets:assert required<=r.keys(),(r['id'],required-r.keys())
    result={'schema_version':2,'phase':'post_fix_full_audit','baseline_commit':INDEX['historical_base_commit'],
        'tested_commit_sha':SHA,'target_count':126,'original_goals_all_satisfied':False,
        'status_semantics':'PASS only covers scope; PARTIAL with PASS is not a completed original goal. Parent PASS requires all children implemented/pass.',
        'counts':{'implementation':dict(Counter(r['implementation_status'] for r in targets)),'verification':dict(Counter(r['verification_status'] for r in targets))},'targets':targets}
    path=ROOT/'docs/acceptance/COMPLETION_MATRIX.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    lines=['# 126 项逐项验收矩阵','',f'应用测试提交：`{SHA}`。所有原目标尚未全部满足。',
        '','PASS 限于该行明确范围；PARTIAL＋PASS 不表示原目标完成。父项仅在全部子项完整实现且通过时通过。命令、真实退出码、原始证据、test ID 和版本详见同目录 JSON；本机 Docker 失败与 Ubuntu CI 成功分列。','',
        '| ID | 实现 | 验证 | 实际范围 / 剩余缺口 |','|---|---|---|---|']
    for r in targets:
        text=r['scope']+(' **缺口：**'+r['uncovered_scope'] if r['uncovered_scope'] else '')
        if r.get('derived_parent'):text=r['actual_result']+'；逐子项见下。'
        lines.append(f"| {r['id']} | {r['implementation_status']} | {r['verification_status']} | {text.replace('|','/')} |")
    lines+=['','## 逐项完整证据字段','','下面逐条保留与 JSON 相同的记录；父项聚合不替代子项证据。','']
    for r in targets:
        lines += [f"<details><summary>{r['id']} · {r['implementation_status']} / {r['verification_status']}</summary>",'','```json',json.dumps(r,ensure_ascii=False,indent=2),'```','','</details>','']
    (path.with_suffix('.md')).write_text('\n'.join(lines).rstrip()+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result['counts'],ensure_ascii=False))


if __name__=='__main__':build()
