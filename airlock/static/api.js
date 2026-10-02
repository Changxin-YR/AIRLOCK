import { EventParser } from './lib.js';

export class Api {
  constructor(token) { this.token = token; }
  async request(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST',
        headers: { Authorization: `Bearer ${this.token}`, ...(body === undefined ? {} : {'Content-Type': 'application/json'}) },
        body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store',
        credentials: 'omit', redirect: 'error', signal: controller.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(`${data.error || '请求不符合接口约束'} (${response.status})`);
      return data;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('请求超时。执行结果可能未知，请刷新状态；不要重新创建同一写操作。');
      throw error;
    } finally { clearTimeout(timeout); }
  }
  async events(signal, changed, status) {
    let cursor = 0;
    while (!signal.aborted) {
      try {
        status('连接中');
        const response = await fetch(`/v1/events?after=${cursor}`, { headers: {Authorization: `Bearer ${this.token}`},
          cache: 'no-store', credentials: 'omit', redirect: 'error', signal });
        if (!response.ok || !response.body) throw new Error('事件连接不可用');
        status('实时连接');
        const reader = response.body.getReader(), decoder = new TextDecoder(), parser = new EventParser();
        try {
          while (!signal.aborted) {
            const {value, done} = await reader.read();
            if (done) break;
            for (const event of parser.push(decoder.decode(value, {stream: true}))) {
              if (Number.isSafeInteger(event.id) && event.id > cursor) { cursor = event.id; changed(); }
            }
          }
        } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
      } catch (error) { if (!signal.aborted) status('连接中断，可手动刷新'); }
      if (!signal.aborted) await new Promise(resolve => {
        const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve(); };
        const timer = setTimeout(finish, 1500);
        signal.addEventListener('abort', finish, {once: true});
      });
    }
  }
}
