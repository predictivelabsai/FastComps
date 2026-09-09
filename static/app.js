const initialParams = new URLSearchParams(location.search);
let i18n = { lang: 'en', translations: {} };
try { i18n = JSON.parse(document.getElementById('i18n-data')?.textContent || '{}'); } catch { /* default English */ }
const tr = (text, values = {}) => {
  let result = i18n.translations?.[text] || text;
  Object.entries(values).forEach(([key, value]) => { result = result.replaceAll(`{${key}}`, value); });
  return result;
};
const locale = { et: 'et-EE', lt: 'lt-LT', en: 'en-GB' }[i18n.lang] || 'en-GB';
const regions = new Intl.DisplayNames([locale], { type: 'region' });
const countryName = (code, fallback = '') => { try { return regions.of(code) || fallback || code; } catch { return fallback || code; } };
const state = { country: (initialParams.get('country') || '').toUpperCase(), view: 'overview' };
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
  ? new Intl.DateTimeFormat(locale, { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value))
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
  } catch { return tr('Source'); }
};
const flag = code => /^[A-Z]{2}$/.test(code || '')
  ? String.fromCodePoint(...[...code].map(character => 127397 + character.charCodeAt()))
  : '🌍';
const updateUrl = () => {
  const query = state.country ? `?country=${encodeURIComponent(state.country)}` : '';
  const hash = state.view === 'overview' ? '' : `#${state.view}`;
  history.replaceState(null, '', `/dashboard${query}${hash}`);
};
const price = observation => {
  if (observation.price_min == null) return tr('Unavailable');
  const format = number => new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(number);
  return `${format(observation.price_min)}${observation.price_max != null ? `–${format(observation.price_max)}` : ''} ${esc(observation.currency || '')}`;
};

async function loadMarkets() {
  const rows = await get('/api/coverage');
  $('#country').innerHTML = `<option value="">🌍 ${esc(tr('All EEA'))}</option>` + rows.map(row => `<option value="${row.country_code}">${flag(row.country_code)} ${esc(countryName(row.country_code, row.country_name))}</option>`).join('');
  $('#country').value = state.country;
  renderCountryFilters(rows);
  renderCoverage(rows);
}

function renderCountryFilters(rows) {
  const host = $('#country-filter-bar');
  host.innerHTML = `<button type="button" data-country="" class="country-filter">🌍 ${esc(tr('All'))} <small>${rows.reduce((sum, row) => sum + Number(row.verified || 0), 0)}</small></button>` + rows.map(row => `<button type="button" data-country="${row.country_code}" class="country-filter" title="${esc(countryName(row.country_code, row.country_name))}">${flag(row.country_code)} ${row.country_code}<small>${row.verified}</small></button>`).join('');
  host.querySelectorAll('button').forEach(button => button.addEventListener('click', () => setCountry(button.dataset.country)));
  updateCountryFilters();
}
function updateCountryFilters() {
  $$('.country-filter').forEach(button => button.classList.toggle('active', button.dataset.country === state.country));
}
function setCountry(country, shouldRefresh = true) {
  state.country = country || '';
  $('#country').value = state.country;
  updateCountryFilters();
  updateUrl();
  if (shouldRefresh) refresh();
}

async function loadOverview() {
  const data = await get('/api/overview', { country: state.country });
  const cards = [
    [tr('Verified competitors'), data.competitors, tr('Grounded provider records')],
    [tr('Clinic locations'), data.locations, tr('Mapped clinic branches')],
    [tr('Price observations'), data.priced_observations, `${data.observations} ${tr('total observations')}`],
    [tr('Retained sources'), data.sources, tr('Auditable market pages')],
  ];
  $('#metrics').innerHTML = cards.map(card => `<article class="metric"><span class="metric-label">${card[0]}</span><strong>${Number(card[1]).toLocaleString()}</strong><small>${card[2]}</small></article>`).join('');
  const sync = data.sync || {};
  $('#sync-status').textContent = sync.status === 'complete'
    ? tr('Market synced {date}', { date: date(sync.last_completed_at) })
    : tr('Sync {status}', { status: tr((sync.status || 'pending').replaceAll('_', ' ')) });
}

