const state = { country: '', view: 'overview' };
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const esc = value => String(value ?? '').replace(/[&<>'"]/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[character]));
const qs = values => {
  const params = new URLSearchParams(Object.entries(values).filter(([, value]) => value !== '' && value != null));
  return params.toString() ? `?${params}` : '';
};
const get = async (path, values = {}) => {
  const response = await fetch(path + qs(values));
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};
const date = value => value
  ? new Intl.DateTimeFormat('en', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value))
  : '—';
const safeUrl = value => {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? esc(url.href) : '#';
  } catch { return '#'; }
};
const readableUrl = (value, preferred = '') => {
  if (preferred) return preferred;
  try {
    const url = new URL(value);
    return `${url.hostname.replace(/^www\./, '')}${decodeURIComponent(url.pathname).replace(/\/$/, '')}`;
  } catch { return 'Source'; }
};
const price = observation => {
  if (observation.price_min == null) return 'Unavailable';
  const format = number => new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(number);
  return `${format(observation.price_min)}${observation.price_max != null ? `–${format(observation.price_max)}` : ''} ${esc(observation.currency || '')}`;
};

async function loadMarkets() {
  const rows = await get('/api/coverage');
  $('#country').insertAdjacentHTML('beforeend', rows.map(row => `<option value="${row.country_code}">${esc(row.country_name)}</option>`).join(''));
  renderCoverage(rows);
}

async function loadOverview() {
  const data = await get('/api/overview', { country: state.country });
  const cards = [
    ['Verified competitors', data.competitors, 'Grounded provider records'],
    ['Clinic locations', data.locations, 'Address-evidenced branches'],
    ['Price observations', data.priced_observations, `${data.observations} total observations`],
    ['Retained sources', data.sources, 'Auditable evidence pages'],
  ];
  $('#metrics').innerHTML = cards.map(card => `<article class="metric"><span class="metric-label">${card[0]}</span><strong>${Number(card[1]).toLocaleString()}</strong><small>${card[2]}</small></article>`).join('');
  const sync = data.sync || {};
  $('#sync-status').textContent = sync.status === 'complete' ? `Evidence synced ${date(sync.last_completed_at)}` : `Sync ${sync.status || 'pending'}`;
}

async function loadPrices(query = '') {
  const rows = await get('/api/observations', { country: state.country, q: query, limit: 100 });
  $('#prices').innerHTML = rows.length ? rows.map(observation => `<tr>
    <td><strong>${esc(observation.competitor)}</strong></td>
    <td>${esc(observation.offering)}<div class="subtext">${esc(observation.original_name || '')}</div></td>
    <td class="price">${price(observation)}</td>
    <td><span class="badge">${esc(observation.price_type)}</span></td>
    <td>${esc(observation.country_code)}</td>
    <td><a class="source-link" href="${safeUrl(observation.source_url)}" target="_blank" rel="noopener noreferrer">${esc(readableUrl(observation.source_url, observation.source_label))} ↗</a><div class="subtext">${date(observation.retrieved_at)}</div></td>
  </tr>`).join('') : '<tr><td colspan="6" class="empty">No observations for this filter.</td></tr>';
}

async function loadCompetitors(query = '') {
  const rows = await get('/api/competitors', { country: state.country, q: query, limit: 150 });
  $('#competitors').innerHTML = rows.length ? rows.map(competitor => `<tr>
    <td><strong>${esc(competitor.name)}</strong><div class="subtext">${esc(competitor.domain || '')}</div></td>
    <td>${esc(competitor.country_code || '—')}</td><td>${competitor.locations}</td><td>${competitor.offerings}</td><td>${competitor.observations}</td><td>${date(competitor.last_observed_at)}</td>
  </tr>`).join('') : '<tr><td colspan="6" class="empty">No competitors for this filter.</td></tr>';
}

