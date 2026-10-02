import {el, number, short, date, states, risks, countdown, canApprove} from './lib.js';

function rowText(row) {
  if (!row) return '不存在';
  return `${row.name} · ${row.tier} · 余额 ${number(row.balance)} 分`;
}
export function reviewPanel(action, draft, busy, decide, clock) {
  if (!action) return el('section', {class: 'empty detail'}, el('span', {class:'empty-mark'}, '✓'),
    el('h2', {}, '当前没有需要处理的动作'), el('p', {}, '从左侧选择记录，或通过演示 Agent 提交新的 SQL。'),
    el('code', {}, 'python scripts/demo_agent.py --scenario delete'));
  const impact = action.impact;
  const title = impact ? ({delete:'删除', update:'更新', insert:'新增'}[impact.operations[0]] || '变更') + '数据 · customers' : '工具调用记录';
  const summary = el('section', {class:`impact ${action.risk}`, id:'impact-summary'},
    el('div', {class:'section-top'}, el('span', {class:'label'}, '快照内实际变更'), el('span', {class:`tag ${action.risk}`}, risks[action.risk])),
    el('div', {class:'impact-number'}, number(impact?.changed_rows), el('span', {}, ' 行')),
    el('p', {}, impact ? `记录数 ${number(impact.before_count)} → ${number(impact.after_count)}；匹配 ${number(impact.matched_rows)} 行。` : '此调用未进入写入预演。'),
    el('span', {class:'certainty'}, impact ? '精确预演 · 仅对本次受限快照成立' : action.reason_code));
  const form = el('div', {class:'review-form'});
  if (action.state === 'pending') {
    const approve = el('button', {class:'button primary', id:'approve', disabled:busy || !canApprove(action,draft)}, '批准并执行');
    const reject = el('button', {class:'button reject', id:'reject', disabled:busy || draft.reason.trim().length < 3}, '拒绝本次操作');
    const sync = () => { approve.disabled = busy || !canApprove(action,draft); reject.disabled = busy || draft.reason.trim().length < 3; };
    approve.addEventListener('click', () => decide(action, 'approve', draft, clock.value()));
    reject.addEventListener('click', () => decide(action, 'reject', draft, clock.value()));
    form.append(el('h3', {}, '你的决定'),
      el('label', {for:'reason'}, '决策依据（至少 3 个字符，会写入审计）'),
      el('textarea', {id:'reason', 'data-field':'reason', maxlength:500, rows:2, placeholder:'说明授权依据、核验结果或拒绝原因…', value:draft.reason,
        oninput:event => { draft.reason=event.target.value; sync(); }}));
    if (action.confirmation_required) form.append(
      el('label', {for:'confirmation'}, '高影响操作：输入 ', el('code', {}, action.confirmation_required), ' 确认范围'),
      el('input', {id:'confirmation', 'data-field':'confirmation', autocomplete:'off', spellcheck:'false', value:draft.confirmation,
        oninput:event => { draft.confirmation=event.target.value; sync(); }}));
    form.append(el('label', {class:'check'}, el('input', {type:'checkbox', id:'ack', 'data-field':'ack', checked:draft.checked,
      onchange:event => { draft.checked=event.target.checked; sync(); }}), '我已核对变更范围，并了解提交后无法自动撤销。'),
      el('div', {class:'decision-buttons'}, reject, approve),
      el('p', {class:'muted small'}, '批准仅对当前参数与快照有效；服务端会在执行前再次校验。'));
  } else form.append(el('div', {class:`outcome ${action.state}`, role:'status'}, el('strong', {}, states[action.state]),
    el('p', {}, action.reason_code), el('span', {class:'small'}, action.state === 'executed' ? '该请求已执行；以下仍保留审批时的原始快照。' : '该请求未执行。需要修改意图时，请提交新的动作。')));
  return el('section', {class:'detail'},
    el('div', {class:'detail-heading'}, el('div', {}, el('h2', {}, title), el('p', {class:'muted small'}, `#${short(action.id)} · ${action.principal}`)),
      el('span', {class:`tag ${action.state}`}, states[action.state])),
    summary,
    impact && el('div', {class:'warning'}, el('strong', {}, '恢复能力未知，不等于可以撤销'),
      el('p', {}, '未提供可验证备份；本项目不承诺自动恢复。不可逆风险不能通过频繁批准被自动降级。')),
    el('section', {class:'section'}, el('div', {class:'section-top'}, el('h3', {}, action.state==='pending' ? '待执行 SQL' : 'SQL 原始请求'), el('span', {class:'muted small'}, '参数独立绑定')),
      el('pre', {class:'sql'}, el('code', {}, action.request.sql)),
      action.request.parameters.length > 0 && el('p', {class:'parameters'}, JSON.stringify(action.request.parameters))),
    impact && el('section', {class:'section'}, el('div', {class:'section-top'}, el('h3', {}, '变更对照'),
      el('span', {class:'muted small'}, impact.sample_truncated ? '仅展示前 5 条变更；不是完整清单' : '完整变更样本')),
      el('div', {class:'table-scroll'}, el('table', {}, el('thead', {}, el('tr', {}, ['ID','变更前','变更后'].map(t=>el('th', {}, t)))),
        el('tbody', {}, impact.sample.map(row=>el('tr', {}, el('td', {class:'mono'}, row.id), el('td', {}, rowText(row.before)),
          el('td', {class:row.after?'':'deleted'}, row.after ? rowText(row.after) : '删除整行')))))),
      impact.changed_rows === 0 && el('p', {class:'muted'}, '没有值发生变化，但这仍是写操作，需要授权。')),
    !impact && action.result && el('section', {class:'section'}, el('h3', {}, '执行结果'), el('pre', {class:'result'}, JSON.stringify(action.result,null,2))),
    el('div', {class:'binding'}, el('span', {}, `快照 ${short(impact?.before_hash) || '—'}`), el('span', {}, `策略 ${short(action.policy_version)}`),
      action.state === 'pending' ? el('span', {id:'countdown', 'data-expires':action.expires_at}, `剩余 ${countdown(action.expires_at)}`) : el('span', {}, date(action.created_at))),
    form);
}
