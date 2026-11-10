"""Real-time synthesised audio: receiver hiss, SSB voice (with the 'Donald
Duck' effect when mistuned), Morse, FSK/DSC bursts, alarms, beacon sweeps.

No sound files are used; everything is generated with numpy in 0.1 s chunks.
"""
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

    def music(self, key, n):
        t = self._time(n)
        note = np.array([262, 330, 392, 523, 440, 349, 294, 392])[(t * 2).astype(int) % 8]
        return (self.osc(key, note, n) + 0.5 * self.osc(key + "h", note * 2, n)) * 0.2


class Audio:
    CH = 2208

    def __init__(self):
        self.ok, self.mute, self.vol = False, False, 0.55
        self.syn = Synth()
        try:
            pygame.mixer.init(SR, -16, 1, 512)
            self.nch = pygame.mixer.get_init()[2]
            self.chan = pygame.mixer.Channel(0)
            self.ok = True
        except Exception:
            pass

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
