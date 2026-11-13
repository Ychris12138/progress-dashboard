"use strict";
(() => {
  const labels = {planned:"待开始", active:"进行中", blocked:"受阻", paused:"暂停", done:"已完成", unknown:"尚无已确认状态", research:"科研", part_time:"兼职", internship:"实习", other:"其他"};
  const categories = ["research", "part_time", "internship", "other"];
  const statuses = ["planned", "active", "blocked", "paused", "done"];
  const $ = id => document.getElementById(id);
  const state = {data:null, build:null, category:"all", status:"all", query:"", view:"projects", mode:"current", historyProject:null, draftId:null, loadSequence:0};
  const returnFocus = new Map();
  const node = (tag, value, cls) => { const el=document.createElement(tag); if(value!==undefined) el.textContent=value; if(cls) el.className=cls; return el; };
  function button(text, handler, cls="quiet") { const el=node("button",text,cls); el.type="button"; el.addEventListener("click",handler); return el; }
  function time(value, short=false) {
    if(!value) return "尚无记录";
    if(/^\d{4}-\d{2}-\d{2}$/.test(value)) return value + (short?"":"（时间未记录）");
    const date=new Date(value); if(Number.isNaN(date.getTime())) return "时间格式异常";
    return new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",...(short?{}:{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false})}).format(date);
  }
  function today() { return new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date()); }
  const normalized = value => String(value??"").normalize("NFKC").toLocaleLowerCase().trim();
  function records() { return state.data?state.data.timeline.flatMap(day=>[...day.timed,...day.untimed]):[]; }
  function currentStatus(card) { return card.state_snapshot?.status ?? "unknown"; }
  function assertData(data, build) {
    if(data?.schema_version!==1 || !Array.isArray(data.projects) || !Array.isArray(data.timeline) || typeof build?.built_at!=="string") throw new Error("数据格式不完整，请重新构建看板。");
    const ids=new Set();
    for(const c of data.projects) {
      if(!c.project || typeof c.project.project_id!=="string" || ids.has(c.project.project_id) || typeof c.project.public_name!=="string" || !categories.includes(c.project.category) || !Array.isArray(c.project.aliases) || !c.project.aliases.every(a=>typeof a==="string") || !Array.isArray(c.latest_progress) || !Array.isArray(c.state_evidence_times) || (c.state_snapshot && !statuses.includes(c.state_snapshot.status))) throw new Error("项目数据格式异常，请重新校验公开数据。");
      ids.add(c.project.project_id);
    }
    const recordIDs=new Set();
    for(const day of data.timeline) {
      if(!/^\d{4}-\d{2}-\d{2}$/.test(day.date) || !Array.isArray(day.timed) || !Array.isArray(day.untimed)) throw new Error("时间轴数据格式异常。");
      for(const r of [...day.timed,...day.untimed]) {
        if(!ids.has(r.project_id) || typeof r.record_id!=="string" || recordIDs.has(r.record_id) || typeof r.summary!=="string" || typeof r.occurred_at!=="string" || typeof r.recorded_at!=="string" || !["progress","state_update"].includes(r.record_type)) throw new Error("记录数据格式异常。");
        recordIDs.add(r.record_id);
      }
    }
  }
  function filteredProjects() {
    const terms=normalized(state.query).split(/\s+/).filter(Boolean);
    const history=new Map(state.data.projects.map(c=>[c.project.project_id,[]]));
    for(const r of records()) history.get(r.project_id).push(r.summary,r.state_snapshot?.next_step,r.state_snapshot?.blocker);
    return state.data.projects.filter(c=>{
      if(state.category!=="all" && c.project.category!==state.category) return false;
      if(state.status!=="all" && currentStatus(c)!==state.status) return false;
      const haystack=normalized([c.project.public_name,c.project.project_id,...c.project.aliases,c.state_snapshot?.next_step,c.state_snapshot?.blocker,...history.get(c.project.project_id)].join(" "));
      return terms.every(term=>haystack.includes(term));
    }).sort((a,b)=>(Date.parse(b.last_recorded_at)||0)-(Date.parse(a.last_recorded_at)||0) || a.project.public_name.localeCompare(b.project.public_name,"zh-CN") || a.project.project_id.localeCompare(b.project.project_id));
  }
  function empty(title, detail, action, handler) {
    const el=node("div",undefined,"empty"); el.append(node("h3",title),node("p",detail)); if(action) el.append(button(action,handler,"secondary")); return el;
  }
  function renderCard(card) {
    const p=card.project, status=currentStatus(card), el=node("article",undefined,"project-card"); el.dataset.projectId=p.project_id;
    const top=node("div",undefined,"card-top"); top.append(node("span",labels[p.category],`category-label ${p.category}`),node("span",labels[status],`status ${status}`));
    el.append(top,node("h3",p.public_name,"project-title"));
    const progress=node("div",undefined,"card-progress"); progress.append(node("span",card.latest_progress.length>1?"最近进展 · 同日先后未定":"最近进展","mini-label"));
    if(!card.latest_progress.length) progress.append(node("p","尚无工作进展记录","muted"));
    for(const r of card.latest_progress) { const item=node("div",undefined,"progress-item"); item.append(node("p",r.summary),node("p",time(r.occurred_at),"date-label")); progress.append(item); }
    el.append(progress);
    const next=node("div",undefined,"card-next"); next.append(node("span","下一步","mini-label"),node("p",card.state_snapshot?.next_step??"尚未记录")); el.append(next);
    if(card.state_snapshot?.blocker) el.append(node("p",`阻塞：${card.state_snapshot.blocker}`,"blocker"));
    const bottom=node("div",undefined,"card-bottom"); const historyButton=button("查看历史 ↗",()=>openHistory(p.project_id),"history-button"); historyButton.setAttribute("aria-label",`查看 ${p.public_name} 的历史`);
    bottom.append(node("small",`最后录入 ${time(card.last_recorded_at,true)}`),historyButton); el.append(bottom); return el;
  }
  function renderTimeline(container, ids, detailed=false) {
    container.replaceChildren(); let count=0;
    const names=new Map(state.data.projects.map(c=>[c.project.project_id,c.project.public_name]));
    for(const day of state.data.timeline) {
      const timed=day.timed.filter(r=>ids.has(r.project_id)), untimed=day.untimed.filter(r=>ids.has(r.project_id));
      if(!timed.length && !untimed.length) continue;
      const section=node("section",undefined,"timeline-day");
      const date=node("div",undefined,"timeline-date"); date.append(node("strong",day.date.slice(5).replace("-"," / ")),node("span",day.date.slice(0,4)));
      const entries=node("div",undefined,"timeline-entries");
      for(const [items,label] of [[timed,"已记录时间（上海）"],[untimed,"当日，时间未记录"]]) {
        if(!items.length) continue; entries.append(node("p",label,"precision-label"));
        for(const r of items) {
          count++; const item=node("article",undefined,"timeline-entry"); item.dataset.recordId=r.record_id;
          const top=node("div",undefined,"entry-top"); top.append(detailed?node("span",r.record_type==="progress"?"工作进展":"状态更新","entry-meta"):button(names.get(r.project_id),()=>openHistory(r.project_id),"entry-project"));
          top.append(node("span",`${detailed?"":r.record_type==="progress"?"工作进展 · ":"状态更新 · "}${time(r.occurred_at)}`,"entry-meta"));
          item.append(top,node("p",r.summary));
          if(r.state_snapshot) {
            const snapshot=node("div",undefined,"entry-state");
            snapshot.append(node("span",`${labels[r.state_snapshot.status]} · 状态证据 ${time(r.state_as_of)}`));
            if(detailed) { snapshot.append(node("p",`下一步：${r.state_snapshot.next_step??"未记录"}`),node("p",`阻塞：${r.state_snapshot.blocker??"未记录"}`)); }
            item.append(snapshot);
          }
          if(detailed) item.append(node("small",`录入于 ${time(r.recorded_at)}`)); entries.append(item);
        }
      }
      section.append(date,entries);container.append(section);
    }
    if(!count) container.append(empty("还没有历史记录","当前项目尚无可展示的记录。"));
    return count;
  }
  function render() {
    if(!state.data) return;
    const all=state.data.projects, visible=filteredProjects(), ids=new Set(visible.map(c=>c.project.project_id));
    $("stat-total").textContent=all.length;
    for(const key of ["active","blocked","done"]) $(`stat-${key}`).textContent=all.filter(c=>currentStatus(c)===key).length;
    for(const b of document.querySelectorAll("[data-category]")) { b.setAttribute("aria-pressed",String(b.dataset.category===state.category));b.querySelector(".count").textContent=b.dataset.category==="all"?all.length:all.filter(c=>c.project.category===b.dataset.category).length; }
    const cards=$("projects"); cards.replaceChildren(...visible.map(renderCard)); cards.setAttribute("aria-busy","false");
    if(!all.length) cards.append(empty("还没有项目记录","从一条本地草稿开始，核对后再加入看板。","记录第一条进度",()=>openRecord()));
    else if(!visible.length) cards.append(empty("没有匹配的项目","试试其他关键词，或清除领域和状态筛选。","清除筛选",clearFilters));
    const count=renderTimeline($("timeline"),ids);
    if(!visible.length) { $("timeline").replaceChildren(empty(all.length?"没有匹配的记录":"还没有历史记录",all.length?"清除筛选后查看全部项目的记录。":"导入第一条草稿后，历史会出现在这里。",all.length?"清除筛选":"记录第一条进度",all.length?clearFilters:()=>openRecord())); }
    $("results").textContent=`显示 ${visible.length} / ${all.length} 个项目 · ${count} 条历史记录`;
  }
  function clearFilters() { state.category="all";state.status="all";state.query="";$("search").value="";$("status-filter").value="all";render(); }
  function setView(view) { state.view=view; for(const v of ["projects","timeline"]) { $(`tab-${v}`).setAttribute("aria-selected",String(v===view));$(`tab-${v}`).tabIndex=v===view?0:-1;$(`panel-${v}`).hidden=v!==view; } }
  function openDialog(id) {
    const d=$(id);returnFocus.set(id,document.activeElement);
    if(typeof d.showModal==="function") d.showModal(); else {d.setAttribute("open","");$("shell").inert=true;}
    d.querySelector("button,input,select,textarea")?.focus();
  }
  function closeDialog(id) {
    const d=$(id); if(typeof d.close==="function") d.close(); else {d.removeAttribute("open");d.dispatchEvent(new Event("close"));}
  }
  function openHistory(id) {
    const card=state.data.projects.find(c=>c.project.project_id===id); if(!card)return;
    state.historyProject=id;$("history-title").textContent=card.project.public_name;$("history-category").textContent=labels[card.project.category];
    const summary=node("div",undefined,"history-summary");summary.append(node("p",`当前状态：${labels[currentStatus(card)]}`),node("p",`下一步：${card.state_snapshot?.next_step??"尚未记录"}`));
    if(card.state_snapshot)summary.append(node("p",`阻塞：${card.state_snapshot.blocker??"未记录"}`),node("small",`状态证据：${card.state_evidence_times.map(t=>time(t)).join("、")}`));
    $("history-summary").replaceChildren(summary);
    if(card.project.aliases.length)$("history-summary").append(node("p",`曾用名：${card.project.aliases.join("、")}`,"history-aliases"));
    renderTimeline($("history-records"),new Set([id]),true);openDialog("history-dialog");
  }
  function recordError(message) { $("record-error").hidden=!message;$("record-error").textContent=message??""; }
  function projectId() { const value=$("record-project").value==="__custom__"?$("custom-project").value.trim():$("record-project").value;if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$/.test(value))throw new Error("请选择项目，或填写有效的项目代号（字母、数字、下划线和短横线）。");return value; }
  function invalidateInstruction() { $("instruction-result").hidden=true;$("copy-status").textContent="";recordError(""); }
  function setMode(mode) {
    state.mode=mode;for(const m of ["current","scan","manual"]) {$(`mode-${m}`).setAttribute("aria-selected",String(m===mode));$(`mode-${m}`).tabIndex=m===mode?0:-1;$(`record-${m}`).hidden=m!==mode;}invalidateInstruction();
  }
  function openRecord(id=null) {
    if(id){if($("record-project").value!==id)newDraft();$("record-project").value=id;$("custom-project-wrap").hidden=true;invalidateInstruction();}
    recordError("");openDialog("record-dialog");
  }
  function validDate(value) { if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return false;const d=new Date(value+"T00:00:00Z");return !Number.isNaN(d.getTime()) && d.toISOString().slice(0,10)===value; }
  function inputTime(id, precision, label) {
    const value=$(id).value;
    if($(precision).value==="date") {if(!validDate(value))throw new Error(`请填写有效的${label}日期。`);return value;}
    const match=value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
    if(!match || !validDate(match[1]) || Number(match[2])>23 || Number(match[3])>59 || Number(match[4]??0)>59)throw new Error(`请填写有效的${label}，精确时间按上海时区解释。`);
    return `${match[1]}T${match[2]}:${match[3]}:${match[4]??"00"}+08:00`;
  }
  function makeInstruction(mode) {
    try {
      const id=projectId();let intro;
      if(mode==="scan") {
        const since=$("scan-since").value, until=$("scan-until").value;
        if(!validDate(since)||!validDate(until)||since>until)throw new Error("请填写有效的补扫日期范围，开始日期不能晚于结束日期。");
        intro=`请为项目 ${id} 补扫 ${since} 至 ${until}（含结束当天，Asia/Shanghai）的工作记录。先从本地来源映射定位用户指定的聊天；映射缺失或多个来源不明确时先询问，不扫描全盘或其他聊天。`;
      } else intro=`请为项目 ${id} 记录本次聊天中已经发生的工作，优先使用当前上下文。`;
      const body=[intro,"请先读取 progress-dashboard 的 AGENTS.md、docs/CONTRACTS.md 和 schemas/draft-v1.schema.json。项目代号不存在时，先用 project.py 生成注册表草稿，不直接写入 public/。",
        "仅提取有证据的进展；区分 progress 和 state_update。保留 occurred_at 的原始精度，state_as_of 使用状态证据有效时间；没有证据时 state_as_of 和 state_snapshot 都为 null，不从补录时间推断状态。",
        "生成本地 draft-v1：沿用已存在的 draft_id / 来源 unit_id；source、evidence 留在本地，公开字段使用脱敏摘要。不要填写 record_id 或 recorded_at，交给 import.py 分配。不能确认的内容标记 needs_review。",
        ...(mode==="scan"?["只读访问所选聊天；从检查点增量读取，并复查最近 5 个已完成轮次，比较消息 ID 和内容哈希。每次最多 50 轮，达到上限仍未覆盖目标范围时返回 incomplete，保存续读边界，不能跳过缺口。无法读取时明确报告，并接受手动提供记录。"]:[]),
        "导入后生成完整本地预览，列出进展、状态、下一步和待核实事项。先向我展示预览和批次摘要，等待我确认；本次不要批准、推送、部署或修改原始聊天。"].join("\n\n");
      $("instruction-text").value=body;$("instruction-result").hidden=false;$("copy-status").textContent="";recordError("");
    } catch(error) { recordError(error.message); }
  }
  async function copyInstruction() {
    const field=$("instruction-text"), value=field.value;if(!value)return;
    try { if(!navigator.clipboard?.writeText)throw new Error("unavailable");await navigator.clipboard.writeText(value);$("copy-status").textContent="指令已复制，请粘贴到对应的 Agent 聊天。"; }
    catch { field.focus();field.select();$("copy-status").textContent="自动复制不可用，已选中指令；请使用系统复制操作。"; }
  }
  function syncSnapshot() {
    const required=$("record-type").value==="state_update";
    if(required)$("has-snapshot").checked=true;
    $("has-snapshot").disabled=required;
    const enabled=$("has-snapshot").checked;$("snapshot-fields").hidden=!enabled;$("snapshot-fields").disabled=!enabled;
  }
  function changePrecision(input, precision) { $(input).type=$(precision).value==="date"?"date":"datetime-local";$(input).step="1";$(input).value=""; }
  function newDraft() {
    $("manual-form").reset();state.draftId=null;$("record-project").disabled=false;$("custom-project").disabled=false;$("occurred-at").type="date";$("occurred-at").value=today();$("state-as-of").type="date";$("state-as-of").value="";syncSnapshot();$("draft-result").hidden=true;$("draft-json").value="";recordError("");
  }
  function requiredText(id,label) {const value=$(id).value.trim();if(!value || value.length>20000)throw new Error(`请填写${label}，且不超过 20000 字符。`);return value;}
  function newId() {
    if(crypto.randomUUID)return "draft_"+crypto.randomUUID().replaceAll("-","");
    if(crypto.getRandomValues)return "draft_"+Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,"0")).join("");
    throw new Error("浏览器无法生成可靠的草稿 ID，请改用 Agent 记录入口。");
  }
  function exportDraft(event) {
    event.preventDefault();recordError("");
    try {
      const id=projectId(), occurred=inputTime("occurred-at","occurred-precision","发生时间"), summary=requiredText("summary","进展摘要"), evidence=requiredText("evidence","记录依据");
      const hasSnapshot=$("has-snapshot").checked || $("record-type").value==="state_update";
      const snapshot=hasSnapshot?{status:$("snapshot-status").value,next_step:$("next-step").value.trim()||null,blocker:$("blocker").value.trim()||null}:null;
      if(snapshot && (!statuses.includes(snapshot.status) || (snapshot.next_step?.length??0)>20000 || (snapshot.blocker?.length??0)>20000))throw new Error("请检查状态快照字段。");
      const stateAsOf=hasSnapshot?inputTime("state-as-of","state-precision","状态证据时间"):null;
      state.draftId??=newId();
      $("record-project").disabled=true;$("custom-project").disabled=true;
      const draft={schema_version:1,draft_id:state.draftId,project_id:id,record_type:$("record-type").value,occurred_at:occurred,summary,state_as_of:stateAsOf,state_snapshot:snapshot,source:null,evidence,verification:$("verified").checked?"confirmed":"needs_review",revision:null};
      const serialized=JSON.stringify(draft,null,2)+"\n";
      $("draft-json").value=serialized;$("draft-result").hidden=false;
      try {
        const blob=new Blob([serialized],{type:"application/json;charset=utf-8"}), url=URL.createObjectURL(blob);
        const link=node("a");link.href=url;link.download=`${state.draftId}.json`;link.hidden=true;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
        $("draft-status").textContent="已发起草稿下载。此操作不会导入或发布；请检查下载结果。";
      } catch { $("draft-status").textContent="下载不可用，请复制下方 JSON 保存为本地文件；尚未导入或发布。";$("draft-json").focus();$("draft-json").select(); }
    } catch(error) { recordError(error.message); }
  }
  function bindTabKeys(container, selector, activate) {
    container.addEventListener("keydown",event=>{
      if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;
      const tabs=[...container.querySelectorAll(selector)], current=tabs.indexOf(document.activeElement);if(current<0)return;
      event.preventDefault();const next=event.key==="Home"?0:event.key==="End"?tabs.length-1:(current+(event.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;
      activate(tabs[next]);tabs[next].focus();
    });
  }
  function bind() {
    document.querySelectorAll("[data-category]").forEach(b=>b.addEventListener("click",()=>{state.category=b.dataset.category;render();}));
    $("search").addEventListener("input",()=>{state.query=$("search").value;render();});$("status-filter").addEventListener("change",()=>{state.status=$("status-filter").value;render();});$("clear-filters").addEventListener("click",clearFilters);
    for(const view of ["projects","timeline"]) $(`tab-${view}`).addEventListener("click",()=>setView(view));
    bindTabKeys(document.querySelector(".view-tabs"),'[role="tab"]',b=>setView(b.id.replace("tab-","")));
    $("open-record").addEventListener("click",()=>openRecord());$("history-record").addEventListener("click",()=>{const id=state.historyProject;closeDialog("history-dialog");openRecord(id);});
    document.querySelectorAll("[data-close]").forEach(b=>b.addEventListener("click",()=>closeDialog(b.dataset.close)));
    document.querySelectorAll("dialog").forEach(d=>{
      d.addEventListener("close",()=>{if(!document.querySelector("dialog[open]")){$("shell").inert=false;const target=returnFocus.get(d.id);if(target?.isConnected)target.focus();}});
      d.addEventListener("keydown",event=>{
        if(event.key==="Escape"){event.preventDefault();closeDialog(d.id);}
        if(event.key!=="Tab")return;
        const focusable=[...d.querySelectorAll('button,input,select,textarea,a[href]')].filter(e=>!e.disabled && !e.closest('[hidden]') && e.tabIndex>=0);
        const first=focusable[0],last=focusable.at(-1);
        if(event.shiftKey && document.activeElement===first){event.preventDefault();last?.focus();}
        if(!event.shiftKey && document.activeElement===last){event.preventDefault();first?.focus();}
      });
    });
    document.querySelectorAll("[data-mode]").forEach(b=>b.addEventListener("click",()=>setMode(b.dataset.mode)));
    bindTabKeys(document.querySelector(".mode-tabs"),'[role="tab"]',b=>setMode(b.dataset.mode));
    $("record-project").addEventListener("change",()=>{$("custom-project-wrap").hidden=$("record-project").value!=="__custom__";invalidateInstruction();$("draft-result").hidden=true;});
    for(const id of ["custom-project","scan-since","scan-until"])$(id).addEventListener("input",invalidateInstruction);
    $("make-current").addEventListener("click",()=>makeInstruction("current"));$("make-scan").addEventListener("click",()=>makeInstruction("scan"));$("copy-instruction").addEventListener("click",copyInstruction);
    $("record-type").addEventListener("change",syncSnapshot);$("has-snapshot").addEventListener("change",syncSnapshot);
    $("occurred-precision").addEventListener("change",()=>changePrecision("occurred-at","occurred-precision"));$("state-precision").addEventListener("change",()=>changePrecision("state-as-of","state-precision"));
    $("manual-form").addEventListener("submit",exportDraft);$("manual-form").addEventListener("input",()=>{$("draft-result").hidden=true;recordError("");});$("new-draft").addEventListener("click",newDraft);$("retry-load").addEventListener("click",load);
    $("scan-since").value=today();$("scan-until").value=today();newDraft();
  }
  function actionsURL(value) {
    if(typeof value!=="string")return null;
    try{const url=new URL(value);return url.origin==="https://github.com" && !url.username && !url.password && !url.search && !url.hash && /^\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/actions(?:\/runs\/\d+)?\/?$/.test(url.pathname)?url.href:null;}catch{return null;}
  }
  async function load() {
    const sequence=++state.loadSequence;$("load-error").hidden=true;$("results").textContent="正在读取记录…";$("projects").setAttribute("aria-busy","true");$("retry-load").disabled=true;
    try{
      const responses=await Promise.all([fetch("./data.json",{cache:"no-store"}),fetch("./build.json",{cache:"no-store"})]);
      if(responses.some(r=>!r.ok))throw new Error("数据加载失败，请确认本地 HTTP 服务和构建结果，再重新加载。");
      const [data,build]=await Promise.all(responses.map(r=>r.json()));assertData(data,build);if(sequence!==state.loadSequence)return;
      state.data=data;state.build=build;
      $("data-meta").textContent=build.data_changed_at?`数据更新时间：${time(build.data_changed_at)}`:`数据最近录入：${time(data.data_updated_at)}（不含修订时间）`;
      $("build-meta").textContent=`网站构建时间：${time(build.built_at)}`;
      const url=actionsURL(build.actions_url);$("actions-link").hidden=!url;$("actions-unavailable").hidden=!!url;if(url)$("actions-link").href=url;else $("actions-link").removeAttribute("href");
      $("preview-banner").hidden=!build.local_preview;$("preview-banner").textContent=build.synthetic?"合成数据 · 仅供本地交互预览，不代表真实工作记录":"本地候选预览 · 尚未发布";
      const select=$("record-project"), existing=select.value;select.replaceChildren(new Option("请选择项目",""));
      for(const c of data.projects)select.add(new Option(`${c.project.public_name} · ${labels[c.project.category]}`,c.project.project_id));select.add(new Option("输入项目代号…","__custom__"));select.value=[...select.options].some(o=>o.value===existing)?existing:"";
      $("custom-project-wrap").hidden=select.value!=="__custom__";render();
    }catch(error){if(sequence!==state.loadSequence)return;$("load-error").hidden=false;$("load-error-text").textContent=error.message;$("results").textContent=state.data?"刷新失败，仍显示上次成功读取的数据。":"未能读取数据；仍可手动生成本地草稿。";$("projects").setAttribute("aria-busy","false");}
    finally{if(sequence===state.loadSequence)$("retry-load").disabled=false;}
  }
  bind();load();
})();
