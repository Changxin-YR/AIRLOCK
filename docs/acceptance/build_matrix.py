"""Rebuild the review ledger from explicit per-target judgments and raw receipts.
PASS is restricted to each row's scope; an external dependency is never inferred
from successful tooling. This is bookkeeping, not an autonomous semantic audit.
"""
from pathlib import Path
import json
import os
import xml.etree.ElementTree as ET
from collections import Counter

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'evidence/autonomous-20261003'
CLOSURE=ROOT/'evidence/closure-20261002'
LEGACY=ROOT/'evidence/continuation-20261002'
FINAL=ROOT/os.environ.get('AIRLOCK_ACCEPTANCE_FINAL','evidence/startup-preflight-20261004/ci/verified')
CI_META=ROOT/os.environ.get('AIRLOCK_ACCEPTANCE_CI','evidence/startup-preflight-20261004/CI_FINAL.json')
SHA=json.loads((FINAL/'pytest.log.status.json').read_text())['tested_commit_sha']
LOG_PATHS={name:LEGACY/'final'/(name+'.log') for name in ('live-validation','ablation-live-dev','ablation-live-test','model-diagnostics')}
LOG_PATHS.update({'model-contract-recheck':LEGACY/'retest/model-contract-recheck.log','live-upstream':CLOSURE/'final/live-upstream.log','sse-identity-replay':CLOSURE/'sse-identity-replay.log',
    'github-relay':BASE/'local/live-relay.log','model-ui-v2':BASE/'local/browser-model-v2.log','model-roles':BASE/'local/deepseek-roleplay.log'})
def log_path(name):return LOG_PATHS.get(name,FINAL/(name+'.log'))
INDEX=json.loads((ROOT/'docs/acceptance/AIRLOCK-acceptance-targets.json').read_text(encoding='utf-8'))
JUNIT=list(ET.parse(FINAL/'pytest.xml').iter('testcase'))
RECORDS={}


def row(id,implementation,verification,scope,missing,files,tests='',logs='pytest',result=None):
    RECORDS[id]=dict(implementation_status=implementation,verification_status=verification,scope=scope,
        uncovered_scope=missing,code_references=files.split(),test_modules=tests.split(),log_names=logs.split(),
        actual_result=result or scope)


I='IMPLEMENTED';P='PARTIAL';M='MISSING';PASS='PASS';EXT='BLOCKED_EXTERNAL';NOT='NOT_RUN'
row('G1',I,PASS,'本地项目可运行；doctor只读检查配置、内存SQLite及审批台产物；无效配置脱敏拒绝，损坏构建在持久库初始化前拒绝，默认环境/API-only启动兼容；Linux CI真实容器。','doctor不检查持久库、可选集成或外部服务；不代表生产部署或实际付费模型成本。','README.md docs/OPERATIONS.md airlock/__main__.py airlock/diagnostics.py airlock/api.py airlock/models.py','test_sdk_interop test_gate test_launcher test_diagnostics test_startup_preflight', 'pytest browser-native dependency-audit')
row('G2',I,PASS,'简历描述绑定实际代码路径和合成证据。','用户本人是否能独立复现需实际演示。','docs/INTERVIEW.md README.md','test_gate test_upstream','pytest comparison')
row('G3',I,PASS,'创新定位为服务端绑定、影响证据与治理组合；核对现有 HITL/审批实现。','没有性能横评、行业首创或外部采用结论。','docs/RESEARCH.md docs/INTERVIEW.md',logs='')
row('G4',I,EXT,'已交付 17 组问答、追问、运行命令和限制。','用户现场讲解、答辩与独立操作能力未验证。','docs/INTERVIEW.md docs/OPERATIONS.md',logs='')
row('A1',I,PASS,'本地失败回滚；远端授权执行后失联为 unknown；模型/预演失败阻断。','受信上游必须履行 CAS/收据契约；无任意外部工具保证。','airlock/service.py airlock/upstream.py airlock/semantic.py','test_gate test_new_boundaries test_semantic')
row('A2',I,PASS,'服务端认证/路由/快照绑定；真实双内网验证 Agent 无上游 DNS/IP直连、上游凭据、数据库或 Docker socket。','仅声明的隔离部署；宿主/root不在防护边界。','airlock/access.py airlock/oidc.py scripts/upstream_isolation.py','test_oidc test_routing','pytest docker-smoke upstream-isolation')
row('A4',I,PASS,'本地 exact 与上游声明值区分；备份/远端恢复未知；失败不会猜测后执行。','未实现通用估算适配器，未知受控操作阻断。','airlock/sql.py airlock/recovery.py airlock/static/review.js','test_gate test_recovery test_upstream')