async function loadPrices(query = '') {
  const rows = await get('/api/observations', { country: state.country, q: query, limit: 100 });
  $('#prices').innerHTML = rows.length ? rows.map(observation => `<tr>
    <td><a class="row-link" href="/competitors/${encodeURIComponent(observation.competitor_id)}"><strong>${esc(observation.competitor)}</strong></a></td>
    <td>${esc(observation.offering)}<div class="subtext">${esc(observation.original_name || '')}</div></td>
    <td class="price">${price(observation)}</td>
    <td><span class="badge">${esc(observation.price_type)}</span></td>
    <td>${flag(observation.country_code)} ${esc(observation.country_code)}</td>
    <td><a class="source-link" href="${safeUrl(observation.source_url)}" target="_blank" rel="noopener noreferrer">${esc(readableUrl(observation.source_url, observation.source_label))} ↗</a><div class="subtext">${date(observation.retrieved_at)}</div></td>
  </tr>`).join('') : `<tr><td colspan="6" class="empty">${esc(tr('No observations for this filter.'))}</td></tr>`;
}

async function loadCompetitors(query = '') {
  const rows = await get('/api/competitors', { country: state.country, q: query, limit: 150 });
  $('#competitors').innerHTML = rows.length ? rows.map(competitor => `<tr>
    <td><a class="row-link" href="/competitors/${encodeURIComponent(competitor.id)}"><strong>${esc(competitor.name)}</strong></a><div class="subtext">${esc(competitor.domain || '')}</div></td>
    <td>${flag(competitor.country_code)} ${esc(competitor.country_code || '—')}</td><td>${competitor.locations}</td><td>${competitor.offerings}</td><td>${competitor.observations}</td><td>${date(competitor.last_observed_at)}</td>
  </tr>`).join('') : `<tr><td colspan="6" class="empty">${esc(tr('No competitors for this filter.'))}</td></tr>`;
}

