"""Real-time synthesised audio: receiver hiss, SSB voice (with the 'Donald
Duck' effect when mistuned), Morse, FSK/DSC bursts, alarms, beacon sweeps,
plus every mechanical and electronic one-shot on the console.

No sound files are used; everything is generated with numpy. The stream is
stereo: each equipment position sits at its own place on the console, and
one-shot effects are panned to where you clicked. Radio audio is passed
through a small loudspeaker model and the one-shots through a short room
response, so the console sounds like hardware in a wheelhouse rather than a
computer.
"""
import math
import numpy as np
import pygame

SR = 22050
SQ2 = math.sqrt(2.0)
MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..", "0": "-----",
    "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....", "6": "-....",
    "7": "--...", "8": "---..", "9": "----.", "/": "-..-.", "?": "..--..", "=": "-...-",
}


def morse_keying(msg, wpm=18):
    """On/off pattern (one element per dot length) for a looping message."""
    out = []
    for ch in msg.upper():
        if ch == " ":
            out += [0] * 4
            continue
        for sym in MORSE.get(ch, ""):
            out += [1] * (3 if sym == "-" else 1) + [0]
        out += [0] * 2
    out += [0] * 14
    return np.array(out, dtype=np.float32), 1.2 / wpm


# ------------------------------------------------------------ stereo field
def pan_gains(pan):
    """Constant-power gains (left, right); centre = (1, 1)."""
    a = (max(-1.0, min(1.0, float(pan))) + 1.0) * math.pi / 4.0
    return math.cos(a) * SQ2, math.sin(a) * SQ2


def place(x, pan=0.0, gain=1.0, width=1.0):
    """Put a mono or stereo buffer into the stereo field. Mono is panned with
    constant power; stereo is balanced and optionally narrowed (width < 1)."""
    if x is None:
        return None
    x = np.asarray(x, dtype=np.float64)
    gl, gr = pan_gains(pan)
    if x.ndim == 1:
        return np.column_stack((x * (gl * gain), x * (gr * gain)))
    if width < 1.0:
        m = x.mean(axis=1, keepdims=True)
        x = m + (x - m) * width
    return x * np.array([gl * gain, gr * gain])


# ----------------------------------------------------------------- filters
def lowpass_ir(fc, taps):
    n = np.arange(taps) - (taps - 1) / 2.0
    return 2.0 * fc / SR * np.sinc(2.0 * fc / SR * n) * np.blackman(taps)


def bandpass_ir(f1, f2, taps):
    return lowpass_ir(f2, taps) - lowpass_ir(f1, taps)


def gain_at(h, f):
    k = np.arange(len(h))
    return float(abs(np.sum(h * np.exp(-2j * np.pi * f * k / SR))))


# small loudspeakers: (low cut, high cut, cone resonance, its half width, resonance gain)
SPEAKERS = {
    "vhf": (430, 3700, 1250, 260, 0.9),
    "air": (380, 3300, 1700, 320, 0.6),
    "hf": (260, 3000, 850, 230, 0.8),
    "phone": (330, 3300, 2300, 420, 0.45),
    "tracer": (170, 4500, 900, 300, 0.5),
    "navtex": (500, 3400, 1900, 300, 0.6),
}


def speaker_ir(kind, taps=129):
    lo, hi, fr, bw, g = SPEAKERS[kind]
    h = bandpass_ir(lo, hi, taps) + g * bandpass_ir(fr - bw, fr + bw, taps)
    return h / max(1e-6, gain_at(h, 1000.0))


class FIR:
    """Streaming FIR filter (overlap-add); keep one instance per audio path."""

    def __init__(self, h):
        self.h = np.asarray(h, dtype=np.float64)
        self.tail = np.zeros(len(self.h) - 1)

    def __call__(self, x):
        x = np.asarray(x, dtype=np.float64)
        y = np.convolve(x, self.h)
        m = len(self.tail)
        y[:m] += self.tail
        n = len(x)
        self.tail = y[n:n + m].copy()
        return y[:n]


def speaker(kind):
    return FIR(speaker_ir(kind))


def fftconv(x, h):
    n = len(x) + len(h) - 1
    N = 1 << max(1, (n - 1).bit_length())
    return np.fft.irfft(np.fft.rfft(x, N) * np.fft.rfft(h, N), N)[:n]