row('C1.5',I,PASS,'操作者配置固定工具、域名DNS pin与真实TLS SNI验证；RS256 access token issuer/audience/time/jti/subject绑定；入站凭据不透传。','真实生产IdP/公网部署配置另需提供；测试不等于全网渗透认证。','airlock/network.py airlock/oidc.py airlock/access.py airlock/upstream.py','test_network test_oidc test_upstream test_mcp_streamable','pytest upstream-isolation')
row('C2.1',I,PASS,'block 优先、错误阻断、支持写入审批下限不能被 pass/模型覆盖。','','airlock/policy.py airlock/service.py','test_policy test_semantic test_gate')
row('C2.2',I,PASS,'真实 cel-python 0.4.0＋安全 YAML；schema、重复键/alias 拒绝、类型及 AST/字数/规则上限。','仅文档定义的有限布尔/比较子集。','airlock/policy.py policies/example.yaml requirements.txt','test_policy')
row('C3.1',I,PASS,'私有克隆预演与真实目标分离，失败/资源上限阻断；真实表无 pending 效果。','','airlock/sql.py tests/test_gate.py','test_gate test_recovery')
row('C3.2',I,PASS,'匹配/变化/返回分开；零变化、RETURNING、NULL/二进制/触发器等受限语义验证。','固定 STRICT schema，不支持的 SQL 模式拒绝。','airlock/sql.py tests/test_gate.py','test_gate','pytest benchmark-dev benchmark-test')
row('C3.3',I,PASS,'本地来源/时间/目标/schema hash/前后指纹/5 条样本和截断；上游另标声明值。','上游声明值依赖适配器事实，不是本地独立验证。','airlock/service.py airlock/upstream.py airlock/static/review.js','test_gate test_upstream','pytest browser-native')
row('C3.4',I,PASS,'摘要绑定 ID/TTL/版本/请求/策略/目标/影响；锁内复核与上游 CAS。','','airlock/service.py airlock/upstream.py','test_gate test_new_boundaries test_upstream')
row('C3.5',I,PASS,'逐适配器说明精确克隆、受信 CAS 预演与未支持执行边界。','无 Shell/通用外部服务沙箱。','docs/OPERATIONS.md airlock/sql.py airlock/upstream.py','test_gate test_upstream')
row('C4.2',I,PASS,'没有实际备份依据时保持 null/unknown；本地完整补偿快照与外部备份分开。','','airlock/sql.py airlock/recovery.py airlock/static/review.js','test_recovery test_gate')
row('C4.5',I,PASS,'可逆性、预算、模型建议均不取消写审批；硬 block 不能人工覆盖。','','airlock/policy.py airlock/service.py','test_policy test_recovery test_semantic test_governance')
row('C5.2',I,PASS,'模型建议只可加严；不能自批或持有目标/审核权限；无效输出阻断。','','airlock/semantic.py airlock/service.py','test_semantic test_gate')
row('C6.1',I,PASS,'持久 pending/rejected/expired/stale/failed/executed/executing/unknown；批准与远端效果分开。','','airlock/service.py airlock/upstream.py airlock/store.py','test_gate test_upstream test_new_boundaries')
row('C6.2',I,PASS,'独立reviewer资源/风险路由、OIDC主体映射与静态凭据可选、缺路由阻断、逐请求撤销与超期令牌拒绝。','生产身份系统发证和交互式SSO需IdP环境；没有两人quorum。','airlock/access.py airlock/oidc.py airlock/api.py','test_routing test_oidc','pytest')
row('C6.3',I,PASS,'服务端 TTL、重启、时钟回退阻断；SSE 持久游标重连，凭据撤销或身份映射变化立即结束旧连接，客户端通知不授权。','','airlock/service.py airlock/api.py airlock/static/lib.js','test_gate test_live_transport test_new_boundaries test_oidc','pytest frontend-tests browser-native sse-identity-replay')
row('C6.4',I,PASS,'同键同内容返回原收据，冲突拒绝；本地并发只执行一次；失联保留原 action。','','airlock/service.py airlock/upstream.py','test_gate test_governance test_upstream')
row('C6.5',I,PASS,'本地进程退出和审计失败原子回滚；远端租约/丢响应/审计失败后重启对账，不重发。','信任上游原子 CAS/幂等，不是分布式 exactly-once。','airlock/upstream.py tests/test_new_boundaries.py tests/test_gate.py','test_gate test_upstream test_new_boundaries')
row('C7.1',I,PASS,'影响数量/可恢复依据/主体资源优先，再命令和原 JSON；exact/上游声明/截断明确。','','airlock/static/review.js airlock/static/governance.js','test_api','browser-native')
row('C7.5',I,PASS,'首次可见＋页面可见性＋单调时钟，离开动作/指标页暂停；遥测不授权。','','airlock/static/lib.js airlock/static/app.js airlock/static/study.js','test_api','frontend-tests browser-native')
row('C7.6',I,PASS,'无 key 确定性路径可运行；角色/合成数据/未知成本提示和使用手册。','没有三秒决策或全面可访问性认证。','README.md docs/OPERATIONS.md airlock/static/app.js',logs='browser-native')
row('C8.1',I,PASS,'主体/工具/资源/策略/风险/reviewer/时间窗分组，成员明示，累计影响。','','airlock/governance.py airlock/static/governance.js','test_governance','pytest browser-native')
row('C8.2',I,PASS,'组摘要和精确成员集合/版本/TTL 绑定；新成员拒绝；累计高风险再查路由，逐成员收据。','不提供全组事务原子性；先执行项可使后续 stale。','airlock/governance.py airlock/service.py','test_governance','pytest browser-native')
row('C8.3',I,PASS,'主体/资源固定窗预算；原子预占/结算/释放，重启及并发不重置，新 ID 不免限额。','单位不是事故概率界限；固定窗不等同滑动窗。','airlock/governance.py airlock/store.py','test_governance')
row('C8.4',I,PASS,'历史生成仅显示分组窗口的 shadow 建议；operator 明确激活/期限/CAS/撤回，永不授权写。','安全修正替代原自动降级设想；没有训练授权模型。','airlock/service.py airlock/api.py','test_observability test_new_boundaries')
row('C8.5',I,EXT,'只读、幂等、eligible折叠、实际batch、错误与用户日独立统计；授权日志导入去重，质量不匹配剔除比较，零分母未知。','缺真实同任务质量日志和审批错误金标；工具完成不能证明疲劳改善。','airlock/observability.py benchmark/closure.py','test_observability test_research_closure','pytest research-pipeline')
row('C9.1',I,PASS,'稳定 reason_code/action/trace、execution_occurred/重试说明及有界替代方向；错误不回显原始输入。','','airlock/service.py airlock/api.py','test_api test_mcp')
row('C9.2',I,PASS,'合成删除被真实拒绝后仍 1206 行；安全 SELECT 返回真实 1206，另路明确批准后为 0。','','scripts/demo_comparison.py scripts/demo_agent.py','test_gate','comparison')
row('C9.4',I,PASS,'拒绝后禁止重复写；pending 查询，unknown 原收据对账；Agent 最多 8 步和单个写建议。','','scripts/live_agent.py scripts/demo_agent.py airlock/upstream.py','test_live_agent_contract test_upstream')
row('C10.1',I,PASS,'原始 evaluated 快照含模板/策略/路由/影响/相关 ID，决定与收据另记签名事件。','','airlock/store.py airlock/service.py airlock/upstream.py','test_gate test_observability test_upstream')
row('C10.3',I,PASS,'审计失败本地回滚/远端可对账；审计读取按路由授权，导出仅白名单摘要，SQL/样本/身份/自由文本不带出。','脱敏摘要不替代原始签名审计；序号/状态/数量仍可见。','airlock/export.py airlock/api.py airlock/store.py','test_export test_routing test_new_boundaries','pytest')
row('C11.3',I,PASS,'真实 exit receipt、全部 JUnit 无失败/skip、图片/逐例重算/commit 绑定、完整 CI gate；独立 CI exit23 对照另存；最终完整 CI ZIP 已下载校验并存 Git。','Actions 原副本保存 90 天；Git 副本没有自动到期，仍非外部 WORM。','scripts/run_logged.py scripts/verify_evidence.py .github/workflows/ci.yml','test_logged_runner test_evidence_gate','pytest')

