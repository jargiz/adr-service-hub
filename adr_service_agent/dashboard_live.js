(() => {
  const historySelections=new Map();
  function applyHistorySelection(card,range,series){
    card.querySelector('[data-trend-range]').value=range;
    card.querySelector('[data-trend-series]').value=series;
    card.querySelectorAll('[data-trend-window]').forEach(panel=>{panel.hidden=panel.dataset.trendWindow!==range;});
    card.querySelectorAll('[data-trend-item]').forEach(item=>{item.hidden=series!=='all'&&item.dataset.trendItem!==series;item.style.display=item.hidden?'none':'';});
  }
  document.addEventListener('change', event => {
    const input=event.target;
    if(!input.dataset || !input.matches('[data-trend-range], [data-trend-series]'))return;
    const card=input.closest('[data-trend-card]');if(!card)return;
    const range=card.querySelector('[data-trend-range]').value;
    const series=card.querySelector('[data-trend-series]').value;
    historySelections.set(card.dataset?.trendCard,{range,series});
    applyHistorySelection(card,range,series);
  });
  const storageKey = 'adr-view:' + location.pathname;
  const main = document.querySelector('main');
  const views = ['all', 'power', 'network', 'av', 'connections'];
  try {
    const saved = sessionStorage.getItem(storageKey);
    if (views.includes(saved) && !document.getElementById('view-connections')?.defaultChecked) {
      const selected = document.getElementById('view-' + saved);
      if (selected) selected.checked = true;
    }
  } catch (_) {}
  document.addEventListener('change', event => {
    const input = event.target;
    if (input.matches('input[name="dashboard-view"]') && input.checked) {
      try { sessionStorage.setItem(storageKey, input.id.slice(5)); } catch (_) {}
    }
  });
  const filterKey = storageKey + ':status';
  let summaryFilter = '';
  try { const saved=sessionStorage.getItem(filterKey); if(['verified','review','unverified'].includes(saved))summaryFilter=saved; } catch (_) {}
  function applySummaryFilter(expand=false) {
    if(!main)return;
    if(summaryFilter)main.dataset.summaryFilter=summaryFilter;else delete main.dataset.summaryFilter;
    const matches=[];
    for(const card of main.querySelectorAll('[data-check-status]')) {
      const show=!summaryFilter||card.dataset.checkStatus===summaryFilter;
      card.classList.toggle('summary-filtered-out',!show);
      if(show&&summaryFilter){matches.push(card);if(expand){const tile=card.querySelector('details.system-tile');if(tile)tile.open=true;
        if(summaryFilter!=='verified')for(const detail of card.querySelectorAll('details'))detail.open=true;}}
    }
    for(const group of main.querySelectorAll('.system-group'))group.classList.toggle('summary-filtered-out',!!summaryFilter&&!group.querySelector('[data-check-status]:not(.summary-filtered-out)'));
    for(const button of main.querySelectorAll('button[data-summary-filter]'))button.setAttribute('aria-pressed',String(button.dataset.summaryFilter===summaryFilter));
    const note=document.getElementById('summary-filter-status'),clear=document.getElementById('summary-filter-clear');
    if(note){note.hidden=!summaryFilter;note.textContent=summaryFilter?(matches.length+' '+({verified:'verified',review:'to review',unverified:'unverified'}[summaryFilter])+' systems'):'';}
    if(clear)clear.hidden=!summaryFilter;
    return matches;
  }
  function selectSummaryFilter(value) {
    summaryFilter=value;
    try{if(value)sessionStorage.setItem(filterKey,value);else sessionStorage.removeItem(filterKey);}catch(_){}
    if(value){const all=document.getElementById('view-all');if(all)all.checked=true;try{sessionStorage.setItem(storageKey,'all');}catch(_){}}
    const matches=applySummaryFilter(!!value)||[];
    if(value)(matches[0]||document.getElementById('summary-filter-status'))?.scrollIntoView({behavior:'auto',block:'start'});
  }
  document.addEventListener('click',event=>{
    const sample=event.target.closest('[data-sample-detail]');
    if(sample){const detail=sample.closest('.trial-chart, .trend-card')?.querySelector('[data-trial-detail]');if(detail)detail.textContent=sample.dataset.sampleDetail;return;}
    const ask=event.target.closest('a[data-ask-shortcut]');
    if(ask){event.preventDefault();selectSummaryFilter('');document.getElementById('ask-adr')?.scrollIntoView({behavior:'auto',block:'start'});return;}
    const button=event.target.closest('button[data-summary-filter]');
    if(button){event.preventDefault();selectSummaryFilter(button.dataset.summaryFilter);return;}
    if(event.target.closest('#summary-filter-clear')){event.preventDefault();selectSummaryFilter('');}
  });
  document.addEventListener('change',event=>{if(event.target.matches('input[name="dashboard-view"]'))selectSummaryFilter('');});
  document.addEventListener('keydown',event=>{
    if(!event.target.matches('svg[data-trial-chart]')||!['ArrowLeft','ArrowRight'].includes(event.key))return;
    const points=[...event.target.querySelectorAll('[data-sample-detail]')];if(!points.length)return;
    event.preventDefault();
    const old=Number(event.target.dataset.sampleIndex??points.length-1);
    const index=Math.max(0,Math.min(points.length-1,old+(event.key==='ArrowRight'?1:-1)));
    event.target.dataset.sampleIndex=String(index);
    const detail=event.target.closest('.trial-chart')?.querySelector('[data-trial-detail]');
    if(detail)detail.textContent=points[index].dataset.sampleDetail;
  });
  if(document.getElementById('view-connections')?.checked)summaryFilter='';
  if(summaryFilter){const all=document.getElementById('view-all');if(all)all.checked=true;}
  applySummaryFilter();

  const pin = () => {
    const nav = document.querySelector('main + .group-tabs');
    if (!nav || !matchMedia('(max-width:700px)').matches) {
      if (nav) nav.style.bottom = '';
      return;
    }
    let bottom = window.visualViewport ? visualViewport.offsetTop + visualViewport.height : innerHeight;
    try {
      if (window.frameElement && window.parent !== window) {
        const frame = window.frameElement.getBoundingClientRect();
        const outer = window.parent.visualViewport;
        bottom = Math.min(bottom, (outer ? outer.offsetTop + outer.height : window.parent.innerHeight) - frame.top);
      }
    } catch (_) {}
    nav.style.bottom = Math.max(0, innerHeight - bottom) + 'px';
  };
  addEventListener('resize', pin, {passive:true});
  addEventListener('scroll', pin, {passive:true});
  if (window.visualViewport) {
    visualViewport.addEventListener('resize', pin, {passive:true});
    visualViewport.addEventListener('scroll', pin, {passive:true});
  }
  try {
    if (window.parent !== window) {
      window.parent.addEventListener('scroll', pin, {passive:true,capture:true});
      window.parent.addEventListener('resize', pin, {passive:true});
    }
  } catch (_) {}
  pin();

  // Same-origin GETs only. No form is submitted or device action initiated here.
  const touched = new WeakSet();
  document.addEventListener('input', e => { if (e.target.closest('form')) touched.add(e.target.closest('form')); });
  document.addEventListener('toggle', e => { if (!applying && e.target.tagName === 'DETAILS') touched.add(e.target); }, true);
  let applying = false;
  function key(node) {
    if (node.nodeType !== 1) return '';
    if (node.id) return '#' + node.id;
    if (node.matches('article.system-card')) return 'system:' + node.querySelector('h3')?.textContent;
    if (node.tagName === 'FORM') return 'form:' + node.getAttribute('action');
    if (node.tagName === 'DETAILS') return 'details:' + (node.className || node.querySelector('summary')?.textContent);
    return node.tagName + ':' + (node.getAttribute('class') || '');
  }
  function patch(old, next) {
    if (old.nodeType !== next.nodeType || old.nodeName !== next.nodeName) {
      old.replaceWith(next.cloneNode(true)); return;
    }
    if (old.nodeType !== 1) {
      if (old.nodeValue !== next.nodeValue) old.nodeValue = next.nodeValue;
      return;
    }
    if (old.id === 'diagnostics' || old.id === 'ask-adr') return;
    if(old.hasAttribute('data-trial-detail')&&old.dataset.trialSession===next.dataset.trialSession)return;
    if (old.isEqualNode(next)) return;
    if (old.tagName === 'FORM' && (touched.has(old) || old.contains(document.activeElement))) return;
    const protectedAttr = name => (name === 'open' && old.tagName === 'DETAILS') || (name === 'checked' && old.matches('input[name="dashboard-view"]'));
    for (const a of [...old.attributes]) if (!protectedAttr(a.name) && !next.hasAttribute(a.name)) old.removeAttribute(a.name);
    for (const a of next.attributes) if (!protectedAttr(a.name) && old.getAttribute(a.name) !== a.value) old.setAttribute(a.name, a.value);
    const remaining = [...old.childNodes];
    let cursor = old.firstChild;
    for (const fresh of next.childNodes) {
      let match = remaining.find(n => key(n) && key(n) === key(fresh));
      if (!match && cursor && !key(cursor) && !key(fresh) && cursor.nodeType === fresh.nodeType) match = cursor;
      if (match) {
        remaining.splice(remaining.indexOf(match), 1);
        if (match !== cursor) old.insertBefore(match, cursor);
        patch(match, fresh);
        cursor = match.isConnected ? match.nextSibling : old.childNodes[[...next.childNodes].indexOf(fresh)+1] || null;
      } else {
        old.insertBefore(fresh.cloneNode(true), cursor);
      }
    }
    for (const stale of remaining) stale.remove();
  }
  const refreshMeta = () => document.querySelector('meta[name="adr-refresh"]');
  let seconds = Number(refreshMeta()?.content || 0);
  let stopped = false;
  const schedule = delay => { if (!stopped && seconds) setTimeout(update, delay || seconds * 1000); };
  async function update() {
    if (document.hidden || document.querySelector('form:not(#adr-question-form):focus-within') || [...document.forms].some(f => f.id !== 'adr-question-form' && touched.has(f))) { schedule(3000); return; }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('./', {method:'GET',credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal});
      if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) throw new Error('Refresh unavailable');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const incoming = doc.querySelector('main');
      if (!incoming || !incoming.querySelector('.toolbar') || doc.querySelector('script[type="module"]')?.textContent !== document.querySelector('script[type="module"]')?.textContent) throw new Error('Page changed; reopen to update');
      if (document.querySelector('form:not(#adr-question-form):focus-within') || [...document.forms].some(f => f.id !== 'adr-question-form' && touched.has(f))) { schedule(3000); return; }
      // Keep the viewed element at the same screen position when content above changes.
      const anchor = [...main.querySelectorAll('summary,h2,h3,.metric,.primary-metric')].find(e => e.getBoundingClientRect().top >= 0 && e.getBoundingClientRect().height);
      const top = anchor?.getBoundingClientRect().top;
      const x = scrollX, y = scrollY;
      applying = true;
      patch(main, incoming);
      main.querySelectorAll('[data-trend-card]').forEach(card=>{
        const choice=historySelections.get(card.dataset.trendCard);
        if(choice)applyHistorySelection(card,choice.range,choice.series);
      });
      applySummaryFilter();
      if (!document.querySelector('main + .group-tabs') && doc.querySelector('main + .group-tabs')) {
        main.after(doc.querySelector('main + .group-tabs').cloneNode(true));
      }
      applying = false;
      const delta = anchor?.isConnected ? anchor.getBoundingClientRect().top - top : 0;
      window.scrollTo({left:x,top:y + (Number.isFinite(delta) ? delta : 0),behavior:'instant'});
      seconds = Number(doc.querySelector('meta[name="adr-refresh"]')?.content || 0);
      const meta = refreshMeta();
      if (meta) meta.content = String(seconds);
      pin();
    } catch (_) {
      // Retain the last page and retry later without a navigation or command retry.
    } finally { applying = false; clearTimeout(timeout); }
    schedule();
  }
  addEventListener('pagehide', () => { stopped = true; });
  // Diagnostic status polling updates only result nodes, preserving the question,
  // consent, selected category and open tiles. GETs never trigger checks.
  let diagnosticSubmitting=false;
  const diag = id => document.getElementById(id);
  const deviceCache = new Map();
  const unknownDeviceValue = value => ['', 'unknown', 'unverified', 'unavailable'].includes(String(value ?? '').trim().toLowerCase());
  const macText = value => String(value ?? '').replace(/[^0-9a-f]/gi, '').toLowerCase();
  function deviceSelection(rows, query, sort) {
    query = String(query || '').trim().toLowerCase();
    const compact = macText(query), macQuery = /^[0-9a-f: .-]+$/i.test(query) && compact.length >= 4;
    const selected = rows.filter(row => !query || row.slice(0,5).some(value => String(value ?? '').toLowerCase().includes(query)) || (macQuery && !unknownDeviceValue(row[3]) && macText(row[3]).includes(compact)));
    const ip = value => { const parts=String(value).split('.'); return parts.length===4 && parts.every(p=>/^\d{1,3}$/.test(p)&&Number(p)<=255) ? parts.reduce((n,p)=>n*256+Number(p),0) : Infinity; };
    const column = {manufacturer:0,hostname:2,mac:3}[sort];
    return selected.slice().sort((a,b) => {
      if (sort === 'ip' || column === undefined) return ip(a[1])-ip(b[1]);
      const missing = Number(unknownDeviceValue(a[column]))-Number(unknownDeviceValue(b[column]));
      if (missing) return missing;
      const left=sort==='mac'?macText(a[column]):String(a[column]??'');
      const right=sort==='mac'?macText(b[column]):String(b[column]??'');
      return left.localeCompare(right,'en',{sensitivity:'base',numeric:true}) || ip(a[1])-ip(b[1]);
    });
  }
  function redrawDeviceLists() {
    for (const [id,rows] of deviceCache) diagnosticRows(id,rows);
  }
  window.ADRDeviceList = {
    select:deviceSelection,
    set(query,sort) {
      const search=diag('diag-device-search'), order=diag('diag-device-sort');
      if(search)search.value=query;if(order)order.value=sort;
      redrawDeviceLists();
    }
  };
  for (const name of ['input','change']) document.addEventListener(name,event=>{
    if (['diag-device-search','diag-device-sort'].includes(event.target.id)) redrawDeviceLists();
  });
  function diagnosticRows(id,rows){
    const body=diag(id);if(!body)return;
    if (id==='diag-devices' || id==='diag-observed') {
      deviceCache.set(id,rows);
      const total=rows.length;
      rows=deviceSelection(rows,diag('diag-device-search')?.value,diag('diag-device-sort')?.value || 'ip');
      if(id==='diag-devices') {
        const count=diag('diag-device-count'),empty=diag('diag-device-empty');
        if(count)count.textContent=rows.length+' of '+total+' devices';
        if(empty)empty.hidden=rows.length>0;
      }
    }
    const serialized=JSON.stringify(rows);if(body.dataset.rows===serialized)return;
    const fragment=document.createDocumentFragment();
    const labels=id==='diag-devices'?['Manufacturer','IP address','Hostname','MAC address','Device type','Identity source','Web interface']:[];
    for(const row of rows){const tr=document.createElement('tr');for(const [column,value] of row.entries()){const td=document.createElement('td');if(labels[column])td.dataset.label=labels[column];
      if(value&&typeof value==='object'&&Array.isArray(value.web)){
        const ip=String(value.ip||''),parts=ip.split('.');
        const safe=parts.length===4&&parts.every(p=>/^(0|[1-9][0-9]{0,2})$/.test(p)&&Number(p)<=255)&&(parts[0]==='10'||(parts[0]==='172'&&Number(parts[1])>=16&&Number(parts[1])<=31)||(parts[0]==='192'&&parts[1]==='168'));
        let links=0;
        if(safe)for(const port of [443,80])if(value.web.some(s=>s.port===port&&s.status==='reachable')){
          const link=document.createElement('a');link.href=(port===443?'https://':'http://')+ip+'/';link.target='_blank';link.rel='noopener noreferrer';link.textContent=port===443?'Open HTTPS':'Open HTTP';td.append(link);links++;
        }
        if(!links)td.textContent='Not detected';
      }else td.textContent=String(value??'Unverified');tr.append(td);}fragment.append(tr);}
    body.replaceChildren(fragment);body.dataset.rows=serialized;
  }
  const siteTimezone=document.querySelector('meta[name="adr-site-timezone"]')?.content||'America/New_York';
  const localDate=value=>{const d=new Date(value);if(!value||Number.isNaN(d.valueOf()))return 'Unverified';try{return new Intl.DateTimeFormat('en-US',{timeZone:siteTimezone,year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(d);}catch{return 'Configure site timezone';}};
  function renderNative(native){
    const status=diag('adr-native-status'),panel=diag('adr-native-history'),sources=diag('adr-native-sources'),list=diag('adr-native-list'),select=diag('adr-native-source');
    if(!status||!panel||!sources||!list||!select)return;
    status.hidden=panel.hidden=!native?.enabled;if(!native?.enabled)return;
    status.textContent=native.error||((native.listener_running?'Native log listener running':'Native log listener stopped')+' · Delivery is verified only when messages arrive.');
    const coverage=native.sources||[],signature=JSON.stringify(coverage);
    if(sources.dataset.coverage!==signature){
      const fragment=document.createDocumentFragment();
      for(const source of coverage){const p=document.createElement('p');p.textContent=source.name+' · '+(source.last_received_at?'Last received '+localDate(source.last_received_at):'Forwarding unverified');fragment.append(p);}
      sources.replaceChildren(fragment);sources.dataset.coverage=signature;
    }
    const options=JSON.stringify(coverage.map(s=>[s.id,s.name]));
    if(select.dataset.options!==options){
      const selected=select.value,fragment=document.createDocumentFragment();
      for(const source of coverage){const option=document.createElement('option');option.value=source.id;option.textContent=source.name;fragment.append(option);}
      select.replaceChildren(fragment);if(coverage.some(s=>s.id===selected))select.value=selected;select.dataset.options=options;
    }
    const events=native.events||[],serialized=JSON.stringify(events);
    if(list.dataset.events!==serialized){
      const fragment=document.createDocumentFragment();
      for(const event of [...events].reverse().slice(0,20)){
        const p=document.createElement('p');p.textContent=event.source+' · '+(event.device_time?'Device time '+localDate(event.device_time):'Received '+localDate(event.received_at)+'; device time unverified')+' · '+(event.event_name?event.event_name+': ':'')+event.message;fragment.append(p);
      }
      if(!events.length){const p=document.createElement('p');p.textContent='No native events received or imported yet.';fragment.append(p);}
      list.replaceChildren(fragment);list.dataset.events=serialized;
    }
  }
  document.addEventListener('click',async e=>{
    if(!e.target.closest('#adr-native-import'))return;
    const button=diag('adr-native-import');if(button.disabled)return;button.disabled=true;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);
    try{
      const file=diag('adr-native-file').files[0],source=diag('adr-native-source').value;
      if(!file||file.size>128*1024||!source)throw new Error('Choose a source and plain-text log smaller than 128 KB.');
      const response=await fetch('native-import',{method:'POST',credentials:'same-origin',redirect:'error',signal:controller.signal,
        headers:{'Content-Type':'text/plain;charset=utf-8','X-ADR-CSRF':diag('diag-csrf').value,'X-ADR-Event-Source':source},body:file});
      const result=await response.json();if(!response.ok)throw new Error(result.error||'Import could not finish.');
      diag('adr-native-import-status').textContent=result.imported+' log lines imported. Device times remain separate from receipt times.';
      diag('adr-native-file').value='';await diagnosticStatus();
    }catch(error){diag('adr-native-import-status').textContent=error.name==='AbortError'?'Import timed out. Check recent events before trying again.':error.message;}
    finally{clearTimeout(timeout);button.disabled=false;}
  });

  let diagnosticPolling=false;
  async function diagnosticStatus(){
    if(!diag('diagnostics')||diagnosticPolling||document.hidden)return;
    diagnosticPolling=true;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
    try{
      const response=await fetch('diagnostic-state',{credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal});
      if(!response.ok)throw new Error();
      const state=await response.json(),result=state.result||{};
      window.ADRVoice?.update(state);
      renderNative(state.native_events);
      diag('diag-progress').textContent=state.progress;
      diag('adr-analysis-progress').textContent=!state.cloud_enabled?'Enable Ask ADR in Configuration.':state.progress;
      diag('diag-summary').textContent=state.summary;
      diag('adr-answer').textContent=state.answer;
      diagnosticRows('diag-targets',(result.targets||[]).map(t=>[t.ip,t.ping.status==='responded'?'Reply':t.ping.status==='no_reply'?'No reply':'Unverified',t.ping.average_ms==null?'Unverified':t.ping.average_ms+' ms']));
      const discovery=state.discovery||(result.kind==='discovery'?result:{});
      diag('diag-discovery').textContent=discovery.kind==='discovery'?discovery.responding.length+' replies / '+discovery.tested+' tested · '+localDate(discovery.checked_at)+'':'';
      diagnosticRows('diag-devices',(discovery.devices||[]).map(d=>[d.manufacturer||'Unknown',d.ip,d.hostname||'Unknown',d.mac||'Unknown',d.device_type||'Unknown',d.identity_source||'Unknown',{ip:d.ip,web:d.services||[]} ]));
      diagnosticRows('diag-observed',(state.observed||[]).map(d=>[d.manufacturer||'Unknown',d.ip,d.hostname||'Unknown',d.mac||'Unknown',localDate(d.identity_checked_at),localDate(d.last_seen)]));
      document.querySelectorAll('button[data-diagnostic]').forEach(b=>{b.disabled=state.blocked||state.busy||diagnosticSubmitting||Boolean(window.ADRVoice?.busy())||(b.dataset.diagnostic==='ask'?!state.cloud_enabled:!state.enabled);});
    }catch(_){if(diag('diag-progress'))diag('diag-progress').textContent='Connection unavailable; previous readings retained.';}
    finally{clearTimeout(timeout);diagnosticPolling=false;}
  }
  document.addEventListener('submit',e=>{if(e.target.id==='adr-question-form')e.preventDefault();});
  document.addEventListener('click',async e=>{
    const button=e.target.closest('button[data-diagnostic]');if(!button||diagnosticSubmitting||window.ADRVoice?.busy())return;
    diagnosticSubmitting=true;
    document.querySelectorAll('button[data-diagnostic]').forEach(b=>b.disabled=true);
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try{
      const body=new URLSearchParams({csrf:diag('diag-csrf').value});
      if(button.dataset.diagnostic==='discover')body.set('subnet',diag('diag-subnet').value);
      if(button.dataset.diagnostic==='ask'){
        body.set('question',diag('adr-question').value);
        body.set('confirm','yes');
      }
      const response=await fetch('diagnostic-'+button.dataset.diagnostic,{method:'POST',body,credentials:'same-origin',redirect:'error',signal:controller.signal});
      if(response.status!==202){
        const doc=new DOMParser().parseFromString(await response.text(),'text/html');
        throw new Error(doc.querySelector('.notice p')?.textContent||'Request could not start.');
      }
      if(button.dataset.diagnostic==='ask')window.ADRVoice?.expectAnswer();
      diagnosticSubmitting=false;await diagnosticStatus();
    }catch(error){
      diagnosticSubmitting=false;await diagnosticStatus();
      const message=error.name==='AbortError'?'Request timed out. Check status before trying again.':error.message;
      diag('diag-progress').textContent=message;diag('adr-analysis-progress').textContent=message;
    }finally{clearTimeout(timeout);}
  });
  diagnosticStatus();
  setInterval(()=>{if(!stopped&&!diagnosticSubmitting)diagnosticStatus();},2500);

  schedule();
})();





