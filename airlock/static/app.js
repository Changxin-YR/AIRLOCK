import {el, number, short, date, states, countdown, ReviewClock, duration} from './lib.js';
import {Api} from './api.js';
import {reviewPanel} from './review.js';

const root=document.querySelector('#app');
let api=null, eventController=null, generation=0, refreshTimer=null, observing=null;
const state={actions:[], metrics:null, selected:null, view:'pending', filter:'', error:'', busy:false, loading:false, audit:[], auditCursor:0, verification:null, next:null,connection:'已登录'};
const drafts=new Map(), clocks=new Map();
function draft(id) { if(!drafts.has(id)) drafts.set(id,{reason:'',confirmation:'',checked:false}); return drafts.get(id); }
function clock(id) { if(!clocks.has(id)) clocks.set(id,new ReviewClock()); return clocks.get(id); }
function setActiveClock() { for(const [id,c] of clocks) c.active(id===state.selected && state.view!=='audit' && !document.hidden); }
document.addEventListener('visibilitychange', setActiveClock);
function selected() { return state.actions.find(a=>a.id===state.selected); }
function select(id) { state.selected=id; setActiveClock(); render(); }
function status(text) { state.connection=text; const element=document.querySelector('#connection'); if(element) element.textContent=text; }
function logout() {
  generation++; eventController?.abort(); clearTimeout(refreshTimer); observing?.disconnect(); api=null;
  for(const c of clocks.values()) c.active(false);
  clocks.clear(); drafts.clear();
  Object.assign(state,{actions:[],metrics:null,selected:null,error:'',busy:false,loading:false,audit:[],auditCursor:0,verification:null,next:null,view:'pending',filter:'',connection:'已登录'});
  login();
}
function login(message='') {
  root.replaceChildren(el('main',{class:'login-screen'}, el('section',{class:'login-card'},
    el('div',{class:'brand dark'}, el('span',{class:'logo'},'A'),el('span',{},'AIRLOCK')),
    el('h1',{},'把执行权留在闸门内。'), el('p',{class:'muted'},'登录知情审批台，先看影响，再做决定。'),
    el('form',{onsubmit:async event=>{
      event.preventDefault(); const input=document.querySelector('#credential'), button=document.querySelector('#login-button');
      button.disabled=true; button.textContent='验证身份…';
      const candidate=new Api(input.value.trim());
      try {
        const me=await candidate.request('/v1/me');
        if(me.principal!=='reviewer:owner') throw new Error('此处仅接受审批人凭据，不能使用 Agent 凭据。');
        input.value=''; api=candidate; await refresh();
        eventController=new AbortController();
        void api.events(eventController.signal,()=>{clearTimeout(refreshTimer);refreshTimer=setTimeout(()=>void refresh(),180);},status);
      } catch(error) { api=null; login(error.message); }
    }}, el('label',{for:'credential'},'审批人凭据'), el('input',{id:'credential',type:'password',required:true,autocomplete:'off',placeholder:'AIRLOCK_REVIEWER_TOKEN'}),
      el('button',{class:'button primary',id:'login-button',type:'submit'},'进入审批台')),
    message && el('p',{class:'error',role:'alert'},message),
    el('div',{class:'login-note'},el('strong',{},'凭据只保存在当前页面内存中'),
      el('p',{},'刷新页面后需要重新登录。不要把审批凭据提供给 Agent，也不要共享本地数据库目录。')),
    el('p',{class:'small muted'},'个人项目 · 固定 SQLite 演示数据 · 非生产安全产品'))));
}
async function refresh(loadMore=false) {
  const current=api, run=generation, requestedView=state.view;
  if(!current || state.loading) return;
  state.loading=true;
  try {
    let path='/v1/actions?limit=100'+(requestedView==='pending'?'&state=pending':'');
    if(loadMore && state.next) path+=`&before=${state.next.before}&before_id=${state.next.before_id}`;
    const [list,metrics]=await Promise.all([current.request(path),current.request('/v1/metrics')]);
    if(current!==api || generation!==run || requestedView!==state.view) return;
    const keep=state.selected;
    const merged=loadMore ? [...state.actions,...list.items] : list.items;
    state.actions=Array.from(new Map(merged.map(a=>[a.id,a])).values()); state.metrics=metrics; state.next=list.next_cursor;
    if(keep && !state.actions.some(a=>a.id===keep)) {
      try { const item=await current.request('/v1/actions/'+keep); if(current===api) state.actions.push(item); } catch { /* Removed or no longer accessible. */ }
    }
    if(current!==api || generation!==run || requestedView!==state.view) return;
    if(!selected()) state.selected=state.actions.find(a=>a.state==='pending')?.id || state.actions[0]?.id || null;
    state.error='';
  } catch(error) { if(current===api) state.error=error.message; }
  finally { if(current===api) {state.loading=false;setActiveClock();render();if(requestedView!==state.view) void refresh();} }
}
async function decide(action,value,form,visibleMs) {
  if(state.busy) return;
  state.busy=true;state.error='';render();
  const current=api;
  try {
    await current.request(`/v1/actions/${action.id}/decision`,{decision:value, review_digest:action.review_digest,
      expected_version:action.version, reason:form.reason.trim(), confirmation:form.confirmation,visible_ms:visibleMs});
    await refresh();
  } catch(error) { if(current===api) state.error=`${error.message}；请刷新并核实该动作状态。`; }
  finally { if(current===api) {state.busy=false;render();} }
}
async function loadAudit(more=false) {
  const current=api;
  try {
    const data=await current.request('/v1/audit?after='+(more?state.auditCursor:0));
    if(current!==api) return;
    state.audit=more?[...state.audit,...data.items]:data.items;state.auditCursor=data.next_after;state.error='';render();
  } catch(error) { if(current===api) {state.error=error.message;render();} }
}
function navigation(view) { state.view=view;state.next=null;setActiveClock();render();if(view==='audit') void loadAudit();else void refresh(); }
function auditPanel() {
  return el('section',{class:'audit-panel'},el('div',{class:'section-top'},el('div',{},el('h2',{},'审批证据回放'),
    el('p',{class:'muted'},'回放当时保存的快照，而不是事后重新计算影响。')),
    el('button',{class:'button',onclick:async()=>{const current=api;try{const result=await current.request('/v1/audit/verify');if(current===api){state.verification=result;render();}}catch(error){state.error=error.message;render();}}},'验证审计链')),
    state.verification && el('div',{class:state.verification.valid?'audit-verdict':'error',role:'status'},
      `HMAC 链${state.verification.valid?'校验通过':'校验失败'} · ${state.verification.events} 个事件 · 链头 ${short(state.verification.head)}`),
    el('p',{class:'warning small'},'没有外部锚定：无法证明尾部未被截断，也不能抵御服务器及密钥同时失陷。'),
    el('ol',{class:'timeline'},state.audit.map(item=>{
      const event=item.event, snapshot=event.detail.snapshot;
      return el('li',{},el('div',{class:'section-top'},el('strong',{},`${states[event.state]||event.state} · #${short(item.action_id)}`),
        el('time',{class:'muted small'},date(event.at))),
        el('p',{class:'small'},snapshot ? `${snapshot.request.sql} · 原始影响 ${number(snapshot.impact?.changed_rows)} 行` : `${event.detail.reviewer||'system'} · ${event.detail.reason||event.kind}`),
        event.detail.visible_ms_untrusted!=null && el('p',{class:'small muted'},`前台查看时长 ${number(event.detail.visible_ms_untrusted)} ms（客户端遥测，不可信、不是安全依据）`),
        el('details',{},el('summary',{},'查看签名与原始证据'),el('pre',{class:'result'},JSON.stringify(item,null,2))));
    })),!state.audit.length && el('p',{class:'empty'},'尚无审计事件。'),
    el('button',{class:'button',onclick:()=>void loadAudit(true)},'继续加载事件'));
}
function render() {
  if(!api) return;
  const focused=document.activeElement?.dataset?.field;
  const position=focused && ['INPUT','TEXTAREA'].includes(document.activeElement.tagName)?[document.activeElement.selectionStart,document.activeElement.selectionEnd]:null;
  observing?.disconnect();
  const metrics=state.metrics, counts=metrics?.states||{};
  const actions=state.actions.filter(a=>(state.view!=='pending'||a.state==='pending')&&a.request.sql.toLowerCase().includes(state.filter.toLowerCase()));
  const side=el('aside',{class:'sidebar'},el('div',{class:'brand'},el('span',{class:'logo'},'A'),el('span',{},'AIRLOCK')),
    el('p',{class:'sidebar-caption'},'服务端执行审批'),
    el('nav',{'aria-label':'主导航'},[['pending','审批队列'],['all','执行记录'],['audit','审计回放']].map(([key,label])=>el('button',{
      class:state.view===key?'nav active':'nav','aria-current':state.view===key?'page':false,onclick:()=>navigation(key)},label,
      key==='pending'&&el('span',{class:'nav-count'},counts.pending||0)))),
    el('div',{class:'sidebar-foot'},el('strong',{},'默认不放行'),el('p',{},'Agent 发起意图。\n服务端持有执行权。'),el('span',{class:'small'},'v0.1 · Personal project')));
  const header=el('header',{class:'header'},el('div',{},el('h1',{},state.view==='audit'?'审计回放':'审批工作台'),
    el('p',{class:'muted small'},'SQLite · customers · 合成演示数据')),
    el('div',{class:'header-actions'},el('span',{class:'connection',id:'connection'},state.connection),
      el('button',{class:'button quiet',onclick:()=>void refresh()},'刷新'),el('button',{class:'button quiet',onclick:logout},'退出')));
  const stats=el('section',{class:'stats','aria-label':'实际运行统计'},[
    ['待审批',number(counts.pending||0),'副作用尚未执行'],
    ['当前数据',number(metrics?.customers),'customers 表实际行数'],
    ['评估 p95',duration(metrics?.evaluation_p95_ms),'内部评估 · 不含提交/网络/人等待'],
  ].map(([label,value,hint])=>el('div',{class:'stat'},el('span',{class:'muted small'},label),el('strong',{},value),el('span',{class:'muted small'},hint))));
  const queue=el('section',{class:'queue','aria-label':'动作列表'},el('div',{class:'queue-head'},el('h2',{},state.view==='pending'?'待处理队列':'动作记录'),el('span',{class:'muted small'},`${actions.length} 条已加载`)),
    el('label',{class:'sr-only',for:'search'},'搜索 SQL'),el('input',{id:'search','data-field':'search',type:'search',placeholder:'搜索已加载的 SQL…',value:state.filter,
      oninput:event=>{state.filter=event.target.value;render();}}),
    el('div',{class:'queue-items'},actions.map(action=>el('button',{class:`action-row ${action.id===state.selected?'selected':''}`,
      'data-action':action.id,onclick:()=>select(action.id),'aria-pressed':action.id===state.selected},
      el('div',{class:'section-top'},el('span',{class:`tag ${action.state}`},states[action.state]),el('span',{class:'small muted'},`#${short(action.id)}`)),
      el('code',{class:'queue-sql'},action.request.sql),el('div',{class:'section-top small'},el('span',{},action.impact?`${number(action.impact.changed_rows)} 行变更`:'无写入预演'),
        el('span',{class:'muted'},new Date(action.created_at*1000).toLocaleTimeString('zh-CN',{hour12:false})))))),
    !actions.length&&el('div',{class:'empty'},el('strong',{},state.loading?'正在加载':'当前没有匹配的记录'),el('p',{},'可清除搜索条件或刷新；数量以服务器状态为准。')),
    state.next&&el('button',{class:'button more',onclick:()=>void refresh(true)},'加载更早记录'));
  const detail=reviewPanel(selected(),draft(state.selected),state.busy,decide,clock(state.selected));
  root.replaceChildren(el('div',{class:'shell'},side,el('main',{class:'workspace'},header,
    state.error&&el('div',{class:'error',role:'alert'},state.error),stats,
    state.view==='audit'?auditPanel():el('div',{class:'workbench'},queue,detail),
    el('footer',{class:'footer'},'所有写入都需要独立审批；未知能力默认阻断。审批通过不代表业务决策一定正确。'))));
  if(focused){const field=document.querySelector(`[data-field="${focused}"]`);if(field){field.focus({preventScroll:true});if(position?.[0]!=null&&field.type!=='checkbox')field.setSelectionRange(...position);}}
  const summary=document.querySelector('#impact-summary');
  if(summary){const id=state.selected;observing=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&id===state.selected){clock(id).firstVisible();setActiveClock();observing.disconnect();}},{threshold:0.5});observing.observe(summary);}
}
setInterval(()=>{const node=document.querySelector('#countdown');if(node)node.textContent='剩余 '+countdown(Number(node.dataset.expires));},1000);
login();