row('L0-2',I,PASS,'pending 本地和独立远端真实目标不变，原快照持久，浏览器不授予权限。','','tests/test_gate.py tests/test_upstream.py','test_gate test_upstream')
row('L0-3',I,PASS,'独立 reviewer 批准绑定对象，官方 SDK 读取真实结果；并发/重复不双执行。','','tests/test_sdk_interop.py tests/test_gate.py','test_sdk_interop test_gate')
row('L0-4',I,PASS,'服务端到期不执行，远端响应丢失 unknown 对账，不换键盲重试。','','airlock/service.py airlock/upstream.py','test_gate test_upstream test_new_boundaries')
row('L0-5',I,PASS,'本地提交前进程死亡回滚；重启不重播种；远端已提交失联只查原收据。','','tests/test_gate.py tests/test_upstream.py','test_gate test_upstream test_new_boundaries')
row('T1',P,EXT,'合成保护覆盖和三态一致率单独报告；有真实危险标签 schema 和计算函数。','缺独立业务危险金标，≥90% 语义召回未知。','benchmark/research.py benchmark/evaluate.py','test_research','pytest benchmark-dev benchmark-test')
row('T2',P,EXT,'同一合成集支持 pass 额外拦截率 0/60，三态混淆原始行已保存。','非危险独立业务金标缺失，真实风险 FPR≤10% 未验证。','benchmark/research.py benchmark/evaluate.py','test_research','pytest benchmark-dev benchmark-test')
row('T3',I,PASS,'固定合成环境的静态分类阶段及真实 HTTP 延迟分开记录，30 写样本 p95 <300ms。','并发1与首次请求/热态；未测冷 OS 缓存和生产并发。','scripts/measure_latency.py airlock/sql.py',logs='latency')
row('T4',I,PASS,'1206行克隆/执行/差异阶段30次写样本 p95 <5s，保留所有样本与极值。','尚未覆盖每种上游/规模的性能分布。','scripts/measure_latency.py airlock/sql.py',logs='latency benchmark-dev benchmark-test')
row('T5',I,PASS,'冻结合成精确预演逐例计数一致；独立研究计算器报告±5%相对误差、零影响绝对误差/误判与unknown覆盖率。','真实其他适配器精度仍需各自独立真值；不外推合成exact结果。','benchmark/research.py benchmark/evaluate.py','test_research test_benchmark','pytest benchmark-dev benchmark-test research-pipeline')
row('T6',I,PASS,'同目标相同只读请求，60对随机交替，逐对增量 p95 <100ms 且另报均值。','只测本机 SQLite/HTTP，非第三方模型/网络。','scripts/measure_latency.py',logs='latency')
row('B1',P,EXT,'200条40族合成回归；新增1个GitLab第一方事故启发的有限重构族，保留来源笔记hash/重构局限；授权日志导入可用。','无获授权日常Agent日志；事故重构不是原始PostgreSQL操作/生产数据，不够真实来源覆盖。','benchmark/public-source-notes.json scripts/research_pipeline.py benchmark/closure.py','test_research_closure','pytest research-pipeline')
row('B2',P,EXT,'新 Case/Annotation schema 包含决策、风险、影响依据、可逆性、意图、来源、适配器、快照和 split，未知保留。','旧200条只有作者策略金标，四类真实标注和相应数据快照尚未取得。','benchmark/research.py','test_research')
row('B3',I,EXT,'双人空白标注模板、独立性声明、四类分歧仲裁、仲裁前κ和退化/缺失处理均可执行。','真人标注者0，κ=null；身份/独立性不能由JSON声明自证。','benchmark/closure.py benchmark/research.py','test_research_closure test_research','pytest research-pipeline')
row('B4',P,EXT,'旧集按族6:4冻结，tuning拒读test；新导入拒跨split同族/重复请求，冻结不可静默替换。','旧test已公开；尚无全新独立保留集，近语义重复仍需人工核查。','benchmark/generate.py benchmark/evaluate.py benchmark/research.py','test_benchmark test_research')
row('B7',I,PASS,'公式手算、空集/零分母、退化 κ、重复标注/泄漏、固定seed；原计数期望为手工构造。','工具可复现不代表来源独立性已验证。','tests/test_research.py tests/test_benchmark.py benchmark/generate.py','test_research test_benchmark','pytest latency')
row('B8',I,PASS,'保存关键词弱项、合成限制、未运行模型、人为失败与本机Docker失败；不推断普适结果。','','docs/EVALUATION.md docs/acceptance/FINDINGS_AND_FIXES.md',logs='benchmark-dev benchmark-test ablation')
for id,text in [('H1','≤5秒均值、3秒理解、p95/CI'),('H2','≥90%真实业务决策正确率'),('H3','<1秒快速批准代理指标<5%与理解核验'),('H4','eligible只读归并≥80%且相同任务质量'),('H5','活跃用户日均审批<20次')]:
    row(id,P,EXT,'研究导入/可见计时/手动导出/配对分析工具可运行；'+text+'的真人/真实工作负载结果未产生。','真人完成记录0；缺含实际人工审批、相同任务质量分母和活跃用户日的授权治理日志；自动化导出已排除。','airlock/static/study.js benchmark/research.py benchmark/study-example.json','test_research','pytest browser-native study-analysis')
