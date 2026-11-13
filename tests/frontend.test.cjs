const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {JSDOM, VirtualConsole} = require('jsdom');
const ROOT = path.resolve(__dirname,'..');
const PYTHON = process.env.PYTHON || 'python3.12';
const html=fs.readFileSync(path.join(ROOT,'src/index.html'),'utf8');
const js=fs.readFileSync(path.join(ROOT,'src/app.js'),'utf8');
const css=fs.readFileSync(path.join(ROOT,'src/styles.css'),'utf8');
const result=spawnSync(PYTHON,['-c',`from dashboard.core import read_json,canonical
from dashboard.render import presentation
v=read_json('tests/fixtures/dashboard-demo.json')
print(canonical(presentation(v['projects'],v['records'])).decode())`],{cwd:ROOT,encoding:'utf8'});
assert.equal(result.status,0,result.stderr);
const fixture=JSON.parse(result.stdout);
const build={built_at:'2026-11-12T21:00:00+08:00',local_preview:true,synthetic:true,actions_url:null,data_changed_at:null};
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
async function mount(t,options={}) {
  const errors=[],requests=[],downloads=[];
  const virtualConsole=new VirtualConsole();virtualConsole.on('jsdomError',e=>errors.push(e.message));
  const dom=new JSDOM(html,{url:'https://example.invalid/progress-dashboard/',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole});
  t.after(()=>dom.window.close());
  const w=dom.window,d=w.document;
  const style=d.createElement('style');style.textContent=css;d.head.append(style);
  const data=structuredClone(options.data||fixture), meta=structuredClone({...build,...options.build});
  w.fetch=async url=>{requests.push(url);if(options.failure)throw new Error('测试网络失败');return {ok:true,json:async()=>url==='./data.json'?data:meta};};
  Object.defineProperty(w.navigator,'clipboard',{value:options.clipboard,configurable:true});
  // DOM tests use a minimal modal API; top-layer layout needs a real browser.
  w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
  w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');this.dispatchEvent(new w.Event('close'));};
  w.URL.createObjectURL=blob=>{if(options.noDownload)throw new Error('blocked');downloads.push({blob});return 'blob:synthetic-test';};
  w.URL.revokeObjectURL=()=>{};
  w.HTMLAnchorElement.prototype.click=function(){downloads.at(-1).filename=this.download;};
  w.eval(js);await tick();await tick();
  return {w,d,data,meta,requests,downloads,errors,el:id=>d.getElementById(id),click:id=>d.getElementById(id).click(),set:(id,value,event='input')=>{const el=d.getElementById(id);el.value=value;el.dispatchEvent(new w.Event(event,{bubbles:true}));}};
}
function openManual(app,project='proj_materials') {app.click('open-record');app.click('mode-manual');app.set('record-project',project,'change');}
function fillManual(app) {app.set('occurred-at','2026-11-12');app.set('summary','完成合成测试工作');app.set('evidence','人工提供的合成测试依据');}
function submit(app) {app.el('manual-form').dispatchEvent(new app.w.Event('submit',{bubbles:true,cancelable:true}));}
function exported(app) {return JSON.parse(app.el('draft-json').value);}
function validatePython(raw) {const r=spawnSync(PYTHON,['-c',`import sys,json
from dashboard.core import draft
draft(json.load(sys.stdin))
print('valid')`],{cwd:ROOT,input:JSON.stringify(raw),encoding:'utf8'});assert.equal(r.status,0,r.stderr);}

