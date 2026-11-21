"""Avvisi sonori e vocali per DX Cluster Map.

I suoni sono generati a runtime (nessun file da distribuire) e riprodotti con
QtMultimedia; la voce usa QtTextToSpeech e, se non disponibile, i comandi di
sintesi del sistema (espeak-ng/spd-say, say di macOS, SAPI di Windows).
"""
from __future__ import annotations

import logging
import math
import os
import shutil
import struct
import subprocess
import sys
import wave

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QSoundEffect

log = logging.getLogger(__name__)

CACHE_DIR = os.path.expanduser("~/.cache/DXClusterMap/sounds")


def _write_tone(path: str, segments, sample_rate: int = 44100):
    """Scrive un WAV mono 16 bit.

    ``segments`` è una lista di (frequenza_Hz, durata_s, ampiezza 0..1).
    Frequenza 0 = silenzio. Ogni segmento ha fade-in/out di 10 ms per evitare
    click.
    """
    frames = bytearray()
    for freq, duration, amp in segments:
        n = max(1, int(sample_rate * duration))
        fade = max(1, int(sample_rate * 0.010))
        for i in range(n):
            if freq <= 0:
                value = 0.0
            else:
                env = 1.0
                if i < fade:
                    env = i / fade
                elif i > n - fade:
                    env = max(0.0, (n - i) / fade)
                value = amp * env * math.sin(2.0 * math.pi * freq * i / sample_rate)
            frames += struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767))
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))


def _ensure_sounds():
    """Crea (una volta) i tre suoni distinti nella cache dell'app."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    sounds = {
        # alert generico: due note ascendenti, deciso ma breve
        "alert": ([(880, 0.16, 0.55), (0, 0.03, 0), (1320, 0.22, 0.55)], "alert.wav"),
        # qualcuno ti sta chiamando: tre note rapide e riconoscibili
        "calling": ([(1046, 0.11, 0.6), (0, 0.02, 0), (1318, 0.11, 0.6),
                     (0, 0.02, 0), (1568, 0.18, 0.6)], "calling.wav"),
        # nuovo DXCC: fanfara breve
        "new_country": ([(784, 0.12, 0.5), (1046, 0.12, 0.5), (1318, 0.20, 0.55)],
                        "new_country.wav"),
    }
    paths = {}
    for key, (segments, name) in sounds.items():
        path = os.path.join(CACHE_DIR, name)
        if not os.path.exists(path) or os.path.getsize(path) < 1000:
            try:
                _write_tone(path, segments)
            except OSError as exc:
                log.warning("Impossibile creare il suono %s: %s", name, exc)
                continue
        paths[key] = path
    return paths


class AlertSounds(QObject):
    """Riproduce suoni e voce secondo le preferenze salvate."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._paths = _ensure_sounds()
        self._effects = {}
        for key, path in self._paths.items():
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(path))
            effect.setLoopCount(1)
            self._effects[key] = effect
        self._volume = 0.7
        self._voice = None
        self._voice_checked = False

    # ---------- voce ----------
    def _init_voice(self):
        self._voice_checked = True
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
        except ImportError:
            return
        try:
            engines = QTextToSpeech.availableEngines()
            # "mock" è un motore finto (usato nei test headless): ignoriamolo
            real = [e for e in engines if e and e.lower() != "mock"]
            if not real:
                return
            self._voice = QTextToSpeech(real[0], self)
            try:
                self._voice.setRate(-0.05)
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001
            log.debug("Voce non disponibile: %s", exc)
            self._voice = None

    def speak(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        if not self._voice_checked:
            self._init_voice()
        if self._voice is not None:
            try:
                self._voice.stop()
                self._voice.say(text)
                return
            except Exception as exc:  # noqa: BLE001
                log.debug("Sintesi vocale Qt fallita: %s", exc)
                self._voice = None
        self._speak_external(text)

    @staticmethod
    def _speak_external(text: str):
        """Fallback con i comandi di sintesi del sistema, senza bloccare la GUI."""
        if sys.platform.startswith("win"):
            try:
                script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.Speak({text!r})"
                )
                subprocess.Popen(["powershell", "-NoProfile", "-Command", script],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                pass
            return
        cmd = None
        if sys.platform == "darwin" and shutil.which("say"):
            cmd = ["say", text]
        elif shutil.which("spd-say"):
            cmd = ["spd-say", "-w", "-r", "-10", text]
        elif shutil.which("espeak-ng"):
            cmd = ["espeak-ng", "-s", "165", text]
        elif shutil.which("espeak"):
            cmd = ["espeak", "-s", "165", text]
        if cmd:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except OSError:
                pass

    # ---------- suoni ----------
    def set_volume(self, value: float):
        """Volume 0.0 .. 1.0."""
        self._volume = max(0.0, min(1.0, float(value)))
        for effect in self._effects.values():
            effect.setVolume(self._volume)

    def play(self, kind: str = "alert"):
        effect = self._effects.get(kind) or self._effects.get("alert")
        if effect is None:
            return
        try:
            effect.setVolume(self._volume)
            if effect.status() == QSoundEffect.Error:
                self._play_external(self._paths.get(kind) or self._paths.get("alert"))
                return
            if effect.isPlaying():
                effect.stop()
            effect.play()
        except Exception as exc:  # noqa: BLE001
            log.debug("Riproduzione suono fallita: %s", exc)
            self._play_external(self._paths.get(kind) or self._paths.get("alert"))

    @staticmethod
    def _play_external(path):
        if not path:
            return
        cmd = None
        if sys.platform == "darwin" and shutil.which("afplay"):
            cmd = ["afplay", path]
        elif shutil.which("paplay"):
            cmd = ["paplay", path]
        elif shutil.which("aplay"):
            cmd = ["aplay", "-q", path]
        if cmd:
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            except OSError:
                pass

    def test(self, voice: bool = True):
        """Prova rapida dal dialogo impostazioni."""
        self.play("alert")
        if voice:
            self.speak("Avvisi sonori attivi")