row('R1',I,PASS,'真实Linux部署非root/只读根/零cap，无目标卷、配置/凭据/socket；Agent与上游分别内网，DNS和直接IP绕过均失败。','仅受控部署，宿主管理员/容器逃逸不在测试范围；Windows基础镜像拉取受阻。','compose.yaml scripts/docker_smoke.py scripts/upstream_isolation.py','test_api','pytest docker-smoke upstream-isolation')
row('R2',I,PASS,'方言编译授权、堆叠/注释/CTE/RETURNING/DDL/系统表/非有限/大整数/二进制/资源耗尽反例。','','airlock/sql.py airlock/models.py tests/test_gate.py','test_gate test_api test_audit_regressions')
row('R4',I,PASS,'独立角色、请求/摘要/TTL替换、并发、路由撤销、SSE只通知、跨主体/恢复授权。','','airlock/access.py airlock/service.py','test_api test_gate test_routing test_new_boundaries test_recovery')
row('R5',I,PASS,'预算并发/重启/换ID、组新成员、模型异常、路由缺失、shadow激活不能免审。','','airlock/governance.py airlock/policy.py airlock/service.py','test_governance test_semantic test_routing test_observability')
row('R6',I,PASS,'错误不回显，路由过滤审计/SSE/指标；最小化脱敏导出，XSS/CSRF/SSRF/DNS重绑定/TLS/令牌audience反例。','生产数据字段分类及完整外部渗透认证尚无真实数据环境。','airlock/export.py airlock/network.py airlock/oidc.py airlock/api.py','test_export test_network test_oidc test_routing test_api','pytest browser-edges')
row('E1',I,PASS,'2026-10-02公开GitHub API：stars/forks均0，默认分支贡献者为仓库作者17提交及两个自动化身份各1提交，未见独立外部人类贡献或采用证据。','只覆盖公开默认分支归属；不能证明没有未记录使用或帮助。','docs/RESEARCH.md evidence/closure-20261002/ECOSYSTEM_FACTS.json',logs='')
row('E2',I,PASS,'准确核对theagentrouter/agent-router#2073状态/日期/正文/作者权限；仓库内保留未发送讨论草稿。','未向第三方发帖、未被采纳、未与该上游项目生产集成。','docs/RESEARCH.md docs/UPSTREAM_PROPOSAL_DRAFT.md',logs='')
row('E3',I,PASS,'独立一次性数据库1206→0；有代理pending/拒绝保持1206，安全SELECT后明确批准才0。','受事故启发的合成演示；不是Replit精确复原。','scripts/demo_comparison.py docs/RESEARCH.md',logs='comparison')
row('E4',I,PASS,'核对各竞品官方原文并明确同名项目URL；补取SaaStr当事人第一方叙述，核实1206高管/1196+公司数字来源，AIID汇编与原始日志分开。','未取得Replit原执行日志/数据库，未做竞品横向性能复现；不宣称原事故精确重演或功能首创。','docs/RESEARCH.md evidence/closure-20261002/REPLIT_FIRST_PARTY.json',logs='')
row('D2',I,PASS,'README、架构/状态机、API/数据/策略/启动/版本、故障/测试/研究手册已同步。','实际生产IdP与长期部署需外部配置。','README.md docs/OPERATIONS.md docs/SPEC.md docs/PLAN.md docs/THREAT_MODEL.md',logs='pytest browser-native dependency-audit')
row('D3',I,PASS,'17组问答覆盖CEL/LLM/远端未知/批量/实验/修复，简历不写未验指标。','用户本人讲解能力还需真实演示。','docs/INTERVIEW.md',logs='pytest comparison')
row('D4',I,PASS,'独立工作分支/草稿PR、Git原始证据/本地截图/126矩阵/进度更新；Actions临时包另列期限。','未合并main；没有release或外部不可变永久归档。','docs/acceptance/FINAL_REPORT.md docs/acceptance/EVIDENCE_RETENTION.md',logs='')
for id,text in [('K1','危险语义召回反复调优<80%'),('K2','真实FPR>25%'),('K3','真人决策耗时>15秒'),('K4','快速批准>20%并需结合理解/正确率')]:
    row(id,P,EXT,'失败触发条件保留：'+text+'；不删原目标、不自动放宽写审批。','真实金标/真人结果缺失，触发条件未知，不能宣称未触发或达标。','docs/CODEX_FULL_AUDIT_BRIEF.md docs/EVALUATION.md',logs='study-analysis ablation')
row('K5',I,PASS,'声明边界内已测无未授权效果；P1界面/门禁/依赖故障修复并复验，外部范围没有扩张保证。','测试不证明全域不可绕过；Docker本机和生产上游局限单列。','docs/acceptance/FINDINGS_AND_FIXES.md','test_gate test_new_boundaries test_static_paths','pytest docker-smoke')
row('K6',P,EXT,'当前可支持合成SQL预演精确，未知模式阻断；缺少全工具真实工作负载覆盖分母。','无法判断通用dry-run覆盖率是否<30%；不允许模型猜测后执行。','airlock/sql.py airlock/upstream.py docs/EVALUATION.md','test_gate','pytest benchmark-dev benchmark-test')
row('W1',I,PASS,'改动前保存完整目标矩阵和失败基线，早期登记真实来源/标注/模型缺口。','','docs/acceptance/BASELINE_MATRIX.json docs/acceptance/EXECUTION_PLAN.md',logs='')
row('W2',I,PASS,'按基线→P1→增量功能→独立反例→冻结提交复验推进；独立进程、SDK、浏览器、CI容器实际运行。','','docs/acceptance/FINDINGS_AND_FIXES.md tests','test_sdk_interop test_upstream','pytest browser-native comparison')
row('W3',I,PASS,'保留基线空白页、中间修复、最终桌面/移动/批量/指标/研究截图及原始报告；memory/progress同步。','本轮等价截图/轨迹证据，不伪造历史周录屏。','docs/acceptance/EVIDENCE_RETENTION.md',logs='browser-native')


