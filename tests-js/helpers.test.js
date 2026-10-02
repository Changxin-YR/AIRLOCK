import test from 'node:test';
import assert from 'node:assert/strict';
import {ReviewClock, EventParser, canApprove, countdown, duration} from '../airlock/static/lib.js';
test('visibility timing excludes background and unselected periods',()=>{
 let now=0;const c=new ReviewClock(()=>now);c.active(true);now=50;assert.equal(c.value(),0);
 c.firstVisible();c.active(true);now=150;c.active(false);now=900;assert.equal(c.value(),100);
 c.active(true);now=1000;assert.equal(c.value(),200);
});
test('approval requires exact scope phrase and reason',()=>{
 const a={state:'pending',confirmation_required:'EXECUTE 1206'};const d={reason:'检查完成',checked:true,confirmation:'EXECUTE 1206'};
 assert.ok(canApprove(a,d));assert.equal(canApprove(a,{...d,confirmation:'EXECUTE 1'}),false);
 assert.equal(canApprove({...a,state:'stale'},d),false);assert.equal(canApprove(a,{...d,checked:false}),false);
});
test('SSE framing survives partial chunks, CRLF and heartbeats',()=>{
 const p=new EventParser();assert.deepEqual(p.push('id: 1\r\nevent: action\r\nda'),[]);
 assert.deepEqual(p.push('ta: {"action_id":"one"}\r\n\r\n: heartbeat\n\n'),[{id:1,data:{action_id:'one'}}]);
 assert.deepEqual(p.push('id: 2\ndata: {}\n\n'),[{id:2,data:{}}]);
});
test('oversized event rejected',()=>{assert.throws(()=>new EventParser().push('x'.repeat(70000)));});
test('countdown clamps expired actions',()=>{assert.match(countdown(1,2000),/已到期/);assert.equal(countdown(120,0),'2分00秒');});

test('latency formatting keeps number and unit together on mobile',()=>{
 assert.equal(duration(null),'—');assert.equal(duration(11.899),'11.9\u00a0ms');assert.equal(duration(1500),'1.50\u00a0s');
});
