'use client';
import {useCallback,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {Api} from '../../airlock/static/api.js';
import {reviewPanel} from '../../airlock/static/review.js';
import {groupsPanel,metricsPanel} from '../../airlock/static/governance.js';
import {number,short,date,states,ReviewClock,duration,countdown} from '../../airlock/static/lib.js';

const navigation=[['pending','审批队列'],['groups','请求归并'],['all','执行记录'],['audit','审计回放'],['metrics','运行指标']];

// The reviewed DOM renderers remain small, escaped view adapters. React owns
// authentication, data fetching, navigation and lifetimes; they never own auth.
function EvidencePanel({kind,action,draft,busy,onDecision,clock,groups,groupDrafts,metrics,onGroup}){
  const ref=useRef(null);
  useLayoutEffect(()=>{
    const focused=ref.current.contains(document.activeElement)?document.activeElement:null;
    const field=focused?.dataset.field;
    const selection=focused&&['TEXTAREA','INPUT'].includes(focused.tagName)?[focused.selectionStart,focused.selectionEnd]:null;
    ref.current.replaceChildren(kind==='groups'?groupsPanel(groups,groupDrafts,busy,onGroup):kind==='metrics'?metricsPanel(metrics):reviewPanel(action,draft,busy,onDecision,clock));
    if(field){const next=[...ref.current.querySelectorAll('[data-field]')].find(e=>e.dataset.field===field);if(next){next.focus({preventScroll:true});if(selection?.[0]!=null&&next.type!=='checkbox')next.setSelectionRange(...selection);}}
    const summary=ref.current.querySelector('#impact-summary');
    const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){clock.firstVisible();clock.active(!document.hidden);observer.disconnect();}},{threshold:.5});
    if(summary)observer.observe(summary);
    return ()=>{observer.disconnect();clock.active(false);};
  },[kind,action,draft,busy,onDecision,clock,groups,groupDrafts,metrics,onGroup]);
  return <div ref={ref} className="evidence-panel"/>;
}

function Audit({items,verification,onVerify,onMore}){
  return <section className="audit-panel"><div className="section-top"><div><h2>审批证据回放</h2><p className="muted">回放当时保存的快照，而不是事后重新计算影响。</p></div><button className="button" onClick={onVerify}>验证审计链</button></div>
    {verification&&<div role="status" className={verification.valid?'audit-verdict':'error'}>HMAC 链{verification.valid?'校验通过':'校验失败'} · {verification.events} 个事件 · 链头 {short(verification.head)} · 外部检查点 {verification.anchor_status}</div>}
    <p className="warning small">检查点应保存在服务器无写权限的位置。最近检查点之后的截尾，以及服务器与全部密钥同时失陷，仍无法由本地链证明。</p>
    <ol className="timeline">{items.map(item=>{const e=item.event,d=e.detail||{},snapshot=d.snapshot;return <li key={item.seq}><div className="section-top"><strong>{states[e.state]||e.kind} · #{short(item.action_id)}</strong><time className="muted small">{date(e.at)}</time></div>
      <p className="small">{snapshot?`${snapshot.request.sql||snapshot.request.tool} · 原始影响 ${number(snapshot.impact?.changed_rows)} 行`:`${d.reviewer||'system'} · ${d.reason||e.kind}`}</p>
      {d.visible_ms_untrusted!=null&&<p className="small muted">前台查看时长 {number(d.visible_ms_untrusted)} ms（客户端遥测，不是安全依据）</p>}
      <details><summary>查看签名与原始证据</summary><pre className="result">{JSON.stringify(item,null,2)}</pre></details></li>;})}</ol>
    {!items.length&&<p className="empty">尚无审计事件。</p>}<button className="button" onClick={onMore}>继续加载事件</button></section>;
}

