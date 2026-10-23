(() => {
  const storageKey = 'adr-view:' + location.pathname;
  const main = document.querySelector('main');
  const views = ['all', 'power', 'network', 'av'];
  try {
    const saved = sessionStorage.getItem(storageKey);
    if (views.includes(saved)) {
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
    if (document.hidden || document.querySelector('form:focus-within') || [...document.forms].some(f => touched.has(f))) { schedule(3000); return; }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('./', {method:'GET',credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal});
      if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) throw new Error('Refresh unavailable');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const incoming = doc.querySelector('main');
      if (!incoming || !incoming.querySelector('.toolbar') || doc.querySelector('script[type="module"]')?.textContent !== document.querySelector('script[type="module"]')?.textContent) throw new Error('Page changed; reopen to update');
      if (document.querySelector('form:focus-within') || [...document.forms].some(f => touched.has(f))) { schedule(3000); return; }
      // Keep the viewed element at the same screen position when content above changes.
      const anchor = [...main.querySelectorAll('summary,h2,h3,.metric,.primary-metric')].find(e => e.getBoundingClientRect().top >= 0 && e.getBoundingClientRect().height);
      const top = anchor?.getBoundingClientRect().top;
      const x = scrollX, y = scrollY;
      applying = true;
      patch(main, incoming);
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
  schedule();
})();