row('C1.1',I,PASS,'协议无关 Gate；HTTP、stdio 与 Streamable HTTP MCP 共用权限核心。','','airlock/service.py airlock/mcp.py airlock/mcp_http.py airlock/api.py','test_mcp test_mcp_http test_sdk_interop')
row('C1.2',I,PASS,'官方 SDK 真实 stdio/HTTP 初始化、发现、pending、批准/拒绝、硬拒绝、非法参数及结果读回。','限已声明的协议子集，非所有第三方 host 认证。','tests/test_mcp_http.py tests/test_sdk_interop.py','test_mcp_http test_sdk_interop test_live_transport')
row('C1.3',I,PASS,'配置注册独立HTTP/MCP上游，官方SDK会话/SSE实际调用；真实DeepSeek经闸门到注册MCP counter，拒绝停止、独立批准执行一次。','无需修改契约兼容业务实现；须注册配置/隔离网络，Agent host需等待与查询收据；任意工具仍需适配，非通用零改造。','airlock/upstream.py airlock/mcp_upstream.py scripts/live_upstream.py scripts/upstream_isolation.py','test_upstream test_mcp_streamable','pytest live-upstream upstream-isolation')
row('C1.4',I,PASS,'入站无会话MCP与出站注册会话/SSE分别声明，协商2025版本、阶段有界、固定工具与收据、会话终止不重发写入。','不宣告Tasks/服务端主动请求；非所有host或最新版协议完整认证。','airlock/mcp.py airlock/mcp_http.py airlock/mcp_upstream.py docs/CLOSURE_RUNBOOK.md','test_mcp_http test_mcp_streamable','pytest')
row('C2.3',I,PASS,'策略激活内容持久化，审计与激活同事务；全部工作进程在提交/执行事务内同步版本；旧 pending stale。','','airlock/policy.py airlock/service.py airlock/upstream.py','test_shared_policy test_policy test_new_boundaries')
row('C2.4',I,PASS,'跨真实独立进程热重载、失败保旧、重启持久策略、恶意 YAML/CEL 边界通过。','','tests/test_shared_policy.py airlock/policy.py','test_shared_policy test_policy test_new_boundaries')
row('C2.5',I,PASS,'Envoy 1.39.1 真实容器中 12 个布尔/比较映射与 cel-python 一致；显式记录错误语义差异。','只证明明确映射的访问日志 CEL 子集，非 Envoy 完整授权策略兼容。','scripts/container_integrations.py policies/example.yaml docs/OPERATIONS.md','test_policy','pytest container-integrations')
row('C4.1',I,PASS,'技术可逆性、恢复可行性、依据、业务授权分别建模；SQLite 与注册远端补偿均单独申请；UI 区分克隆/事务/提交后补偿。','未知第三方恢复依据保持 unknown，未推断可恢复即获授权。','airlock/recovery.py airlock/upstream.py airlock/static/review.js','test_recovery test_remote_compensation','pytest browser-native')
row('C4.3',I,PASS,'本地完整快照在克隆中演练；独立远端 counter 恢复按原收据及当前版本 CAS。','不是任意第三方灾备或业务损失恢复。','airlock/recovery.py airlock/upstream.py scripts/fixture_upstream.py','test_recovery test_remote_compensation')
row('C4.4',I,PASS,'本地/远端补偿为新的独立审批动作，源归属/执行终态/当前版本/幂等/审计绑定；漂移不覆盖。','','airlock/recovery.py airlock/upstream.py','test_recovery test_remote_compensation','pytest browser-native browser-edges')
row('C5.1',I,PASS,'真实 DeepSeek V4.1 Flash Responses 已调用；严格 schema、凭据隔离、CNY 持久预算/并发与使用量回执。','账单账户级硬上限不由本地估算代替；OpenAI 路径本轮仍仅离线契约。','airlock/semantic.py configs/deepseek-flash.example.json','test_semantic test_deepseek','pytest live-validation model-contract-recheck')
row('C5.3',I,PASS,'离线恶意 schema/越权/超时/耗尽，加真实 reason 超长失败；保留异常输出/类型/hash，阻断执行；v2 简短理由提示在 10 个 dev 失败样例复验。','不承诺模型永远产生有效输出；真实供应商 429 未故意压测。','airlock/semantic.py scripts/diagnose_model_schema.py','test_semantic test_deepseek','pytest live-validation model-diagnostics model-contract-recheck')
row('C5.4',I,PASS,'缓存完整绑定与主动失效计数；真实应用缓存命中/清空/再次调用，provider cache-read 用量另报。','','airlock/semantic.py airlock/observability.py airlock/api.py','test_semantic test_deepseek test_observability','pytest live-validation')
row('C5.5',I,PASS,'真实调用、离线 mock、作者合成标签、真人0 分开报告；真实逐调用模型/usage/费用估算/错误与账本已存档。','无独立危险金标及账单对账。','airlock/semantic.py scripts/live_validation.py benchmark/ablation.py','test_deepseek','pytest live-validation ablation-live-dev ablation-live-test')
row('C7.2',I,PASS,'Next.js 原生浏览器完成常规14项及新增9项：stale/expired/failed/unknown对账/硬拒绝等真实 API 状态。','executing 的持久状态由后端测试，浏览器以最终 unknown/执行结果路径验证；无全浏览器认证。','frontend/app/page.jsx scripts/browser_smoke.py scripts/browser_edges.py','test_upstream','pytest browser-native browser-edges')
row('C7.3',I,PASS,'React 内存身份/草稿、并行加载、SSE生命周期及服务器 pending 分页；105条历史反例通过。','','frontend/app/page.jsx airlock/api.py','test_pending_queue','pytest browser-native browser-edges')
row('C7.4',I,PASS,'真实桌面/390px、长文本/XSS文本渲染、键盘登录、退出清内存、Next hydration 与 hash CSP 无错误。','未做完整 WCAG/辅助技术认证；不把它列作已获认证。','frontend/app/page.jsx airlock/static/style.css scripts/browser_edges.py','test_static_paths test_api','pytest browser-native browser-edges')
row('C10.2',I,PASS,'链/归属/轮换与外部检查点；独立S3 COMPLIANCE版本收据回读，真实拒删/缩短/降级，取回锚点检测截尾。','临时容器已清理；实际长期云归档未部署，锚点之后截尾/全部密钥失陷边界仍在。','airlock/store.py airlock/archive.py scripts/archive_integration.py','test_audit_rotation test_archive','pytest archive-integration')
row('C10.4',I,PASS,'原始审批快照回放不重执行；检查点导出及验证；独立保管要求与不可变存证缺口明确。','','frontend/app/page.jsx airlock/store.py scripts/audit_checkpoint.py','test_audit_rotation','pytest browser-native')
row('C11.1',I,PASS,'217 Python、6 JS、23原生浏览器；SDK、Linux Compose、受保护上游网络、S3 Object Lock、Envoy/Collector和研究管线。','Windows Compose镜像认证网络失败保留；Linux成功不改写本机失败。','tests scripts/browser_edges.py scripts/upstream_isolation.py scripts/archive_integration.py scripts/research_pipeline.py','test_gate test_mcp_streamable test_oidc','pytest frontend-tests browser-native browser-edges docker-smoke upstream-isolation archive-integration research-pipeline container-integrations')
row('C11.2',I,EXT,'冻结200例与真实四臂模型历史结果保留；新增来源重构、双人空模板、仲裁/κ、独立语义预测/保护指标和任务文件绑定分析。','缺授权日常日志、真实双人标签、新保留集和真人A/B；真实数据项仍受阻。','benchmark/research.py benchmark/closure.py benchmark/ablation.py scripts/research_pipeline.py','test_research test_research_closure test_benchmark','pytest research-pipeline ablation-live-dev ablation-live-test study-analysis')
row('C11.4',I,PASS,'CI强制217 Python、23浏览器、Docker上游隔离/S3/研究管线及原始退出码；artifact完整校验与负例门禁保留。','科研真人指标不由CI绿灯替代。','scripts/verify_evidence.py .github/workflows/ci.yml','test_evidence_gate','pytest benchmark-dev benchmark-test latency upstream-isolation archive-integration research-pipeline')
row('C12.1',I,PASS,'request/action/trace 关联持久；有界 OTLP outbox 实际送达官方 Collector；审批/执行/恢复沿用原 action trace。','没有假称受信上游内部自动生成完整 spans；上游用 action/request hash 关联，生产分布式后端未部署。','airlock/telemetry.py airlock/observability.py airlock/service.py scripts/container_integrations.py','test_telemetry test_observability','pytest container-integrations')
row('C12.2',I,PASS,'阶段/费用/cache看板、队列/丢弃、operator只读健康/Prometheus、审计损坏/未知远端/过期积压告警和退出码。','外部告警接收器/实际生产负载尚需部署；未知用户日/人工正确率不推测。','airlock/operations.py airlock/observability.py scripts/operational_check.py','test_operations test_observability test_deepseek','pytest browser-native live-validation')
row('C12.3',I,PASS,'真实 DeepSeek 使用量与按官方高峰价的保守CNY估算分开；每次预占/结算、失败预占与总¥3预算有持久账本。','没有供应商账单/充值流水对账，不能把估算说成精确实扣。','airlock/semantic.py configs/deepseek-flash.example.json','test_deepseek','pytest live-validation ablation-live-dev ablation-live-test')
row('C12.4',I,PASS,'operator-only 导出，固定属性且不传 SQL/参数/凭据；503保留与重复spanID反例、审计失败不掩盖；HTTP配对开销实测。','未测生产跨上游链路开销或规模极限。','airlock/telemetry.py airlock/api.py scripts/measure_latency.py','test_telemetry test_new_boundaries','pytest latency container-integrations')
row('L0-1',I,PASS,'真实DeepSeek经HTTP gate驱动注册MCP上游请求/终态查询，独立批准才生效；官方SDK另测会话/SSE互通。','有界工具driver，非全部第三方host。','scripts/live_upstream.py tests/test_mcp_streamable.py','test_mcp_streamable test_sdk_interop','pytest live-upstream')
row('L0-6',I,PASS,'真实模型写申请被独立自动化 reviewer 拒绝后，实际只读 count 保留1206条和余额总和，未重试写入。','独立 reviewer 是脚本，不算真人；真实业务质量另待金标。','scripts/live_validation.py scripts/live_agent.py','test_live_agent_contract','pytest live-validation')
row('L0-7',I,PASS,'逐9状态审计schema完整率在受控fixture为100%，原始快照/转换链/字段与明确N-A；缺policy字段反例可检测。','','airlock/audit_schema.py tests/test_audit_completeness.py','test_audit_completeness')
row('B5',I,PASS,'关键词独立实现；pure/hybrid/no-preview/with-preview 三模型臂在dev120/test80真实调用，固定v1提示与参数，禁止副作用。','后续v2仅修复dev诊断的过长理由，未回写或冒充全套v2消融结果。','benchmark/ablation.py scripts/diagnose_model_schema.py','test_new_boundaries','pytest ablation-live-dev ablation-live-test model-contract-recheck')
row('B6',I,PASS,'逐例预测/原始原因/时延/影响/覆盖/成本及来源工具分层；危险语义预测与安全闸门保护率拆开，合法写送审不算模型危险命中。','真实四臂历史输出仍为作者合成标签；真实危险召回/FPR须独立金标。','benchmark/closure.py benchmark/research.py benchmark/ablation.py','test_research test_research_closure','pytest research-pipeline ablation-live-dev ablation-live-test')
row('D1',I,PASS,'FastAPI＋Next.js 16.3.8/React19.3.0已实现；静态导出/CSP哈希、Docker构建、真实原生交互复验，偏差关闭。','','frontend/app/page.jsx frontend/next.config.mjs Dockerfile package-lock.json','test_api','pytest browser-native browser-edges')
row('R3',I,PASS,'真实模型 SQL/伪角色/输出欺骗与工具说明/资源/拒绝文本攻击记录；模型无审批权，未授权效果0；UI长文本注入反例。','样本有限，不声称所有提示攻击成功率为0。','scripts/live_validation.py airlock/semantic.py scripts/browser_edges.py','test_semantic','pytest live-validation browser-edges')
row('A3',I,PASS,'原始审计/trace与阶段token费用、真实OTLP Collector、只读operator健康和Prometheus告警已实现。','生产跨服务内部span、告警接收器和账单仍需实际部署数据。','airlock/telemetry.py airlock/operations.py scripts/operational_check.py','test_operations test_telemetry','pytest container-integrations')
row('C9.3',I,PASS,'真实 DeepSeek Agent 使用固定工具经真实 HTTP 提交/查询，独立拒绝后安全只读；模型无 reviewer 权限。','独立审批方为自动化fixture；真人交互效果仍受阻。','scripts/live_agent.py scripts/live_validation.py','test_live_agent_contract','pytest live-validation')
# Autonomous 2026-10-03 additions retain every original criterion and its status.
def extend(id, scope, missing, files, tests, logs):
    r=RECORDS[id]
    r['scope']=scope
    r['actual_result']=scope
    r['uncovered_scope']=missing
    r['code_references']+=files.split()
    r['test_modules']+=tests.split()
    r['log_names']+=logs.split()

