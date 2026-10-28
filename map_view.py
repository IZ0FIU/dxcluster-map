import json
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView

HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@joergdietrich/leaflet.terminator@1.1.0/L.Terminator.min.js"></script>
  <style>
    html, body, #map { height: 100%; margin: 0; }
    .dist { margin-top: 6px; padding-top: 6px; border-top: 1px solid #ccc;
            color: #0a5; font-weight: bold; }
    .country { font-weight: bold; margin-bottom: 4px; color: #555; }
    .dark-popup .country { color: #ccc; }
  </style>
</head>
<body>
  <div id="map"></div>
  <script>
    const map = L.map('map', {worldCopyJump: true}).setView([30, 10], 2);

    // --- LAYER MAPPE ---
    const lightLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 10, attribution: '&copy; OpenStreetMap'
    });
    
    const darkLayer = L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 10, attribution: '&copy; Esri &mdash; Esri, DeLorme, NAVTEQ'
    });
    
    let currentLayer = lightLayer;
    lightLayer.addTo(map);

    window.setTheme = function(isDark) {
      if (isDark && currentLayer !== darkLayer) {
        map.removeLayer(currentLayer);
        darkLayer.addTo(map);
        currentLayer = darkLayer;
      } else if (!isDark && currentLayer !== lightLayer) {
        map.removeLayer(currentLayer);
        lightLayer.addTo(map);
        currentLayer = lightLayer;
      }
    };

    // --- GRAYLINE ---
    let terminator = null;
    window.toggleGrayline = function(show) {
      try {
        if (typeof L.terminator !== 'function') return;
        if (show) {
          if (!terminator) {
            terminator = L.terminator().addTo(map);
            if (terminator.bringToFront) terminator.bringToFront();
            setInterval(() => { if (terminator) terminator.setTime(); }, 60000);
          } else {
            if (!map.hasLayer(terminator)) {
              terminator.addTo(map);
              if (terminator.bringToFront) terminator.bringToFront();
            }
          }
        } else {
          if (terminator && map.hasLayer(terminator)) map.removeLayer(terminator);
        }
      } catch (e) { console.error("Errore Grayline:", e); }
    };

    // --- GEOLOCALIZZAZIONE UTENTE ---
    let userLat = null;
    let userLng = null;
    window.setUserLocation = function(lat, lng) {
      userLat = lat;
      userLng = lng;
    };

    function getDistanceHtml(s) {
      if (userLat === null || userLng === null) return null;
      const R = 6371.0;
      const phi1 = userLat * Math.PI / 180;
      const phi2 = s.lat * Math.PI / 180;
      const dphi = (s.lat - userLat) * Math.PI / 180;
      const dlambda = (s.lng - userLng) * Math.PI / 180;
      const a = Math.sin(dphi/2)**2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda/2)**2;
      const dist = 2 * R * Math.asin(Math.sqrt(a));
      
      const y = Math.sin(dlambda) * Math.cos(phi2);
      const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dlambda);
      const az = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
      return `${dist.toFixed(0)} km — az ${az.toFixed(0)}°`;
    }

    // --- MARKER E POPUP ---
    let markers = [];
    let markersById = {};
    let spotDataById = {};

    function buildPopup(s) {
      let distHtml = getDistanceHtml(s);
      
      let countryHtml = '';
      if (s.country) {
        countryHtml = '<div class="country">' + s.country + '</div>';
      }

      let html =
        '<b>' + s.dx_call + '</b> (' + s.band + ')<br>' +
        s.freq.toFixed(1) + ' kHz ' + s.mode + '<br>' +
        countryHtml +
        'Spotter: ' + s.spotter + '<br>' +
        (s.dxcc ? 'DXCC: ' + s.dxcc + '<br>' : '') +
        '<small>' + s.timestamp + '</small>';
      if (distHtml) {
        html += '<div class="dist">↔ ' + distHtml + '</div>';
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
        
        m.bindPopup(buildPopup(s));
        
        markers.push(m);
        markersById[s.id] = m;
      });
    };

    window.focusOn = function(id) {
      const m = markersById[id];
      const s = spotDataById[id];
      if (!m || !s) return;
      m.setPopupContent(buildPopup(s));
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
            "country": getattr(s, 'country', None),
            "color": s.color,
            "timestamp": s.timestamp.strftime("%H:%M UTC"),
        } for s in spots if s.has_coords]
        self.page().runJavaScript(f"window.updateSpots({json.dumps(data)});")

    def focus_on(self, spot_id):
        self.page().runJavaScript(f"window.focusOn({json.dumps(spot_id)});")

    def set_user_location(self, lat, lng):
        lat_str = "null" if lat is None else str(lat)
        lng_str = "null" if lng is None else str(lng)
        self.page().runJavaScript(f"window.setUserLocation({lat_str}, {lng_str});")

    def toggle_grayline(self, show):
        self.page().runJavaScript(
            f"if (typeof window.toggleGrayline === 'function') window.toggleGrayline({json.dumps(show)});"
        )
        
    def set_theme(self, is_dark):
        self.page().runJavaScript(f"window.setTheme({json.dumps(is_dark)});")
