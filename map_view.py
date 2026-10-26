import json
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView


HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    html, body, #map { height: 100%; margin: 0; }
    .dist { margin-top: 6px; padding-top: 6px; border-top: 1px solid #ccc;
            color: #0a5; font-weight: bold; }
  </style>
</head>
<body>
  <div id="map"></div>
  <script>
    const map = L.map('map', {worldCopyJump: true}).setView([30, 10], 2);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 10, attribution: '&copy; OpenStreetMap'
    }).addTo(map);

    let markers = [];
    let markersById = {};
    let spotDataById = {};

    function buildPopup(s, distanceHtml) {
      let html =
        '<b>' + s.dx_call + '</b> (' + s.band + ')<br>' +
        s.freq.toFixed(1) + ' kHz ' + s.mode + '<br>' +
        'Spotter: ' + s.spotter + '<br>' +
        (s.dxcc ? 'DXCC: ' + s.dxcc + '<br>' : '') +
        '<small>' + s.timestamp + '</small>';
      if (distanceHtml) {
        html += '<div class="dist">↔ ' + distanceHtml + '</div>';
      }
      return html;
    }

    window.updateSpots = function(spots) {
      markers.forEach(m => map.removeLayer(m));
      markers = [];
      markersById = {};
      spotDataById = {};
      spots.forEach(s => {
        if (s.lat == null || s.lng == null) return;
        spotDataById[s.id] = s;
        const m = L.circleMarker([s.lat, s.lng], {
          radius: 6, weight: 1, color: '#222',
          fillColor: s.color, fillOpacity: 0.85
        }).addTo(map);
        m.bindPopup(buildPopup(s, null));
        markers.push(m);
        markersById[s.id] = m;
      });
    };

    window.focusOn = function(id, distanceHtml) {
      const m = markersById[id];
      const s = spotDataById[id];
      if (!m || !s) return;
      m.setPopupContent(buildPopup(s, distanceHtml));
      map.flyTo(m.getLatLng(), 6, {duration: 1.2});
      m.openPopup();
    };
  </script>
</body>
</html>
"""


class MapView(QWebEngineView):
    def __init__(self):
        super().__init__()
        self.setHtml(HTML, QUrl("https://spothole.app/"))

    def update_spots(self, spots):
        data = [{
            "id": s.id,
            "lat": s.lat, "lng": s.lng,
            "dx_call": s.dx_call, "freq": s.freq_khz,
            "mode": s.mode, "band": s.band,
            "spotter": s.spotter, "dxcc": s.dxcc,
            "color": s.color,
            "timestamp": s.timestamp.strftime("%H:%M UTC"),
        } for s in spots if s.has_coords]
        self.page().runJavaScript(f"window.updateSpots({json.dumps(data)});")

    def focus_on(self, spot_id, distance_html=None):
        self.page().runJavaScript(
            f"window.focusOn({json.dumps(spot_id)}, {json.dumps(distance_html)});"
        )