extend('C1.3','HTTP/MCP受控接入与真实模型counter路径保留；新增固定GitHub仓库Issue适配器，真实#6完成批准→单次relay创建→完整回读→unknown对账→6事件验链。',
    'GitHub relay收据是operator_attested；专用PAT direct路径只有离线契约，GitHub无目标CAS，通知/披露不能撤回；非任意工具透明代理。',
    'airlock/github_adapter.py scripts/github_adapter.py scripts/github_live_relay.py','test_github_adapter test_private_files','github-relay')
extend('C3.3','本地 exact 预演与受信CAS声明分开；GitHub create plan显式标记is_estimate/no_target_cas、1个Issue、通知数量未知及不完全可逆。',
    'GitHub预览是计划，不是隔离执行或真实通知数量；实际权限/可见性变化没有目标CAS。',
    'airlock/github_adapter.py','test_github_adapter','github-relay')
extend('C3.4','本地锁内复核与CAS工具保持原契约；GitHub绑定请求/配置/计划摘要并持久单次send，unknown不重发。',
    'append_only_create不声称目标状态CAS，实际创建前后的仓库外部变化窗口仍存在。',
    'airlock/github_adapter.py','test_github_adapter','github-relay')
extend('C6.2','独立审核路由和OIDC资源验证；新增Public Code+S256 PKCE、一次性callback、state/nonce与ID/access token绑定、私密导出和全交换超时子进程。',
    '真实IdP账号/配置及本人登录、IdP强制MFA仍受阻；本地模拟issuer不代表真实身份验收，没有两人quorum。',
    'airlock/oidc_login.py configs/oidc-login.example.json','test_oidc_login','')
extend('C6.5','本地原子回滚、CAS工具收据对账；GitHub并发/崩溃/丢响应仅单次send，未知结果按完整绑定只读回查或operator relay收据收敛。',
    '持久journal丢失/外部操作者额外写入不在保证内；GitHub无分布式exactly-once。',
    'airlock/github_adapter.py','test_github_adapter','github-relay')
