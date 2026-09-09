(() => {
  const host = document.getElementById('daily-scan-treemap');
  const source = document.getElementById('daily-scan-data');
  if (!host || !source) return;

  let rows = [];
  try { rows = JSON.parse(source.textContent || '[]'); } catch { rows = []; }
  if (!rows.length || !window.Plotly) {
    host.innerHTML = '<p class="scan-empty">No comparable cross-clinic price signals are available yet.</p>';
    return;
  }

  const flag = code => /^[A-Z]{2}$/.test(code || '')
    ? String.fromCodePoint(...[...code].map(character => 127397 + character.charCodeAt()))
    : '🌍';
  const money = value => new Intl.NumberFormat(undefined, {
    style: 'currency', currency: 'EUR', maximumFractionDigits: 2,
  }).format(Number(value || 0));
  const midpoint = row => (Number(row.lowest_price || 0) + Number(row.highest_price || 0)) / 2;
  const leafLevels = rows.map(row => Math.log1p(midpoint(row)));
  const minLevel = Math.min(...leafLevels);
  const maxLevel = Math.max(...leafLevels);
  const normalizedLevel = row => {
    const level = Math.log1p(midpoint(row));
    return maxLevel === minLevel ? .5 : (level - minLevel) / (maxLevel - minLevel);
  };

  const nodes = new Map();
  const add = (id, label, parent, value, level, detail, targetId = null, text = '') => {
    const node = nodes.get(id) || {
      id, label, parent, value: 0, weightedLevel: 0, weight: 0, detail, targetId, text,
    };
    node.value += value;
    node.weightedLevel += level * value;
    node.weight += value;
    nodes.set(id, node);
  };

  rows.forEach((row, index) => {
    const country = row.country_code || 'EEA';
    const type = row.treatment_type || 'General medicine & other treatments';
    const treatment = row.treatment || 'Treatment';
    const value = Math.max(1, Number(row.clinic_count || 1));
    const level = normalizedLevel(row);
    const countryId = `country:${country}`;
    const typeId = `${countryId}:type:${type}`;
    const leafId = `${typeId}:treatment:${treatment}:${index}`;
    const low = Number(row.lowest_price || 0);
    const high = Number(row.highest_price || 0);
    const range = low === high ? money(low) : `${money(low)} – ${money(high)}`;
    add(countryId, `${flag(country)} ${country}`, '', value, level, `${country} · ${value} clinic observations`);
    add(typeId, type, countryId, value, level, `${country} · ${type}`);
    const clinics = row.lowest_clinic === row.highest_clinic
      ? row.lowest_clinic : `${row.lowest_clinic} → ${row.highest_clinic}`;
    add(leafId, treatment, typeId, value, level,
      `${range}<br>${clinics}`, row.target_id, range);
  });
  const data = [...nodes.values()];

  Plotly.newPlot(host, [{
    type: 'treemap',
    ids: data.map(node => node.id),
    labels: data.map(node => node.label),
    parents: data.map(node => node.parent),
    values: data.map(node => node.value),
    branchvalues: 'total',
    customdata: data.map(node => [node.detail, node.targetId]),
    text: data.map(node => node.text),
    texttemplate: '<b>%{label}</b><br>%{text}',
    marker: {
      colors: data.map(node => node.weightedLevel / node.weight),
      colorscale: [[0, '#2c9976'], [.5, '#efbf53'], [1, '#ca5c49']],
      cmin: 0, cmax: 1,
      line: { color: '#ffffff', width: 2 },
    },
    textfont: { family: 'Inter, system-ui, sans-serif', size: 14 },
    hovertemplate: '<b>%{label}</b><br>%{customdata[0]}<br>Comparable clinics: %{value}<extra></extra>',
    pathbar: { visible: true, edgeshape: '>' },
  }], {
    margin: { l: 8, r: 8, t: 38, b: 8 },
    paper_bgcolor: '#ffffff', plot_bgcolor: '#ffffff',
  }, { responsive: true, displayModeBar: false });

  host.on('plotly_click', event => {
    const targetId = event.points?.[0]?.customdata?.[1];
    if (!targetId) return;
    const card = document.getElementById(targetId);
    if (!card) return;
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.remove('highlight');
    requestAnimationFrame(() => card.classList.add('highlight'));
    setTimeout(() => card.classList.remove('highlight'), 1700);
  });
})();
