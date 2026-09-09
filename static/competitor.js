const host = document.getElementById('competitor-map');
const payload = document.getElementById('competitor-map-data');
if (host && payload && window.L) {
  let rows = [];
  try { rows = JSON.parse(payload.textContent); } catch { rows = []; }
  const map = L.map(host).setView([54.5, 15], 4);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const markers = L.featureGroup().addTo(map);
  rows.forEach(row => {
    const marker = L.circleMarker([Number(row.latitude), Number(row.longitude)], {
      radius: 8, color: '#155b48', weight: 2, fillColor: '#35a77d', fillOpacity: .82,
    });
    const copy = document.createElement('div');
    const title = document.createElement('strong');
    title.textContent = row.name || 'Clinic location';
    const address = document.createElement('p');
    address.textContent = [row.address, row.city, row.postal_code].filter(Boolean).join(', ');
    copy.append(title, address);
    marker.bindPopup(copy).addTo(markers);
  });
  if (rows.length) map.fitBounds(markers.getBounds().pad(.12), { maxZoom: 14 });
}
