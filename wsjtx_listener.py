"""Listener UDP per WSJT-X.

WSJT-X invia datagrammi UDP (protocollo documentato: Qt QDataStream, big-endian)
all'indirizzo configurato in Settings > Reporting (default 127.0.0.1:2237).
Leggiamo i messaggi di tipo Status (qtype 0) e Decode (qtype 1) e trasformiamo
le decodifiche in Spot per la mappa.

Geolocalizzazione (in ordine di affidabilità):
  1. grid nel testo del messaggio (es. "CQ IK1XYZ JN45")
  2. grid dello spotter derivata dal campo de_grid dello Status (per il tooltip)
"""
import logging
import re
import struct
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QUdpSocket, QHostAddress, QAbstractSocket

from models import Spot
from geo import maidenhead_to_latlon
from dxcc_table import lookup_dxcc

log = logging.getLogger(__name__)

# Magic reale del protocollo WSJT-X (verificato su datagrammi reali 3.0.2)
MAGIC = 0xADBCCBDA

# Nominativo plausibile: parte opzionale di prefisso ("3A/"), base 2-7
# caratteri contenente almeno una cifra, suffisso opzionale ("/P", "/M").
CALL_RE = re.compile(r"^(?:[A-Z0-9]{1,4}/)?[A-Z0-9]{2,7}(?:/[A-Z0-9]{1,4})?$")


def _looks_like_call(token: str) -> bool:
    """Nominativo valido: match della regex, almeno una cifra e non un locator."""
    if not CALL_RE.match(token) or not any(c.isdigit() for c in token):
        return False
    return GRID_RE.fullmatch(token) is None
# Locator Maidenhead nel testo del messaggio
GRID_RE = re.compile(r"\b([A-R]{2}[0-9]{2}(?:[A-X]{2})?)\b")