def room_ir(wet=0.2, seed=11):
    """Early reflections and a short diffuse tail: a steel wheelhouse."""
    r = np.random.default_rng(seed)
    n = int(0.11 * SR)
    h = np.zeros(n)
    h[0] = 1.0
    for d, g in ((0.0047, 0.5), (0.0083, 0.42), (0.0121, 0.36), (0.0169, 0.3), (0.0233, 0.25),
                 (0.0307, 0.19), (0.0401, 0.14), (0.0523, 0.1)):
        h[int(d * SR)] += g * wet * (1 if r.random() > 0.35 else -1)
    k = np.arange(n)
    tail = r.standard_normal(n) * np.exp(-k / (0.028 * SR)) * 0.05 * wet
    tail[:int(0.01 * SR)] = 0
    return h + np.convolve(tail, np.ones(4) / 4.0, mode="same")


def limit(x, knee=0.8):
    """Soft limiter so a pile-up of sounds rounds off instead of clipping."""
    a = np.abs(x)
    over = a > knee
    if not over.any():
        return x
    y = x.copy()
    y[over] = np.sign(x[over]) * (knee + (1 - knee) * np.tanh((a[over] - knee) / (1 - knee)))
    return y


# ------------------------------------------------------------------- synth
class Synth:
    def __init__(self):
        self.t = 0                      # sample counter at the start of this chunk
        self.rng = np.random.default_rng(7)
        self.ph = {}
        self.vph = {}
        self.mcache = {}
        self.tails = {}
        self.lp = 0.0

    def _time(self, n):
        return (self.t + np.arange(n)) / SR

    def osc(self, key, f, n):
        """Phase-continuous sine; f may be a scalar or a per-sample array."""
        f = np.broadcast_to(np.asarray(f, dtype=np.float64), (n,))
        ph = self.ph.get(key, 0.0) + 2 * np.pi * np.cumsum(f) / SR
        self.ph[key] = float(ph[-1] % (2 * np.pi))
        return np.sin(ph)

    def white(self, n):
        return self.rng.standard_normal(n) * 0.33

    def noise(self, n, soft=0.55):
        x = self.rng.standard_normal(n) * 0.33
        y = np.empty(n)
        acc = self.lp
        # one-pole low-pass in blocks (cheap approximation, keeps hiss smooth)
        k = 8
        xs = x.reshape(-1, k) if n % k == 0 else None
        if xs is None:
            return x
        m = xs.mean(axis=1)
        out = np.empty(len(m))
        for i in range(len(m)):
            acc = soft * acc + (1 - soft) * m[i]
            out[i] = acc
        y = (xs * 0.7 + out[:, None]).reshape(-1)
        self.lp = acc
        return y

    def clicks(self, key, n, rate, tau=0.0012, ring=0.0):
        """Poisson-timed clicks (rain drops, static crackle, ratchets) with
        their decays carried across chunk boundaries."""
        L = int(tau * SR * 6) + 2
        k = np.arange(L)
        kern = np.exp(-k / max(1.0, tau * SR))
        if ring:
            kern = kern * np.cos(2 * np.pi * ring * k / SR)
        imp = (self.rng.random(n) < rate / SR) * self.rng.standard_normal(n)
        y = np.convolve(imp, kern)
        tail = self.tails.get(key)
        if tail is not None:
            m = min(len(tail), len(y))
            y[:m] += tail[:m]
        self.tails[key] = y[n:].copy()
        return y[:n] * 0.5

    def voice(self, key, n, shift=0.0, invert=False):
        """Speech-like babble. `shift` (Hz) moves every component the way a
        mistuned SSB receiver does; `invert` = wrong sideband selected."""
        t = self._time(n)
        seed = (hash(key) % 97) * 0.37
        f0 = 118 * (1 + 0.13 * np.sin(2 * np.pi * 0.71 * t + seed) + 0.05 * np.sin(2 * np.pi * 2.3 * t))
        env = np.clip(np.sin(2 * np.pi * 3.3 * t + seed) + 0.6 * np.sin(2 * np.pi * 1.37 * t) + 0.35, 0, 1)
        env *= (np.sin(2 * np.pi * 0.19 * t + seed) > -0.72)
        tc = t[0]
        F1 = 560 + 230 * np.sin(2 * np.pi * 1.1 * tc + seed)
        F2 = 1500 + 520 * np.sin(2 * np.pi * 0.83 * tc + 1 + seed)
        K = 22
        ph0 = self.vph.get(key)
        if ph0 is None:
            ph0 = self.rng.uniform(0, 6.28, K)
        k = np.arange(1, K + 1)
        base = np.outer(f0, k)                                  # n x K audio freqs
        fc = base[0]
        amp = np.exp(-((fc - F1) / 260) ** 2) + 0.7 * np.exp(-((fc - F2) / 420) ** 2) + 0.05
        amp *= (fc > 250) & (fc < 2800)
        fo = (3000 - base if invert else base) + shift
        amp = amp * ((fo[0] > 60) & (fo[0] < 3600))
        ph = ph0 + 2 * np.pi * np.cumsum(fo, axis=0) / SR
        self.vph[key] = ph[-1] % (2 * np.pi)
        return (np.sin(ph) * amp).sum(axis=1) * env * 0.33

    def morse(self, key, msg, n, pitch=700.0, wpm=18):
        ck = (msg, wpm)
        if ck not in self.mcache:
            self.mcache[ck] = morse_keying(msg, wpm)
        pat, dot = self.mcache[ck]
        idx = ((self.t + np.arange(n)) / (dot * SR)).astype(np.int64) % len(pat)
        return self.osc(key, pitch, n) * pat[idx] * 0.5

    def morse_on(self, msg, t, wpm=18):
        ck = (msg, wpm)
        if ck not in self.mcache:
            self.mcache[ck] = morse_keying(msg, wpm)
        pat, dot = self.mcache[ck]
        return bool(pat[int(t / dot) % len(pat)])

    def fsk(self, key, n, baud=100, centre=1700.0, shift=170.0):
        i = ((self.t + np.arange(n)) * baud // SR).astype(np.uint64)
        bits = ((i * np.uint64(2654435761)) >> np.uint64(13)) & np.uint64(1)
        return self.osc(key, centre + shift * (bits.astype(np.float64) - 0.5), n) * 0.45

    def alarm(self, key, n):
        """Radiotelephone two-tone alarm: 2200 Hz / 1300 Hz, 250 ms each."""
        t = self._time(n)
        return self.osc(key, np.where((t * 4).astype(int) % 2 == 0, 2200.0, 1300.0), n) * 0.5

    def warble(self, key, n, f1=1000.0, f2=1600.0, rate=5.0):
        t = self._time(n)
        return self.osc(key, np.where((t * rate).astype(int) % 2 == 0, f1, f2), n) * 0.4

    def buzzer(self, key, n, f=420.0, rate=1.5):
        """Electromechanical alarm buzzer (square-ish, gated)."""
        t = self._time(n)
        s = np.tanh(4.0 * self.osc(key, f, n)) * 0.3
        return s * ((t * rate) % 1 < 0.6)

    def beep(self, key, n, f=1900.0, rate=4.0):
        t = self._time(n)
        return self.osc(key, f, n) * ((t * rate) % 1 < 0.5) * 0.4

    def sweep(self, key, n):
        """121.5 MHz homing signal: downward audio sweep, about 3 per second."""
        t = self._time(n)
        return self.osc(key, 1600 - 1300 * ((t * 3) % 1), n) * 0.45

    def tick(self, key, n, shift=0.0):
        """Time-signal seconds tick (5 ms of 1 kHz) plus a quiet 500 Hz tone."""
        t = self._time(n)
        return (self.osc(key, 1000 + shift, n) * ((t % 1) < 0.012)
                + 0.12 * self.osc(key + "b", 500 + shift, n) * ((t % 60) < 45))

    def fax(self, key, n, shift=0.0):
        t = self._time(n)
        pos = ((t * 2) % 1 * 48).astype(np.int64)
        line = (t * 2).astype(np.int64) // 6
        black = ((pos * 7919 + line * 104729) % 7) < 3
        return self.osc(key, 1500 + 800 * black + shift, n) * 0.4

    def rumble(self, key, n, cut=16):
        """Low-passed noise (fans, motors): white noise held and interpolated."""
        m = n // cut + 2
        last = self.ph.get(key, 0.0)
        pts = np.concatenate(([last], self.rng.standard_normal(m) * 0.5))
        self.ph[key] = float(pts[n // cut])
        return np.interp(np.arange(n) / float(cut), np.arange(m + 1), pts)

    def whine(self, key, f, n):
        """Peaky pulse-train buzz, e.g. a radar modulator at its PRF."""
        s = self.osc(key, f / 2.0, n)
        return s ** 12

    def music(self, key, n):
        t = self._time(n)
        note = np.array([262, 330, 392, 523, 440, 349, 294, 392])[(t * 2).astype(int) % 8]
        return (self.osc(key, note, n) + 0.5 * self.osc(key + "h", note * 2, n)) * 0.2

    def glide(self, key, target, n, rate):
        """Per-sample ramp from the last value towards `target` at `rate`/s."""
        a = self.ph.get("g:" + key, target)
        step = rate * n / SR
        b = a + max(-step, min(step, target - a))
        self.ph["g:" + key] = b
        return np.linspace(a, b, n)


# ---------------------------------------------------------- one-shot sounds
def _e(n, tau):
    return np.exp(-np.arange(n) / (tau * SR))


def _tone(f, dur, tau=None, vol=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * t) * vol
    env = _e(n, tau) if tau else np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (0.004 * SR))
    return x * env


def _chirp(f0, f1, dur, tau=None, vol=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * (f0 * t + (f1 - f0) * t * t / (2 * dur))) * vol
    env = _e(n, tau) if tau else np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (0.004 * SR))
    return x * env


def _mix(*parts):
    n = max(len(p) for p in parts)
    out = np.zeros(n)
    for p in parts:
        out[:len(p)] += p
    return out


def _at(x, delay):
    return np.concatenate((np.zeros(int(delay * SR)), x))


def build_sfx():
    """Every mechanical and electronic one-shot sound, synthesised."""
    r = np.random.default_rng(42)

    def nz(dur, tau, vol=1.0, lp=1):
        n = int(dur * SR)
        x = r.standard_normal(n)
        if lp > 1:
            x = np.convolve(x, np.ones(lp) / lp, mode="same") * math.sqrt(lp)
        return x * _e(n, tau) * vol * 0.4

    b = {}
    b["detent"] = _mix(nz(0.012, 0.0012, 0.7), _tone(3100, 0.012, 0.002, 0.25))
    b["pot"] = nz(0.01, 0.002, 0.25, 3)
    b["press"] = _mix(nz(0.03, 0.002, 1.0, 2), _tone(950, 0.03, 0.005, 0.5), _tone(190, 0.04, 0.012, 0.5))
    b["release"] = _mix(nz(0.02, 0.0015, 0.6), _tone(1400, 0.02, 0.004, 0.3))
    b["key"] = _mix(b["press"] * 0.6, _at(_tone(1760, 0.05, None, 0.22), 0.004))
    b["clunk"] = _mix(nz(0.05, 0.004, 1.2, 3), _tone(230, 0.07, 0.02, 0.9), _tone(1350, 0.03, 0.006, 0.3),
                      _at(_mix(nz(0.03, 0.003, 0.5, 2), _tone(260, 0.04, 0.012, 0.35)), 0.024))
    b["stop"] = _mix(nz(0.03, 0.003, 0.5, 4), _tone(150, 0.05, 0.015, 0.5))
    b["tab"] = _mix(b["clunk"], _tone(110, 0.12, 0.035, 0.8))
    b["cover"] = _mix(nz(0.02, 0.002, 0.8), _tone(2600, 0.12, 0.028, 0.22), _tone(3900, 0.09, 0.02, 0.14), _tone(420, 0.05, 0.012, 0.3))
    b["thunk"] = _mix(nz(0.05, 0.005, 1.2, 4), _tone(120, 0.2, 0.06, 1.0), _tone(75, 0.25, 0.08, 0.7))
    b["relay"] = _mix(nz(0.02, 0.0025, 1.0, 2), _tone(330, 0.05, 0.012, 0.6), _at(nz(0.015, 0.002, 0.5), 0.009))
    b["relay2"] = _mix(nz(0.012, 0.0015, 0.7, 2), _tone(520, 0.03, 0.006, 0.35), _at(nz(0.008, 0.001, 0.3), 0.006))
    b["sqtail"] = nz(0.14, 0.04, 0.9)
    b["sqopen"] = _mix(nz(0.06, 0.014, 0.8, 2), _tone(180, 0.03, 0.01, 0.2))
    b["blip"] = _tone(1320, 0.045, None, 0.25)
    b["beep"] = _tone(1000, 0.09, None, 0.3)
    b["kbeep"] = _tone(2600, 0.035, None, 0.11)
    b["beep2"] = _mix(_tone(1000, 0.08, None, 0.3), _at(_tone(1000, 0.08, None, 0.3), 0.14))
    b["warm"] = _mix(_tone(880, 0.12, None, 0.25), _at(_tone(1320, 0.2, None, 0.25), 0.13))
    b["ok"] = _mix(_tone(880, 0.08, None, 0.25), _at(_tone(1320, 0.12, None, 0.25), 0.09))
    b["done"] = _mix(*[_at(_tone(f, 0.16, 0.12, 0.3), i * 0.11) for i, f in enumerate((660, 880, 1100, 1320, 1760))])
    n = int(0.28 * SR)
    b["error"] = np.sign(np.sin(2 * np.pi * 140 * np.arange(n) / SR)) * 0.16 * np.minimum(1, (n - np.arange(n)) / 600.0)
    t = np.arange(int(0.35 * SR)) / SR
    b["fault"] = _mix(b["relay"], _at(np.sin(2 * np.pi * (520 * t - 450 * t * t)) * 0.22 * _e(len(t), 0.15), 0.03))
    b["probe"] = _mix(nz(0.008, 0.001, 0.5), _tone(2200, 0.01, 0.002, 0.2))
    b["page"] = nz(0.16, 0.05, 0.5, 6) * np.linspace(0.2, 1, int(0.16 * SR))
    lo, hi = (697, 770, 852, 941), (1209, 1336, 1477)
    for i, k in enumerate("123456789*0#"):
        b["dtmf" + k] = _mix(_tone(lo[i // 3], 0.09, None, 0.16), _tone(hi[i % 3], 0.09, None, 0.16))
    bits = r.integers(0, 2, 700).repeat(SR // 1200)
    ph = np.cumsum(2 * np.pi * (1300 + 800 * bits) / SR)
    b["data"] = np.sin(ph) * 0.2
    bits = r.integers(0, 2, 160).repeat(SR // 100)
    b["fsk"] = np.sin(np.cumsum(2 * np.pi * (1615 + 170 * bits) / SR)) * 0.22
    bits = r.integers(0, 2, 90).repeat(SR // 300)
    b["sbd"] = np.sin(np.cumsum(2 * np.pi * (1800 + 400 * bits) / SR)) * 0.14
    b["login"] = _mix(*[_at(_tone(f, 0.11, None, 0.2), i * 0.14) for i, f in enumerate((1200, 1800, 1200, 2100, 2400))])
    ring = _mix(_tone(440, 0.8, None, 0.12), _tone(480, 0.8, None, 0.12))
    b["ring"] = _mix(ring, _at(ring, 1.3))
    b["busy"] = _mix(*[_at(_tone(425, 0.25, None, 0.14), i * 0.5) for i in range(3)])
    b["connect"] = _mix(b["relay"], _at(_tone(2100, 0.35, None, 0.15), 0.05))
    n = int(0.55 * SR)
    t = np.arange(n) / SR
    b["printer"] = r.standard_normal(n) * 0.11 * (np.sin(2 * np.pi * 62 * t) > -0.2) * (0.6 + 0.4 * np.sin(2 * np.pi * 9 * t)) \
        + np.sin(2 * np.pi * 124 * t) * 0.03
    # dot-matrix head: nine pins fired across one character cell
    dot = np.zeros(int(0.03 * SR))
    for i in range(9):
        c = nz(0.004, 0.0004, 0.8)
        j = int(i * 0.0029 * SR)
        dot[j:j + len(c)] += c[:len(dot) - j]
    b["dot"] = _mix(dot, _tone(2150, 0.03, 0.008, 0.05), _tone(95, 0.03, 0.01, 0.06))
    n = int(0.5 * SR)
    b["burst406"] = np.sign(np.sin(2 * np.pi * 400 * np.arange(n) / SR)) * np.sin(2 * np.pi * 1100 * np.arange(n) / SR) * 0.1
    b["sart"] = _mix(_tone(2400, 0.05, None, 0.2), _at(_tone(2400, 0.05, None, 0.2), 0.09))
    b["acquire"] = _mix(_tone(1500, 0.04, None, 0.2), _at(_tone(2000, 0.06, None, 0.2), 0.05))
    b["drop"] = _mix(_tone(1500, 0.05, None, 0.18), _at(_tone(1000, 0.07, None, 0.18), 0.06))
    b["ready"] = _tone(2200, 0.035, None, 0.13)
    b["lost"] = _mix(*[_at(_tone(f, 0.08, None, 0.2), i * 0.11) for i, f in enumerate((1800, 1400, 1000))])
    b["lock"] = _mix(_tone(1046, 0.09, None, 0.16), _at(_tone(1568, 0.16, None, 0.16), 0.1))
    b["unlock"] = _mix(_tone(1568, 0.09, None, 0.14), _at(_tone(1046, 0.16, None, 0.14), 0.1))
    b["ringin"] = _mix(_tone(2100, 0.11, None, 0.14), _at(_tone(1300, 0.11, None, 0.14), 0.16),
                       _at(_tone(2100, 0.11, None, 0.14), 0.42), _at(_tone(1300, 0.11, None, 0.14), 0.58))
    b["tick"] = _mix(nz(0.004, 0.0005, 0.6), _tone(4000, 0.004, 0.0008, 0.1))
    b["handoff"] = _mix(_tone(2900, 0.012, 0.003, 0.08), _at(_tone(3400, 0.012, 0.003, 0.06), 0.03))
    # bat-handle toggle: sharp metallic snap; breaker: heavy clack; thumbwheel: ratchet
    b["toggle"] = _mix(nz(0.008, 0.0008, 1.0), _tone(2400, 0.012, 0.0025, 0.3), _tone(820, 0.02, 0.004, 0.25),
                       _at(nz(0.006, 0.0007, 0.5), 0.006))
    b["breaker"] = _mix(nz(0.03, 0.003, 1.3, 2), _tone(160, 0.09, 0.022, 0.75), _tone(1100, 0.02, 0.004, 0.3),
                        _at(nz(0.02, 0.002, 0.7), 0.012), _at(_tone(240, 0.05, 0.012, 0.3), 0.012))
    b["thumb"] = _mix(nz(0.005, 0.0006, 0.7), _tone(3300, 0.006, 0.001, 0.15), _at(nz(0.003, 0.0004, 0.3), 0.004))
    b["type"] = _mix(nz(0.008, 0.0009, 0.8), _tone(1900, 0.01, 0.0015, 0.15), _at(nz(0.02, 0.003, 0.45, 3), 0.011),
                     _at(_tone(170, 0.03, 0.008, 0.25), 0.011))
    b["type2"] = _mix(nz(0.008, 0.0008, 0.7), _tone(2300, 0.01, 0.0013, 0.12), _at(nz(0.018, 0.003, 0.4, 3), 0.009),
                      _at(_tone(205, 0.03, 0.007, 0.22), 0.009))
    b["type3"] = _mix(nz(0.01, 0.001, 0.9, 2), _tone(1500, 0.01, 0.002, 0.13), _at(nz(0.02, 0.003, 0.5, 4), 0.013),
                      _at(_tone(150, 0.035, 0.009, 0.28), 0.013))
    # power: transformer thump and self-test bleep / pop on the way down
    b["pwron"] = _mix(nz(0.03, 0.004, 0.8, 5), _tone(80, 0.25, 0.07, 0.6), _at(_tone(1000, 0.06, None, 0.12), 0.18))
    b["pwroff"] = _mix(nz(0.02, 0.003, 0.5, 4), _tone(60, 0.15, 0.05, 0.4), _chirp(900, 300, 0.12, 0.05, 0.05))
    # CRT degauss: thump, 100 Hz coil buzz dying away, the shadow mask's 'boing'
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    buzz = np.tanh(3 * np.sin(2 * np.pi * 100 * t)) * 0.13 * np.exp(-t / 0.28)
    b["degauss"] = _mix(nz(0.06, 0.012, 1.1, 6), _tone(55, 0.6, 0.18, 0.8), buzz, _tone(240, 0.4, 0.07, 0.22))
    # high voltage coming on: relay then a short crackle
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    imp = (r.random(n) < 0.03 * np.exp(-t / 0.08)) * r.standard_normal(n)
    crack = np.convolve(imp, np.exp(-np.arange(40) / 6.0))[:n] * 0.35
    b["hv"] = _mix(b["relay"], _at(crack, 0.02), _at(_chirp(3000, 6000, 0.2, 0.08, 0.02), 0.02))
    # hull slam in heavy weather: deep thud and a creak
    n = int(0.6 * SR)
    t = np.arange(n) / SR
    creak = np.sin(2 * np.pi * (310 * t - 60 * t * t)) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 37 * t))) * np.exp(-t / 0.25) * 0.05
    b["slam"] = _mix(nz(0.3, 0.08, 1.2, 60), _tone(38, 0.6, 0.22, 0.7), _tone(70, 0.4, 0.12, 0.35), _at(creak, 0.14))
    # contactor (test load / changeover) and an electric starter cranking
    b["contactor"] = _mix(nz(0.04, 0.005, 1.4, 3), _tone(95, 0.12, 0.03, 0.9), _at(nz(0.02, 0.002, 0.6), 0.016))
    b["paper"] = _mix(nz(0.25, 0.08, 0.6, 2) * np.linspace(1, 0.3, int(0.25 * SR)), _at(nz(0.05, 0.01, 0.4), 0.2))
    b["feed"] = r.standard_normal(int(0.3 * SR)) * 0.05 * (np.sin(2 * np.pi * 45 * np.arange(int(0.3 * SR)) / SR) > 0) \
        + _tone(90, 0.3, None, 0.05)
    b["chime"] = _mix(_tone(1318, 0.5, 0.25, 0.14), _at(_tone(1046, 0.7, 0.3, 0.12), 0.18))
    b["sweepdn"] = _chirp(1400, 300, 0.25, None, 0.12)
    return b


def roomify(x, ir):
    y = fftconv(np.asarray(x, dtype=np.float64), ir)
    a = np.abs(y)
    nz = np.flatnonzero(a > 1e-4)
    return y[:nz[-1] + 1] if len(nz) else y


class Audio:
    CH = 2208

    def __init__(self):
        self.ok, self.mute = False, False
        self.vol, self.master = 0.55, 0.8
        self.syn = Synth()
        self.sounds, self._last = {}, {}
        self.nch = 2
        try:
            pygame.mixer.init(SR, -16, 2, 512)
            self.nch = pygame.mixer.get_init()[2]
            pygame.mixer.set_num_channels(24)
            pygame.mixer.set_reserved(1)
            self.chan = pygame.mixer.Channel(0)
            room = room_ir()
            for k, x in build_sfx().items():
                self.sounds[k] = self._sound(roomify(x, room))
            self.ok = True
        except Exception:
            pass

    def _pcm(self, x):
        x = np.asarray(x, dtype=np.float64)
        if x.ndim == 1:
            x = np.column_stack((x, x))
        if self.nch == 1:
            x = x.mean(axis=1)
        elif self.nch > 2:
            x = np.column_stack([x] + [np.zeros(len(x))] * (self.nch - 2))
        a = (np.clip(x, -1, 1) * 30000).astype(np.int16)
        return pygame.sndarray.make_sound(np.ascontiguousarray(a))

    def _sound(self, x):
        return self._pcm(x)

    def set_master(self, v):
        self.master = max(0.0, min(1.0, v))

    def play(self, name, vol=1.0, pan=0.0):
        """Fire a one-shot effect (rate-limited so fast knob spins don't machine-gun)."""
        if not self.ok or self.mute or name not in self.sounds:
            return
        now = pygame.time.get_ticks()
        if now - self._last.get(name, -999) < 28:
            return
        self._last[name] = now
        ch = pygame.mixer.find_channel(True)
        if ch is None or ch is self.chan:
            return
        ch.play(self.sounds[name])
        g = min(1.0, vol * 0.8 * self.master)
        gl, gr = pan_gains(pan)
        ch.set_volume(min(1.0, g * gl), min(1.0, g * gr))

    def pump(self, gen):
        """Keep one chunk queued behind the one playing."""
        if not self.ok:
            return
        for _ in range(3):
            if self.chan.get_busy() and self.chan.get_queue() is not None:
                break
            x = None if self.mute else gen(self.syn, self.CH)
            self.syn.t += self.CH
            if x is None:
                x = np.zeros((self.CH, 2))
            snd = self._pcm(limit(np.asarray(x, dtype=np.float64) * (self.vol * self.master)))
            if self.chan.get_busy():
                self.chan.queue(snd)
            else:
                self.chan.play(snd)