// Chart inspection is entirely local. Never fetch data or submit device actions.
(() => {
  const chartSelector = 'svg.trend-chart, svg.history-chart, .gauge svg, table';
  let viewer = null;
  function openChart(source) {
    if (viewer) return;
    const isTable = source.tagName.toLowerCase() === 'table';
    const deviceTable = isTable && source.querySelector('#diag-devices,#diag-observed');
    const card = source.closest('.trial-chart, .trend-card, .sense-series, .gauge, section, article, details');
    const dialog = document.createElement('dialog');
    dialog.className = 'chart-viewer';
    dialog.setAttribute('aria-labelledby', 'chart-viewer-title');
    dialog.innerHTML = '<header><h2 id="chart-viewer-title"></h2><button type="button" data-chart-close aria-label="Close enlarged graph">Close</button></header><div class="chart-viewer-tools"><button type="button" data-chart-out aria-label="Zoom out">−</button><output aria-live="polite">100%</output><button type="button" data-chart-in aria-label="Zoom in">+</button><button type="button" data-chart-reset>Reset zoom</button></div><p class="chart-viewer-help">Pinch or use + / − to zoom. Drag to pan. Tap for a recorded reading; use arrow keys to step through samples.</p><div class="chart-viewer-legend"></div><div class="chart-viewer-viewport" tabindex="0" aria-label="Enlarged graph"><div class="chart-viewer-canvas"></div></div><p class="chart-viewer-detail" role="status">Showing the recorded graph at the time it was opened.</p>';
    dialog.querySelector('h2').textContent = isTable ? (deviceTable ? 'Devices' : source.caption?.textContent || card?.querySelector('h2,h3,h4,summary')?.textContent || 'Table') : (card?.querySelector('h4')?.textContent || source.getAttribute('aria-label') || 'History');
    dialog.querySelector('[data-chart-close]').setAttribute('aria-label','Close enlarged view');
    dialog.querySelector('.chart-viewer-help').textContent='Pinch to zoom · Drag to pan';
    const legend = source.parentElement.querySelector('.trend-legend') || card?.querySelector('.trend-legend');
    if (legend) dialog.querySelector('.chart-viewer-legend').append(legend.cloneNode(true));
    const svg = source.cloneNode(true);
    svg.removeAttribute('tabindex');
    svg.removeAttribute('data-trial-chart');
    svg.removeAttribute('aria-haspopup');
    svg.removeAttribute('id');
    svg.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
    svg.querySelectorAll('button,input,select,textarea').forEach(node=>node.disabled=true);
    if(!isTable)svg.setAttribute('role', 'img');
    else svg.classList.add('viewer-table');
    const viewport = dialog.querySelector('.chart-viewer-viewport');
    const canvas = dialog.querySelector('.chart-viewer-canvas');
    const detail = dialog.querySelector('.chart-viewer-detail');
    canvas.append(svg);
    dialog.addEventListener('submit',event=>event.preventDefault());
    if(isTable && source.querySelector('#diag-devices,#diag-observed') && window.ADRDeviceList) {
      const original=document.querySelector('.device-list-controls');
      if(original){
        const controls=original.cloneNode(true);
        controls.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
        const search=controls.querySelector('input[type="search"]'),order=controls.querySelector('select');
        search.value=original.querySelector('input[type="search"]').value;
        order.value=original.querySelector('select').value;
        function filter(){
          window.ADRDeviceList.set(search.value,order.value);
          const copy=source.cloneNode(true);
          copy.querySelectorAll('[id]').forEach(node=>node.removeAttribute('id'));
          svg.replaceChildren(...copy.childNodes);
        }
        search.addEventListener('input',filter);order.addEventListener('change',filter);
        dialog.querySelector('.chart-viewer-legend').before(controls);
      }
    }
    document.body.append(dialog);
    viewer = dialog;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.addEventListener('close', () => {
      document.body.style.overflow = oldOverflow;
      viewer = null;
      dialog.remove();
      if (source.isConnected) source.focus({preventScroll:true});
    });
    dialog.showModal();
    const box = isTable ? {width:700,height:280} : svg.viewBox.baseVal;
    if(isTable)detail.hidden=true;
    let scale = 1, baseWidth = Math.max(viewport.clientWidth, 320), selected = -1;
    let moved = false, pointers = new Map(), gesture = null;
    function zoom(next, cx = viewport.clientWidth / 2, cy = viewport.clientHeight / 2) {
      next = Math.max(1, Math.min(8, next));
      const ratio = next / scale;
      const left = (viewport.scrollLeft + cx) * ratio - cx;
      const top = (viewport.scrollTop + cy) * ratio - cy;
      scale = next;
      svg.style.width = (isTable?Math.max(baseWidth,700):baseWidth) * scale + 'px';
      svg.style.height = isTable ? 'auto' : baseWidth * scale * box.height / box.width + 'px';
      if(isTable)svg.style.fontSize=13*scale+'px';
      viewport.scrollLeft = left; viewport.scrollTop = top;
      dialog.querySelector('output').textContent = Math.round(scale * 100) + '%';
      dialog.querySelector('[data-chart-out]').disabled = scale === 1;
      dialog.querySelector('[data-chart-in]').disabled = scale === 8;
    }
    zoom(1);
    const resize = () => { baseWidth = Math.max(viewport.clientWidth, 320); zoom(scale); };
    addEventListener('resize', resize, {passive:true});
    dialog.addEventListener('close', () => removeEventListener('resize', resize));
    const samples = [...svg.querySelectorAll('[data-sample-detail]')].filter(p => !p.closest('[style*="display: none"], [hidden]')).sort((a,b) => Number(a.getAttribute('x'))-Number(b.getAttribute('x')));
    function select(index) {
      if (!samples.length) return;
      selected = Math.max(0, Math.min(samples.length - 1, index));
      const sample = samples[selected];
      detail.textContent = sample.dataset.sampleDetail;
      svg.querySelector('.chart-selection')?.remove();
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const x = Number(sample.getAttribute('x')) + Number(sample.getAttribute('width')) / 2;
      line.setAttribute('d', `M${x} 18V${box.height - 30}`);
      line.setAttribute('class', 'chart-selection');
      svg.append(line);
    }
    dialog.querySelector('[data-chart-close]').onclick = () => dialog.close();
    dialog.querySelector('[data-chart-in]').onclick = () => zoom(scale * 1.5);
    dialog.querySelector('[data-chart-out]').onclick = () => zoom(scale / 1.5);
    dialog.querySelector('[data-chart-reset]').onclick = () => { zoom(1); viewport.scrollLeft = viewport.scrollTop = 0; };
    viewport.addEventListener('click', event => {
      if (moved || isTable) return;
      const hit = event.target.closest('[data-sample-detail]');
      if (hit && samples.includes(hit)) { select(samples.indexOf(hit)); return; }
      const rect = svg.getBoundingClientRect();
      const x = box.x + (event.clientX - rect.left) / rect.width * box.width;
      let nearest = -1, distance = Infinity;
      samples.forEach((p, i) => {
        const dx = Math.abs(Number(p.getAttribute('x')) + Number(p.getAttribute('width')) / 2 - x);
        if (dx < distance) { distance = dx; nearest = i; }
      });
      if (nearest >= 0) select(nearest);
    });
    viewport.addEventListener('keydown', event => {
      if (!isTable && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
        event.preventDefault(); select(selected < 0 ? 0 : selected + (event.key === 'ArrowRight' ? 1 : -1));
        samples[selected]?.scrollIntoView({block:'nearest', inline:'nearest'});
      }
      if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(scale * 1.5); }
      if (event.key === '-') { event.preventDefault(); zoom(scale / 1.5); }
    });
    function beginGesture() {
      const points = [...pointers.values()];
      gesture = {points, left:viewport.scrollLeft, top:viewport.scrollTop, scale,
        distance:points.length === 2 ? Math.hypot(points[1].x-points[0].x, points[1].y-points[0].y) : 0};
    }
    viewport.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      if (!pointers.size) moved = false;
      pointers.set(event.pointerId, {x:event.clientX, y:event.clientY});
      if (pointers.size > 1) moved = true;
      // Keep sample hit targets for taps; capture only after movement.
      beginGesture();
    });
    viewport.addEventListener('pointermove', event => {
      if (!pointers.has(event.pointerId)) return;
      pointers.set(event.pointerId, {x:event.clientX, y:event.clientY});
      const points = [...pointers.values()];
      if (points.length === 2 && gesture.distance > 0) {
        moved = true; viewport.setPointerCapture(event.pointerId);
        const rect = viewport.getBoundingClientRect();
        zoom(gesture.scale * Math.hypot(points[1].x-points[0].x, points[1].y-points[0].y) / gesture.distance,
          (points[0].x+points[1].x)/2-rect.left, (points[0].y+points[1].y)/2-rect.top);
      } else if (points.length === 1 && gesture.points.length === 1) {
        const dx = points[0].x - gesture.points[0].x, dy = points[0].y - gesture.points[0].y;
        if (Math.hypot(dx,dy) > 5) moved = true;
        if (moved) { viewport.setPointerCapture(event.pointerId); viewport.scrollLeft = gesture.left-dx; viewport.scrollTop = gesture.top-dy; }
      }
    });
    for (const name of ['pointerup','pointercancel','lostpointercapture']) viewport.addEventListener(name, event => {
      pointers.delete(event.pointerId); beginGesture();
    });
    viewport.addEventListener('wheel', event => {
      if (!event.ctrlKey) return;
      event.preventDefault(); const rect = viewport.getBoundingClientRect();
      zoom(scale * Math.exp(-event.deltaY * .01), event.clientX-rect.left, event.clientY-rect.top);
    }, {passive:false});
    dialog.querySelector('[data-chart-close]').focus();
  }
  document.addEventListener('click', event => {
    const source = event.target.closest(chartSelector);
    if (!source || source.closest('.chart-viewer') || event.target.closest('a,button,input,select,textarea,label')) return;
    event.preventDefault(); event.stopImmediatePropagation(); openChart(source);
  }, true);
  document.addEventListener('keydown', event => {
    if (!event.target.matches(chartSelector) || !['Enter',' '].includes(event.key)) return;
    event.preventDefault(); openChart(event.target);
  });
})();