class _QtDataStreamReader:
    """Lettore QDataStream big-endian. Le QString possono essere serializzate
    in due modi a seconda della Qt del mittente:
      - Qt6 (WSJT-X 3.0.2+): quint32 lunghezza in BYTE + UTF-8
      - Qt5 (WSJT-X 2.x):    quint32 lunghezza in unità UTF-16 + UTF-16-BE
    Il primo byte del contenuto distingue i due casi: in UTF-16-BE i testi
    ASCII/comuni iniziano con 0x00 (non capita in UTF-8)."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise EOFError("datagramma incompleto")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u32(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self._take(4))[0]

    def f64(self) -> float:
        return struct.unpack(">d", self._take(8))[0]

    def bool_(self) -> bool:
        return self._take(1)[0] != 0

    def string(self) -> str:
        length = self.u32()
        if length == 0xFFFFFFFF:
            return ""
        if length == 0 or length > self.remaining():
            raise EOFError("stringa oltre il datagramma")
        if self.data[self.pos] == 0:
            # Qt5: length = unità UTF-16, contenuto big-endian
            raw = self._take(length * 2)
            try:
                return raw.decode("utf-16-be")
            except UnicodeDecodeError:
                return raw.decode("utf-16-be", errors="replace")
        # Qt6: length = byte UTF-8
        raw = self._take(length)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


class WSJTXListener(QObject):
    """Riceve i datagrammi di WSJT-X ed emette Spot pronti per la mappa."""

    decode_received = Signal(object)  # Spot
    status_received = Signal(dict)    # info di stato (dial, de_call, de_grid)
    listening_changed = Signal(bool, str)  # (ok, messaggio errore/eventuale)

    DEFAULT_PORT = 2238

    def __init__(self, port: int = DEFAULT_PORT, relay_targets=None):
        super().__init__()
        self.dial_hz = None
        self.de_call = ""
        self.de_grid = ""
        self.decode_count = 0
        self.datagram_count = 0
        self.forwarded_count = 0
        self.tx_mode = ""  # dallo Status: serve quando Decode manda mode='~'
        self.port = port
        # Ponte UDP: copie byte-per-byte di ogni datagramma verso questi
        # destinatari [(host, porta), ...] (es. WavelogGate spostato su 2238)
        self.relay_targets = list(relay_targets or [])
        self._relay_socket = QUdpSocket(self) if self.relay_targets else None

        self.socket = QUdpSocket(self)
        self.socket.readyRead.connect(self._read_ready)
        ok = self.socket.bind(
            QHostAddress.AnyIPv4, port,
            QAbstractSocket.BindFlag.ShareAddress | QAbstractSocket.BindFlag.ReuseAddressHint
        )
        if ok:
            log.info("WSJT-X listener attivo su UDP :%d", port)
            # Supporto WSJT-X "Group Server" (multicast): gruppo default 239.255.0.0
            for group in ("239.255.0.0",):
                if not self.socket.joinMulticastGroup(QHostAddress(group)):
                    log.debug("join multicast %s fallita (non bloccante)", group)
            self.listening_changed.emit(True, "")
        else:
            err = self.socket.errorString() or "porta in uso"
            log.warning("WSJT-X listener: BIND FALLITO su :%d (%s)", port, err)
            self.listening_changed.emit(False, err)

    def stop(self):
        self.socket.close()

    # ---------- ricezione ----------
    def _read_ready(self):
        while self.socket.hasPendingDatagrams():
            size = self.socket.pendingDatagramSize()
            if size <= 0:
                break
            data, _host, _port = self.socket.readDatagram(size)
            self.datagram_count += 1
            raw = bytes(data)
            self._relay(raw)
            # readDatagram ritorna un QByteArray PySide: convertiamolo in bytes
            try:
                self._parse(raw)
            except (EOFError, struct.error) as e:
                log.debug("Datagramma WSJT-X ignorato (%s)", e)
            except Exception:
                log.exception("Errore inatteso parsing WSJT-X")

    def _relay(self, data: bytes):
        """Inoltra il datagramma inalterato a tutti i destinatari configurati."""
        if not self._relay_socket:
            return
        for host, rport in self.relay_targets:
            try:
                self._relay_socket.writeDatagram(data, QHostAddress(host), rport)
                self.forwarded_count += 1
            except Exception as e:
                log.warning("Inoltro verso %s:%d fallito: %s", host, rport, e)

    def _parse(self, data: bytes):
        r = _QtDataStreamReader(data)
        if r.u32() != MAGIC:
            return
        r.u32()                  # schema number
        qtype = r.u32()
        # Tipi reali del protocollo WSJT-X (verificati su datagrammi 3.0.2):
        # 0=Heartbeat, 1=Status, 2=Decode, 3=Clear, 5=Logged ADIF, ...
        if qtype == 1:
            self._parse_status(r)
        elif qtype == 2:
            self._parse_decode(r)
        # Heartbeat (0), Clear (3), Logged (5)... ignorati

    def _parse_status(self, r: _QtDataStreamReader):
        """Status reale (schema verificato): id, [extra u32=0], dial_hz,
        mode, dx_call, report, tx_mode, 3 bool, rx_df, tx_df, de_call, de_grid.
        Alcune versioni non hanno il campo extra: prova entrambe le letture
        e valida il dial (tra 100 kHz e 30 GHz)."""
        backup_pos = r.pos
        ok = False
        for with_lead in (True, False):
            r.pos = backup_pos
            try:
                r.string()               # id
                if with_lead:
                    r.u32()              # campo extra presente nel 3.0.2
                dial = r.u32()           # dial frequency (Hz)
                if not (100_000 <= dial <= 30_000_000_000):
                    continue
                self.tx_mode = r.string()
                r.string()               # dx_call (selezionato nella finestra)
                r.string()               # report
                r.string()               # tx_mode (ripetuto)
                r.bool_(); r.bool_(); r.bool_()   # tx_enabled, transmitting, decoding
                r.i32()                  # rx_df
                r.i32()                  # tx_df
                self.dial_hz = dial
                self.de_call = r.string() or self.de_call
                self.de_grid = r.string() or self.de_grid
                ok = True
                break
            except (EOFError, struct.error):
                continue
        if not ok:
            raise EOFError("Status non riconosciuto")
        self.status_received.emit({
            "dial_hz": self.dial_hz,
            "de_call": self.de_call,
            "de_grid": self.de_grid,
            "datagrams": self.datagram_count,
            "decodes": self.decode_count,
        })

    def _parse_decode(self, r: _QtDataStreamReader):
        """Decode reale (schema verificato): flag u8, time u32, snr i32,
        dt f64, df u32, mode, message, [low_confidence...].
        Il mode per FT8/FT4 arriva come '~': usiamo il tx_mode dello Status."""
        backup_pos = r.pos
        snr = None
        mode = ""
        message = ""
        for variant in (1, 2):   # 1 = un flag byte (3.0.2), 2 = due bool (2.x)
            r.pos = backup_pos
            snr = None
            mode = ""
            message = ""
            try:
                r.string()           # id ("WSJT-X") presente in ogni messaggio
                for _ in range(variant):
                    r.bool_()
                r.u32()              # time (ms da mezzanotte)
                snr = r.i32()        # snr (dB)
                r.f64()              # delta_time
                delta_freq = r.u32() # delta_frequency (Hz)
                if not 0 <= delta_freq <= 10_000:
                    continue
                mode = r.string()    # es. FT8/FT4 — o '~'
                message = r.string() # testo della decodifica
                if mode == "~":
                    mode = self.tx_mode or "FT8"
                break
            except (EOFError, struct.error):
                continue
        if snr is None or not message or self.dial_hz is None:
            return

        freq_khz = (self.dial_hz + delta_freq) / 1000.0
        dx_call, dx_grid = self._extract_call_and_grid(message)
        if not dx_call:
            return

        # Geolocalizzazione (in ordine di affidabilità):
        # 1. locator nel testo del messaggio  2. centro dell'entità DXCC
        lat = lng = None
        country = None
        approx = False
        if dx_grid:
            try:
                lat, lng = maidenhead_to_latlon(dx_grid)
            except ValueError:
                lat = lng = None
        if lat is None:
            hit = lookup_dxcc(dx_call)
            if hit:
                lat, lng, country = hit
                approx = True

        self.decode_count += 1
        comment = f"SNR {snr:+d} — {message[:100]}"
        if approx:
            comment += " (posizione DXCC)"
        spot = Spot(
            spotter=self.de_call or "WSJTX",
            dx_call=dx_call[:16],
            freq_khz=freq_khz,
            mode=mode[:16],
            comment=f"SNR {snr:+d} — {message[:100]}",
            timestamp=datetime.now(timezone.utc),
            lat=lat,
            lng=lng,
            country=country,
            source="wsjtx",
        )
        self.decode_received.emit(spot)

    @staticmethod
    def _extract_call_and_grid(message: str):
        """Estrae il nominativo DX e l'eventuale locator dal testo della
        decodifica. I messaggi tipici sono:
          'CQ IK1XYZ JN45' / 'CQ DX 3A/ABC JM45' / 'IK1XYZ W1ABC R-05'
        Il primo nominativo valido dopo gli eventuali token CQ/DE è il DX.
        """
        tokens = message.strip().split()
        dx_call = None
        skipped = set()
        # salta i token CQ/CQDX/CQXXX/DE della parte iniziale
        while tokens:
            head = tokens[0].upper().rstrip("*")
            if head in ("CQ", "DE", "QRZ") or head.startswith("CQ"):
                skipped.add(head)
                tokens = tokens[1:]
                continue
            break
        for tok in tokens:
            t = tok.upper().rstrip("*.,")
            if t not in skipped and _looks_like_call(t):
                dx_call = t
                break

        m = None
        for cand in GRID_RE.finditer(message):
            # "RR73", "RRR", "73" sono codici FT8 di fine QSO, non locator
            tok = cand.group(1).upper()
            if tok in ("RR73", "RRR", "73", "RR", "R73"):
                continue
            m = cand
            break
        grid = m.group(1) if m else None
        # evita di confondere un locator col nominativo quando è subito dopo
        if grid and grid.upper() == (dx_call or "").upper():
            grid = None
        return dx_call, grid