export default function Console(){
  const [api,setApi]=useState(null),[credential,setCredential]=useState(''),[loginBusy,setLoginBusy]=useState(false);
  const [view,setView]=useState('pending'),[actions,setActions]=useState([]),[metrics,setMetrics]=useState(null),[groups,setGroups]=useState([]);
  const [selected,setSelected]=useState(null),[filter,setFilter]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[loading,setLoading]=useState(false);
  const [next,setNext]=useState(null),[connection,setConnection]=useState('已登录'),[audit,setAudit]=useState([]),[auditCursor,setAuditCursor]=useState(0),[verification,setVerification]=useState(null);
  const drafts=useRef(new Map()),clocks=useRef(new Map()),groupDrafts=useRef(new Map()),run=useRef(0),currentApi=useRef(null),refreshRef=useRef(null);
  const action=actions.find(a=>a.id===selected);
  if(!drafts.current.has(selected))drafts.current.set(selected,{reason:'',confirmation:'',checked:false});
  if(!clocks.current.has(selected))clocks.current.set(selected,new ReviewClock());
  const activeClock=clocks.current.get(selected);
  const refresh=useCallback(async(more=false)=>{
    if(!api)return;
    const generation=++run.current;setLoading(true);
    try{
      let path='/v1/actions?limit=100'+(view==='pending'?'&state=pending':'');
      if(more&&next)path+=`&before=${next.before}&before_id=${next.before_id}`;
      const [list,data,grouped]=await Promise.all([api.request(path),api.request('/v1/metrics'),api.request('/v1/groups')]);
      if(generation!==run.current||currentApi.current!==api)return;
      if(selected&&!list.items.some(a=>a.id===selected)){try{list.items.push(await api.request('/v1/actions/'+selected));}catch{/* Scope may have been revoked. */}}
      if(generation!==run.current||currentApi.current!==api)return;
      setActions(old=>[...new Map((more?[...old,...list.items]:list.items).map(a=>[a.id,a])).values()]);
      setMetrics(data);setGroups(grouped.items);setNext(list.next_cursor);
      setSelected(old=>list.items.some(a=>a.id===old)?old:list.items.find(a=>a.state==='pending')?.id||list.items[0]?.id||null);setError('');
    }catch(e){if(generation===run.current&&currentApi.current===api)setError(e.message);}
    finally{if(generation===run.current)setLoading(false);}
  },[api,view,next,selected]);
  refreshRef.current=refresh;
  useEffect(()=>{if(api)void refreshRef.current();},[api,view]);
  useEffect(()=>{
    if(!api)return;
    const controller=new AbortController();let timer;
    void api.events(controller.signal,()=>{clearTimeout(timer);timer=setTimeout(()=>void refreshRef.current(),180);},setConnection);
    return ()=>{controller.abort();clearTimeout(timer);};
  },[api]);
  useEffect(()=>{
    const active=()=>{for(const [id,clock] of clocks.current)clock.active(id===selected&&['pending','all'].includes(view)&&!document.hidden);};
    active();document.addEventListener('visibilitychange',active);
    return ()=>{document.removeEventListener('visibilitychange',active);for(const clock of clocks.current.values())clock.active(false);};
  },[selected,view]);
  useEffect(()=>{const timer=setInterval(()=>{const node=document.querySelector('#countdown');if(node)node.textContent='剩余 '+countdown(Number(node.dataset.expires));},1000);return ()=>clearInterval(timer);},[]);
  async function login(event){
    event.preventDefault();setLoginBusy(true);setError('');const candidate=new Api(credential.trim());
    try{const me=await candidate.request('/v1/me');if(me.role!=='reviewer')throw new Error('此处仅接受审批人凭据，不能使用 Agent 凭据。');setCredential('');currentApi.current=candidate;setApi(candidate);}
    catch(e){setError(e.message);}finally{setLoginBusy(false);}
  }
  function logout(){run.current++;currentApi.current=null;setApi(null);setCredential('');setActions([]);setMetrics(null);setGroups([]);setSelected(null);setError('');setBusy(false);setLoading(false);setView('pending');setFilter('');setNext(null);setAudit([]);setAuditCursor(0);setVerification(null);drafts.current.clear();groupDrafts.current.clear();for(const c of clocks.current.values())c.active(false);clocks.current.clear();}
  const decide=useCallback(async(action,value,form,visible)=>{
    if(busy)return;setBusy(true);setError('');const current=api;
    try{await current.request(`/v1/actions/${action.id}/decision`,{decision:value,review_digest:action.review_digest,expected_version:action.version,reason:form.reason.trim(),confirmation:form.confirmation,visible_ms:visible});if(currentApi.current===current)await refreshRef.current();}
    catch(e){if(currentApi.current===current)setError(e.message+'；请刷新并核实该动作状态。');}finally{if(currentApi.current===current)setBusy(false);}
  },[api,busy]);
  const decideGroup=useCallback(async(group,value,draft)=>{
    if(busy)return;setBusy(true);setError('');const current=api;
    try{const result=await current.request('/v1/groups/decision',{group_id:group.id,group_digest:group.digest,member_ids:group.members.map(a=>a.id),decision:value,reason:draft.reason.trim(),confirmation:draft.confirmation});if(currentApi.current!==current)return;await refreshRef.current();if(result.receipts.some(r=>['stale','conflict'].includes(r.state)))setError('部分成员快照失效或冲突，请核对执行记录。');}
    catch(e){if(currentApi.current===current)setError(e.message);}finally{if(currentApi.current===current)setBusy(false);}
  },[api,busy]);
  async function loadAudit(more=false){const current=api;try{const data=await current.request('/v1/audit?after='+(more?auditCursor:0));if(currentApi.current!==current)return;setAudit(old=>more?[...old,...data.items]:data.items);setAuditCursor(data.next_after);}catch(e){if(currentApi.current===current)setError(e.message);}}
  function navigate(key){setView(key);setNext(null);if(key==='audit')void loadAudit();}
  if(!api)return <main className="login-screen"><section className="login-card"><div className="brand dark"><span className="logo">A</span><span>AIRLOCK</span></div><h1>把执行权留在闸门内。</h1><p className="muted">登录知情审批台，先看影响，再做决定。</p>
    <form onSubmit={login}><label htmlFor="credential">审批人凭据</label><input id="credential" type="password" value={credential} onChange={e=>setCredential(e.target.value)} required autoComplete="off" placeholder="AIRLOCK_REVIEWER_TOKEN"/><button id="login-button" className="button primary" disabled={loginBusy}>{loginBusy?'验证身份…':'进入审批台'}</button></form>
    {error&&<p className="error" role="alert">{error}</p>}<div className="login-note"><strong>凭据只保存在当前页面内存中</strong><p>刷新页面后需要重新登录。审批凭据与 Agent 凭据分别保管。</p></div><p className="small muted">个人项目 · 合成演示数据</p></section></main>;
  const filtered=actions.filter(a=>(view!=='pending'||a.state==='pending')&&(a.request.sql||a.request.tool).toLowerCase().includes(filter.toLowerCase()));
  return <div className="shell"><aside className="sidebar"><div className="brand"><span className="logo">A</span><span>AIRLOCK</span></div><p className="sidebar-caption">服务端执行审批</p><nav aria-label="主导航">{navigation.map(([key,label])=><button key={key} className={view===key?'nav active':'nav'} aria-label={label} aria-current={view===key?'page':undefined} onClick={()=>navigate(key)}>{label}{key==='pending'&&<span className="nav-count">{metrics?.states.pending||0}</span>}</button>)}</nav><div className="sidebar-foot"><strong>默认不放行</strong><p>Agent 发起意图。<br/>服务端持有执行权。</p><span className="small">Personal project</span></div></aside>
    <main className="workspace"><header className="header"><div><h1>{view==='audit'?'审计回放':'审批工作台'}</h1><p className="muted small">SQLite · customers · 合成演示数据</p></div><div className="header-actions"><span id="connection" className="connection">{connection}</span><button className="button quiet" onClick={()=>void refresh()}>刷新</button><button className="button quiet" onClick={logout}>退出</button></div></header>
      {error&&<div className="error" role="alert">{error}</div>}<section className="stats" aria-label="实际运行统计">{[['待审批',number(metrics?.states.pending||0),'副作用尚未执行'],['当前数据',number(metrics?.customers),'customers 表实际行数'],['评估 p95',duration(metrics?.evaluation_p95_ms),'内部评估 · 不含提交/网络/人等待']].map(([label,value,hint])=><div className="stat" key={label}><span className="muted small">{label}</span><strong>{value}</strong><span className="muted small">{hint}</span></div>)}</section>
      {view==='audit'?<Audit items={audit} verification={verification} onMore={()=>void loadAudit(true)} onVerify={async()=>{const current=api;try{const result=await current.request('/v1/audit/verify');if(currentApi.current===current)setVerification(result);}catch(e){if(currentApi.current===current)setError(e.message);}}}/>:
      <div className={['pending','all'].includes(view)?'workbench':'standalone-panel'}>{['pending','all'].includes(view)&&<section className="queue" aria-label="动作列表"><div className="queue-head"><h2>{view==='pending'?'待处理队列':'动作记录'}</h2><span className="muted small">{filtered.length} 条已加载</span></div><label className="sr-only" htmlFor="search">搜索 SQL</label><input id="search" data-field="search" type="search" placeholder="搜索已加载的 SQL…" value={filter} onChange={e=>setFilter(e.target.value)}/><div className="queue-items">{filtered.map(a=><button key={a.id} className={`action-row ${a.id===selected?'selected':''}`} data-action={a.id} aria-pressed={a.id===selected} onClick={()=>setSelected(a.id)}><div className="section-top"><span className={`tag ${a.state}`}>{states[a.state]}</span><span className="small muted">#{short(a.id)}</span></div><code className="queue-sql">{a.request.sql||a.request.tool}</code><div className="section-top small"><span>{a.impact?`${number(a.impact.changed_rows)} 影响单位`:'无写入预演'}</span><span className="muted">{new Date(a.created_at*1000).toLocaleTimeString('zh-CN',{hour12:false})}</span></div></button>)}</div>{!filtered.length&&<div className="empty"><strong>{loading?'正在加载':'当前没有匹配的记录'}</strong><p>可清除搜索条件或刷新；数量以服务器状态为准。</p></div>}{next&&<button className="button more" onClick={()=>void refresh(true)}>加载更早记录</button>}</section>}
      <EvidencePanel kind={view} action={action} draft={drafts.current.get(selected)} busy={busy} onDecision={decide} clock={activeClock} groups={groups} groupDrafts={groupDrafts.current} metrics={metrics} onGroup={decideGroup}/></div>}
      <footer className="footer">所有写入都需要独立审批；未知能力默认阻断。审批通过不代表业务决策一定正确。</footer></main></div>;
}