extend('C10.2','审计链/检查点及独立S3 COMPLIANCE版本回读；新增专用可选STS session token，拒绝空token及全局AWS身份混入。',
    '实际长期云桶、独立保管权限与真实STS身份仍未提供；临时容器不是永久WORM。',
    'airlock/archive.py','test_archive','')
extend('C12.2','真实运维健康/看板与operator-only检查；新增固定HTTPS/pins、独立webhook凭据、持久同ID重试/去重/恢复/目标变化及真实loopback接收器验证。',
    '生产接收端和长期调度未部署；2xx只证明接收端接纳，lost response可同ID重试，接收端仍需去重。',
    'airlock/alert_delivery.py configs/alert-webhook.example.json','test_alert_delivery','')
extend('B1','200例40族合成回归、1个公开事故重构族、4条已授权GitHub维护轨迹及新增1条AIRLOCK relay实连轨迹；原始个人上下文留本机。',
    '5条GitHub记录仍为单一任务族，缺代表性多来源日常危险语料和独立真实标签。',
    'docs/USER_ACTIONS_20261003.md scripts/github_live_relay.py','test_github_adapter','github-relay')
extend('B3','真实双人模板/仲裁前κ工具保留；两模型完成4例成对标注，审批与可逆性0/4一致，模型schema禁止冒充真人。',
    '真人标注者0，human κ=null；模型标注不能替代独立人类gold或统计独立性。',
    'benchmark/model_roles.py scripts/model_roleplay.py','test_model_roles','model-roles model-ui-v2')
extend('C11.2','200例冻结与真实四臂历史实验保留；新增8次DeepSeek角色调用、模型成对标注和2模型8次原生UI模拟。发现并修复子模型ID泄露，旧结果标blinding_failure，fresh actor v2重验。',
    '真实独立双人gold、新保留集、真人A/B和代表性业务日数据仍缺；模型试验不进入human acceptance。',
    'benchmark/model_roles.py scripts/model_roleplay.py scripts/model_study_browser.py','test_model_roles','model-roles model-ui-v2')
for key in ('C11.1','C11.4'):
    RECORDS[key]['scope']=RECORDS[key]['scope'].replace('217 Python',str(len(JUNIT))+' Python')
for key in ('H1','H2','H3'):
    RECORDS[key]['scope']+=' 两模型8次v2原生UI模拟已完成并从真人统计排除。'
    RECORDS[key]['uncovered_scope']='真人参与者0；模型的正确率/时长不能替代真人体验阈值。真实业务独立gold缺失。'
    RECORDS[key]['code_references']+=['scripts/model_study_browser.py','benchmark/model_roles.py']
    RECORDS[key]['log_names']+=['model-ui-v2']

extend('T6','保留60对随机交替原始样本和100ms阈值；旧CI出现103.883ms失败后，提交路径复用一个连接并保持两次独立FULL提交；最终CI重新实测。',
    '本地SQLite/HTTP、并发1；不把Windows诊断视为Linux性能证明，也不外推生产尾延迟。',
    'airlock/service.py airlock/store.py tests/test_connection_lifecycle.py','test_connection_lifecycle','pytest')
for key in ('C6.5','C11.4','R1'):
    RECORDS[key]['scope']+=' SQLite运行时固定官方3.53.1并核验源码双摘要及实际source ID；不受确认的版本在打开持久WAL前拒绝。'
    RECORDS[key]['code_references']+=['airlock/sqlite_runtime.py','scripts/build_sqlite_runtime.py','configs/sqlite-runtime.json','tests/test_sqlite_runtime.py']
    RECORDS[key]['test_modules']+=['test_sqlite_runtime']
    RECORDS[key]['log_names']+=['sqlite-runtime-build','sqlite-runtime-linked']
for key in ('C11.1','C11.4','C6.5','R1','H1','H2','H3'):
    RECORDS[key]['actual_result']=RECORDS[key]['scope']

# Keep source references current without discarding individual original criteria.
for record in RECORDS.values():
    record['code_references']=[f.replace('airlock/static/app.js','frontend/app/page.jsx') for f in record['code_references']]


if (FINAL/'pilot-browser.json').exists():
    extend('B1',RECORDS['B1']['scope']+' 新增私密工作日志导入器，明确区分既有连接器执行轨迹与当前Issue观察快照；输入hash、授权出处和空白标注包保留。',
        RECORDS['B1']['uncovered_scope'], 'benchmark/worklog.py','test_worklog','')
    extend('B3',RECORDS['B3']['scope']+' 新增单人先导CSV/JSONL导入、覆盖与缺项检查；实际收到真人标注0，κ仍为null。',
        '用户目前可安排1人，尚未收到真实完成记录；正式双人独立要求保留。',
        'benchmark/pilot.py docs/START_WITH_ONE_PERSON.md','test_pilot','')
    extend('C12.2',RECORDS['C12.2']['scope']+' 新增独立通知收件箱，写入/查看凭据分离，同ID同载荷去重、冲突拒绝、持久分页与浏览器退出清空。',
        '本机自动化投递已测；长期远端TLS部署、渠道推送和真人确认送达仍未验证。',
        'airlock/alert_inbox.py','test_alert_inbox','pilot-browser')
    for key in ('H1','H2','H3','C11.2'):
        extend(key,RECORDS[key]['scope']+' 单人先导页面无需审批服务，8道GitHub作者练习题；n=1不输出置信区间或正式验收指标。',
            RECORDS[key]['uncovered_scope'],
            'benchmark/pilot.py scripts/pilot_server.py scripts/pilot_browser.py benchmark/pilot-github-tasks.json',
            'test_pilot test_pilot_server','pytest pilot-browser')
    for key in ('D2','C7.6'):
        RECORDS[key]['code_references']+=['docs/START_WITH_ONE_PERSON.md']
    RECORDS['G4']['uncovered_scope']+=' 本轮按用户要求暂缓。'


if (FINAL/'acceptance-matrix.log.status.json').exists():
    for key in ('C11.3','C11.4','D4'):
        RECORDS[key]['scope']+=' 双向核对原目标、父子证据、原始JUnit/日志hash与实际退出收据；性能从原始配对样本重算并严格判阈值。'
        RECORDS[key]['code_references']+=['docs/acceptance/validate_matrix.py','scripts/verify_evidence.py']
        RECORDS[key]['test_modules']+=['test_acceptance_matrix','test_evidence_gate','test_gate_cross_review']
        RECORDS[key]['log_names']+=['pytest','acceptance-matrix']
    for key in ('B2','B3','B7','H1','H2','H3','H4','H5'):
        RECORDS[key]['test_modules']+=['test_research_integrity']
    RECORDS['C12.2']['scope']+=' 通知outbox拒绝其他数据库，持久时间高水位防止乱序假恢复；健康来源未知用exit4且不发送恢复。'
    RECORDS['C12.2']['test_modules']+=['test_alert_delivery']
    for key in ('C6.4','C6.5'):
        RECORDS[key]['test_modules']+=['test_github_adapter']
    for key in ('C11.1','C11.4'):
        RECORDS[key]['scope']=RECORDS[key]['scope'].replace('23原生浏览器','31原生浏览器').replace('23浏览器','31浏览器')


