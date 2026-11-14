"""Bits shared by all the radios: the receive monitor (captions of what the
loudspeaker is saying) and intelligibility garbling."""
import pygame
from . import ui
from .ui import C, text


def garble(ch, q, i):
    """Return ch if character i survives at readability q (0..1), else '~'."""
    if ch == " " or q >= 0.999:
        return ch
    return ch if ((i * 7919 + 13) % 101) / 101.0 < q else "~"


class Monitor:
    """Scrolling log of received traffic. The radios feed it one character
    at a time, garbled according to signal quality and tuning accuracy."""

    def __init__(self, maxlines=120):
        self.lines, self.key, self.maxlines, self.snd = [], None, maxlines, None

    def feed(self, key, header, ch, color=None):
        if key != self.key or not self.lines:
            self.lines.append([header, "", color or C["lcdfg"]])
            self.key = key
        self.lines[-1][1] += ch
        if len(self.lines[-1][1]) > 900:
            self.lines[-1][1] = self.lines[-1][1][-700:]
        del self.lines[:-self.maxlines]

    def note(self, header, msg, color=None):
        self.lines.append([header, msg, color or C["amber"]])
        self.key = None
        if self.snd:
            ui.sfx(self.snd, 0.8)
        del self.lines[:-self.maxlines]

    def text_all(self):
        return " ".join(l[1] for l in self.lines)

    def draw(self, s, rect, size=12):
        r = pygame.Rect(rect)
        ui.lcd(s, r)
        lh = int(size * 1.4)
        y = r.bottom - 8
        clip = s.get_clip()
        s.set_clip(r.inflate(-6, -6))
        for hdr, msg, col in reversed(self.lines):
            rows = ui.wrap(msg, size, r.w - 24)
            y -= lh * len(rows) + lh + 4
            if y + lh * (len(rows) + 1) < r.y:
                break
            text(s, hdr, (r.x + 10, y), size - 1, C["dim"], bold=True)
            for i, ln in enumerate(rows):
                text(s, ln, (r.x + 10, y + lh * (i + 1)), size, col)
        s.set_clip(clip)


class Voice:
    """Plays one synthesised speech clip (a telephone or handset voice) in
    real time through a loudspeaker model. Position follows the sim clock,
    so a call carries on while you work on another tab."""

    def __init__(self, kind="phone"):
        from .audio import speaker
        self.fir = speaker(kind)
        self.text = self.who = None
        self.start, self.cur, self.done_t = 0.0, None, -1.0

    def say(self, text, who, now, delay=0.6):
        from .world import Msg
        self.text, self.who, self.start, self.cur = text, who, now + delay, None
        if Msg.speech is not None:
            Msg.speech.request(text, who)

    def active(self, now):
        return self.text is not None

    def clip(self):
        from .world import Msg
        if self.text is None or Msg.speech is None or not Msg.speech.ok:
            return None
        return Msg.speech.get(self.text, self.who)

    def chunk(self, n, now, vol=1.0):
        """n samples of the voice (or None) for the audio chunk starting now."""
        import numpy as np
        from .speech import SR, chunk
        if self.text is None:
            return None
        c = self.clip()
        if c is None:
            if now > self.start + max(4.0, len(self.text) / 12.0):    # no speech engine: give up after the caption time
                self.text = None
            return None
        exp = int((now - self.start) * SR)
        if self.cur is None or abs(self.cur - exp) > SR * 0.3:
            self.cur = exp
        x = chunk(c, self.cur, n).real
        self.cur += n
        if self.cur > len(c) + SR // 4:
            self.text, self.done_t = None, now
        return self.fir(x * 1.2) * vol