async function loadTreemap() {
  const rows = await get('/api/treemap', { country: state.country, limit: 1000 });
  const host = $('#treatment-treemap');
  if (!rows.length) {
    if (window.Plotly) Plotly.purge(host);
    host.innerHTML = '<p class="empty">No priced treatments for this filter.</p>';
    return;
  }
  const nodes = new Map();
  const add = (id, label, parent, value, priceLevel, detail) => {
    const existing = nodes.get(id) || { id, label, parent, value: 0, weightedPrice: 0, weight: 0, detail };
    existing.value += value;
    if (Number.isFinite(priceLevel)) {
      existing.weightedPrice += priceLevel * value;
      existing.weight += value;
    }
    nodes.set(id, existing);
  };
  rows.forEach(row => {
    const count = Number(row.observations) || 1;
    const level = Number(row.price_level);
    const countryId = `country:${row.country_code}`;
    const typeId = `${countryId}:type:${row.treatment_type}`;
    const leafId = `${typeId}:treatment:${row.treatment}:${row.currency || ''}`;
    add(countryId, row.country_code, '', count, level, 'Country');
    add(typeId, row.treatment_type, countryId, count, level, 'Treatment type');
    add(leafId, row.treatment, typeId, count, level, `${Number(row.median_price).toLocaleString('en', { maximumFractionDigits: 2 })} ${row.currency || ''} median · ${count} observations · ${row.sources} sources`);
  });
  const data = [...nodes.values()];
  await Plotly.react(host, [{
    type: 'treemap',
    ids: data.map(node => node.id),
    labels: data.map(node => node.label),
    parents: data.map(node => node.parent),
    values: data.map(node => node.value),
    branchvalues: 'total',
    customdata: data.map(node => node.detail),
    marker: {
      colors: data.map(node => node.weight ? node.weightedPrice / node.weight : .5),
      colorscale: [[0, '#2c9976'], [.5, '#efbf53'], [1, '#ca5c49']],
      cmin: 0, cmax: 1,
      line: { color: '#ffffff', width: 2 },
    },
    textfont: { family: 'Inter, system-ui, sans-serif', size: 13 },
    hovertemplate: '<b>%{label}</b><br>%{customdata}<br>Size: %{value}<extra></extra>',
    pathbar: { visible: true, edgeshape: '>' },
  }], {
    margin: { l: 8, r: 8, t: 36, b: 8 }, paper_bgcolor: '#ffffff', plot_bgcolor: '#ffffff',
  }, { responsive: true, displayModeBar: false });
}

function renderCoverage(rows) {
  $('#coverage-grid').innerHTML = rows.map(row => `<article class="coverage-card"><div class="coverage-top"><span class="country-code">${row.country_code}</span><span class="status ${row.coverage_status}">${row.coverage_status.replace('_', ' ')}</span></div><div class="coverage-name">${esc(row.country_name)}</div><div class="progress"><i style="width:${row.progress_pct}%"></i></div><div class="coverage-meta"><span>${row.verified}/${row.target} verified</span><span>${row.candidates} candidates</span></div></article>`).join('');
}
async function loadCoverage() { renderCoverage(await get('/api/coverage')); }

async function loadEvidence() {
  const rows = await get('/api/evidence', { country: state.country, limit: 60 });
  $('#evidence-list').innerHTML = rows.length ? rows.map(item => `<article class="evidence-item"><span class="evidence-market">${esc(item.country_code || 'EEA')}</span><div><a href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">${esc(readableUrl(item.url, item.display_url))}</a><p>${esc(item.excerpt || `${item.provider || 'Source'} evidence`)}</p></div><span class="evidence-time">${date(item.retrieved_at)}</span></article>`).join('') : '<p class="empty">No retained sources for this filter.</p>';
}

async function loadCandidates() {
  const rows = await get('/api/candidates', { country: state.country, limit: 100 });
  $('#candidates').innerHTML = rows.length ? rows.map(item => `<tr><td><strong>${esc(item.name || item.official_domain || 'Unnamed lead')}</strong><div class="subtext">${esc(item.official_domain || '')}</div></td><td>${esc(item.country_code || '—')}</td><td><span class="badge">${esc(item.state)}</span></td><td>${item.source_count}</td><td>${date(item.last_seen_at)}</td></tr>`).join('') : '<tr><td colspan="5" class="empty">No candidates for this filter.</td></tr>';
}

