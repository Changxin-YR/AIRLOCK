/** Shared pure helpers. All untrusted display content becomes a text node. */
export function el(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key.startsWith('on') && typeof value === 'function') element.addEventListener(key.slice(2), value);
    else if (key === 'class') element.className = value;
    else if (['value', 'checked', 'disabled'].includes(key)) element[key] = value;
    else if (value !== false && value != null) element.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}
export const states = { pending: '等待审批', executed: '已执行', blocked: '策略阻断', rejected: '已拒绝',
  expired: '已过期', stale: '快照失效', failed: '执行失败', executing:'执行中', unknown:'结果未知 · 需对账' };
export const risks = { critical: '高影响', high: '需审查', low: '只读', blocked: '不支持 / 禁止' };
export const number = value => value == null ? '—' : Number(value).toLocaleString('zh-CN');
export const short = value => (value || '').slice(0, 10);
export const date = value => new Date(value * 1000).toLocaleString('zh-CN', { hour12: false });
export function countdown(expires, now = Date.now()) {
  const remaining = Math.max(0, Math.ceil(expires - now / 1000));
  return remaining ? `${Math.floor(remaining / 60)}分${String(remaining % 60).padStart(2, '0')}秒` : '已到期，等待同步';
}
export function canApprove(action, draft) {
  return action?.state === 'pending' && draft.reason.trim().length >= 3 && draft.checked &&
    draft.confirmation === action.confirmation_required;
}
export class ReviewClock {
  constructor(now = () => performance.now()) { this.now = now; this.total = 0; this.since = null; this.seen = false; }
  firstVisible() { this.seen = true; }
  active(value) {
    if (this.since !== null) this.total += this.now() - this.since;
    this.since = value && this.seen ? this.now() : null;
  }
  value() { return Math.max(0, Math.round(this.total + (this.since === null ? 0 : this.now() - this.since))); }
}
/** Streaming parser tolerates split TCP chunks and CRLF; enforces a bounded frame. */
export class EventParser {
  constructor() { this.buffer = ''; }
  push(chunk) {
    this.buffer += chunk;
    this.buffer = this.buffer.replace(/\r\n/g, '\n');
    if (this.buffer.length > 65536) throw new Error('事件帧超出限制');
    const parts = this.buffer.split('\n\n');
    this.buffer = parts.pop();
    return parts.flatMap(part => {
      const id = /^id:\s*(\d+)$/m.exec(part);
      const data = /^data:\s*(.*)$/m.exec(part);
      return id && data ? [{ id: Number(id[1]), data: JSON.parse(data[1]) }] : [];
    });
  }
}

export function duration(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const ms = Number(value);
  return ms < 1000 ? `${ms.toFixed(1)}\u00a0ms` : `${(ms / 1000).toFixed(2)}\u00a0s`;
}