test('initial cards, counts and explicit synthetic banner',async t=>{const a=await mount(t);assert.equal(a.d.querySelectorAll('.project-card').length,6);assert.equal(a.el('stat-total').textContent,'6');assert.equal(a.el('stat-active').textContent,'1');assert.equal(a.el('stat-blocked').textContent,'1');assert.equal(a.el('stat-done').textContent,'1');assert.match(a.el('preview-banner').textContent,/合成数据/);assert.match(a.el('results').textContent,/9 条/);assert.deepEqual(a.requests,['./data.json','./build.json']);assert.deepEqual(a.errors,[]);});
test('classification, query and current status compose',async t=>{const a=await mount(t);a.d.querySelector('[data-category="research"]').click();assert.equal(a.d.querySelectorAll('.project-card').length,2);a.set('search','文献笔记');assert.equal(a.d.querySelectorAll('.project-card').length,1);a.set('status-filter','planned','change');assert.equal(a.d.querySelectorAll('.project-card').length,0);assert.match(a.el('projects').textContent,/没有匹配/);a.click('clear-filters');assert.equal(a.d.querySelectorAll('.project-card').length,6);});
test('search matches historical progress, not only latest',async t=>{const a=await mount(t);a.set('search','第一批样例');assert.equal(a.d.querySelectorAll('.project-card').length,1);assert.match(a.el('projects').textContent,/问答标注/);a.click('tab-timeline');assert.equal(a.el('timeline').querySelectorAll('.timeline-entry').length,3);assert.match(a.el('timeline').textContent,/等待规则说明/);});
test('search whitespace, multiple terms and no-match reset',async t=>{const a=await mount(t);a.set('search','  文献   参数  ');assert.equal(a.d.querySelectorAll('.project-card').length,1);a.set('search','不存在的测试字符串');assert.equal(a.el('timeline').querySelectorAll('.timeline-entry').length,0);a.el('projects').querySelector('button').click();assert.equal(a.el('search').value,'');assert.equal(a.d.querySelectorAll('.project-card').length,6);});
test('all five states plus unknown can be filtered',async t=>{const a=await mount(t);for(const status of ['active','planned','blocked','paused','done','unknown']){a.set('status-filter',status,'change');assert.equal(a.d.querySelectorAll('.project-card').length,1,status);}});
test('project history is complete and keeps evidence times and aliases',async t=>{const a=await mount(t);a.d.querySelector('[data-project-id="proj_materials"] .history-button').click();assert.equal(a.el('history-dialog').open,true);assert.equal(a.el('history-records').querySelectorAll('.timeline-entry').length,3);assert.match(a.el('history-summary').textContent,/文献笔记/);assert.match(a.el('history-records').textContent,/状态证据/);assert.match(a.el('history-records').textContent,/录入于/);});
test('status updates do not replace recent work progress',async t=>{const a=await mount(t);const card=a.d.querySelector('[data-project-id="proj_labels"]');assert.match(card.querySelector('.status').textContent,/受阻/);assert.match(card.querySelector('.card-progress').textContent,/完成样例对照/);assert.doesNotMatch(card.querySelector('.card-progress').textContent,/等待规则说明/);});
test('date uncertainty remains visible and latest candidates are not arbitrarily reduced',async t=>{const a=await mount(t);const card=a.d.querySelector('[data-project-id="proj_materials"]');assert.equal(card.querySelectorAll('.progress-item').length,2);assert.match(card.textContent,/同日先后未定/);assert.match(a.el('timeline').textContent,/当日，时间未记录/);assert.doesNotMatch(card.textContent,/00:00:00/);});
test('timeline and tab keyboard navigation preserve filters',async t=>{const a=await mount(t);a.set('status-filter','blocked','change');a.el('tab-projects').focus();a.el('tab-projects').dispatchEvent(new a.w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert.equal(a.el('panel-projects').hidden,true);assert.equal(a.el('tab-timeline').getAttribute('aria-selected'),'true');assert.equal(a.el('timeline').querySelectorAll('.timeline-entry').length,3);});
test('history closes with Escape and restores focus',async t=>{const a=await mount(t);const trigger=a.d.querySelector('.history-button');trigger.focus();trigger.click();a.el('history-dialog').dispatchEvent(new a.w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert.equal(a.el('history-dialog').open,false);assert.equal(a.d.activeElement,trigger);});
test('record this project preselects it',async t=>{const a=await mount(t);a.d.querySelector('[data-project-id="proj_labels"] .history-button').click();a.click('history-record');assert.equal(a.el('history-dialog').open,false);assert.equal(a.el('record-dialog').open,true);assert.equal(a.el('record-project').value,'proj_labels');});
test('current-chat instruction describes local draft and approval boundary',async t=>{const a=await mount(t);a.click('open-record');a.set('record-project','proj_materials','change');a.click('make-current');assert.match(a.el('instruction-text').value,/proj_materials/);assert.match(a.el('instruction-text').value,/不要填写 record_id 或 recorded_at/);assert.match(a.el('instruction-text').value,/不要批准、推送、部署/);assert.equal(a.el('instruction-result').hidden,false);});
test('scan instruction validates date range and includes 50-turn and gap rules',async t=>{const a=await mount(t);a.click('open-record');a.click('mode-scan');a.set('record-project','proj_labels','change');a.set('scan-since','2026-11-12');a.set('scan-until','2026-11-10');a.click('make-scan');assert.equal(a.el('record-error').hidden,false);a.set('scan-until','2026-11-12');a.click('make-scan');assert.equal(a.el('record-error').hidden,true);assert.match(a.el('instruction-text').value,/最多 50 轮/);assert.match(a.el('instruction-text').value,/不能跳过缺口/);assert.match(a.el('instruction-text').value,/含结束当天/);});
test('changing project or dates invalidates stale instruction',async t=>{const a=await mount(t);a.click('open-record');a.set('record-project','proj_labels','change');a.click('make-current');a.set('record-project','proj_tools','change');assert.equal(a.el('instruction-result').hidden,true);});
test('clipboard success and rejection both have actionable outcomes',async t=>{let copied='';const a=await mount(t,{clipboard:{writeText:async value=>{copied=value;}}});a.click('open-record');a.set('record-project','proj_labels','change');a.click('make-current');a.click('copy-instruction');await tick();assert.equal(copied,a.el('instruction-text').value);assert.match(a.el('copy-status').textContent,/已复制/);Object.defineProperty(a.w.navigator,'clipboard',{value:{writeText:async()=>{throw new Error('denied');}},configurable:true});a.click('copy-instruction');await tick();assert.match(a.el('copy-status').textContent,/自动复制不可用/);assert.equal(a.el('instruction-text').selectionEnd,a.el('instruction-text').value.length);});
test('manual date-only draft validates in Python and omits private system IDs',async t=>{const a=await mount(t);openManual(a);fillManual(a);submit(a);const d=exported(a);validatePython(d);assert.equal(d.occurred_at,'2026-11-12');assert.equal(d.verification,'needs_review');assert.equal(d.state_snapshot,null);assert.equal(d.state_as_of,null);assert.equal(d.source,null);assert.equal('recorded_at' in d,false);assert.equal('record_id' in d,false);assert.equal(a.downloads.length,1);assert.match(a.downloads[0].filename,/^draft_[a-f0-9]+\.json$/);});
test('repeat download reuses ID and new entry resets it',async t=>{const a=await mount(t);openManual(a);fillManual(a);submit(a);const first=exported(a).draft_id;submit(a);assert.equal(exported(a).draft_id,first);assert.equal(a.el('record-project').disabled,true);a.click('new-draft');assert.equal(a.el('record-project').disabled,false);fillManual(a);submit(a);assert.notEqual(exported(a).draft_id,first);});
test('precise input explicitly uses Shanghai time; unknown state stays null',async t=>{const a=await mount(t);openManual(a);fillManual(a);a.set('occurred-precision','instant','change');assert.equal(a.el('occurred-at').value,'');a.set('occurred-at','2026-11-12T16:30');submit(a);const d=exported(a);assert.equal(d.occurred_at,'2026-11-12T16:30:00+08:00');validatePython(d);});
test('state-only draft requires complete snapshot and independent evidence date',async t=>{const a=await mount(t);openManual(a);fillManual(a);a.set('record-type','state_update','change');assert.equal(a.el('has-snapshot').checked,true);assert.equal(a.el('has-snapshot').disabled,true);submit(a);assert.equal(a.el('record-error').hidden,false);a.set('state-as-of','2026-11-10');a.set('snapshot-status','blocked','change');a.set('blocker','等待合成测试规则');a.el('verified').checked=true;submit(a);const d=exported(a);assert.equal(d.state_as_of,'2026-11-10');assert.equal(d.state_snapshot.status,'blocked');assert.equal(d.state_snapshot.next_step,null);assert.equal(d.verification,'confirmed');validatePython(d);});
test('missing fields, whitespace and invalid project IDs fail before download',async t=>{const a=await mount(t);openManual(a);submit(a);assert.equal(a.downloads.length,0);fillManual(a);a.set('summary','   ');submit(a);assert.equal(a.downloads.length,0);a.set('summary','完成测试');a.set('record-project','__custom__','change');a.set('custom-project','../private');submit(a);assert.equal(a.downloads.length,0);assert.match(a.el('record-error').textContent,/项目代号/);});
test('download fallback preserves valid JSON for manual save',async t=>{const a=await mount(t,{noDownload:true});openManual(a);fillManual(a);submit(a);assert.match(a.el('draft-status').textContent,/下载不可用/);assert.equal(a.el('draft-result').hidden,false);validatePython(exported(a));});
test('empty dataset still supports instructions and manual custom project draft',async t=>{const a=await mount(t,{data:{schema_version:1,projects:[],timeline:[],data_updated_at:null}});assert.match(a.el('projects').textContent,/还没有项目/);openManual(a,'__custom__');a.set('custom-project','proj_new');fillManual(a);submit(a);validatePython(exported(a));assert.equal(exported(a).project_id,'proj_new');});
test('malicious strings render only as text in cards, timeline and history',async t=>{const data=structuredClone(fixture), attack='<img src=x onerror="window.__executed=true"><script>window.__executed=true</script>';
 const target=data.projects.find(c=>c.project.project_id==='proj_materials');target.project.public_name=attack;target.project.aliases=[attack];target.latest_progress[0].summary=attack;
 const r=data.timeline.flatMap(d=>[...d.timed,...d.untimed]).find(r=>r.project_id===target.project.project_id);r.summary=attack;
 const a=await mount(t,{data});a.d.querySelector(`[data-project-id="${target.project.project_id}"] .history-button`).click();assert.equal(a.d.querySelectorAll('main img, dialog img, main script, dialog script').length,0);assert.equal(a.w.__executed,undefined);assert.match(a.el('history-title').textContent,/<img/);});
test('Actions link rejects script and unapproved origins; accepts explicit GitHub actions',async t=>{for(const url of ['javascript:alert(1)','https://evil.invalid/actions','https://github.com.evil.invalid/a/b/actions']){const a=await mount(t,{build:{actions_url:url}});assert.equal(a.el('actions-link').hidden,true);}const a=await mount(t,{build:{actions_url:'https://github.com/example/repo/actions'}});assert.equal(a.el('actions-link').hidden,false);assert.equal(a.el('actions-link').rel,'noopener noreferrer');});
test('network failure is recoverable and does not disable local record entry',async t=>{const a=await mount(t,{failure:true});assert.equal(a.el('load-error').hidden,false);assert.equal(a.el('retry-load').disabled,false);openManual(a,'__custom__');a.set('custom-project','proj_offline');fillManual(a);submit(a);validatePython(exported(a));a.w.fetch=async url=>({ok:true,json:async()=>url==='./data.json'?fixture:build});a.click('retry-load');await tick();await tick();assert.equal(a.el('load-error').hidden,true);assert.equal(a.d.querySelectorAll('.project-card').length,6);});
test('malformed payload surfaces a recoverable error',async t=>{const a=await mount(t,{data:{schema_version:1,projects:[],timeline:null}});assert.equal(a.el('load-error').hidden,false);assert.match(a.el('load-error-text').textContent,/数据格式/);});
test('no persistent browser storage, third-party assets or write requests',async t=>{const a=await mount(t);openManual(a);fillManual(a);submit(a);assert.equal(a.w.localStorage.length,0);assert.equal(a.w.sessionStorage.length,0);assert.deepEqual(a.requests,['./data.json','./build.json']);assert.deepEqual([...a.d.querySelectorAll('script[src],link[rel=stylesheet]')].map(e=>e.getAttribute('src')||e.getAttribute('href')),['./styles.css','./app.js']);});
test('responsive rules cover 360/390px without fixed-width panels and controls have labels',async t=>{const a=await mount(t);assert.ok(a.d.styleSheets[0].cssRules.length>0);assert.match(css,/@media\(max-width:540px\)/);assert.match(css,/grid-template-columns:1fr/);assert.match(css,/font-size:16px/);for(const el of a.d.querySelectorAll('input,select,textarea'))assert.ok(el.labels.length>0,el.id);assert.match(html,/width=device-width,initial-scale=1/);});

test('exported draft imports idempotently through the real local engine',async t=>{
 const a=await mount(t);openManual(a);fillManual(a);submit(a);
 const r=spawnSync(PYTHON,['-c',`import sys,json,tempfile
from pathlib import Path
from dashboard.core import Context,atomic_json,load_public
from dashboard.engine import import_draft
raw=json.load(sys.stdin)
with tempfile.TemporaryDirectory() as tmp:
 root=Path(tmp).resolve();repo=root/'repo';repo.mkdir()
 atomic_json(repo/'public/projects.json',{'schema_version':1,'projects':[]})
 ctx=Context(repo,root/'private')
 first=import_draft(ctx,raw);second=import_draft(ctx,raw)
 assert first['record_id']==second['record_id'] and second['duplicate']
 assert load_public(repo)==([],[])
 print('imported without publishing')`],{cwd:ROOT,input:JSON.stringify(exported(a)),encoding:'utf8'});
 assert.equal(r.status,0,r.stderr);assert.match(r.stdout,/without publishing/);
});
