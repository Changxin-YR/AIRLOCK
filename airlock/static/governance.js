import {el,number,duration,short,states} from './lib.js';

export function groupsPanel(groups,drafts,busy,decide) {
  return el('section',{class:'audit-panel'},el('h2',{},'相似请求与批量决定'),
    el('p',{class:'warning'},'成员按申请人、工具、资源、策略、风险、审批范围和当前时间窗口分组。批准后逐项校验；前项可能使后项快照失效。'),
    !groups.length&&el('p',{},'尚无待审批请求组。'),groups.map(group=>{
      const key=group.id+group.digest;
      if(!drafts.has(key)) drafts.set(key,{reason:'',confirmation:'',checked:false});
      const draft=drafts.get(key);
      const approve=el('button',{class:'button primary',disabled:true},'批准列出的成员');
      const reject=el('button',{class:'button reject',disabled:true},'拒绝列出的成员');
      const sync=()=>{approve.disabled=reject.disabled=busy||!draft.checked||draft.reason.trim().length<3||draft.confirmation!==group.confirmation_required;};
      approve.addEventListener('click',()=>decide(group,'approve',draft)); reject.addEventListener('click',()=>decide(group,'reject',draft));sync();
      return el('section',{class:'section','data-group':group.id},el('h3',{},`${group.members.length} 个成员 · 累计 ${number(group.cumulative_units)} 影响单位`),
        el('p',{class:'muted small'},`组摘要 ${short(group.digest)} · 未包含未来加入的成员`),
        el('ol',{},group.members.map(a=>el('li',{},el('strong',{},`#${short(a.id)} · ${a.resource} · ${states[a.state]}`),
          el('pre',{class:'sql'},a.request.sql||JSON.stringify(a.request.arguments)),
          el('p',{},`变化 ${number(a.impact.changed_rows)} · 匹配 ${number(a.impact.matched_rows)} · 快照 ${short(a.review_digest)}`),
          el('details',{},el('summary',{},'核对成员完整影响快照'),el('pre',{class:'result'},JSON.stringify(a.impact,null,2)))))),
        el('label',{},'共同决策依据',el('textarea',{'data-field':'group-reason-'+group.id,value:draft.reason,maxlength:500,
          oninput:e=>{draft.reason=e.target.value;sync();}})),
        el('label',{},`输入 ${group.confirmation_required}`,el('input',{'data-field':'group-confirm-'+group.id,value:draft.confirmation,
          oninput:e=>{draft.confirmation=e.target.value;sync();}})),
        el('label',{class:'check'},el('input',{type:'checkbox',checked:draft.checked,onchange:e=>{draft.checked=e.target.checked;sync();}}),'我已逐项核对上面列出的全部成员与累计影响'),
        el('div',{class:'decision-buttons'},reject,approve));
    }));
}

export function metricsPanel(metrics) {
  if(!metrics) return el('section',{class:'audit-panel'},'尚无数据');
  const semantic=metrics.semantic||{};
  return el('section',{class:'audit-panel'},el('h2',{},'运行指标'),el('p',{class:'muted'},metrics.scope),
    el('h3',{},'阶段时延'),el('div',{class:'table-scroll'},el('table',{class:'metrics-table'},
      el('thead',{},el('tr',{},['阶段','样本数','p50','p95','p99'].map(v=>el('th',{},v)))),
      el('tbody',{},Object.entries(metrics.stages_ms||{}).map(([key,v])=>el('tr',{},el('td',{},key),el('td',{},v.n),
        ...['p50','p95','p99'].map(q=>el('td',{},v[q]==null?'尚无数据':duration(v[q])))))))),
    el('h3',{},'模型、成本与缓存'),el('p',{},`有效供应商回执 ${semantic.provider_receipts||0} · 应用结果缓存命中 ${semantic.application_cache_hits||0} · 评估错误 ${semantic.errors||0}`),
    el('p',{},`输入 token ${number(semantic.input_tokens)} · 输出 token ${number(semantic.output_tokens)} · 供应商 cache-read ${number(semantic.provider_cache_read_tokens)}`),
    el('p',{},Object.keys(semantic.cost_by_currency||{}).length ? `按所配价格表计算费用：${Object.entries(semantic.cost_by_currency).map(([unit,value])=>`${unit} ${value==null?'尚无完整用量':value.toFixed(6)}`).join(' · ')}` : semantic.cost_usd==null?'费用：尚无完整 usage 与价格证据':`按所配价格表计算费用：USD ${semantic.cost_usd.toFixed(6)}`),
    metrics.provider_admission&&el('pre',{class:'result'},JSON.stringify(metrics.provider_admission,null,2)),
    metrics.telemetry&&el('p',{},`遥测：待导出 ${metrics.telemetry.pending_spans} · 已导出 ${metrics.telemetry.exported_spans} · 容量丢弃 ${metrics.telemetry.dropped_spans}`),
    el('p',{class:'muted'},'应用结果缓存与供应商 prompt cache 分开计量。无数据不表示费用为零；这些指标不参与授权。'),
    el('h3',{},'三态分布与预演覆盖'),el('pre',{class:'result'},JSON.stringify({decisions:metrics.decisions,preview_coverage:metrics.preview_coverage,idempotent_receipts_total:metrics.idempotent_receipts_total,governance:metrics.governance},null,2)));
}