async function loadWatchlist() {
  const rows = await get('/api/watchlist', { country: state.country });
  $('#watchlist-grid').innerHTML = rows.length ? rows.map(item => `<article class="watch-card"><div class="watch-top"><span class="country-code">${esc(item.country_code)}</span><span class="watch-priority">P${item.priority ?? '—'}</span></div><h3>${esc(item.name)}</h3><p>${esc(item.positioning || item.segment || 'Curated competitor')}</p><div class="tag-row">${(item.capabilities || []).slice(0, 4).map(capability => `<span>${esc(String(capability).replaceAll('_', ' '))}</span>`).join('')}</div><small>${item.observations} observations · ${date(item.last_observed_at)}</small></article>`).join('') : '<p class="empty">No active watchlist targets for this filter.</p>';
}

async function loadRuns() {
  const rows = await get('/api/runs', { limit: 30 });
  $('#runs').innerHTML = rows.length ? rows.map(run => `<tr><td><strong>${esc(String(run.id).replace('fc:', '').slice(0, 22))}</strong><div class="subtext">${esc(run.actor || run.source_system)}</div></td><td>${esc(run.trigger_kind || '—')}</td><td><span class="badge">${esc(run.status)}</span></td><td>${date(run.started_at)}</td><td>${esc(run.error || Object.entries(run.stats || {}).map(([key, value]) => `${key}: ${value}`).slice(0, 3).join(' · ') || '—')}</td></tr>`).join('') : '<tr><td colspan="5" class="empty">No collection runs yet.</td></tr>';
}

async function refresh() {
  await Promise.all([
    loadOverview(), loadPrices($('#price-search').value), loadCompetitors($('#competitor-search').value),
    loadTreemap(), loadEvidence(), loadCandidates(), loadWatchlist(), loadRuns(),
  ]);
  if (state.view === 'coverage') await loadCoverage();
}

function selectView(view, updateHash = true) {
  state.view = ['overview', 'competitors', 'coverage', 'evidence'].includes(view) ? view : 'overview';
  $$('.nav-button').forEach(button => button.classList.toggle('active', button.dataset.view === state.view));
  $$('.view-panel').forEach(panel => panel.classList.toggle('hidden', panel.dataset.panel !== state.view));
  if (updateHash) history.replaceState(null, '', state.view === 'overview' ? '/dashboard' : `/dashboard#${state.view}`);
}
$$('.nav-button').forEach(button => button.addEventListener('click', () => selectView(button.dataset.view)));
selectView(location.hash.slice(1) || 'overview', false);
window.addEventListener('hashchange', () => selectView(location.hash.slice(1), false));

$('#country').addEventListener('change', () => { state.country = $('#country').value; refresh(); });
let priceTimer;
let competitorTimer;
$('#price-search').addEventListener('input', () => { clearTimeout(priceTimer); priceTimer = setTimeout(() => loadPrices($('#price-search').value), 250); });
$('#competitor-search').addEventListener('input', () => { clearTimeout(competitorTimer); competitorTimer = setTimeout(() => loadCompetitors($('#competitor-search').value), 250); });
$$('.suggestions button').forEach(button => button.addEventListener('click', () => { $('#question').value = button.textContent; $('#assistant-form').requestSubmit(); }));

