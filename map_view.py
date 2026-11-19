import base64
import json
import logging
import re

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtGui import QDesktopServices

log = logging.getLogger(__name__)

# Nominativi ammessi: base 2-7 caratteri con almeno una cifra, prefisso e
# suffisso opzionali con barra (es. 3A/IK1XYZ, IK1XYZ/P)
CALL_RE = re.compile(r"^(?:[A-Z0-9]{1,4}/)?[A-Z0-9]{2,7}(?:/[A-Z0-9]{1,4})?$")


def valid_call(call) -> bool:
    """True se il nominativo è plausibile e sicuro da usare in un URL/link."""
    if not call:
        return False
    text = str(call).strip().upper()
    if not CALL_RE.match(text):
        return False
    # richiede almeno una cifra (i veri nominativi le hanno sempre)
    return any(c.isdigit() for c in text)


class ExternalLinkPage(QWebEnginePage):
    """Pagina WebEngine bloccata: solo il caricamento iniziale è permesso;
    i click sui link vengono aperti nel browser di sistema."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        # Consenti solo la navigazione iniziale (setHtml)
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeRedirect:
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
  <script src="https://cdn.jsdelivr.net/npm/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>

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

    /* --- LEGENDA BANDE (12) --- */
    #legend {
      position: absolute; top: 10px; right: 10px; z-index: 1000;
      background: rgba(255,255,255,0.92); border: 1px solid #bbb;
      border-radius: 6px; padding: 6px 10px; font-size: 11px;
      box-shadow: 0 1px 5px rgba(0,0,0,0.25); display: none;
      max-height: 90%; overflow-y: auto;
    }
    #legend h4 { margin: 0 0 4px 0; font-size: 11px; color: #333; }
    #legend .row { display: flex; align-items: center; gap: 6px; line-height: 1.5; }
    #legend .swatch { display: inline-block; width: 10px; height: 10px;
                      border-radius: 50%; border: 1px solid #222; }
    #legend.dark { background: rgba(40,40,40,0.92); border-color: #555; }
    #legend.dark h4 { color: #ccc; }
    #legend.dark .row { color: #ccc; }

    /* --- POPUP SCURI (9) --- */
    body.dark-popups .leaflet-popup-content-wrapper,
    body.dark-popups .leaflet-popup-tip {
      background: #2b2b2b; color: #ddd;
    }
    body.dark-popups .leaflet-popup-content-wrapper .country { color: #ccc; }
    body.dark-popups .leaflet-popup-content-wrapper a.popup-link { color: #7fd7ff; }

    /* --- MARKER UTENTE (11) --- */
    .user-marker { font-size: 18px; text-align: center; line-height: 18px;
                   text-shadow: 0 0 3px #fff, 0 0 3px #fff; }
    .sat-marker { font-size: 20px; text-align: center; line-height: 20px;
                  text-shadow: 0 0 4px #000; }
    .sat-label { background: rgba(0,0,0,0.75); color: #fff; border: none;
                 border-radius: 3px; font-size: 11px; padding: 1px 5px;
                 box-shadow: none; font-weight: bold; }
    .sat-label::before { display: none; }
  </style>
</head>
<body>
  <div id="map"></div>
  <div id="legend"><h4>Bande</h4></div>
  <script>
    // ---------- SICUREZZA: utilità ----------
    // Canale dati sicuro: Python invia base64(JSON), qui decodifichiamo e facciamo JSON.parse.
    // Nessun dato di rete viene mai interpolato come codice JavaScript.
    window.__recv = function(fn, b64args) {
      try {
        var dec = new TextDecoder("utf-8");
        var args = b64args.map(function(b) {
          var bin = atob(b);
          var bytes = new Uint8Array(bin.length);
          for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          return JSON.parse(dec.decode(bytes));
        });
        var f = window[fn];
        if (typeof f === "function") f.apply(null, args);
      } catch (e) { console.error("recv error:", e); }
    };

    // Escape HTML: tutti i dati provenienti dall'esterno passano da qui prima di andare nei popup.
    function esc(s) {
      return String(s == null ? "" : s).replace(/[&<>"']/g, function(c) {
        return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
      });
    }

    // Link QRZ solo per nominativi plausibili (nessun URL costruito da dati non validati).
    var CALL_RE = /^(?:[A-Z0-9]{1,4}\\/)?[A-Z0-9]{2,7}(?:\\/[A-Z0-9]{1,4})?$/;
    function qrzLink(call) {
      var c = String(call || "").trim().toUpperCase();
      if (!CALL_RE.test(c) || !/[0-9]/.test(c)) return esc(c || "—");
      return '<a href="https://www.qrz.com/db/' + encodeURIComponent(c) + '" class="popup-link">' + esc(c) + '</a>';
    }

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
      var lg = document.getElementById('legend');
      if (lg) lg.className = isDark ? 'dark' : '';
      // Tema scuro anche per i popup di Leaflet (9)
      document.body.classList.toggle('dark-popups', !!isDark);
    };

    // --- LEGENDA BANDE (12) ---
    var BAND_COLORS_LEGEND = {
      "160m": "#8b0000", "80m": "#b22222", "60m": "#ff4500",
      "40m": "#ff8c00", "30m": "#ffd700", "20m": "#32cd32",
      "17m": "#00ced1", "15m": "#1e90ff", "12m": "#9370db",
      "10m": "#ff69b4", "6m": "#ff1493"
    };
    (function buildLegend() {
      var lg = document.getElementById('legend');
      for (var band in BAND_COLORS_LEGEND) {
        var row = document.createElement('div');
        row.className = 'row';
        row.innerHTML = '<span class="swatch" style="background:' + BAND_COLORS_LEGEND[band] + '"></span>' + band;
        lg.appendChild(row);
      }
    })();
    window.toggleLegend = function(show) {
      var lg = document.getElementById('legend');
      if (lg) lg.style.display = show ? 'block' : 'none';
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

    // --- ICONA UTENTE (11) ---
    let userMarker = null;

    window.setUserLocation = function(lat, lng) {
      userLat = lat; userLng = lng;
      if (lat === null || lng === null) {
        if (userMarker) { map.removeLayer(userMarker); userMarker = null; }
        return;
      }
      const icon = L.divIcon({ className: 'user-marker', html: '📡', iconSize: [18, 18], iconAnchor: [9, 9] });
      if (userMarker) {
        userMarker.setLatLng([lat, lng]);
      } else {
        userMarker = L.marker([lat, lng], { icon: icon, zIndexOffset: 1000 }).addTo(map);
        userMarker.bindPopup('<b>La tua stazione</b><small> (locator impostato)</small>');
      }
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

    // --- ROTTA VERSO TARGET (16) ---
    let routeLine = null;
    let routeMarker = null;

    window.showRoute = function(lat, lng) {
      if (routeLine) { map.removeLayer(routeLine); routeLine = null; }
      if (routeMarker) { map.removeLayer(routeMarker); routeMarker = null; }
      if (userLat === null || userLng === null) return false;

      const curvePoints = getGreatCirclePoints(userLat, userLng, lat, lng);
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
      if (currentSegment.length > 0) segments.push(currentSegment);

      routeLine = L.polyline(segments, {
        color: '#00a5ff', weight: 2, opacity: 0.9, dashArray: '1, 7'
      }).addTo(map);
      routeMarker = L.circleMarker([lat, lng], {
        radius: 7, weight: 2, color: '#00a5ff', fillColor: '#00a5ff', fillOpacity: 0.4
      }).addTo(map);
      routeMarker.bindPopup('<b>Target locator</b>');
      return true;
    };

    window.clearRoute = function() {
      if (routeLine) { map.removeLayer(routeLine); routeLine = null; }
      if (routeMarker) { map.removeLayer(routeMarker); routeMarker = null; }
    };

    // --- HEATMAP PER QUADRATO GRIGLIA (26) ---
    let heatLayer = null;
    let heatData = [];

    window.updateHeat = function(points) {
      heatData = points || [];
      if (heatLayer) heatLayer.setLatLngs(heatData);
    };

    window.toggleHeat = function(show) {
      try {
        if (typeof L.heatLayer !== 'function') return;
        if (show) {
          if (!heatLayer) {
            heatLayer = L.heatLayer(heatData, {
              radius: 40, blur: 22, maxZoom: 8, minOpacity: 0.35,
              gradient: { 0.2: '#2a6496', 0.5: '#ffaa00', 0.9: '#ff4500' }
            }).addTo(map);
          }
        } else if (heatLayer) {
          map.removeLayer(heatLayer);
          heatLayer = null;
        }
      } catch (e) { console.error("Errore heatmap:", e); }
    };

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
      let countryHtml = s.country ? '<div class="country">' + esc(s.country) + '</div>' : '';

      let dxLink = qrzLink(s.dx_call);
      let spotterCountry = s.spotter_country ? ' <small>' + esc(s.spotter_country) + '</small>' : '';
      let spotterLink = s.spotter ? 'Spotter: ' + qrzLink(s.spotter) + spotterCountry + '<br>' : '';

      let html =
        '<b>' + dxLink + '</b> (' + esc(s.band) + ')<br>' +
        esc(Number(s.freq).toFixed(1)) + ' kHz ' + esc(s.mode) + '<br>' +
        countryHtml +
        spotterLink +
        (s.dxcc ? 'DXCC: ' + esc(s.dxcc) + '<br>' : '') +
        (s.comment ? '<small>' + esc(s.comment) + '</small><br>' : '') +
        '<small>' + esc(s.timestamp) + '</small>';
      if (distHtml) {
        html += '<div class="dist">↔ ' + esc(distHtml) + '</div>';
      }
      return html;
    }

    window.updateSpots = function(spots) {
      clearPath();
      clusterGroup.clearLayers();
      spotDataById = {};
      spotMarkers = {};

      (spots || []).forEach(s => {
        if (s.lat == null || s.lng == null) return;
        spotDataById[s.id] = s;
        const m = L.circleMarker([s.lat, s.lng], Object.assign(
          { color: '#222', fillColor: esc(s.color) }, markerStyle(s)));
        m.bindPopup(buildPopup(s));
        clusterGroup.addLayer(m);
        spotMarkers[s.id] = m;
      });
      restyleMarkers();
    };

    // --- ETA' DEI MARKER (7): piu' lo spot e' fresco, piu' e' grande e visibile ---
    let spotMarkers = {};

    function markerStyle(s) {
      const ageMin = (Date.now() - (s.created || 0)) / 60000;
      const f = Math.max(0, Math.min(1, 1 - ageMin / 30)); // sfuma in 30 minuti
      return { radius: 4 + 5 * f, fillOpacity: 0.35 + 0.6 * f, weight: f > 0.85 ? 2 : 1 };
    }

    function restyleMarkers() {
      for (const id in spotMarkers) {
        const s = spotDataById[id];
        if (s) spotMarkers[id].setStyle(markerStyle(s));
      }
    }
    // Aggiorna il "fade" dei marker ogni 30 secondi
    setInterval(restyleMarkers, 30000);

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
    let pendingSatCenter = false;

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
      allTles = tles || [];
      selectedSatNames = selectedNames || [];
      // Alla selezione di nuovi satelliti la mappa si centra sul primo creato
      pendingSatCenter = selectedSatNames.length > 0;

      for (let key in satMarkers) {
        if (!selectedSatNames.includes(key)) {
          try { if (map.hasLayer(satMarkers[key])) map.removeLayer(satMarkers[key]); } catch (e) {}
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

              if (satMarkers[sat.name] && map.hasLayer(satMarkers[sat.name])) {
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
                satMarkers[sat.name].setPopupContent(`<b>${esc(sat.name)}</b><br>Alt: ${alt.toFixed(0)} km${extraInfo}`);
              } else {
                const icon = L.divIcon({ className: 'sat-marker', html: '🛰️', iconSize: [20, 20], iconAnchor: [10, 10] });
                const marker = L.marker([lat, lon], { icon: icon, zIndexOffset: 1000 }).addTo(map);
                marker.bindPopup(`<b>${esc(sat.name)}</b>`);
                // Etichetta permanente: il satellite si riconosce a colpo d'occhio
                marker.bindTooltip(sat.name, { permanent: true, direction: 'right', offset: [10, 0], className: 'sat-label' });
                marker.on('click', function() {
                  drawTrajectory(sat.name);
                });
                satMarkers[sat.name] = marker;
                // Alla (ri)selezione, centra la mappa sul satellite appena creato
                if (pendingSatCenter) {
                  map.panTo([lat, lon]);
                  pendingSatCenter = false;
                }
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
        self._apply_security_settings()
        self.setHtml(HTML, QUrl("https://spothole.app/"))

    def _apply_security_settings(self):
        """Rinforza il profilo del WebEngine: nessun accesso a file/contenuto
        locale, niente auditing link, niente pagine di errore."""
        s = self.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.HyperlinkAuditingEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, False)
        s.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, True)

    def createWindow(self, _type):
        # Blocca window.open / popup generati dalla pagina
        return None

    def contextMenuEvent(self, event):
        event.ignore()

    # ---------- Canale sicuro Python -> JS ----------
    @staticmethod
    def _b64(obj) -> str:
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def _run(self, fn: str, *args):
        """Chiama window.__recv(fn, [b64args]) invece di interpolare dati
        (potenzialmente ostili) dentro una stringa JavaScript."""
        payload = ",".join(json.dumps(self._b64(a)) for a in args)
        self.page().runJavaScript(
            f'if (window.__recv) window.__recv({json.dumps(fn)}, [{payload}]);'
        )

    # ---------- API pubbliche ----------
    def update_spots(self, spots):
        data = []
        for s in spots:
            if not s.has_coords:
                continue
            data.append({
                "id": s.id,
                "lat": float(s.lat),
                "lng": float(s.lng),
                "dx_call": str(s.dx_call or "")[:16],
                "freq": float(s.freq_khz),
                "mode": str(s.mode or "")[:16],
                "band": str(s.band or "")[:8],
                "spotter": str(s.spotter or "")[:16],
                "spotter_country": str(s.spotter_country or "")[:48] if getattr(s, "spotter_country", None) else None,
                "dxcc": str(s.dxcc or "")[:64] if s.dxcc else None,
                "country": str(s.country or "")[:64] if getattr(s, "country", None) else None,
                "comment": str(s.comment or "")[:120] if s.comment else None,
                "color": s.color if re.match(r"^#[0-9a-fA-F]{6}$", s.color or "") else "#888888",
                "timestamp": s.timestamp.strftime("%H:%M UTC"),
                # Età del marker (7): epoch ms di creazione dello spot
                "created": int(s.timestamp.timestamp() * 1000) if s.timestamp else 0,
            })
        self._run("updateSpots", data)

    def focus_on(self, spot_id):
        self._run("focusOn", str(spot_id))

    def set_user_location(self, lat, lng):
        self._run("setUserLocation", lat, lng)

    def set_distance_unit(self, unit):
        self._run("setDistanceUnit", "mi" if unit == "mi" else "km")

    def toggle_grayline(self, show):
        self._run("toggleGrayline", bool(show))

    def toggle_legend(self, show):
        """Mostra/nasconde la legenda delle bande sulla mappa (miglioramento 12)."""
        self._run("toggleLegend", bool(show))

    def show_route(self, lat, lng):
        """Rotta a grande cerchio verso il target locator (16)."""
        self._run("showRoute", float(lat), float(lng))

    def clear_route(self):
        self._run("clearRoute")

    def update_heat(self, points):
        """Punti heatmap: lista [lat, lng, peso] (26)."""
        self._run("updateHeat", points)

    def toggle_heat(self, show):
        self._run("toggleHeat", bool(show))

    def set_theme(self, is_dark):
        self._run("setTheme", bool(is_dark))

    def update_satellites(self, tles, selected_names):
        data = [{"name": str(t.name)[:64], "line1": t.line1, "line2": t.line2} for t in tles]
        self._run("updateSatellites", data, list(selected_names))