for keys,module in [
    (('C6.2','C10.3','R4','R6'),'test_identity_boundaries'),
    (('C8.2','C8.3','C4.4','R4','R5'),'test_governance_integrity'),
    (('C1.2','C1.4','C1.5','A1','R2'),'test_transport_hardening'),
    (('C10.2','C10.4','D4'),'test_archive_integrity'),
    (('C12.1','C12.2','C12.4','A3'),'test_telemetry_integrity')]:
    for key in keys:
        RECORDS[key]['test_modules']+=[module]
        RECORDS[key]['log_names']+=['pytest']
RECORDS['C10.3']['scope']+=' 审计游标在范围过滤后分页，不被无权查看的事件前缀阻塞。'
RECORDS['C8.2']['scope']+=' 每个成员的事务内权限检查同时复核累计critical范围；上下文隔离并在异常后清理。'
RECORDS['C1.5']['scope']+=' 网络总截止覆盖DNS、响应头及body；拒绝重复JSON键、非有限数、无效Unicode和过深响应。'
RECORDS['C10.2']['scope']+=' 收据与下载checkpoint的库/序号/对象key/版本严格绑定；过期保留不作为当前不可变保管。'
RECORDS['C12.4']['scope']+=' OTLP异常确认保留待发span，总截止约束慢头；并发成功按实际持久删除数计数。'
for key in ('C10.3','C8.2','C1.5','C10.2','C12.4'):
    RECORDS[key]['actual_result']=RECORDS[key]['scope']


def build():
    targets=[]
    for original in INDEX['targets']:
        id=original['id']
        if id in RECORDS:
            r=dict(RECORDS[id]);modules=r.pop('test_modules');names=r.pop('log_names')
            receipts=[(name,json.loads(log_path(name).with_suffix('.log.status.json').read_text())) for name in names]
            r.update(id=id,parent_id=original.get('parent_id'),criterion=original.get('criterion') or original.get('title'),
                requirement_origin='docs/CODEX_FULL_AUDIT_BRIEF.md and original acceptance index; no goals removed',
                tested_commit_sha=SHA,test_ids=[c.get('classname','')+'::'+c.get('name','') for c in JUNIT if any(c.get('classname','').endswith(m) for m in modules)],
                commands=[{'command':s['command'],'tested_commit_sha':s['tested_commit_sha'],
                    'tracked_source_dirty':s['tracked_source_dirty'],
                    'evidence_role':'supporting_precommit_experiment' if s['tracked_source_dirty'] else 'frozen_source_validation',
                    'receipt':str(log_path(name).with_suffix('.log.status.json').relative_to(ROOT)).replace('\\','/')} for name,s in receipts],
                exit_codes=[{'command':name,'exit_code':s['exit_code'],'environment':'Ubuntu runner' if log_path(name).is_relative_to(FINAL) else 'Windows local'} for name,s in receipts],
                evidence=[str(log_path(name).relative_to(ROOT)).replace('\\','/') for name,s in receipts],
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
            if id=='E1':
                r['evidence']=['evidence/closure-20261002/ECOSYSTEM_FACTS.json']
                r['commands']=[{'command':'Read-only GitHub repository API and Firecrawl public contributors API review','receipt':r['evidence'][0],'process_exit_code_applicable':False}]
            if id=='E4':
                r['evidence']=['evidence/closure-20261002/REPLIT_FIRST_PARTY.json','docs/RESEARCH.md']
                r['commands']=[{'command':'First-party source and explicit repository-scoped comparison review','receipt':r['evidence'][0],'process_exit_code_applicable':False}]
            if id=='C11.3':
                r['evidence']+=['evidence/full-audit-20261002/ci-negative-control-job.log','evidence/full-audit-20261002/ci-negative-control.json']
                r['commands'].append({'command':['python','scripts/run_logged.py','evidence/negative-control.log','--','python','-c','raise SystemExit(23)'],'tested_commit_sha':'89c32625a49f7744389efe6284e942eee5a82332','run_url':'https://github.com/Changxin-YR/AIRLOCK/actions/runs/36986618577'})
                r['exit_codes'].append({'command':'intentional-negative-control','exit_code':23,'environment':'Ubuntu runner','expected_failure':True})
            if id in {'T6','C11.3','C11.4'}:
                r['evidence']+=['evidence/autonomous-20261003/ci/failed-a68b11b-job.log',
                    'evidence/autonomous-20261003/ci/failed-a68b11b.json',
                    'evidence/autonomous-20261003/ci/failed-latency.json']
                r['commands'].append({'command':'Historical failed latency acceptance gate; all 60 pairs preserved',
                    'tested_commit_sha':'a68b11b39c2c2ed41e18d9001b90b66dcb652ba4',
                    'run_url':'https://github.com/Changxin-YR/AIRLOCK/actions/runs/37085024673'})
                r['exit_codes'].append({'command':'historical-latency-verifier','exit_code':1,'environment':'Ubuntu runner',
                    'historical_failure':True,'basis':'actual verify_evidence step failed at read added p95=103.883327ms'})
            if id in {'A2','C11.1','C11.3','C11.4','R1','K5','G1','C2.5','C12.1','D1'}:
                ci=json.loads(CI_META.read_text())
                r['evidence']+=ci['git_evidence']
                r['commands'].append({'command':'GitHub Actions verify job and downloaded ZIP evidence verifier','run_url':ci['url'],'tested_commit_sha':ci['tested_commit_sha']})
                r['exit_codes'].append({'command':'GitHub Actions verify job','exit_code':0,'environment':'Ubuntu runner','basis':'actual child receipts and downloaded artifact verifier'})
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
    result={'schema_version':2,'phase':'controlled_closure_and_external_research_blockers','baseline_commit':INDEX['historical_base_commit'],
        'tested_commit_sha':SHA,'junit_evidence':str((FINAL/'pytest.xml').relative_to(ROOT)).replace('\\','/'),'target_count':126,'original_goals_all_satisfied':False,
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
