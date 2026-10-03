// Independent synthetic logout races; intentionally non-cooperative fetch ignores AbortSignal.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('airlock/static/alert-inbox.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function check(stage) {
  const elements = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, {value: '', hidden: false, textContent: '', children: [],
      handlers: {}, addEventListener(event, handler) {this.handlers[event] = handler;},
      replaceChildren() {this.children = [];}, append() {throw Error('late event rendered after logout');}});
    return elements.get(id);
  };
  let releaseFetch, releaseBody;
  const body = new Promise(resolve => {releaseBody = resolve;});
  const response = {ok: true, status: 200, json: () => body};
  const fetchResult = new Promise(resolve => {releaseFetch = resolve;});
  const sandbox = {document: {getElementById: get, createElement() {throw Error('late event rendered');}},
    window: {addEventListener() {}}, AbortController, fetch: () => fetchResult};
  vm.runInNewContext(code, sandbox);
  get('read-token').value = 'synthetic-browser-read-token';
  get('login-form').handlers.submit({preventDefault() {}});
  if (stage === 'body') { releaseFetch(response); await tick(); }
  get('logout').handlers.click();
  if (stage === 'headers') releaseFetch(response);
  releaseBody({events: [{event_id: 'synthetic-late-event'}], next_before: 5});
  await tick(); await tick();
  assert.equal(get('read-token').value, '');
  assert.equal(get('events').children.length, 0);
  assert.equal(get('inbox').hidden, true);
  assert.equal(get('login').hidden, false);
  assert.equal(get('load-more').hidden, true);
}

(async () => {
  await check('headers');
  await check('body');
  process.stdout.write(JSON.stringify({status: 'PASS', independent_synthetic_races: 2,
    checks: ['logout-before-headers', 'logout-during-json-body'], business_effects: 0}) + '\n');
})().catch(error => {process.stderr.write(String(error)); process.exitCode = 1;});
