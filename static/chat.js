const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>'"]/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[character]));
const safeUrl = value => {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? esc(url.href) : '#';
  } catch { return '#'; }
};
const readableUrl = (value, preferred = '') => {
  if (preferred && !/^https?:\/\//i.test(preferred)) return preferred;
  try {
    const url = new URL(value || preferred);
    return `${url.hostname.replace(/^www\./, '')}${decodeURIComponent(url.pathname).replace(/\/$/, '')}`;
  } catch { return preferred || 'Source'; }
};

let threadId = '';
try { threadId = JSON.parse($('#chat-state').textContent).thread_id || ''; } catch { /* empty state */ }

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

function appendMessage(role, content = '') {
  const article = document.createElement('article');
  article.className = `chat-message ${role}`;
  article.innerHTML = `<div class="chat-role">${role === 'user' ? 'You' : 'FastComps AI'}</div><div class="chat-bubble"><p>${esc(content)}</p></div>`;
  $('#chat-messages').appendChild(article);
  return article;
}

function streamCard() {
  const article = appendMessage('assistant');
  article.querySelector('.chat-bubble').innerHTML = '<div class="analysis-meta"></div><div class="stream-progress"><div class="stream-progress-copy"><span>Understanding your question…</span><b>8%</b></div><div class="stream-track"><i style="width:8%"></i></div></div><p class="answer-text"></p>';
  return article;
}

function renderVisual(card, data) {
  const rows = (data.rows || []).filter(row => Number.isFinite(Number(row.value)));
  if (!rows.length) return;
  const max = Math.max(...rows.map(row => Math.abs(Number(row.value))), 1);
  const host = document.createElement('div');
  host.className = 'analysis-visual';
  host.innerHTML = `<strong>${esc(data.title || 'Governed analysis')}</strong>${rows.map(row => `<div class="analysis-bar"><span title="${esc(row.label)}">${esc(row.label)}</span><i><b style="width:${Math.max(3, Math.abs(Number(row.value)) / max * 100)}%"></b></i><em>${new Intl.NumberFormat('en', { maximumFractionDigits: 2 }).format(Number(row.value))}</em></div>`).join('')}`;
  card.querySelector('.chat-bubble').appendChild(host);
}

function renderCitations(card, items) {
  if (!items?.length) return;
  const host = document.createElement('div');
  host.className = 'chat-citations';
  host.innerHTML = `<span>Sources</span>${items.map(item => `<a href="${safeUrl(item.url)}" target="_blank" rel="noopener noreferrer">↗ ${esc(readableUrl(item.url, item.label))}</a>`).join('')}`;
  card.querySelector('.chat-bubble').appendChild(host);
}

function handleEvent(card, event, answer) {
  const data = event.data;
  if (event.name === 'thread') {
    threadId = data.thread_id || threadId;
    history.replaceState(null, '', `/?thread=${encodeURIComponent(threadId)}`);
  } else if (event.name === 'progress') {
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

async function refreshHistory() {
  const response = await fetch('/api/threads');
  if (!response.ok) return;
  const rows = await response.json();
  $('.history-list').innerHTML = rows.map(row => `<a class="history-link${String(row.id) === threadId ? ' active' : ''}" href="/?thread=${encodeURIComponent(row.id)}"><span>◌</span>${esc(row.title || 'New chat')}</a>`).join('') || '<p class="history-empty">No conversations yet</p>';
}

async function submitQuestion(question) {
  const welcome = $('#chat-welcome');
  if (welcome) welcome.classList.add('hidden');
  appendMessage('user', question);
  const card = streamCard();
  const answer = { text: '' };
  const send = $('#chat-form button');
  send.disabled = true;
  $('#chat-question').value = '';
  $('#chat-messages').scrollTop = $('#chat-messages').scrollHeight;
  try {
    const response = await fetch('/api/assistant/stream', {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question, workspace: 'chat', thread_id: threadId || null }),
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
        if (raw.trim()) handleEvent(card, sseEvent(raw), answer);
      }
      $('#chat-messages').scrollTop = $('#chat-messages').scrollHeight;
      if (part.done) break;
    }
    await refreshHistory();
  } catch {
    card.querySelector('.stream-progress').hidden = true;
    card.querySelector('.answer-text').textContent = 'I could not complete that analysis just now. Please try again.';
  } finally {
    send.disabled = false;
    $('#chat-question').focus();
  }
}

$('#chat-form').addEventListener('submit', event => {
  event.preventDefault();
  const question = $('#chat-question').value.trim();
  if (question) submitQuestion(question);
});
$('#chat-question').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    $('#chat-form').requestSubmit();
  }
});
document.querySelectorAll('.chat-suggestions button').forEach(button => button.addEventListener('click', () => submitQuestion(button.textContent)));
