'use strict';
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let me, assets=[], runs=[], requests=[], current='catalogue', selected=null, toastTimer;
const labels={purview:'Microsoft Purview',sources:'Source connections',catalogue:'Data catalogue',lineage:'Lineage explorer',quality:'Quality monitor',requests:'Access requests',audit:'Audit trail',settings:'Account & team'};
const date=(s)=>s?new Date(s).toLocaleString(): 'Not scanned';
function badge(status){return `<span class="badge ${['failed','quality_failed','blocked','source_error','revoked','rejected'].includes(status)?'bad':['pending','schema_drift','expired','unscanned'].includes(status)?'warn':''}">${esc(status.replaceAll('_',' '))}</span>`;}
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6000);}
async function api(path,options={}){
  const headers={'Content-Type':'application/json',...(options.method&&options.method!=='GET'?{'X-CSRF-Token':me?.csrf||''}:{})};
  const r=await fetch('/api'+path,{...options,headers,credentials:'same-origin'});
  let data=await r.json();
  if(!r.ok){if(r.status===401 && path!='/login'){me=null;$('#workspace').hidden=true;$('#login-screen').hidden=false;}
    throw new Error(typeof data.detail==='string'?data.detail:'Please check the form values');}
  return data;
}
const post=(p,data={})=>api(p,{method:'POST',body:JSON.stringify(data)});
function modal(html){$('#modal-content').innerHTML=html;$('#modal').showModal();}
function table(head, rows){return `<div class="table-wrap"><table><thead><tr>${head.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.length?rows.map(row=>`<tr>${row.map(v=>`<td>${v}</td>`).join('')}</tr>`).join(''):`<tr><td colspan="${head.length}" class="empty">No records yet</td></tr>`}</tbody></table></div>`;}
function heading(k,title,desc,action=''){return `<div class="page-head"><div><span class="eyebrow">${k}</span><h1>${title}</h1><p>${desc}</p></div>${action}</div>`;}
function scanButton(){return me.role==='admin'?'<button class="primary" data-action="scan">↻ &nbsp; Scan & check sources</button>':'';}
async function refresh(){[assets,runs,requests]=await Promise.all([api('/assets'),api('/runs'),api('/requests')]);$('#pending-count').textContent=requests.filter(r=>r.status==='pending'&&r.can_decide).length||'';}
async function enter(){ $('#login-screen').hidden=true;$('#workspace').hidden=false;$('#audit-nav').hidden=me.role!=='admin';$('#purview-nav').hidden=me.role!=='admin';$('#identity').textContent=`${me.username} · ${me.role}`;await refresh();await render();}
async function render(){
  $('#crumb').textContent=labels[current];
  document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===current));
  if(current==='catalogue') renderCatalogue();
  if(current==='quality') renderQuality();
  if(current==='requests') renderRequests();
  if(current==='settings') renderSettings();
  if(current==='lineage') await renderLineage();
  if(current==='audit') await renderAudit();
  if(current==='sources') await renderSources();
  if(current==='purview') await renderPurview();
}
function renderCatalogue(){
  const latest=runs[0];const checks=latest?.results||[];const passed=checks.filter(r=>r.passed).length;
  $('#content').innerHTML=heading('YOUR DATA, IN CONTEXT','Data catalogue','Find the right dataset. Understand its meaning. Know who owns it.',scanButton())+
  `<div class="metrics"><div class="metric"><span>CATALOGUED ASSETS</span><strong>${assets.length.toString().padStart(2,'0')}</strong><small>Across CSV + operational database</small></div><div class="metric"><span>HEALTHY DATASETS</span><strong>${assets.filter(a=>a.status==='ready').length} <small>/ ${assets.length}</small></strong><small>Passing current quality gates</small></div><div class="metric"><span>QUALITY CHECKS</span><strong>${passed} <small>/ ${checks.length||'—'}</small></strong><small>Latest scan results</small></div><div class="metric"><span>DOCUMENTED OWNERS</span><strong>${new Set(assets.map(a=>a.owner.team)).size.toString().padStart(2,'0')}</strong><small>Accountable source & analytics teams</small></div></div>`+
  `<div class="toolbar"><input class="search" id="asset-search" type="search" aria-label="Search datasets" placeholder="Search datasets, fields, owners…"><span class="muted">${assets.length} assets · Last scan ${esc(date(latest?.at))}</span></div><div class="cards" id="asset-cards"></div><div class="notice"><strong>Governed discovery.</strong> Definitions are visible to signed-in users. Data previews require owner approval and a passing quality gate. Customer contact data is classified as personal.</div>`;
  drawCards(assets);
}
function drawCards(list){$('#asset-cards').innerHTML=list.length?list.map(a=>`<article class="card"><div class="card-head"><span class="source-icon">${a.id==='sales'?'↗':'▤'}</span><h3>${esc(a.name)}</h3>${badge(a.status)}</div><p class="description">${esc(a.description)}</p><div class="card-meta"><span>OWNER<br><strong>${esc(a.owner.team)}</strong></span><span>SOURCE<br><strong>${esc(a.source)}</strong></span><span>SCHEMA<br><strong>${a.columns.length} documented fields</strong></span></div><div class="card-bottom"><span class="badge ${a.classification==='confidential'?'warn':'neutral'}">${esc(a.classification)}</span><button data-action="detail" data-id="${esc(a.id)}">Explore dataset →</button></div></article>`).join(''):'<div class="empty">No matching datasets. Try a field name or owner.</div>';}
async function detail(id){
  selected=await api('/assets/'+encodeURIComponent(id));const a=selected;
  modal(`<div class="detail-top"><div><span class="eyebrow">DATASET / REVISION ${a.revision}</span><h2>${esc(a.name)}</h2></div>${badge(a.status)}</div><p class="muted">${esc(a.description)}</p><div class="notice"><strong>${esc(a.owner.team)}</strong> · ${esc(a.owner.contact)}<br>${esc(a.source)}<br>Scanned ${esc(date(a.scanned_at))} · Downstream impact: ${esc(a.downstream.join(', ')||'None')}</div><h3>Field definitions</h3>${table(['Field','Definition','Type','Sensitivity'],a.columns.map(c=>[esc(c.name),esc(c.definition),esc(c.type),esc(c.classification)]))}<h3>Access & retention</h3><p class="small">${esc(a.access.purpose)}. ${esc(a.access.retention)}.</p><p class="small muted">Approvals grant a seven-day preview entitlement inside Atlas. External source permissions and deletion are separate operational processes.</p>${a.status==='schema_drift'?`<p class="error">Schema changed. Observed: ${esc(a.observed_columns.join(', '))}. Preview is blocked.</p>`:''}<div class="actions">${a.can_preview?`<button class="primary" data-action="preview" data-id="${esc(a.id)}">Preview data</button>`:`<button class="primary" data-action="request" data-id="${esc(a.id)}">Request access</button>`}${a.can_manage?`<button data-action="edit" data-id="${esc(a.id)}">Edit definitions</button>${a.status==='schema_drift'?`<button data-action="review-schema" data-id="${esc(a.id)}">Review schema change</button>`:''}`:''}<button data-action="versions" data-id="${esc(a.id)}">Version history</button></div>`);
}
function renderQuality(){
  const latest=runs[0];
  $('#content').innerHTML=heading('OBSERVE & IMPROVE','Quality monitor','Persistent checks, schema changes, and downstream impact.',scanButton())+
  `<div class="notice">Sources are checked every five minutes by default. Failed source checks block publication of enriched sales. Counts refer to the latest completed scan; no external alerts are sent.</div>`+
  (latest?`<section class="panel"><h3>Latest run #${latest.id} ${badge(latest.status)}</h3><p class="muted small">${esc(latest.summary)} · ${esc(date(latest.at))}</p>${table(['Dataset','Rule','Result','Rows checked','Failures'],latest.results.map(r=>[esc(r.asset),esc(r.rule),badge(r.passed?'passed':'failed'),r.rows_checked,`${r.failure_count} ${r.failed_rows.length?'(rows '+esc(r.failed_rows.join(', '))+')':''}`]))}</section>`:'<div class="empty">Run the first scan to collect quality evidence.</div>')+
  `<section class="panel"><h3>Scan history</h3>${table(['Run','Time','Triggered by','Result','Summary'],runs.map(r=>['#'+r.id,esc(date(r.at)),esc(r.actor),badge(r.status),esc(r.summary)]))}</section>`;
}
async function renderLineage(){
  const data=await api('/lineage');
  $('#content').innerHTML=heading('FOLLOW THE JOURNEY','Lineage explorer','Trace source fields into enriched sales and understand change impact.')+
  `<section class="panel"><h3>Sales data flow</h3><div class="lineage-flow"><div class="lineage-sources">${['customers','products','orders'].map(id=>`<div class="node">${esc(assets.find(a=>a.id===id)?.name||id)}<span>${id==='customers'?'CRM · CSV':'Operational · SQLite'}</span></div>`).join('')}</div><div class="arrow">→</div><div class="node target">Enriched sales<span>Managed transformation v1</span></div></div></section>`+
  `<div class="notice">${data.run_id?`Lineage last captured during successful transformation in run #${data.run_id}, ${esc(date(data.captured_at))}.`:'No transformation has completed yet. The table below shows declared lineage.'} Check dataset status before using this historical evidence. Revenue uses current product prices and excludes taxes, discounts and returns.</div>`+
  `<section class="panel"><h3>Column-level lineage</h3>${table(['Target field','Source fields','Transformation'],data.declared.map(e=>[esc(e.target+'.'+e.target_column),e.sources.map(s=>`<code>${esc(s)}</code>`).join('<br>'),esc(e.transformation)]))}</section>`;
}
function renderRequests(){
  $('#content').innerHTML=heading('PURPOSE-BASED PERMISSIONS','Access requests','Ask for access, record a decision, and review time-limited entitlements.')+
  (requests.length?requests.map(r=>`<section class="panel request-row"><div><h3>${esc(r.asset_id)} ${badge(r.effective_status)}</h3><p><strong>${esc(r.user_id)}</strong> · ${esc(r.purpose)}</p><p class="small">Requested ${esc(date(r.requested_at))}${r.expires?` · Expires ${esc(date(r.expires))}`:''}${r.decided_by?`<br>Decision by ${esc(r.decided_by)} · ${esc(r.note)}`:''}</p></div><div class="actions">${r.can_decide&&r.status==='pending'?`<button class="primary" data-action="decide" data-choice="approve" data-id="${r.id}">Approve</button><button data-action="decide" data-choice="reject" data-id="${r.id}">Reject</button>`:r.can_decide&&r.effective_status==='approved'?`<button data-action="decide" data-choice="revoke" data-id="${r.id}">Revoke access</button>`:''}</div></section>`).join(''):'<div class="panel empty">No access requests yet. Open a dataset in the catalogue to request a preview.</div>');
}
async function renderAudit(){const events=await api('/audit');$('#content').innerHTML=heading('ACCOUNTABILITY, RECORDED','Audit trail','Application events for sign-in, metadata changes, access decisions and data previews.')+`<div class="notice">The latest 200 events are shown. Events are append-only through this API; database administrators can modify storage. Export to protected external logging for stronger evidence retention.</div><section class="panel">${table(['Time','Actor','Action','Resource','Details'],events.map(e=>[esc(date(e.at)),esc(e.actor),esc(e.action),esc(e.resource),esc(JSON.stringify(e.details))]))}</section>`;}
async function renderSources(){
  const sources=await api('/sources');
  $('#content').innerHTML=heading('CONNECT & DISCOVER','Source connections','Read-only database scans and managed CSV imports.',scanButton())+
  `<section class="panel"><h3>Registered connectors</h3>${table(['Dataset','Connector','Managed location','Table'],sources.map(s=>[esc(s.asset_id),esc(s.kind),esc(s.location),esc(s.table_name||'—')]))}</section><div class="notice">The operational database connector is configured for the included products and orders tables. CSV imports are copied into managed storage; Atlas never receives arbitrary filesystem paths or SQL. Limits: 5 MB and 5,000 rows per source.</div>`+
  (me.role==='admin'?`<section class="panel"><h3>Connect another CSV dataset</h3><p class="small muted">Imported fields begin as personal and the dataset as confidential. Owners can refine definitions. A fresh scan is required before any preview.</p><form id="source-form"><div class="form-grid"><div><label>Asset ID<input name="asset_id" pattern="[a-z][a-z0-9_]{2,59}" placeholder="supplier_master" required></label><label>Display name<input name="name" minlength="3" required></label><label>Owner team<input name="owner_team" required></label></div><div><label>Business description<textarea name="description" minlength="10" required></textarea></label><label>Unique key column<input name="key_column" placeholder="supplier_id" required></label><label>CSV file<input name="csv_file" type="file" accept=".csv,text/csv" required></label></div></div><button class="primary">Connect dataset</button></form></section>`:'');
}
async function renderPurview(){
  const state=await api('/purview/status');
  $('#content').innerHTML=heading('AZURE DATA MAP CONNECTOR','Microsoft Purview','Publish documented assets and captured lineage to your Purview account.')+
  `<div class="notice"><strong>${state.configured?'Configured for publishing':'Not connected to Azure'}</strong><br>${state.configured?'Configuration is present; test authentication and publish to verify the remote catalogue.':'No Azure account is required to preview the metadata export. Configure the server environment when your account is ready.'}<br>Dataset rows, user passwords, sessions and individual access requests are never included.</div>`+
  `<section class="panel"><h3>Connection configuration</h3>${table(['Setting','Value'],[['Endpoint',esc(state.endpoint||'Not configured')],['Collection',esc(state.collection_id||'Not configured')],['Stable namespace',esc(state.namespace)],['Azure authentication',esc(state.auth_mode)],['Publish after source scans',state.sync_after_scan?'Enabled':'Disabled'],['Custom type creation',state.create_types?'Enabled':'Disabled']])}${state.configuration_error?`<p class="error">${esc(state.configuration_error)}</p>`:''}<div class="actions"><button class="primary" data-action="purview-preview">Preview metadata export</button><button data-action="purview-test" ${state.configured?'':'disabled'}>Test Azure connection</button><button data-action="purview-sync" ${state.configured?'':'disabled'}>Publish catalogue</button></div></section>`+
  `<div class="notice">Stable qualified names let repeated publishes update the same entities. Native dataset lineage is published as a Process. Column definitions and detailed mappings are also exported; their native portal visualization has not been verified. Labels are custom metadata, not Microsoft sensitivity labels or access policies.</div>`+
  `<section class="panel"><h3>Publication history</h3>${table(['Run / time','Actor','Result','Verified','Summary'],state.history.map(r=>['#'+r.id+'<br>'+esc(date(r.at)),esc(r.actor),badge(r.status),r.verified_count+' / '+r.entity_count,esc(r.summary)]))}</section>`;
}
function renderSettings(){
  $('#content').innerHTML=heading('WORKSPACE ADMINISTRATION','Account & team','Manage your credentials and named workspace accounts.')+`<div class="form-grid"><section class="panel"><h3>Change your password</h3><form id="password-form"><label>Current password<input name="current_password" type="password" autocomplete="current-password" required></label><label>New password (12+ characters)<input name="new_password" type="password" autocomplete="new-password" minlength="12" required></label><button class="primary">Change password</button></form></section>${me.role==='admin'?`<section class="panel"><h3>Create a team account</h3><form id="user-form"><label>Username<input name="username" pattern="[a-zA-Z0-9_.-]{3,80}" required></label><label>Temporary password (12+ characters)<input name="password" type="password" minlength="12" autocomplete="new-password" required></label><label>Role<select name="role"><option value="analyst">Analyst</option><option value="steward">Steward</option><option value="admin">Administrator</option></select></label><label>Team<input name="team" placeholder="Customer Operations" required></label><button class="primary">Create account</button></form><p class="small muted">Stewards manage assets whose owner team exactly matches their account team. Share credentials through your approved secure channel.</p></section>`:''}</div>`;
}
async function act(action,id,choice){
  if(action==='purview-preview'){
    const plan=await post('/purview/preview');
    modal(`<h2>Purview export preview</h2><p>${plan.entity_count} metadata entities. <strong>No Azure request was made.</strong></p><p class="small muted">Owner contact details and free-text definitions are included. Review before publishing. Credentials, dataset rows and individual access decisions are excluded.</p>${table(['Entity type','Count'],Object.entries(plan.counts).map(([k,v])=>[esc(k),v]))}<p class="small">Captured lineage run: ${plan.lineage_run_id||'None yet; run a source scan first'}<br>Snapshot hash: <code>${esc(plan.payload_hash)}</code></p><details><summary>Inspect exact entity payload</summary><pre>${esc(JSON.stringify(plan.payload,null,2))}</pre></details><details><summary>Inspect custom type definitions</summary><pre>${esc(JSON.stringify(plan.type_definitions,null,2))}</pre></details>`);return;
  }
  if(action==='purview-test'){
    const result=await post('/purview/test');toast(result.message);return;
  }
  if(action==='purview-sync'){
    toast('Publishing metadata and verifying remote entities…');
    try{const result=await post('/purview/sync');toast(result.summary);}finally{await renderPurview();}return;
  }
  if(action==='scan'){
    toast('Scanning sources and checking quality…');const r=await post('/scans');await refresh();await render();toast(`Run #${r.id}: ${r.summary}`);return;
  }
  if(action==='detail'){await detail(id);return;}
  if(action==='preview'){
    const data=await api(`/assets/${encodeURIComponent(id)}/preview`);const columns=Object.keys(data.rows[0]||{});
    modal(`<h2>Data preview / ${esc(id)}</h2><p class="small muted">Showing up to 25 of ${data.total_rows} rows. This read has been recorded in the audit trail.</p>${table(columns,data.rows.map(r=>columns.map(c=>esc(r[c]))))}`);return;
  }
  if(action==='request'){modal(`<h2>Request ${esc(id)} access</h2><p class="muted">Explain the business purpose. An owner must approve before you can preview data.</p><form id="request-form" data-id="${esc(id)}"><label>Purpose<textarea name="purpose" minlength="10" maxlength="1000" required placeholder="I need this dataset to…"></textarea></label><button class="primary">Submit request</button></form>`);return;}
  if(action==='decide'){modal(`<h2>${esc(choice[0].toUpperCase()+choice.slice(1))} access</h2><p class="muted">${choice==='approve'?'Approval grants seven days of application preview access.':'Record the reason for this decision.'}</p><form id="decision-form" data-id="${id}" data-choice="${choice}"><label>Decision note<textarea name="note" minlength="5" required></textarea></label><button class="primary">Confirm ${choice}</button></form>`);return;}
  if(action==='edit'){
    const a=selected;modal(`<h2>Edit ${esc(a.name)}</h2><form id="metadata-form" data-id="${esc(a.id)}" data-revision="${a.revision}"><label>Business description<textarea name="description" minlength="10" required>${esc(a.description)}</textarea></label><label>Classification<select name="classification"><option ${a.classification==='internal'?'selected':''}>internal</option><option ${a.classification==='confidential'?'selected':''}>confidential</option></select></label>${a.columns.map(c=>`<label>${esc(c.name)} definition<input data-column="${esc(c.name)}" value="${esc(c.definition)}" required></label>`).join('')}<button class="primary">Save revision ${a.revision+1}</button></form>`);return;
  }
  if(action==='review-schema'){
    const a=selected;
    modal(`<h2>Review observed schema</h2><p class="small muted">Only additive changes and reordering can be accepted here. New fields are marked personal; the dataset becomes confidential. Existing preview grants will be revoked. A fresh scan is required.</p><form id="schema-form" data-id="${esc(a.id)}" data-revision="${a.revision}">${a.observed_columns.map(name=>`<label>${esc(name)} definition<input data-column="${esc(name)}" value="${esc(a.columns.find(c=>c.name===name)?.definition||'')}" required></label>`).join('')}<button class="primary">Accept schema & revoke existing grants</button></form>`);return;
  }
  if(action==='versions'){
    const data=await api(`/assets/${encodeURIComponent(id)}/versions`);
    modal(`<h2>Metadata version history</h2>${data.map(v=>`<details><summary>Revision ${v.revision} · ${esc(v.actor)} · ${esc(date(v.at))}</summary><pre>${esc(JSON.stringify(v.document,null,2))}</pre></details>`).join('')}`);
  }
}
document.addEventListener('click',async e=>{
  const nav=e.target.closest('[data-view]');if(nav){current=nav.dataset.view;try{await refresh();await render();}catch(error){toast(error.message);}return;}
  const button=e.target.closest('[data-action]');if(!button)return;
  button.disabled=true;
  try{await act(button.dataset.action,button.dataset.id,button.dataset.choice);}catch(error){toast(error.message);}finally{button.disabled=false;}
});
document.addEventListener('input',e=>{if(e.target.id==='asset-search'){const q=e.target.value.toLowerCase();drawCards(assets.filter(a=>JSON.stringify(a).toLowerCase().includes(q)));}});
document.addEventListener('submit',async e=>{
  e.preventDefault();const form=e.target;const button=form.querySelector('button');if(button)button.disabled=true;
  const values=Object.fromEntries(new FormData(form));
  try{
    if(form.id==='login-form'){
      me=await post('/login',{username:$('#username').value,password:$('#password').value});$('#password').value='';$('#login-error').textContent='';await enter();return;
    }
    if(form.id==='request-form') await post(`/assets/${encodeURIComponent(form.dataset.id)}/requests`,values);
    if(form.id==='decision-form') await post(`/requests/${form.dataset.id}/decision`,{...values,action:form.dataset.choice});
    if(form.id==='metadata-form'){
      values.revision=Number(form.dataset.revision);values.definitions={};form.querySelectorAll('[data-column]').forEach(input=>values.definitions[input.dataset.column]=input.value);
      await api(`/assets/${encodeURIComponent(form.dataset.id)}`,{method:'PUT',body:JSON.stringify(values)});
    }
    if(form.id==='schema-form'){
      const definitions={};form.querySelectorAll('[data-column]').forEach(input=>definitions[input.dataset.column]=input.value);
      await post(`/assets/${encodeURIComponent(form.dataset.id)}/schema/accept`,{revision:Number(form.dataset.revision),definitions});
    }
    if(form.id==='source-form'){
      const file=form.querySelector('[type="file"]').files[0];
      if(!file||file.size>5000000)throw new Error('Choose a CSV file no larger than 5 MB');
      delete values.csv_file;values.csv_content=await file.text();
      await post('/sources/csv',values);
    }
    if(form.id==='user-form'){await post('/users',values);form.reset();toast('Account created');return;}
    if(form.id==='password-form'){await post('/password',values);me=null;$('#workspace').hidden=true;$('#login-screen').hidden=false;form.reset();toast('Password changed. Sign in again.');return;}
    $('#modal').close();await refresh();await render();toast('Saved successfully');
  }catch(error){if(form.id==='login-form')$('#login-error').textContent=error.message;else toast(error.message);}finally{if(button)button.disabled=false;}
});
$('#close-modal').addEventListener('click',()=>$('#modal').close());
$('#logout').addEventListener('click',async()=>{try{await post('/logout');me=null;$('#workspace').hidden=true;$('#login-screen').hidden=false;}catch(error){toast(error.message);}});
(async()=>{try{me=await api('/me');await enter();}catch(error){if(me)toast(error.message);}})();
