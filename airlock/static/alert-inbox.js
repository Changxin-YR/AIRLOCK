'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const labels = Object.freeze({
    audit_integrity_failed: '审计完整性检查失败',
    remote_outcome_needs_reconciliation: '远端结果需要核对',
    pending_expiry_backlog: '待处理审批存在过期积压',
    telemetry_outbox_pressure: '遥测发送队列积压',
    telemetry_spans_dropped: '遥测记录发生丢弃',
  });
  let token = '', nextBefore = null, generation = 0, pending = null;
  const status = (text) => { $('inbox-status').textContent = text; };
  function logout() {
    generation += 1;
    if (pending) pending.abort();
    pending = null; token = ''; nextBefore = null;
    $('read-token').value = ''; $('events').replaceChildren();
    $('inbox').hidden = true; $('login').hidden = false; $('load-more').hidden = true;
    status('已退出，页面中的令牌和通知已清空。');
  }
  function appendEvent(event) {
    const article = document.createElement('article');
    article.dataset.eventId = event.event_id;
    const heading = document.createElement('div'); heading.className = 'event-heading';
    const badge = document.createElement('h3'); badge.className = `badge ${event.kind === 'alert' ? 'alert' : 'recovery'}`;
    badge.textContent = event.kind === 'alert' ? '健康提醒' : '已恢复';
    const received = document.createElement('time'); received.textContent = event.received_at;
    heading.append(badge, received); article.append(heading);
    const list = document.createElement('ul');
    for (const [prefix, codes] of [['当前：', event.alert_codes], ['恢复：', event.resolved_codes]]) {
      for (const code of codes) {
        const row = document.createElement('li');
        const name = document.createElement('span'); name.textContent = prefix + (labels[code] || code) + ' ';
        const raw = document.createElement('code'); raw.textContent = code;
        row.append(name, raw); list.append(row);
      }
    }
    article.append(list);
    const identifier = document.createElement('p'); identifier.className = 'event-id'; identifier.textContent = '事件 ID：' + event.event_id;
    article.append(identifier); $('events').append(article);
  }
  async function load(more = false) {
    if (!token) return;
    const current = ++generation;
    if (pending) pending.abort();
    pending = new AbortController();
    status('正在读取…');
    const query = more && nextBefore !== null ? `?before=${encodeURIComponent(nextBefore)}` : '';
    try {
      const response = await fetch('/api/events' + query, {
        headers: { Authorization: 'Bearer ' + token }, cache: 'no-store',
        credentials: 'omit', redirect: 'error', signal: pending.signal,
      });
      if (current !== generation) return;
      if (response.status === 401) { logout(); status('只读令牌无效，请重新输入。'); return; }
      if (!response.ok) throw new Error('unavailable');
      const result = await response.json();
      if (current !== generation) return;
      if (!more) $('events').replaceChildren();
      result.events.forEach(appendEvent); nextBefore = result.next_before;
      $('login').hidden = true; $('inbox').hidden = false;
      $('load-more').hidden = nextBefore === null;
      status($('events').children.length ? `已显示 ${$('events').children.length} 条通知。` : '尚未收到通知。');
    } catch (error) {
      if (current === generation && error.name !== 'AbortError') status('收件箱暂时不可用，请稍后刷新。');
    } finally { if (current === generation) pending = null; }
  }
  $('login-form').addEventListener('submit', (event) => {
    event.preventDefault(); token = $('read-token').value; $('read-token').value = ''; void load();
  });
  $('refresh').addEventListener('click', () => { void load(); });
  $('load-more').addEventListener('click', () => { void load(true); });
  $('logout').addEventListener('click', logout);
  window.addEventListener('pagehide', logout);
})();
