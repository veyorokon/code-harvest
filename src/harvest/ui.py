#!/usr/bin/env python3
# Web UI template for harvest viewer
SERVE_HTML = """<!doctype html><meta charset=utf-8><title>Harvest</title>
<style>
  body{font-family:system-ui,sans-serif;margin:0}
  header{padding:12px 16px;box-shadow:0 1px 0 #ddd;position:sticky;top:0;background:#fff}
  main{padding:16px;display:grid;gap:12px;grid-template-columns: 1fr minmax(320px, 40%)}
  input,select{padding:6px 8px;margin-right:8px}
  table{border-collapse:collapse;width:100%}
  td,th{border-bottom:1px solid #eee;padding:6px 8px;text-align:left}
  tr:hover{background:#fafafa}
  pre{background:#0b1020;color:#e6e6e6;padding:12px;border-radius:8px;overflow:auto;white-space:pre}
  #pane{position:sticky;top:60px;height:calc(100vh - 88px)}
  .highlight-toggle{margin-left:8px;font-size:12px}
  /* Syntax highlighting colors */
  .hl-keyword{color:#569cd6}
  .hl-string{color:#ce9178}
  .hl-comment{color:#6a9955}
  .hl-number{color:#b5cea8}
  .hl-function{color:#dcdcaa}
  .hl-class{color:#4ec9b0}
  .hl-operator{color:#d4d4d4}
  #meta small{color:#666}
  .muted{color:#666}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
  .truncate{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block;vertical-align:bottom}
  .button{padding:6px 10px;border:1px solid #ddd;border-radius:8px;background:#fff;cursor:pointer}
  .button:active{transform:translateY(1px)}
  .right{float:right}
  #palette{position:fixed;inset:0;background:rgba(0,0,0,.25);display:none;align-items:center;justify-content:center}
  #palette .box{background:#fff;border:1px solid #ddd;border-radius:10px;min-width:360px;max-width:640px;box-shadow:0 10px 30px rgba(0,0,0,.15)}
  #palette header{padding:8px 12px;border-bottom:1px solid #eee}
  #palette input{width:calc(100% - 24px);margin:8px 12px}
  #palette ul{list-style:none;margin:0;padding:0;max-height:40vh;overflow:auto}
  #palette li{padding:8px 12px;border-top:1px solid #f3f3f3;cursor:pointer}
  #palette li:hover{background:#f6f6f6}
</style>
<header><strong>Harvest</strong> · <span id=meta></span></header>
<main>
  <div>
    <div>
      <input id=q placeholder="symbol regex (chunks) or path regex (files)">
      <select id=entity><option>chunks</option><option>files</option></select>
      <select id=lang><option value="">language</option><option>python</option><option>javascript</option><option>javascriptreact</option><option>typescript</option><option>typescriptreact</option></select>
      <button id=copyLink class="button">Copy link</button>
      <button id=export class="button right">Export JSONL</button>
      <button id=saveView class="button">Save view</button>
      <select id=views class="button"><option value="">views…</option></select>
      <label class="muted" style="margin-left:8px;">
        <input type="checkbox" id="showTech"> Show technical columns
      </label>
      <span id=stats class="muted"></span>
    </div>
    <div>
      <table id=results><thead></thead><tbody></tbody></table>
    </div>
  </div>
  <aside id=pane>
    <div class="muted">Preview <button id="highlightToggle" class="button highlight-toggle">Highlight</button></div>
    <pre id=code>(click a chunk row)</pre>
  </aside>
</main>
<div id="palette">
  <div class="box">
    <header>Command palette (⌘/Ctrl+K)</header>
    <input id="palQ" placeholder="Type to filter…">
    <ul id="palList"></ul>
  </div>
</div>
<script>
const $ = sel => document.querySelector(sel);
const debounce = (fn, ms=200) => { let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a), ms); } };
const shorten = (s, head=8, tail=6) => !s ? "" : (s.length <= head+tail+1 ? s : s.slice(0,head)+"…"+s.slice(-tail));
const copy = async (text) => { try { await navigator.clipboard.writeText(text); } catch {} }

let __meta = null;
let highlightEnabled = false;

// Lightweight syntax highlighter
function highlightCode(code, language) {
  if (!highlightEnabled || !code) return escapeHtml(code);
  
  // Basic tokenizer for common languages
  const tokens = tokenize(code, language);
  return tokens.map(token => {
    if (token.type === 'text') return escapeHtml(token.value);
    return `<span class="hl-${token.type}">${escapeHtml(token.value)}</span>`;
  }).join('');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function tokenize(code, language) {
  const tokens = [];
  let pos = 0;
  
  // Language-specific patterns
  const patterns = getLanguagePatterns(language);
  
  while (pos < code.length) {
    let matched = false;
    
    for (const pattern of patterns) {
      const regex = new RegExp(pattern.regex, 'g');
      regex.lastIndex = pos;
      const match = regex.exec(code);
      
      if (match && match.index === pos) {
        tokens.push({ type: pattern.type, value: match[0] });
        pos = regex.lastIndex;
        matched = true;
        break;
      }
    }
    
    if (!matched) {
      tokens.push({ type: 'text', value: code[pos] });
      pos++;
    }
  }
  
  return tokens;
}

function getLanguagePatterns(language) {
  switch (language) {
    case 'python':
      return [
        { regex: '#.*$', type: 'comment' },
        { regex: '\\\\b(def|class|if|elif|else|for|while|try|except|finally|with|import|from|return|yield|lambda|and|or|not|in|is|True|False|None)\\\\b', type: 'keyword' },
        { regex: '"[^"]*"', type: 'string' },
        { regex: "'[^']*'", type: 'string' },
        { regex: '\\\\d+', type: 'number' }
      ];
    case 'javascript':
    case 'typescript':
      return [
        { regex: '//.*$', type: 'comment' },
        { regex: '\\\\b(function|const|let|var|if|else|for|while|try|catch|finally|return|class|extends|import|export|default|async|await|true|false|null|undefined)\\\\b', type: 'keyword' },
        { regex: '"[^"]*"', type: 'string' },
        { regex: "'[^']*'", type: 'string' },
        { regex: '`[^`]*`', type: 'string' },
        { regex: '\\\\d+', type: 'number' }
      ];
    default:
      return [
        { regex: '//.*$', type: 'comment' },
        { regex: '"[^"]*"', type: 'string' },
        { regex: "'[^']*'", type: 'string' },
        { regex: '\\\\d+', type: 'number' }
      ];
  }
}

// Helper functions for highlighting
function getCurrentLanguage() {
  // Try to get language from current selection or context
  const rows = document.querySelectorAll('#results tbody tr');
  for (const row of rows) {
    if (row.style.outline.includes('solid')) {
      const cells = row.querySelectorAll('td');
      for (const cell of cells) {
        if (cell.textContent && ['python', 'javascript', 'typescript', 'yaml', 'markdown'].includes(cell.textContent)) {
          return cell.textContent;
        }
      }
    }
  }
  return null;
}

function displayCode(content, language) {
  const codeEl = document.getElementById('code');
  if (highlightEnabled && content && content !== '(click a chunk row)') {
    codeEl.innerHTML = highlightCode(content, language);
  } else {
    codeEl.textContent = content;
  }
}

function toggleHighlight() {
  highlightEnabled = !highlightEnabled;
  const btn = document.getElementById('highlightToggle');
  btn.textContent = highlightEnabled ? 'Plain' : 'Highlight';
  btn.style.backgroundColor = highlightEnabled ? '#e6f3ff' : '';
  
  // Re-render current content
  const codeEl = document.getElementById('code');
  const currentContent = codeEl.textContent || codeEl.innerText;
  if (currentContent && currentContent !== '(click a chunk row)') {
    displayCode(currentContent, getCurrentLanguage());
  }
}

function getState(){
  const u = new URL(location.href);
  return {
    entity: $('#entity').value,
    q: $('#q').value,
    lang: $('#lang').value,
    showTech: $('#showTech').checked,
    dlPath: u.searchParams.get('dl_path'),
    dlStart: u.searchParams.get('dl_start'),
    dlEnd: u.searchParams.get('dl_end')
  };
}
function setState(s){
  $('#entity').value = s.entity || 'files';
  $('#q').value = s.q || '';
  $('#lang').value = s.lang || '';
  $('#showTech').checked = !!s.showTech;
}
function stateToParams(s){
  const p = new URLSearchParams();
  if (s.entity && s.entity!=='files') p.set('entity', s.entity);
  if (s.q) p.set(s.entity==='chunks' ? 'symbol_regex' : 'path_regex', s.q);
  if (s.lang) p.set('language', s.lang);
  if (s.showTech) p.set('tech','1');
  // preserve deep link parameters
  if (s.dlPath) p.set('dl_path', s.dlPath);
  if (s.dlStart) p.set('dl_start', s.dlStart);
  if (s.dlEnd) p.set('dl_end', s.dlEnd);
  return p;
}
function readStateFromURL(){
  const u = new URL(location.href);
  const e = u.searchParams.get('entity') || 'files';
  const s = {
    entity: e,
    q: u.searchParams.get(e==='chunks' ? 'symbol_regex' : 'path_regex') || '',
    lang: u.searchParams.get('language') || '',
    showTech: u.searchParams.get('tech') === '1',
    dlPath: u.searchParams.get('dl_path'),
    dlStart: u.searchParams.get('dl_start'),
    dlEnd: u.searchParams.get('dl_end')
  };
  setState(s);
  return s;
}
function writeURL(s){
  const p = stateToParams(s).toString();
  history.replaceState(null, '', p ? ('?'+p) : location.pathname);
}

async function meta(){
  const r=await fetch('api/meta'); const j=await r.json();
  __meta = j;
  document.getElementById('meta').textContent = j.source.type + ' · ' + j.created_at + ' · files=' + j.counts.total_files;
  
  // populate language dropdown with detected languages
  const langSelect = document.getElementById('lang');
  const languages = Object.keys(j.counts.files_by_language || {})
    .filter(lang => lang && lang !== 'null') // filter out null/empty languages
    .sort();
  
  // clear existing options except the first (empty) one
  while (langSelect.children.length > 1) langSelect.removeChild(langSelect.lastChild);
  
  // add detected languages
  languages.forEach(lang => {
    const opt = document.createElement('option');
    opt.value = lang;
    opt.textContent = lang;
    langSelect.appendChild(opt);
  });
  
  // add "unknown" option if there are files with null language
  const nullCount = j.counts.files_by_language['null'] || j.counts.files_by_language[null];
  if (nullCount) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = `unknown (${nullCount})`;
    langSelect.appendChild(opt);
  }
}
// Progressive rendering state
let allRows = [];
let currentCols = [];
let isLoading = false;
let hasMore = false;
let nextCursor = null;

async function search(append = false){
  if (isLoading) return;
  isLoading = true;
  
  const entity=document.getElementById('entity').value;
  const q=document.getElementById('q').value;
  const lang=document.getElementById('lang').value;
  const url=new URL('api/search', location.href);
  url.searchParams.set('entity', entity);
  if(q) url.searchParams.set(entity==='chunks' ? 'symbol_regex':'path_regex', q);
  if(lang) url.searchParams.set('language', lang);
  
  // Progressive loading: add limit and cursor for large datasets
  // Only use pagination for append operations or when we know there are many results
  if (append) {
    url.searchParams.set('limit', '1000');
    if (nextCursor !== null) {
      url.searchParams.set('cursor', nextCursor.toString());
    }
  } else if (allRows.length > 500) {
    // Only add limit for initial searches if we already know there are many results
    url.searchParams.set('limit', '1000');
  }
  
  // choose columns (hide id/hash by default)
  const showTech = document.getElementById('showTech').checked;
  const baseCols = (entity==='chunks')
    ? ["file_path","symbol","kind","start_line","end_line","language","public"]
    : ["path","name","language","size"];
  const techCols = (entity==='chunks') ? ["id","hash"] : ["hash"];
  const cols = showTech ? baseCols.concat(techCols) : baseCols;
  url.searchParams.set('fields', cols.join(','));
  
  try {
    const t0=performance.now();
    const r=await fetch(url); 
    const response=await r.json();
    
    // Handle both paginated and non-paginated responses
    let rows, total;
    if (Array.isArray(response)) {
      // Non-paginated response (backward compatibility)
      rows = response;
      total = rows.length;
      hasMore = false;
      nextCursor = null;
    } else {
      // Paginated response
      rows = response.items || [];
      total = response.total || 0;
      hasMore = response.has_more || false;
      nextCursor = response.next_cursor;
    }
    
    if (!append) {
      allRows = rows;
      currentCols = cols;
    } else {
      allRows = allRows.concat(rows);
    }
    
    const loadTime = Math.round(performance.now()-t0);
    $("#stats").textContent = `${allRows.length}${hasMore ? '+' : ''} of ${total} result(s) · ${loadTime}ms${hasMore ? ' · scroll for more' : ''}`;
    
    renderTable();
    
    // check for deep link preview after loading results
    const s = getState();
    if (s.dlPath && !append) {
      const start = parseInt(s.dlStart||"1"), end = parseInt(s.dlEnd||"0");
      try {
        const r2 = await fetch(`api/file?path=${encodeURIComponent(s.dlPath)}&start=${start}&end=${end > 0 ? end : ''}`);
        const j2 = await r2.json();
        // Convert escaped newlines to actual newlines
        const content = (j2.text || '(no content available for this file)').replace(/\\\\n/g, '\\n');
        displayCode(content, getCurrentLanguage());
      } catch(e) {
        document.getElementById('code').textContent = '(error loading file preview)';
      }
    }
  } finally {
    isLoading = false;
  }
}

function renderTable() {
  const thead=document.querySelector('#results thead'); 
  const tbody=document.querySelector('#results tbody');
  const cols = currentCols;
  
  thead.innerHTML=''; tbody.innerHTML='';
  if(allRows.length===0){ thead.innerHTML='<tr><th>No results</th></tr>'; return; }
  
  thead.innerHTML='<tr>'+cols.map(c=>'<th>'+c.replace("_"," ")+'</th>').join('')+'<th>actions</th></tr>';
  
  // Virtualized rendering for large datasets
  const visibleRows = allRows.slice(0, Math.min(allRows.length, 1000)); // limit DOM rows
  tbody.innerHTML=visibleRows.map(x=>{
    const entity = $('#entity').value;
    const attrs = (entity==='chunks')
      ? `data-file="${x.file_path}" data-start="${x.start_line}" data-end="${x.end_line}"`
      : `data-file="${x.path}"`;
    const actionCell = '<td class="mono"><button class="button" title="Copy deep link" data-act="copy-link">link</button> <button class="button" title="Copy path" data-act="copy-path">path</button>' + (__meta && __meta.source && __meta.source.type==="github" ? ' <button class="button" title="Open on GitHub" data-act="open-gh">gh</button>' : '') + '</td>';
    return '<tr '+attrs+'>'+cols.map(c=>{
      let v = x[c];
      if ((c==="id" || c==="hash") && v){
        const short = shorten(String(v));
        return `<td class="mono"><span class="truncate" title="${String(v)}">${short}</span> <button class="button mono" data-copy="${String(v)}" title="Copy ${c}">copy</button></td>`;
      }
      // Handle null/undefined values better
      if (v === null || v === undefined) {
        if (c === 'language') {
          return '<td class="muted">unknown</td>';
        }
        return '<td class="muted">—</td>';
      }
      return '<td>'+String(v)+'</td>';
    }).join('')+actionCell+'</tr>';
  }).join('');
  
  // Add scroll listener for infinite loading
  setupScrollListener();
  
  // row click → preview (chunks and files)
  tbody.onclick = async (e) => {
    // copy buttons
    const btn = e.target.closest('button[data-copy]');
    if (btn) { copy(btn.dataset.copy); return; }
    // action buttons
    const ab = e.target.closest('button[data-act]');
    if (ab){
      const tr = e.target.closest('tr'); if (!tr) return;
      const fp = tr.dataset.file || (tr.querySelector('td')?.textContent || "");
      if (ab.dataset.act === 'copy-path'){ copy(fp); return; }
      if (ab.dataset.act === 'copy-link'){
        const entity = $('#entity').value;
        const s = getState();
        // deep link: include file path and optional line span
        const u = new URL(location.href.split('#')[0]);
        const params = stateToParams(s);
        params.set('dl_path', fp);
        if (entity==='chunks'){ params.set('dl_start', tr.dataset.start||''); params.set('dl_end', tr.dataset.end||''); }
        u.search = params.toString();
        copy(u.toString()); return;
      }
      if (ab.dataset.act === 'open-gh' && __meta && __meta.source && __meta.source.type==="github"){
        const {owner,repo,branch} = __meta.source;
        const start = tr.dataset.start, end = tr.dataset.end;
        const lines = (start && end) ? `#L${start}-L${end}` : '';
        const url = `https://github.com/${owner}/${repo}/blob/${branch}/${fp}${lines}`;
        window.open(url, "_blank"); return;
      }
    }
    const tr = e.target.closest('tr'); if (!tr) return;
    const entity = document.getElementById('entity').value;
    
    // Get file path - for chunks use data-file, for files use first cell content (path)
    const fp = entity === 'chunks' ? tr.dataset.file : (tr.querySelector('td')?.textContent || "");
    if (!fp) return;
    
    // For chunks, use line range; for files, show entire file
    const start = entity === 'chunks' ? parseInt(tr.dataset.start||"1") : 1;
    const end = entity === 'chunks' ? parseInt(tr.dataset.end||"0") : 0;
    
    try {
      const r2 = await fetch(`api/file?path=${encodeURIComponent(fp)}&start=${start}&end=${end > 0 ? end : ''}`);
      const j2 = await r2.json();
      // Convert escaped newlines to actual newlines
      const content = (j2.text || '(no content available for this file)').replace(/\\\\n/g, '\\n');
      displayCode(content, getCurrentLanguage());
    } catch(e) {
      document.getElementById('code').textContent = '(error loading file: ' + fp + ')';
    }
  }
}

// Infinite scroll handler
function setupScrollListener() {
  const tbody = document.querySelector('#results tbody');
  if (!tbody) return;
  
  // Remove existing listener to avoid duplicates
  tbody.removeEventListener('scroll', handleScroll);
  
  // Add scroll listener to tbody
  tbody.addEventListener('scroll', handleScroll);
  
  // Also listen on the main container for window scroll
  window.removeEventListener('scroll', handleScroll);
  window.addEventListener('scroll', handleScroll);
}

const handleScroll = debounce(() => {
  if (!hasMore || isLoading) return;
  
  // Check if near bottom of page
  const scrollTop = window.scrollY;
  const scrollHeight = document.documentElement.scrollHeight;
  const clientHeight = window.innerHeight;
  
  if (scrollTop + clientHeight >= scrollHeight - 400) {
    search(true); // append=true for next page
  }
}, 150);

// saved views
const VKEY = 'harvest.views';
function loadViews(){ try{ return JSON.parse(localStorage.getItem(VKEY)||'[]'); }catch{return []} }
function storeViews(v){ localStorage.setItem(VKEY, JSON.stringify(v)); }
function refreshViews(){
  const list = loadViews();
  const sel = $('#views'); 
  sel.innerHTML = '<option value="">views…</option>' + list.map(v=>`<option value="${v.id}">${v.name}</option>`).join('');
  
  // Add delete button if there are saved views
  const deleteBtn = $('#deleteView');
  if (deleteBtn) deleteBtn.remove();
  
  if (list.length > 0) {
    const btn = document.createElement('button');
    btn.id = 'deleteView';
    btn.className = 'button';
    btn.textContent = 'Delete view';
    btn.style.marginLeft = '4px';
    btn.onclick = deleteCurrentView;
    sel.parentNode.insertBefore(btn, sel.nextSibling);
  }
}
function saveCurrentView(){
  const name = prompt('Save view as:'); if(!name) return;
  const list = loadViews();
  const id = Date.now().toString(36);
  list.push({id, name, params: Object.fromEntries(stateToParams(getState()))});
  storeViews(list); refreshViews();
}
function deleteCurrentView(){
  const sel = $('#views');
  const selectedId = sel.value;
  if (!selectedId) {
    alert('Please select a view to delete');
    return;
  }
  
  const list = loadViews();
  const view = list.find(v => v.id === selectedId);
  if (!view) return;
  
  if (confirm(`Delete view "${view.name}"?`)) {
    const newList = list.filter(v => v.id !== selectedId);
    storeViews(newList);
    sel.value = ''; // clear selection
    refreshViews();
  }
}
$('#saveView').onclick = saveCurrentView;
$('#views').onchange = (e)=>{
  const id = e.target.value; if(!id) return;
  const v = loadViews().find(x=>x.id===id); if(!v) return;
  const u = new URL(location.href); u.search = new URLSearchParams(v.params).toString();
  history.replaceState(null,'',u.search);
  readStateFromURL(); resetAndSearch();
};
refreshViews();

// Reset progressive state on new searches
function resetAndSearch() {
  allRows = [];
  hasMore = false;
  nextCursor = null;
  search();
}

// hydrate from URL, then render
meta().then(()=>{
  const s = readStateFromURL();
  writeURL(getState()); // normalize URL
  resetAndSearch();
});

document.getElementById('q').oninput = debounce(resetAndSearch, 250);
document.getElementById('showTech').onchange = resetAndSearch;
document.getElementById('entity').onchange = ()=>{ writeURL(getState()); resetAndSearch(); };
document.getElementById('lang').onchange = ()=>{ writeURL(getState()); resetAndSearch(); };
document.getElementById('copyLink').onclick = ()=> copy(location.href);
document.getElementById('highlightToggle').onclick = toggleHighlight;
document.getElementById('export').onclick = ()=>{
  const s = getState();
  const params = stateToParams(s);
  // choose default fields depending on entity
  const baseCols = (s.entity==='chunks') ? ["id","file_path","symbol","kind","start_line","end_line","language","public","hash"] : ["path","name","language","size","hash"];
  params.set('entity', s.entity);
  params.set('fields', baseCols.join(','));
  const url = 'api/export?' + params.toString();
  window.open(url, "_blank");
};
// hotkeys & palette
let selIndex = 0;
function rows(){ return Array.from(document.querySelectorAll('#results tbody tr')); }
function select(i){
  const r = rows(); if (!r.length) return;
  selIndex = Math.max(0, Math.min(i, r.length-1));
  r.forEach((el,idx)=> el.style.outline = (idx===selIndex ? '2px solid #8ab4f8' : ''));
  r[selIndex].scrollIntoView({block:'nearest'});
}
function openPreview(){
  const r = rows()[selIndex]; if(!r) return;
  if ($('#entity').value !== 'chunks') return;
  const fp = r.dataset.file, start = parseInt(r.dataset.start||"1"), end = parseInt(r.dataset.end||"0");
  fetch(`api/file?path=${encodeURIComponent(fp)}&start=${start}&end=${end}`).then(r=>r.json()).then(j=>{
    // Convert escaped newlines to actual newlines
    const content = (j.text || '(no content available for this file)').replace(/\\\\n/g, '\\n');
    displayCode(content, getCurrentLanguage());
  });
}
const PALETTE_CMDS = [
  {name:'Focus search (/)', run: ()=> $('#q').focus() },
  {name:'Toggle tech columns (.)', run: ()=> { $('#showTech').checked=!$('#showTech').checked; resetAndSearch(); } },
  {name:'Switch to files (g f)', run: ()=> { $('#entity').value='files'; resetAndSearch(); } },
  {name:'Switch to chunks (g c)', run: ()=> { $('#entity').value='chunks'; resetAndSearch(); } },
  {name:'Export JSONL', run: ()=> $('#export')?.click() },
  {name:'Copy link', run: ()=> copy(location.href) },
];
function openPalette(){
  $('#palette').style.display='flex';
  $('#palQ').value=''; renderPalette('');
  $('#palQ').focus();
}
function closePalette(){ $('#palette').style.display='none'; }
function renderPalette(q){
  const ul = $('#palList'); const r = q ? PALETTE_CMDS.filter(c=>c.name.toLowerCase().includes(q.toLowerCase())) : PALETTE_CMDS;
  ul.innerHTML = r.map((c,i)=> `<li data-i="${i}">${c.name}</li>`).join('');
  ul.onclick = (e)=>{ const li = e.target.closest('li'); if(!li) return; r[+li.dataset.i].run(); closePalette(); };
}
document.addEventListener('keydown', (e)=>{
  if (e.key==='/' && !e.metaKey && !e.ctrlKey){ e.preventDefault(); $('#q').focus(); return; }
  if ((e.metaKey||e.ctrlKey) && e.key.toLowerCase()==='k'){ e.preventDefault(); openPalette(); return; }
  if (e.key==='.' && !e.metaKey && !e.ctrlKey){ $('#showTech').checked=!$('#showTech').checked; resetAndSearch(); return; }
  if (e.key==='g'){ window.__gPressed=true; setTimeout(()=>window.__gPressed=false,500); return; }
  if (e.key==='f' && window.__gPressed){ $('#entity').value='files'; resetAndSearch(); return; }
  if (e.key==='c' && window.__gPressed){ $('#entity').value='chunks'; resetAndSearch(); return; }
  if (e.key==='j'){ select(selIndex+1); return; }
  if (e.key==='k'){ select(selIndex-1); return; }
  if (e.key==='Enter'){ openPreview(); return; }
  if (e.key==='Escape'){ closePalette(); return; }
});
$('#palQ')?.addEventListener('input', (e)=> renderPalette(e.target.value));
</script>"""