async function loadTreemap() {
  const rows = await get('/api/treemap', { country: state.country, limit: 1000 });
  const host = $('#treatment-treemap');
  if (!rows.length) {
    if (window.Plotly) Plotly.purge(host);
    host.innerHTML = `<p class="empty">${esc(tr('No priced treatments for this filter.'))}</p>`;
    return;
  }
  const nodes = new Map();
  const add = (id, label, parent, value, priceLevel, detail, country = '', treatment = '') => {
    const existing = nodes.get(id) || { id, label, parent, value: 0, weightedPrice: 0, weight: 0, detail, country, treatment };
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
    add(countryId, `${flag(row.country_code)} ${row.country_code}`, '', count, level, tr('Country'), row.country_code);
    add(typeId, row.treatment_type, countryId, count, level, tr('Treatment type'), row.country_code);
    add(leafId, row.treatment, typeId, count, level, `${Number(row.median_price).toLocaleString(locale, { maximumFractionDigits: 2 })} ${row.currency || ''} ${tr('median')} · ${count} ${tr('observations')} · ${row.sources} ${tr('sources')}`, row.country_code, row.treatment);
  });
  const data = [...nodes.values()];
  await Plotly.react(host, [{
    type: 'treemap',
    ids: data.map(node => node.id),
    labels: data.map(node => node.label),
    parents: data.map(node => node.parent),
    values: data.map(node => node.value),
    branchvalues: 'total',
    customdata: data.map(node => [node.detail, node.country, node.treatment]),
    marker: {
      colors: data.map(node => node.weight ? node.weightedPrice / node.weight : .5),
      colorscale: [[0, '#2c9976'], [.5, '#efbf53'], [1, '#ca5c49']],
      cmin: 0, cmax: 1,
      line: { color: '#ffffff', width: 2 },
    },
    textfont: { family: 'Inter, system-ui, sans-serif', size: 13 },
    hovertemplate: '<b>%{label}</b><br>%{customdata[0]}<br>Size: %{value}<extra></extra>',
    pathbar: { visible: true, edgeshape: '>' },
  }], {
    margin: { l: 8, r: 8, t: 36, b: 8 }, paper_bgcolor: '#ffffff', plot_bgcolor: '#ffffff',
  }, { responsive: true, displayModeBar: false });
  if (host.removeAllListeners) host.removeAllListeners('plotly_click');
  host.on('plotly_click', event => {
    const point = event.points?.[0];
    const country = point?.customdata?.[1];
    const treatment = point?.customdata?.[2];
    if (!country || !treatment) return;
    setCountry(country, false);
    $('#price-search').value = treatment;
    loadPrices(treatment);
    $('#treemap-drilldown').textContent = `${flag(country)} ${country} · ${tr('market prices for')} “${treatment}”`;
    $('#prices').closest('.panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

let marketMap;
let marketMarkers;
function ensureMarketMap() {
  if (marketMap || !window.L) return;
  marketMap = L.map('market-map', { zoomControl: true }).setView([54.5, 15], 4);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(marketMap);
  marketMarkers = L.featureGroup().addTo(marketMap);
}
async function loadMap() {
  const rows = await get('/api/locations', { country: state.country });
  ensureMarketMap();
  if (!marketMap) return;
  marketMarkers.clearLayers();
  rows.forEach(item => {
    const marker = L.circleMarker([Number(item.latitude), Number(item.longitude)], {
      radius: 7, color: '#155b48', weight: 2, fillColor: '#35a77d', fillOpacity: .82,
    });
    const providerPath = `/competitors/${encodeURIComponent(item.competitor_id)}`;
    marker.bindPopup(`<strong>${esc(item.competitor)}</strong><br>${esc([item.address, item.city].filter(Boolean).join(', '))}<br><span>${flag(item.country_code)} ${esc(item.country_code)}</span><br><a href="${providerPath}">${esc(tr('View provider and prices →'))}</a>`);
    marker.addTo(marketMarkers);
  });
  if (rows.length) marketMap.fitBounds(marketMarkers.getBounds().pad(.08), { maxZoom: 13 });
  else marketMap.setView([54.5, 15], 4);
  $('#market-map-summary').textContent = rows.length
    ? tr('{count} geocoded clinic locations {scope}', { count: rows.length.toLocaleString(locale), scope: state.country ? `${tr('in')} ${flag(state.country)} ${state.country}` : tr('across the EEA') })
    : tr('No geocoded clinic locations for this filter.');
}

function renderCoverage(rows) {
  $('#coverage-grid').innerHTML = rows.map(row => `<article class="coverage-card"><div class="coverage-top"><span class="country-code">${flag(row.country_code)} ${row.country_code}</span><span class="status ${row.coverage_status}">${esc(tr(row.coverage_status.replaceAll('_', ' ')))}</span></div><div class="coverage-name">${esc(countryName(row.country_code, row.country_name))}</div><div class="progress"><i style="width:${row.progress_pct}%"></i></div><div class="coverage-meta"><span>${row.verified}/${row.target} ${esc(tr('verified'))}</span><span>${row.candidates} ${esc(tr('candidates'))}</span></div></article>`).join('');
}
async function loadCoverage() { renderCoverage(await get('/api/coverage')); }

async function loadMarket() {
  const rows = await get('/api/market', { country: state.country, limit: 60 });
  $('#market-list').innerHTML = rows.length ? rows.map(item => `<article class="market-item"><span class="market-market">${esc(item.country_code || 'EEA')}</span><div><a href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">${esc(readableUrl(item.url, item.display_url))}</a><p>${esc(item.excerpt || `${item.provider || tr('Source')} ${tr('market')}`)}</p></div><span class="market-time">${date(item.retrieved_at)}</span></article>`).join('') : `<p class="empty">${esc(tr('No retained sources for this filter.'))}</p>`;
}

async function loadCandidates() {
  const rows = await get('/api/candidates', { country: state.country, limit: 100 });
  $('#candidates').innerHTML = rows.length ? rows.map(item => `<tr><td><strong>${esc(item.name || item.official_domain || tr('Unnamed lead'))}</strong><div class="subtext">${esc(item.official_domain || '')}</div></td><td>${esc(item.country_code || '—')}</td><td><span class="badge">${esc(tr(item.state))}</span></td><td>${item.source_count}</td><td>${date(item.last_seen_at)}</td></tr>`).join('') : `<tr><td colspan="5" class="empty">${esc(tr('No candidates for this filter.'))}</td></tr>`;
}

async function loadWatchlist() {
  const rows = await get('/api/watchlist', { country: state.country });
  $('#watchlist-grid').innerHTML = rows.length ? rows.map(item => `<article class="watch-card"><div class="watch-top"><span class="country-code">${esc(item.country_code)}</span><span class="watch-priority">P${item.priority ?? '—'}</span></div><h3>${esc(item.name)}</h3><p>${esc(item.positioning || item.segment || tr('Curated competitor'))}</p><div class="tag-row">${(item.capabilities || []).slice(0, 4).map(capability => `<span>${esc(tr(String(capability).replaceAll('_', ' ')))}</span>`).join('')}</div><small>${item.observations} ${esc(tr('observations'))} · ${date(item.last_observed_at)}</small></article>`).join('') : `<p class="empty">${esc(tr('No active watchlist targets for this filter.'))}</p>`;
}

async function loadRuns() {
  const rows = await get('/api/runs', { limit: 30 });
  $('#runs').innerHTML = rows.length ? rows.map(run => `<tr><td><strong>${esc(String(run.id).replace('fc:', '').slice(0, 22))}</strong><div class="subtext">${esc(run.actor || run.source_system)}</div></td><td>${esc(tr(run.trigger_kind || '—'))}</td><td><span class="badge">${esc(tr(run.status))}</span></td><td>${date(run.started_at)}</td><td>${esc(run.error || Object.entries(run.stats || {}).map(([key, value]) => `${key}: ${value}`).slice(0, 3).join(' · ') || '—')}</td></tr>`).join('') : `<tr><td colspan="5" class="empty">${esc(tr('No collection runs yet.'))}</td></tr>`;
}

async function refresh() {
  await Promise.all([
    loadOverview(), loadPrices($('#price-search').value), loadCompetitors($('#competitor-search').value),
    loadTreemap(), loadMap(), loadMarket(), loadCandidates(), loadWatchlist(), loadRuns(),
  ]);
  if (state.view === 'coverage') await loadCoverage();
}

function selectView(view, updateHash = true) {
  state.view = ['overview', 'competitors', 'map', 'coverage', 'market'].includes(view) ? view : 'overview';
  $$('.nav-button').forEach(button => button.classList.toggle('active', button.dataset.view === state.view));
  $$('.view-panel').forEach(panel => panel.classList.toggle('hidden', panel.dataset.panel !== state.view));
  if (updateHash) updateUrl();
  if (state.view === 'map') setTimeout(() => marketMap?.invalidateSize(), 0);
}
$$('.nav-button').forEach(button => button.addEventListener('click', () => selectView(button.dataset.view)));
selectView(location.hash.slice(1) || 'overview', false);
window.addEventListener('hashchange', () => selectView(location.hash.slice(1), false));

$('#country').addEventListener('change', () => setCountry($('#country').value));
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
  card.innerHTML = `<div class="analysis-meta"></div><div class="stream-progress"><div class="stream-progress-copy"><span>${esc(tr('Understanding your question…'))}</span><b>8%</b></div><div class="stream-track"><i style="width:8%"></i></div></div><p class="answer-text"></p>`;
  feed.appendChild(card);
  return card;
}
function renderVisual(card, data) {
  const rows = (data.rows || []).filter(row => Number.isFinite(Number(row.value)));
  if (!rows.length) return;
  const max = Math.max(...rows.map(row => Math.abs(Number(row.value))), 1);
  const host = document.createElement('div');
  host.className = 'analysis-visual';
  host.innerHTML = `<div class="analysis-visual-head"><strong>${esc(data.title || tr('Governed analysis'))}</strong><span>${Number(data.market?.records || 0).toLocaleString(locale)} ${esc(tr('records'))}</span></div><div class="analysis-bars">${rows.map(row => `<div class="analysis-bar"><span title="${esc(row.label)}">${esc(row.label)}</span><i><b style="width:${Math.max(3, Math.abs(Number(row.value)) / max * 100)}%"></b></i><em>${new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(Number(row.value))}</em></div>`).join('')}</div>`;
  card.appendChild(host);
}
function renderCitations(card, items) {
  if (!items?.length) return;
  const host = document.createElement('div');
  host.className = 'citations';
  host.innerHTML = `<span class="eyebrow">${esc(tr('SOURCES'))}</span>${items.map(citation => `<a href="${safeUrl(citation.url)}" target="_blank" rel="noopener noreferrer">↗ ${esc(readableUrl(citation.url, citation.label))}</a>`).join('')}`;
  card.appendChild(host);
}
function handleStreamEvent(card, event, answer) {
  const data = event.data;
  if (event.name === 'progress') {
    const progress = card.querySelector('.stream-progress');
    progress.hidden = false;
    progress.querySelector('span').textContent = data.label || tr('Working…');
    progress.querySelector('b').textContent = `${data.percent || 0}%`;
    progress.querySelector('i').style.width = `${Math.max(3, Math.min(100, data.percent || 0))}%`;
  } else if (event.name === 'plan') {
    card.querySelector('.analysis-meta').innerHTML = `<span>${esc(data.metric_label)}</span><span>${esc(tr('by'))} ${esc(data.dimension_label)}</span>${data.country ? `<span>${esc(data.country)}</span>` : ''}`;
  } else if (event.name === 'visual') renderVisual(card, data);
  else if (event.name === 'token') {
    answer.text += data.token || '';
    card.querySelector('.stream-progress').hidden = true;
    card.querySelector('.answer-text').innerHTML = esc(answer.text).replace(/\n/g, '<br>');
  } else if (event.name === 'citations') renderCitations(card, data.items);
  else if (event.name === 'error') {
    card.querySelector('.stream-progress').hidden = true;
    card.querySelector('.answer-text').textContent = data.message || tr('The analysis could not be completed.');
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
    card.querySelector('.answer-text').textContent = tr('I could not complete that analysis just now. The dashboard market data remains available.');
  } finally {
    button.disabled = false;
    feed.scrollTop = feed.scrollHeight;
  }
});

Promise.all([loadMarkets(), refresh()]).catch(error => {
  $('#sync-status').textContent = tr('Market connection unavailable');
  console.error(error);
});
