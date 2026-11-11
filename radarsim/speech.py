"""Real spoken radio traffic.

Text is synthesised with eSpeak NG (bundled by the `espeakng-loader` pip
package, so no system install is needed) on a background thread, then given
a communications-radio character: 300-2800 Hz band-pass, pre-emphasis and
compression. Each clip is kept as an analytic (complex) signal so the HF
receiver can apply a true SSB frequency shift or sideband inversion to it.

If the package is missing the radios fall back to captions plus the old
speech-shaped noise, and the status bar says so.
"""
import ctypes
import queue
import re
import threading
import zlib
import numpy as np

SR = 22050
# (espeak voice, words per minute, pitch 0-99) - one per station, chosen by name
VOICES = [("en-gb-x-rp+m3", 150, 42), ("en+m1", 146, 50), ("en-us+m5", 152, 38), ("en-gb-scotland+m2", 146, 48),
          ("en+m7", 150, 34), ("en-us+m4", 156, 55), ("en-gb-x-rp+m6", 144, 46), ("en+f2", 150, 52),
          ("en-us+m2", 148, 44), ("en-gb-x-rp+f3", 148, 50)]
FIXED = {"PENHALE COASTGUARD": 0, "PENHALE INFORMATION": 9, "NORTHSEA RADIO": 7, "ATLANTIC WX": 2,
         "AEGEAN RADIO": 4, "RESCUE 193": 5, "NORDIC STAR": 3, "PENHALE COASTGUARD MF": 0}
SPELL = {"MMSI": "M M S I", "QNH": "Q N H", "MV": "M V", "UTC": "U T C", "D-S-C": "D S C", "SART": "sart",
         "EPIRB": "ee perb", "SECURITE": "say cure e tay", "FV": "F V", "WX": "weather"}
DIGIT = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "niner"]


def spoken(text):
    """Turn console-style capitals into something a synthesiser reads the
    way an operator would say it: figures digit by digit, call signs spelt."""
    out = []
    for tok in re.sub(r"\[.*?\]", " ", text).split():
        core = tok.strip(".,:;()")
        tail = tok[len(tok.rstrip(".,:;")):]
        if core in SPELL:
            w = SPELL[core]
        elif core.isdigit():
            w = " ".join(DIGIT[int(c)] for c in core)
        elif any(c.isdigit() for c in core) and any(c.isalpha() for c in core):
            w = " ".join(DIGIT[int(c)] if c.isdigit() else c for c in core if c.isalnum())
        else:
            w = core.lower()
        out.append(w + tail)
    return " ".join(out)


def radio_filter(x):
    """Band-limit and compress like a communications transmitter; returns the
    analytic signal (real part = audio)."""
    n = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1.0 / SR)
    g = 1.0 / (1.0 + (300.0 / np.maximum(f, 1.0)) ** 6) / (1.0 + (f / 2800.0) ** 10)
    g *= np.sqrt(np.clip(f / 900.0, 0.35, 2.2))                 # pre-emphasis: lifts consonants
    y = np.fft.irfft(X * g, n)
    y /= (np.percentile(np.abs(y), 99.5) + 1e-9)
    y = np.tanh(1.6 * y)                                        # speech compressor / limiter
    Y = np.fft.fft(y)
    ff = np.fft.fftfreq(n, 1.0 / SR)
    Y[ff < 0] = 0
    Y[(ff > 0)] *= 2
    Y[np.abs(ff) > 3000] = 0
    z = np.fft.ifft(Y)
    return (z / (np.abs(z.real).max() + 1e-9) * 0.8).astype(np.complex64)


class Speech:
    def __init__(self):
        self.ok, self.error = False, ""
        self.clips, self.pending = {}, set()
        self.q = queue.Queue()
        try:
            import espeakng_loader
            self._lib_path = espeakng_loader.get_library_path()
            self._data = espeakng_loader.get_data_path()
            self.ok = True
        except Exception as e:                                  # package not installed
            self.error = "speech synthesis unavailable (pip install espeakng-loader): %s" % e
            return
        threading.Thread(target=self._worker, daemon=True).start()

    @staticmethod
    def voice_for(name):
        if name in FIXED:
            return FIXED[name]
        return zlib.crc32(name.encode()) % len(VOICES)

    def request(self, text, who):
        k = (text, self.voice_for(who))
        if self.ok and k not in self.clips and k not in self.pending:
            self.pending.add(k)
            self.q.put(k)

    def get(self, text, who):
        """Analytic clip (complex64) or None if not synthesised yet."""
        k = (text, self.voice_for(who))
        c = self.clips.get(k)
        if c is None:
            self.request(text, who)
        return c

    def wait(self, timeout=20.0):
        import time
        t = time.time()
        while self.ok and self.pending and time.time() - t < timeout:
            time.sleep(0.02)

    def _worker(self):
        try:
            lib = ctypes.CDLL(self._lib_path)
            sr = lib.espeak_Initialize(2, 0, self._data.encode(), 0)        # 2 = synchronous retrieval
            if sr <= 0:
                raise RuntimeError("espeak_Initialize failed")
            buf = []
            CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)

            def cb(wav, n, events):
                if wav and n > 0:
                    buf.append(np.ctypeslib.as_array(wav, shape=(n,)).copy())
                return 0
            keep = CB(cb)
            lib.espeak_SetSynthCallback(keep)
        except Exception as e:
            self.ok, self.error = False, "speech synthesis failed to start: %s" % e
            self.pending.clear()
            return
        while True:
            k = self.q.get()
            text, vi = k
            try:
                name, rate, pitch = VOICES[vi]
                if lib.espeak_SetVoiceByName(name.encode()) != 0:
                    lib.espeak_SetVoiceByName(b"en")
                lib.espeak_SetParameter(1, rate, 0)
                lib.espeak_SetParameter(3, pitch, 0)
                lib.espeak_SetParameter(4, 55, 0)
                del buf[:]
                t = spoken(text).encode("utf-8")
                lib.espeak_Synth(t, len(t) + 1, 0, 1, 0, 1, None, None)
                x = np.concatenate(buf).astype(np.float64) if buf else np.zeros(SR // 2)
                if sr != SR:
                    x = np.interp(np.arange(0, len(x), sr / float(SR)), np.arange(len(x)), x)
                nz = np.flatnonzero(np.abs(x) > 400)
                if len(nz):
                    x = x[max(0, nz[0] - 800):nz[-1] + 1600]
                self.clips[k] = radio_filter(x)
            except Exception as e:
                self.error = "speech synthesis error: %s" % e
                self.clips[k] = np.zeros(SR // 2, dtype=np.complex64)
            self.pending.discard(k)


def chunk(clip, cur, n):
    """n samples of a clip from sample `cur`, zero-padded outside it."""
    out = np.zeros(n, dtype=clip.dtype)
    a, b = max(cur, 0), min(cur + n, len(clip))
    if b > a:
        out[a - cur:b - cur] = clip[a:b]
    return out
