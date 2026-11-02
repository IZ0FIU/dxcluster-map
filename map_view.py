import json
from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtGui import QDesktopServices

class ExternalLinkPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.css" />
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.Default.css" />
  
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.4.1/dist/leaflet.markercluster.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@joergdietrich/leaflet.terminator@1.1.0/L.Terminator.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/satellite.js@5.0.0/dist/satellite.min.js"></script>
  
  <style>
    html, body, #map { height: 100%; margin: 0; }
    
    /* FIX PER LE LINEE DEI TASSELLI (TILE SEAMS) */
    .leaflet-tile {
      width: 256.5px !important;
      height: 256.5px !important;
    }
    
    .dist { margin-top: 6px; padding-top: 6px; border-top: 1px solid #ccc;
            color: #0a5; font-weight: bold; }
    .country { font-weight: bold; margin-bottom: 4px; color: #555; }
    .dark-popup .country { color: #ccc; }
    .popup-link { color: inherit; text-decoration: underline; font-weight: bold; }
    .popup-link:hover { text-decoration: none; color: #0a5; }
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
        map.removeLayer(currentLayer); darkLayer.addTo(map); currentLayer = darkLayer;
      } else if (!isDark && currentLayer !== lightLayer) {
        map.removeLayer(currentLayer); lightLayer.addTo(map); currentLayer = lightLayer;
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

    // --- GEOLOCALIZZAZIONE E PERCORSO ---
    let userLat = null;
    let userLng = null;
    let distanceUnit = "km";
    let pathLine = null;

    window.setUserLocation = function(lat, lng) {
      userLat = lat; userLng = lng;
    };

    window.setDistanceUnit = function(unit) {
      distanceUnit = unit;
    };

    function clearPath() {
      if (pathLine) {
        map.removeLayer(pathLine);
        pathLine = null;
      }
    }

    function getGreatCirclePoints(lat1, lon1, lat2, lon2, numPoints = 64) {
      const d2r = Math.PI / 180;
      const r2d = 180 / Math.PI;
      const phi1 = lat1 * d2r;
      const lambda1 = lon1 * d2r;
      const phi2 = lat2 * d2r;
      const lambda2 = lon2 * d2r;

      const d = 2 * Math.asin(Math.sqrt(Math.pow(Math.sin((phi1 - phi2) / 2), 2) +
                  Math.cos(phi1) * Math.cos(phi2) * Math.pow(Math.sin((lambda1 - lambda2) / 2), 2)));
      
      if (d === 0) return [[lat1, lon1], [lat2, lon2]];

      const points = [];
      for (let i = 0; i <= numPoints; i++) {
        const f = i / numPoints;
        const A = Math.sin((1 - f) * d) / Math.sin(d);
        const B = Math.sin(f * d) / Math.sin(d);
        const x = A * Math.cos(phi1) * Math.cos(lambda1) + B * Math.cos(phi2) * Math.cos(lambda2);
        const y = A * Math.cos(phi1) * Math.sin(lambda1) + B * Math.cos(phi2) * Math.sin(lambda2);
        const z = A * Math.sin(phi1) + B * Math.sin(phi2);
        const lat = Math.atan2(z, Math.sqrt(Math.pow(x, 2) + Math.pow(y, 2)));
        const lon = Math.atan2(y, x);
        points.push([lat * r2d, lon * r2d]);
      }
      return points;
    }

    function drawPath(targetLat, targetLng) {
      clearPath();
      if (userLat === null || userLng === null) return;
      
      const curvePoints = getGreatCirclePoints(userLat, userLng, targetLat, targetLng);
      
      // Segmentazione per evitare la linea orizzontale all'antimeridiano
      const segments = [];
      let currentSegment = [];
      
      for (let i = 0; i < curvePoints.length; i++) {
        const point = curvePoints[i];
        if (currentSegment.length > 0) {
          const lastLon = currentSegment[currentSegment.length - 1][1];
          if (Math.abs(point[1] - lastLon) > 180) {
            segments.push(currentSegment);
            currentSegment = [];
          }
        }
        currentSegment.push(point);
      }
      if (currentSegment.length > 0) {
        segments.push(currentSegment);
      }

      pathLine = L.polyline(segments, {
        color: '#ff8c00', weight: 2, opacity: 0.8, dashArray: '5, 5'
      }).addTo(map);
    }

    function getDistanceHtml(s) {
      if (userLat === null || userLng === null) return null;
      const R = 6371.0;
      const phi1 = userLat * Math.PI / 180;
      const phi2 = s.lat * Math.PI / 180;
      const dphi = (s.lat - userLat) * Math.PI / 180;
      const dlambda = (s.lng - userLng) * Math.PI / 180;
      const a = Math.sin(dphi/2)**2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlambda/2)**2;
      let dist = 2 * R * Math.asin(Math.sqrt(a));
      
      const y = Math.sin(dlambda) * Math.cos(phi2);
      const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dlambda);
      const az = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
      
      let unitStr = "km";
      if (distanceUnit === "mi") {
        dist = dist * 0.621371;
        unitStr = "mi";
      }
      return `${dist.toFixed(0)} ${unitStr} — az ${az.toFixed(0)}°`;
    }

    // --- MARKER E CLUSTER ---
    const clusterGroup = L.markerClusterGroup({
      maxClusterRadius: 50, spiderfyOnMaxZoom: true, showCoverageOnHover: false, zoomToBoundsOnClick: true
    });
    map.addLayer(clusterGroup);

    let spotDataById = {};

    function buildPopup(s) {
      let distHtml = getDistanceHtml(s);
      let countryHtml = s.country ? '<div class="country">' + s.country + '</div>' : '';
      
      let dxLink = '<a href="https://www.qrz.com/db/' + s.dx_call + '" class="popup-link">' + s.dx_call + '</a>';
      let spotterLink = s.spotter ? '<a href="https://www.qrz.com/db/' + s.spotter + '" class="popup-link">' + s.spotter + '</a>' : '';

      let html =
        '<b>' + dxLink + '</b> (' + s.band + ')<br>' +
        s.freq.toFixed(1) + ' kHz ' + s.mode + '<br>' +
        countryHtml +
        'Spotter: ' + spotterLink + '<br>' +
        (s.dxcc ? 'DXCC: ' + s.dxcc + '<br>' : '') +
        '<small>' + s.timestamp + '</small>';
      if (distHtml) {
        html += '<div class="dist">↔ ' + distHtml + '</div>';
      }
      return html;
    }

    window.updateSpots = function(spots) {
      clearPath();
      clusterGroup.clearLayers();
      spotDataById = {};

      spots.forEach(s => {
        if (s.lat == null || s.lng == null) return;
        spotDataById[s.id] = s;
        const m = L.circleMarker([s.lat, s.lng], {
          radius: 6, weight: 1, color: '#222', fillColor: s.color, fillOpacity: 0.85
        });
        m.bindPopup(buildPopup(s));
        clusterGroup.addLayer(m);
      });
    };

    window.focusOn = function(id) {
      const s = spotDataById[id];
      if (!s) return;
      
      let targetMarker = null;
      clusterGroup.eachLayer(function(marker) {
        if (marker.getLatLng().lat === s.lat && marker.getLatLng().lng === s.lng) {
          targetMarker = marker;
        }
      });
      
      if (targetMarker) {
        clusterGroup.zoomToShowLayer(targetMarker, function() {
          targetMarker.openPopup();
        });
        drawPath(s.lat, s.lng); 
      }
    };

    // --- SATELLITI ---
    let allTles = [];
    let selectedSatNames = [];
    let satMarkers = {};
    let satInterval = null;
    let trajectoryLine = null;

    function clearTrajectory() {
      if (trajectoryLine) {
        map.removeLayer(trajectoryLine);
        trajectoryLine = null;
      }
    }

    function drawTrajectory(satName) {
      clearTrajectory();
      const sat = allTles.find(t => t.name === satName);
      if (!sat) return;

      const satrec = satellite.twoline2satrec(sat.line1, sat.line2);
      const segments = []; 
      let currentSegment = [];
      const now = new Date();
      const stepMinutes = 1;
      const totalMinutes = 90;

      for (let i = 0; i <= totalMinutes; i += stepMinutes) {
        const time = new Date(now.getTime() + i * 60000);
        try {
          const posVel = satellite.propagate(satrec, time);
          if (posVel.position) {
            const gmst = satellite.gstime(time);
            const geodetic = satellite.eciToGeodetic(posVel.position, gmst);
            const lat = satellite.degreesLat(geodetic.latitude);
            const lon = satellite.degreesLong(geodetic.longitude);

            if (currentSegment.length > 0) {
              const lastLon = currentSegment[currentSegment.length - 1][1];
              if (Math.abs(lon - lastLon) > 180) {
                segments.push(currentSegment);
                currentSegment = [];
              }
            }
            currentSegment.push([lat, lon]);
          }
        } catch (e) {}
      }
      if (currentSegment.length > 0) {
        segments.push(currentSegment);
      }

      if (segments.length > 0) {
        trajectoryLine = L.polyline(segments, {
          color: '#ffaa00', weight: 2, opacity: 0.7, dashArray: '5, 5'
        }).addTo(map);
      }
    }

    window.updateSatellites = function(tles, selectedNames) {
      allTles = tles;
      selectedSatNames = selectedNames;

      for (let key in satMarkers) {
        if (!selectedSatNames.includes(key)) {
          map.removeLayer(satMarkers[key]);
          delete satMarkers[key];
        }
      }
      clearTrajectory();

      if (satInterval) clearInterval(satInterval);
      if (allTles.length === 0) return;

      const updatePositions = () => {
        const now = new Date();
        allTles.forEach(sat => {
          if (!selectedSatNames.includes(sat.name)) return;

          try {
            const satrec = satellite.twoline2satrec(sat.line1, sat.line2);
            const positionAndVelocity = satellite.propagate(satrec, now);
            const positionEci = positionAndVelocity.position;
            
            if (positionEci) {
              const gmst = satellite.gstime(now);
              const positionGd = satellite.eciToGeodetic(positionEci, gmst);
              const lat = satellite.degreesLat(positionGd.latitude);
              const lon = satellite.degreesLong(positionGd.longitude);
              const alt = positionGd.height;

              if (satMarkers[sat.name]) {
                satMarkers[sat.name].setLatLng([lat, lon]);
                
                let extraInfo = "";
                if (userLat !== null && userLng !== null) {
                  const observerGd = {
                    latitude: satellite.degreesToRadians(userLat),
                    longitude: satellite.degreesToRadians(userLng),
                    height: 0
                  };
                  const lookAngles = satellite.ecfToLookAngles(observerGd, satellite.eciToEcf(positionEci, gmst));
                  const elev = satellite.radiansToDegrees(lookAngles.elevation);
                  const az = satellite.radiansToDegrees(lookAngles.azimuth);
                  extraInfo = `<br><b>El:</b> ${elev.toFixed(1)}° <b>Az:</b> ${az.toFixed(1)}°`;
                }
                satMarkers[sat.name].setPopupContent(`<b>${sat.name}</b><br>Alt: ${alt.toFixed(0)} km${extraInfo}`);
              } else {
                const marker = L.circleMarker([lat, lon], {
                  radius: 5, weight: 2, color: '#fff', fillColor: '#ff00ff', fillOpacity: 1
                }).addTo(map);
                marker.bindPopup(`<b>${sat.name}</b>`);
                marker.on('click', function() {
                  drawTrajectory(sat.name);
                });
                satMarkers[sat.name] = marker;
              }
            }
          } catch (e) {}
        });
      };

      updatePositions();
      satInterval = setInterval(updatePositions, 5000);
    };
  </script>
</body>
</html>
"""

class MapView(QWebEngineView):
    def __init__(self):
        super().__init__()
        self.setPage(ExternalLinkPage(self))
        self.setHtml(HTML, QUrl("https://spothole.app/"))

    def contextMenuEvent(self, event):
        event.ignore()

    def update_spots(self, spots):
        data = [{
            "id": s.id, "lat": s.lat, "lng": s.lng, "dx_call": s.dx_call, 
            "freq": s.freq_khz, "mode": s.mode, "band": s.band,
            "spotter": s.spotter, "dxcc": s.dxcc,
            "country": getattr(s, 'country', None),
            "color": s.color, "timestamp": s.timestamp.strftime("%H:%M UTC"),
        } for s in spots if s.has_coords]
        self.page().runJavaScript(f"window.updateSpots({json.dumps(data)});")

    def focus_on(self, spot_id):
        self.page().runJavaScript(f"window.focusOn({json.dumps(spot_id)});")

    def set_user_location(self, lat, lng):
        lat_str = "null" if lat is None else str(lat)
        lng_str = "null" if lng is None else str(lng)
        self.page().runJavaScript(f"window.setUserLocation({lat_str}, {lng_str});")

    def set_distance_unit(self, unit):
        self.page().runJavaScript(f"window.setDistanceUnit({json.dumps(unit)});")

    def toggle_grayline(self, show):
        self.page().runJavaScript(
            f"if (typeof window.toggleGrayline === 'function') window.toggleGrayline({json.dumps(show)});"
        )
        
    def set_theme(self, is_dark):
        self.page().runJavaScript(f"window.setTheme({json.dumps(is_dark)});")

    def update_satellites(self, tles, selected_names):
        data = [{"name": t.name, "line1": t.line1, "line2": t.line2} for t in tles]
        self.page().runJavaScript(f"window.updateSatellites({json.dumps(data)}, {json.dumps(list(selected_names))});")
