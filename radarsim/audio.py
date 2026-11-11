"""Real-time synthesised audio: receiver hiss, SSB voice (with the 'Donald
Duck' effect when mistuned), Morse, FSK/DSC bursts, alarms, beacon sweeps.

No sound files are used; everything is generated with numpy in 0.1 s chunks.
"""
import math
import numpy as np
import pygame

SR = 22050
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


class Synth:
    def __init__(self):
        self.t = 0                      # sample counter at the start of this chunk
        self.rng = np.random.default_rng(7)
        self.ph = {}
        self.vph = {}
        self.mcache = {}
        self.lp = 0.0

    def _time(self, n):
        return (self.t + np.arange(n)) / SR

    def osc(self, key, f, n):
        """Phase-continuous sine; f may be a scalar or a per-sample array."""
        f = np.broadcast_to(np.asarray(f, dtype=np.float64), (n,))
        ph = self.ph.get(key, 0.0) + 2 * np.pi * np.cumsum(f) / SR
        self.ph[key] = float(ph[-1] % (2 * np.pi))
        return np.sin(ph)

    def noise(self, n, soft=0.55):
        x = self.rng.standard_normal(n) * 0.33
        y = np.empty(n)
        acc = self.lp
        # one-pole low-pass in blocks (cheap approximation, keeps hiss smooth)
        k = 8
        xs = x.reshape(-1, k) if n % k == 0 else None
        if xs is None:
            return x
        for i in range(xs.shape[0]):
            acc = soft * acc + (1 - soft) * xs[i].mean()
            y[i * k:(i + 1) * k] = xs[i] * 0.7 + acc
        self.lp = acc
        return y

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


def _e(n, tau):
    return np.exp(-np.arange(n) / (tau * SR))


def _tone(f, dur, tau=None, vol=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * t) * vol
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
    b["sqtail"] = nz(0.14, 0.04, 0.9)
    b["blip"] = _tone(1320, 0.045, None, 0.25)
    b["beep"] = _tone(1000, 0.09, None, 0.3)
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
    b["login"] = _mix(*[_at(_tone(f, 0.11, None, 0.2), i * 0.14) for i, f in enumerate((1200, 1800, 1200, 2100, 2400))])
    ring = _mix(_tone(440, 0.8, None, 0.12), _tone(480, 0.8, None, 0.12))
    b["ring"] = _mix(ring, _at(ring, 1.3))
    b["connect"] = _mix(b["relay"], _at(_tone(2100, 0.35, None, 0.15), 0.05))
    n = int(0.55 * SR)
    t = np.arange(n) / SR
    b["printer"] = r.standard_normal(n) * 0.11 * (np.sin(2 * np.pi * 62 * t) > -0.2) * (0.6 + 0.4 * np.sin(2 * np.pi * 9 * t)) \
        + np.sin(2 * np.pi * 124 * t) * 0.03
    n = int(0.5 * SR)
    b["burst406"] = np.sign(np.sin(2 * np.pi * 400 * np.arange(n) / SR)) * np.sin(2 * np.pi * 1100 * np.arange(n) / SR) * 0.1
    b["sart"] = _mix(_tone(2400, 0.05, None, 0.2), _at(_tone(2400, 0.05, None, 0.2), 0.09))
    b["acquire"] = _mix(_tone(1500, 0.04, None, 0.2), _at(_tone(2000, 0.06, None, 0.2), 0.05))
    return b


class Audio:
    CH = 2208

    def __init__(self):
        self.ok, self.mute, self.vol = False, False, 0.55
        self.syn = Synth()
        self.sounds, self._last = {}, {}
        try:
            pygame.mixer.init(SR, -16, 1, 512)
            self.nch = pygame.mixer.get_init()[2]
            pygame.mixer.set_num_channels(16)
            pygame.mixer.set_reserved(1)
            self.chan = pygame.mixer.Channel(0)
            for k, x in build_sfx().items():
                self.sounds[k] = self._sound(x)
            self.ok = True
        except Exception:
            pass

    def _sound(self, x):
        a = (np.clip(x, -1, 1) * 30000).astype(np.int16)
        if self.nch == 2:
            a = np.ascontiguousarray(np.column_stack((a, a)))
        return pygame.sndarray.make_sound(a)

    def play(self, name, vol=1.0):
        """Fire a one-shot effect (rate-limited so fast knob spins don't machine-gun)."""
        if not self.ok or self.mute or name not in self.sounds:
            return
        now = pygame.time.get_ticks()
        if now - self._last.get(name, -999) < 28:
            return
        self._last[name] = now
        ch = pygame.mixer.find_channel(True)
        if ch is not None and ch is not self.chan:
            ch.set_volume(min(1.0, vol * 0.8))
            ch.play(self.sounds[name])

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
                x = np.zeros(self.CH)
            a = (np.clip(x * self.vol, -1, 1) * 30000).astype(np.int16)
            if self.nch == 2:
                a = np.ascontiguousarray(np.column_stack((a, a)))
            snd = pygame.sndarray.make_sound(a)
            if self.chan.get_busy():
                self.chan.queue(snd)
            else:
                self.chan.play(snd)