function sseEvent(raw) {
  let name = 'message';
  const parts = [];
  raw.split(/\r?\n/).forEach(line => {
    if (line.startsWith('event:')) name = line.slice(6).trim();
    if (line.startsWith('data:')) parts.push(line.slice(5).trimStart());
  });
  let data = {};
  try { data = JSON.parse(parts.join('\n') || '{}'); } catch { /* malformed upstream event */ }
  return { name, data };
}
function streamCard(feed) {
  const card = document.createElement('div');
  card.className = 'assistant-message stream-message';
  card.innerHTML = '<div class="analysis-meta"></div><div class="stream-progress"><div class="stream-progress-copy"><span>Understanding your question…</span><b>8%</b></div><div class="stream-track"><i style="width:8%"></i></div></div><p class="answer-text"></p>';
  feed.appendChild(card);
  return card;
}
function renderVisual(card, data) {
  const rows = (data.rows || []).filter(row => Number.isFinite(Number(row.value)));
  if (!rows.length) return;
  const max = Math.max(...rows.map(row => Math.abs(Number(row.value))), 1);
  const host = document.createElement('div');
  host.className = 'analysis-visual';
  host.innerHTML = `<div class="analysis-visual-head"><strong>${esc(data.title || 'Governed analysis')}</strong><span>${Number(data.evidence?.records || 0).toLocaleString()} records</span></div><div class="analysis-bars">${rows.map(row => `<div class="analysis-bar"><span title="${esc(row.label)}">${esc(row.label)}</span><i><b style="width:${Math.max(3, Math.abs(Number(row.value)) / max * 100)}%"></b></i><em>${new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(Number(row.value))}</em></div>`).join('')}</div>`;
  card.appendChild(host);
}
function renderCitations(card, items) {
  if (!items?.length) return;
  const host = document.createElement('div');
  host.className = 'citations';
  host.innerHTML = `<span class="eyebrow">SOURCES</span>${items.map(citation => `<a href="${safeUrl(citation.url)}" target="_blank" rel="noopener noreferrer">↗ ${esc(readableUrl(citation.url, citation.label))}</a>`).join('')}`;
  card.appendChild(host);
}
function handleStreamEvent(card, event, answer) {
  const data = event.data;
  if (event.name === 'progress') {
    const progress = card.querySelector('.stream-progress');
    progress.hidden = false;
    progress.querySelector('span').textContent = data.label || 'Working…';
    progress.querySelector('b').textContent = `${data.percent || 0}%`;
    progress.querySelector('i').style.width = `${Math.max(3, Math.min(100, data.percent || 0))}%`;
  } else if (event.name === 'plan') {
    card.querySelector('.analysis-meta').innerHTML = `<span>${esc(data.metric_label)}</span><span>by ${esc(data.dimension_label)}</span>${data.country ? `<span>${esc(data.country)}</span>` : ''}`;
  } else if (event.name === 'visual') renderVisual(card, data);
  else if (event.name === 'token') {
    answer.text += data.token || '';
    card.querySelector('.stream-progress').hidden = true;
    card.querySelector('.answer-text').innerHTML = esc(answer.text).replace(/\n/g, '<br>');
  } else if (event.name === 'citations') renderCitations(card, data.items);
  else if (event.name === 'error') {
    card.querySelector('.stream-progress').hidden = true;
    card.querySelector('.answer-text').textContent = data.message || 'The analysis could not be completed.';
  } else if (event.name === 'done') card.querySelector('.stream-progress').hidden = true;
}

$('#assistant-form').addEventListener('submit', async event => {
  event.preventDefault();
  const question = $('#question').value.trim();
  if (!question) return;
  const feed = $('#assistant-feed');
  const button = event.currentTarget.querySelector('button');
  feed.insertAdjacentHTML('beforeend', `<div class="assistant-message user"><p>${esc(question)}</p></div>`);
  const card = streamCard(feed);
  const streamed = { text: '' };
  $('#question').value = '';
  button.disabled = true;
  feed.scrollTop = feed.scrollHeight;
  try {
    const response = await fetch('/api/assistant/stream', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question, country: state.country || null, workspace: 'dashboard' }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const part = await reader.read();
      buffer += decoder.decode(part.value || new Uint8Array(), { stream: !part.done });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (raw.trim()) handleStreamEvent(card, sseEvent(raw), streamed);
      }
      feed.scrollTop = feed.scrollHeight;
      if (part.done) break;
    }
  } catch {
    card.querySelector('.stream-progress').hidden = true;
    card.querySelector('.answer-text').textContent = 'I could not complete that analysis just now. The dashboard evidence remains available.';
  } finally {
    button.disabled = false;
    feed.scrollTop = feed.scrollHeight;
  }
});

Promise.all([loadMarkets(), refresh()]).catch(error => {
  $('#sync-status').textContent = 'Evidence connection unavailable';
  console.error(error);
});
