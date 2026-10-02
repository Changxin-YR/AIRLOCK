import {el,ReviewClock} from './lib.js';
const root=document.querySelector('#study');
let tasks=[],position=0,session=null,clock=null,observing=null;
document.addEventListener('visibilitychange',()=>clock?.active(!document.hidden));
function start() {
  const input=el('input',{type:'file',accept:'.json',id:'tasks'});
  const who=el('input',{id:'participant',maxlength:80,placeholder:'匿名参与者编号'});
  const consent=el('input',{type:'checkbox',id:'consent'});
  const source=el('select',{id:'source'},el('option',{value:'human'},'本人参与'),el('option',{value:'automation'},'自动化验证'));
  const error=el('p',{role:'alert'});
  root.replaceChildren(el('h1',{},'审批信息呈现研究'),el('p',{},'本页面只记录模拟决策，不执行工具。任务应包含独立业务授权金标。你可以随时退出；导出前数据只保存在本页内存。'),
    el('label',{for:'participant'},'匿名编号'),who,el('label',{for:'tasks'},'研究者提供的任务 JSON'),input,
    el('label',{for:'source'},'记录来源'),source,el('label',{},consent,'我同意记录模拟决定和页面可见时长，并手动导出匿名结果。'),
    el('button',{class:'button primary',id:'start-study',onclick:async()=>{
      try {
        if(!who.value.trim()||!consent.checked||!input.files[0]) throw Error('请填写编号、同意参与并选择任务。');
        if(input.files[0].size>100000) throw Error('任务文件过大');
        const data=JSON.parse(await input.files[0].text());
        if(data.version!==1||!Array.isArray(data.tasks)||data.tasks.length<2||data.tasks.length>100) throw Error('任务格式或数量不符');
        const ids=new Set();
        for(const t of data.tasks) {
          if(typeof t.id!=='string'||ids.has(t.id)||!['approve','reject'].includes(t.gold)||typeof t.intent!=='string'||typeof t.sql!=='string'||typeof t.diff!=='string') throw Error('任务 ID、业务意图、SQL、diff 或金标无效');
          if(t.check && (typeof t.check.question!=='string'||!Array.isArray(t.check.options)||t.check.options.length<2||t.check.options.length>6||t.check.options.some(v=>typeof v!=='string')||new Set(t.check.options).size!==t.check.options.length||!t.check.options.includes(t.check.answer))) throw Error('理解核验题格式无效');
          ids.add(t.id);
        }
        // Stable participant counterbalancing; each task appears once for each participant.
        const bytes=new TextEncoder().encode(who.value.trim());
        const hash=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));
        const offset=hash[0]%2;
        tasks=data.tasks.map((t,i)=>({...t,arm:(i+offset)%2?'B':'A'}));
        if(hash[1]%2) tasks.reverse();
        session={kind:'airlock-study-v1',participant_id:who.value.trim(),source:source.value,consent:true,
          protocol:data.protocol||'unspecified',task_file_sha256:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await input.files[0].arrayBuffer()))).map(b=>b.toString(16).padStart(2,'0')).join(''),
          started_at:new Date().toISOString(),responses:[],counterbalance:offset};
        position=0; render();
      } catch(e){error.textContent=e.message;}
    }},'开始模拟任务'),error);
}
function render() {
  observing?.disconnect(); clock?.active(false);
  if(position>=tasks.length) {
    root.replaceChildren(el('h1',{},'模拟任务完成'),el('p',{},'结果尚未发送。导出文件交由研究者核对；自动化记录会被分析器排除。'),
      el('button',{class:'button primary',id:'export-study',onclick:()=>{
        const url=URL.createObjectURL(new Blob([JSON.stringify(session,null,2)],{type:'application/json'}));
        const link=el('a',{href:url,download:'airlock-study.json'});link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }},'导出匿名结果'));return;
  }
  const task=tasks[position];clock=new ReviewClock();
  const summary=el('section',{id:'study-summary'},el('h2',{},`任务 ${position+1} / ${tasks.length}`),el('p',{},task.intent));
  if(task.arm==='B') summary.append(el('h3',{},'预计变化'),el('pre',{class:'result'},task.diff));
  summary.append(el('h3',{},'请求'),el('pre',{class:'sql'},task.sql));
  const choose=choice=>{
    clock.active(false);const response={case_id:task.id,arm:task.arm,choice,correct:choice===task.gold,
      visible_ms:clock.value(),at:new Date().toISOString()};
    const finish=()=>{session.responses.push(response);position++;render();};
    if(!task.check){finish();return;}
    observing?.disconnect();
    const answers=el('select',{id:'study-comprehension'},el('option',{value:''},'请选择'));
    task.check.options.forEach(value=>answers.append(el('option',{value},value)));
    const submit=el('button',{id:'study-check-submit',class:'button primary',disabled:true,onclick:()=>{response.comprehension_choice=answers.value;finish();}},'提交理解核验');
    answers.addEventListener('change',()=>{submit.disabled=!answers.value;});
    root.replaceChildren(el('h2',{},'理解核验'),el('label',{for:'study-comprehension'},task.check.question),answers,submit);
  };
  root.replaceChildren(summary,el('p',{class:'muted'},'仅根据提供的业务授权判断，本页不会提交真实操作。'),
    el('button',{class:'button reject',id:'study-reject',onclick:()=>choose('reject')},'拒绝'),
    el('button',{class:'button primary',id:'study-approve',onclick:()=>choose('approve')},'批准'));
  observing=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){clock.firstVisible();clock.active(!document.hidden);observing.disconnect();}},{threshold:.5});
  observing.observe(summary);
}
start();
