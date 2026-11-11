"""MF/HF SSB transceiver, antenna tuner, DSC watch receiver, spectrum scope
and an ionospheric propagation predictor.

SSB demodulation is modelled properly: the receiver re-inserts the carrier
at the dial frequency, so any tuning error shifts every audio component by
that many hertz (the 'Donald Duck' voice) and the wrong sideband inverts the
speech spectrum. Captions only become readable when you are tuned within
about 50 Hz on the correct sideband - use the CLARIFIER.
"""
import math
import numpy as np
import pygame
from . import ui
from .ui import C, text, Knob, Selector, Button, Guard, Station
from .world import HF_STATIONS, HF_DSC, HF_RT, ITU_BANDS, itu_channel, s_units, s_text, CPS, fmt_lat, fmt_lon
from .radiocore import Monitor, garble
from .speech import SR, chunk
from .world import Msg

MODES = ["USB", "LSB", "AM", "CW", "FSK"]
EMISSION = {"USB": "J3E", "LSB": "J3E", "AM": "H3E", "CW": "A1A", "FSK": "F1B"}
PASS = {"USB": (0.3, 2.7), "LSB": (-2.7, -0.3), "AM": (-3.0, 3.0), "CW": (-0.25, 0.25), "FSK": (-0.25, 0.25)}
RATE = {"voice": CPS, "navtex": 8.0, "cw": 1.7, "wwv": 5.0, "bc": 6.0, "fax": 6.0, "dsc": 0.0}
NB, SPAN, WH = 448, 24.0, 135
PRED = ["NORTHSEA RADIO", "AEGEAN RADIO", "ATLANTIC WX", "WWV TIME SIGNAL", "PENHALE COASTGUARD MF"]


class HF(Station):
    name = "MF / HF SSB"
    hint = ("Type a frequency on the keypad then kHz (or an ITU channel then CH). Turn the big knob "
            "or click the waterfall to tune. TUNE the antenna before transmitting. SPACE = PTT.")

    def __init__(self, app):
        super().__init__(app)
        w = self.world
        self.f, self.split, self.chan = 8764.0, 0.0, None
        self.entry = ""
        self.atu_f, self.tuning_until = None, 0.0
        self.tx, self.tx_t0, self.key_ptt = False, 0.0, False
        self.mon = Monitor()
        self.sigs, self.active = [], []
        self.temp = []
        self.flags = {}
        self.dsc_log, self.dsc_seen = [], {}
        self.distress = None
        self.pending = []
        self.swr, self.po, self.s_dbm = 1.0, 0.0, -130.0
        self.rng = np.random.default_rng(5)
        self.wf = np.zeros((NB, WH), dtype=np.uint8)
        self.line = np.full(NB, -130.0)
        self.wsurf = pygame.Surface((NB, WH), 0, 8)
        pal = []
        for i in range(256):
            x = i / 255.0
            pal.append((int(255 * min(1, max(0, 2.2 * x - 0.9))), int(255 * min(1, max(0, 2.0 * x - 0.35) ** 1.2)),
                        int(255 * min(1, max(0.06, 1.6 * x if x < 0.5 else 1.6 - 1.6 * x + 0.2 * x)))))
        self.wsurf.set_palette(pal)
        self._wt = 0.0
        self.pred_i, self._pred, self._pt = 0, None, -9

        self.meter_sel = self.add(Selector(706, 136, 22, "METER", ["S", "PO", "SWR", "IC"], 0,
            "METER: S = received signal strength (S9 = -73 dBm = 50 uV, 6 dB per S-unit); PO = "
            "forward power; SWR = standing wave ratio at the tuner; IC = PA collector current."))
        self.mode = self.add(Selector(790, 136, 22, "MODE", MODES, 0,
            "MODE / emission class: USB J3E (marine R/T standard), LSB, AM H3E, CW A1A (Morse), "
            "FSK F1B (NAVTEX, telex, DSC). All marine HF voice is UPPER sideband."))
        self.pwr = self.add(Selector(874, 136, 22, "POWER", ["LOW 60W", "MED 150W", "HIGH 400W"], 1,
            "Transmit power (PEP). Use the minimum needed for reliable communication."))
        self.knob = self.add(Knob(92, 296, 42, "TUNING", encoder=True, on_turn=self._turn,
            tip="Main tuning. Step size is set by STEP. Wheel = 1 step per click."))
        self.step = self.add(Selector(196, 300, 22, "STEP", ["10 Hz", "100 Hz", "1 kHz"], 1, "Tuning step."))
        self.rit = self.add(Knob(276, 300, 22, "CLARIFIER", -300, 300, 0, "CLARIFIER (RIT): shifts "
            "ONLY the receive frequency by up to +/-300 Hz so an off-frequency voice sounds natural, "
            "without moving your transmit frequency.", fmt=lambda v: "%+d Hz" % v))
        self.af = self.add(Knob(356, 300, 22, "AF GAIN", 0, 1, 0.6, "Audio volume."))
        self.rf = self.add(Knob(436, 300, 22, "RF GAIN", 0, 1, 1.0, "RF GAIN: reduce on very strong "
            "signals to stop the receiver overloading. Normally fully clockwise."))
        self.b_tune = self.add(Button((490, 250, 74, 40), "TUNE", "ANTENNA TUNER: matches the whip "
            "antenna to 50 ohm at the transmit frequency (takes ~2 s, radiates a low-power carrier). "
            "Re-tune after every frequency change of more than about 0.4 %.", color="green"))
        self.b_att = self.add(Button((570, 250, 74, 40), "ATT\n20dB", "ATTENUATOR: 20 dB pad in front of the receiver.", toggle=True, size=10))
        self.b_2182 = self.add(Button((650, 250, 74, 40), "2182", "Instant select 2182 kHz, the MF radiotelephone distress frequency.", color="red"))
        self.b_alarm = self.add(Button((490, 298, 74, 40), "2-TONE\nALARM", "Radiotelephone alarm signal "
            "generator (2200/1300 Hz). Historic on 2182 kHz - superseded by DSC under GMDSS, kept for training.", toggle=True, size=10, color="red"))
        self.ptt = self.add(Button((570, 298, 154, 40), "PTT  (SPACE)", "Press to talk.", color="red", size=12))
        self.keys = ui.keypad(self, 750, 232, [["1", "2", "3", "CLR"], ["4", "5", "6", "CH"],
                                               ["7", "8", "9", "kHz"], [".", "0", "BS", "T/R"]], 42, 30, 5,
                              "Frequency entry: digits then kHz for a simplex frequency, or an ITU channel "
                              "number (e.g. 816) then CH for a duplex pair. T/R swaps to listen on your TX frequency.")
        self.guard = self.add(Guard((1350, 84, 104, 100), "DISTRESS", "MF/HF DSC DISTRESS: lift the "
            "cover and hold 3 s. Sent on the DSC frequency selected at right - choose the band by "
            "distance and time of day (see the propagation panel)."))
        self.dband = self.add(Selector(1536, 166, 18, "DSC BAND kHz", ["%g" % f for f in HF_DSC], 3,
            "DSC distress frequency for the alert: 2187.5 (ground wave, ~150 nm), 8414.5 (the "
            "first-choice HF band), or 4/6/12/16 MHz according to propagation."))
        self.b_rt = self.add(Button((1466, 78, 116, 26), "TO R/T FREQ", "Set the transceiver to the "
            "radiotelephone distress frequency associated with the selected DSC band.", size=10))
        self.b_prev = self.add(Button((976, 234, 30, 26), "<", "Previous station."))
        self.b_next = self.add(Button((1220, 234, 30, 26), ">", "Next station."))
        self.b_um = self.add(Button((1262, 234, 72, 26), "UTC -1h", "Instructor: move the clock back one hour to see the bands change.", size=10))
        self.b_up = self.add(Button((1340, 234, 72, 26), "UTC +1h", "Instructor: move the clock forward one hour.", size=10))
        self.b_sm = self.add(Button((1424, 234, 72, 26), "SSN -", "Instructor: lower solar activity (sunspot number) - lowers the MUF.", size=10))
        self.b_sp = self.add(Button((1502, 234, 72, 26), "SSN +", "Instructor: raise solar activity - raises the MUF.", size=10))

    # --------------------------------------------------------------- control
    @property
    def txf(self):
        return self.f + self.split

    def set_freq(self, f, split=0.0, chan=None):
        self.f, self.split, self.chan = max(100.0, min(29999.99, f)), split, chan

    def _turn(self, n):
        st = [0.01, 0.1, 1.0][self.step.idx]
        self.set_freq(round((self.f + n * st) / st) * st, self.split, self.chan)

    def after(self, delay, fn):
        self.pending.append((self.world.t + delay, fn))

    def log(self, msg, col=None):
        self.dsc_log.append((self.world.utc_str()[:5], msg, col or C["lcdfg"]))
        del self.dsc_log[:-30]

    def _key(self, k):
        if k in "0123456789.":
            if len(self.entry) < 8:
                self.entry += k
        elif k == "CLR":
            self.entry = ""
        elif k == "BS":
            self.entry = self.entry[:-1]
        elif k == "T/R":
            if self.split:
                self.set_freq(self.f + self.split, -self.split, self.chan)
        elif self.entry:
            try:
                v = float(self.entry)
            except ValueError:
                v = None
            self.entry = ""
            if v is None:
                return
            if k == "kHz" and 100 <= v < 30000:
                self.set_freq(v)
            elif k == "CH":
                p = itu_channel(int(v))
                if p:
                    self.set_freq(p[1], p[0] - p[1], int(v))
                else:
                    self.mon.note(self.world.utc_str(), "[NO SUCH ITU CHANNEL %d - use e.g. 421, 816, 1221, 1621]" % int(v), C["amber"])

    def handle(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_SPACE:
                self.key_ptt = True
                return True
            ch = ev.unicode
            if ch and ch in "0123456789.":
                self._key(ch)
                return True
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._key("kHz")
                return True
            if ev.key == pygame.K_BACKSPACE:
                self._key("BS")
                return True
            if ev.key in (pygame.K_UP, pygame.K_RIGHT):
                self._turn(1)
                return True
            if ev.key in (pygame.K_DOWN, pygame.K_LEFT):
                self._turn(-1)
                return True
        if ev.type == pygame.KEYUP and ev.key == pygame.K_SPACE:
            self.key_ptt = False
            return True
        if super().handle(ev):
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and pygame.Rect(36, 420, 896, 406).collidepoint(ev.pos):
            off = (ev.pos[0] - 36) / 896.0 * SPAN - SPAN / 2
            self.set_freq(round((self.f + off) * 10) / 10.0, self.split, self.chan)
            return True
        return False

    # ------------------------------------------------------------- reception
    def demod(self, st, p):
        """How one signal comes out of the current demodulator (or None)."""
        m, k = self.mode.value, st["kind"]
        d = (st["f"] - (self.f + self.rit.val / 1000.0)) * 1000.0      # Hz above the dial
        qs = max(0.0, min(1.0, (p["snr"] - 2) / 14.0))
        if k in ("voice", "fax"):
            if m in ("USB", "LSB"):
                if abs(d) > 3200:
                    return None
                inv = m != st["mode"]
                qt = 0.0 if inv else max(0.0, min(1.0, (300 - abs(d)) / 250.0))
                return dict(kind=k, shift=d if m == "USB" else -d, inv=inv, q=qt * qs)
            if m == "AM" and abs(d) < 3500:
                return dict(kind=k, shift=260.0, inv=False, q=0.0)
            return None
        if k in ("wwv", "bc"):
            if m == "AM":
                return dict(kind=k, shift=0.0, inv=False, q=qs) if abs(d) < 3500 else None
            if m in ("USB", "LSB") and abs(d) < 3000:
                return dict(kind=k, shift=d if m == "USB" else -d, inv=False, q=qs * (abs(d) < 40), het=abs(d))
            return None
        if k == "cw":
            if m == "CW" and abs(d) < 400:
                return dict(kind=k, pitch=700 + d, q=qs * (abs(d) < 250))
            pitch = d if m == "USB" else -d
            if m in ("USB", "LSB") and 80 < pitch < 3000:
                return dict(kind=k, pitch=pitch, q=0.0, silent=True)
            return None
        if k in ("navtex", "dsc"):
            if m == "FSK" and abs(d) < 300:
                return dict(kind=k, centre=1700 + d, q=qs * (abs(d) < 120))
            c = d if m == "USB" else -d
            if m in ("USB", "LSB") and 150 < c < 3000:
                return dict(kind=k, centre=c, q=0.0, silent=True)
        return None

    def stations(self):
        w = self.world
        self.temp = [t for t in self.temp if w.t < t["t0"] + t.get("_len", 30.0)]
        return HF_STATIONS + self.temp

    def rx_ok(self, audio=True):
        h = self.world.hh
        ok = h["atu"] and h["rxm"] and h["synth"] and h["ifl"]
        return ok and (not audio or (h["cosc"] and h["pdet"] and h["afo"] and h["spk"]))

    def update(self, dt):
        w, h = self.world, self.world.hh
        for item in list(self.pending):
            if w.t >= item[0]:
                self.pending.remove(item)
                item[1]()
        for k, b in self.keys.items():
            if b.pop():
                self._key(k)
        if self.b_2182.pop():
            self.set_freq(2182.0)
            self.mode.set(0)
        if self.b_rt.pop():
            self.set_freq(HF_RT[self.dband.idx])
            self.mode.set(0)
        if self.b_prev.pop():
            self.pred_i = (self.pred_i - 1) % len(PRED)
            self._pt = -9
        if self.b_next.pop():
            self.pred_i = (self.pred_i + 1) % len(PRED)
            self._pt = -9
        for b, dh in ((self.b_um, -1), (self.b_up, 1)):
            if b.pop():
                w.utc_h = (w.utc_h + dh) % 24
                w._hf_cache.clear()
                self._pt = -9
        for b, ds in ((self.b_sm, -20), (self.b_sp, 20)):
            if b.pop():
                w.ssn = max(0, min(200, w.ssn + ds))
                w._hf_cache.clear()
                self._pt = -9
        if self.b_tune.pop() and h["atu"] and h["synth"]:
            self.tuning_until = w.t + 2.2
            self._tune_f = self.txf
        if self.tuning_until and w.t >= self.tuning_until:
            self.tuning_until = 0.0
            self.atu_f = self._tune_f
            self.flags["atu_tuned"] = w.t
        if self.guard.pop_fired():
            self.send_distress()
        # transmit
        tx = (self.ptt.down or (self.key_ptt and self.app.station is self)) and not self.tuning_until
        if tx != self.tx:
            ui.sfx("relay", 1.0)
        if self.tuning_until and w.t - getattr(self, "_rl", 0) > 0.13:      # tuner relays hunting for a match
            self._rl = w.t
            ui.sfx("relay", 0.45)
        if tx and not self.tx:
            self.tx_t0 = w.t
        if self.tx and not tx:
            self._released(w.t - self.tx_t0)
        self.tx = tx
        txf = self.txf
        det = abs(txf - self.atu_f) / txf if self.atu_f else 1.0
        self.swr = 9.9 if not h["atu"] else min(9.9, 1.15 + max(0.0, det - 0.004) * 260)
        if self.tuning_until:
            k = 1 - (self.tuning_until - w.t) / 2.2
            self.swr = max(1.15, 6.0 * (1 - k) ** 2 + 1.15 + 0.6 * abs(math.sin(k * 20)) * (1 - k))
        pmax = [60.0, 150.0, 400.0][self.pwr.idx]
        chain = all(h[k] for k in ("mic", "afa", "bal", "cosc", "sbf", "synth", "txm", "drv", "pa"))
        if self.tuning_until:
            self.po = 15.0 if chain else 0.0
        elif tx and chain:
            env = 1.0 if self.mode.value in ("AM", "CW", "FSK") or self.b_alarm.on else \
                0.25 + 0.75 * abs(math.sin(w.t * 9.1) * math.sin(w.t * 3.7 + 1))
            self.po = pmax * env * (0.12 if self.swr > 3 else 1.0)
        else:
            self.po = 0.0
        # receive
        frx = self.f + self.rit.val / 1000.0
        self.sigs = []
        answering = {t["f"] for t in self.temp}      # a station replying to us stops its broadcast
        for st in self.stations():
            if "t0" not in st and st["f"] in answering:
                continue
            if abs(st["f"] - self.f) < SPAN / 2 + 3 and w.hf_on(st):
                self.sigs.append((st, w.hf_rx(st)))
        self.noise = w.hf_noise(self.f)
        att = (20 if self.b_att.on else 0) + (1 - self.rf.val) * 40
        tot = 10 ** (self.noise / 10)
        self.active = []
        if self.rx_ok(False) and not tx:
            for st, p in self.sigs:
                dm = self.demod(st, p)
                if dm:
                    tot += 10 ** (p["pr"] / 10)
                    self.active.append((st, p, dm))
            self.s_dbm = 10 * math.log10(tot) - att
        else:
            self.s_dbm = -140.0
        self.active.sort(key=lambda a: -a[1]["pr"])
        if self.rx_ok(True):
            for st, p, dm in self.active[:2]:
                self._caption(st, p, dm)
        self._dsc_watch()
        self._wt += dt
        if self._wt > 0.08:
            self._wt = 0.0
            self._spectrum()

    def voice_pos(self, st):
        """(clip, sample position) of a voice station's transmission right now."""
        sp = Msg.speech
        if st["kind"] != "voice" or sp is None or not sp.ok:
            return None, 0
        clip = sp.get(st["text"], st["name"])
        if clip is None:
            return None, 0
        w = self.world
        if "t0" in st:
            st["_len"] = len(clip) / float(SR) + 1.0
            return clip, int((w.t - st["t0"]) * SR)
        if st["duty"]:
            st["_on"] = len(clip) / float(SR) + 1.0
            return clip, int(((w.t + st.get("_ph", 0)) % st["duty"][0]) * SR)
        return clip, int(w.t * SR) % (len(clip) + int(SR * 1.5))

    def _caption(self, st, p, dm):
        w = self.world
        rate = RATE[st["kind"]]
        if not rate or dm.get("silent"):
            return
        txt = st["text"]
        clip, pos = self.voice_pos(st)
        if clip is not None:
            i = int(pos / float(len(clip)) * len(txt.rstrip()))
            if pos < 0 or i >= len(txt.rstrip()):
                st["_ci"] = None
                return
        elif "t0" in st:
            i = int((w.t - st["t0"]) * rate)
            if i < 0 or i >= len(txt):
                return
        else:
            i = int(w.t * rate)
        last = st.get("_ci")
        if last == i:
            return
        if last is None or i < last or i - last > 12:
            last = i - 1
        st["_ci"] = i
        hdr = "%s  %s  %g kHz  %s  SNR %d dB  via %s" % (w.utc_str(), st["name"], st["f"], s_text(p["pr"]), p["snr"], p["mode"])
        for j in range(last + 1, i + 1):
            ch = garble(txt[j % len(txt)], dm["q"], j)
            self.mon.feed(st["key"] + self.mode.value, hdr, ch, C["lcdfg"] if dm["q"] > 0.6 else C["amber"])
            if dm["q"] > 0.85 and ch != " ":
                self.flags["copy:" + st["name"]] = self.flags.get("copy:" + st["name"], 0) + 1

    def _dsc_watch(self):
        w = self.world
        if not self.rx_ok(False):
            return
        for st in HF_STATIONS:
            if st["kind"] != "dsc":
                continue
            on = w.hf_on(st)
            if on and not self.dsc_seen.get(st["key"]):
                p = w.hf_rx(st)
                if p["snr"] > 8:
                    self.log("RX %g kHz ROUTINE TEST  SNR %d dB" % (st["f"], p["snr"]))
                    ui.sfx("blip", 0.5)
            self.dsc_seen[st["key"]] = on

    def send_distress(self):
        w, h = self.world, self.world.hh
        f = HF_DSC[self.dband.idx]
        if not all(h[k] for k in ("synth", "txm", "drv", "pa", "atu")):
            self.log("TX FAULT - ALERT NOT SENT", C["red"])
            return
        self.atu_f = f
        self.distress = dict(t0=w.t, f=f, acked=False)
        self.flags["hf_distress_sent"] = f
        self.burst_until = w.t + 1.6
        self.log("TX DISTRESS ALERT ON %g kHz" % f, C["red"])
        self.log("  %s %s" % (fmt_lat(w.lat), fmt_lon(w.lon)), C["red"])
        st = next(s for s in HF_STATIONS if s["kind"] == "dsc" and (s["f"] == f or (f > 3000 and s["f"] > 3000)))
        p = w.hf_path(st["lat"], st["lon"], f, 0.4 if self.pwr.idx == 2 else 0.15)
        d = self.distress

        def ack():
            if d is not self.distress:
                return
            if p["snr"] > 8:
                d["acked"] = True
                self.flags["hf_distress_acked"] = f
                ui.sfx("beep2")
                self.log("RX DISTRESS ACK ON %g kHz" % f, C["yellow"])
                self.log("  COAST STATION %d km  SNR %d dB" % (p["d"], p["snr"]), C["yellow"])
                self.log("  GO TO R/T %g kHz - SEND MAYDAY" % HF_RT[self.dband.idx], C["yellow"])
            else:
                ui.sfx("error")
                self.log("NO ACK ON %g kHz (SNR %d dB AT COAST)" % (f, p["snr"]), C["amber"])
                self.log("  PATH CLOSED - TRY ANOTHER BAND", C["amber"])
        self.after(9, ack)

    def _released(self, dur):
        w = self.world
        if dur < 1.5:
            return
        txf, m = self.txf, self.mode.value
        self.mon.note("%s  TX %g kHz %s  %d W  SWR %.1f" % (w.utc_str(), txf, EMISSION[m], self.po if self.po else 0, self.swr),
                      "[YOU TRANSMITTED FOR %.0f s]" % dur, C["cyan"])
        if not all(w.hh[k] for k in ("mic", "afa", "bal", "cosc", "sbf", "synth", "txm", "drv", "pa")):
            self.mon.note(w.utc_str(), "[NO RF OUTPUT - TRANSMITTER FAULT. Investigate on the CIRCUITS bench.]", C["red"])
            return
        if self.swr > 3:
            self.mon.note(w.utc_str(), "[HIGH SWR %.1f - PA PROTECTION FOLDED POWER BACK. Press TUNE on this frequency first.]" % self.swr, C["red"])
            return
        if m != "USB" or dur < 3:
            return
        self.flags["hf_tx_%g" % txf] = w.t
        pw = [0.06, 0.15, 0.4][self.pwr.idx]
        best = None
        for st in HF_STATIONS:
            if st["kind"] != "voice" or "WX" in st["name"]:
                continue
            pair = st["f"]
            for band, (s0, c0) in ITU_BANDS.items():
                if c0 <= st["f"] < c0 + 180:
                    pair = st["f"] - c0 + s0
            if abs(pair - txf) < 0.06 and (best is None or abs(st["f"] - self.f) < abs(best[0]["f"] - self.f)):
                best = (st, w.hf_path(st["lat"], st["lon"], txf, pw))
        if not best:
            self.mon.note(w.utc_str(), "[NO REPLY - no station keeps watch on %g kHz. Coast stations listen on the "
                          "SHIP frequency paired with their channel: enter the ITU channel number then CH.]" % txf, C["amber"])
            return
        st, p = best
        if p["snr"] < 6:
            self.mon.note(w.utc_str(), "[NO REPLY - your signal reached %s only %d dB above noise (path: %s, MUF %.1f MHz). "
                          "Choose a band below the MUF with less absorption.]" % (st["name"], p["snr"], p["mode"], p["muf"]), C["amber"])
            return
        rd = 5 if p["snr"] > 22 else (4 if p["snr"] > 14 else 3)
        self.flags["hf_contact:" + st["name"]] = w.t
        self.flags["hf_contact"] = w.t
        self.temp.append(dict(name=st["name"], lat=st["lat"], lon=st["lon"], f=st["f"], mode="USB", pkw=st["pkw"],
                              kind="voice", duty=None, key="rep%d" % int(w.t), t0=w.t + 3.0,
                              text="%s, %s, THIS IS %s. GOOD %s. READING YOU STRENGTH %d. PASS YOUR MESSAGE. OVER.   "
                              % (w.name, w.name, st["name"], "EVENING" if w.utc_h > 17 or w.utc_h < 4 else "DAY", rd)))

    # -------------------------------------------------------------- spectrum
    def _spectrum(self):
        w, rng = self.world, self.rng
        fa = self.f + (np.arange(NB) - NB / 2 + 0.5) * SPAN / NB
        line = self.noise - 15 + rng.normal(0, 2.2, NB)
        if self.world.hh["rxm"] and self.world.hh["synth"] and self.world.hh["atu"]:
            for st, p in self.sigs:
                fc, pr, k = st["f"], p["pr"], st["kind"]
                if k in ("voice", "fax"):
                    lo, hi = (0.3, 2.7) if k == "voice" else (1.5, 2.3)
                    sgn = 1 if st["mode"] == "USB" else -1
                    mk = ((fa - fc) * sgn > lo) & ((fa - fc) * sgn < hi)
                    talk = math.sin(w.t * 3.1 + fc) + 0.6 * math.sin(w.t * 1.3) > -0.5 or k == "fax"
                    if talk:
                        line[mk] = np.maximum(line[mk], pr - 8 - rng.uniform(0, 16, int(mk.sum())))
                elif k in ("wwv", "bc"):
                    mk = np.abs(fa - fc) < (4.5 if k == "bc" else 1.2)
                    line[mk] = np.maximum(line[mk], pr - 16 - rng.uniform(0, 14, int(mk.sum())) - np.abs(fa[mk] - fc) * 3)
                    line[np.argmin(np.abs(fa - fc))] = pr
                elif k == "cw":
                    if self.app.audio.syn.morse_on(st["text"], w.t):
                        line[np.argmin(np.abs(fa - fc))] = pr
                else:
                    for off in (-0.085, 0.085):
                        if rng.random() < 0.7:
                            line[np.argmin(np.abs(fa - fc - off))] = pr - 2
            if self.tx or self.tuning_until:
                mk = (fa > self.txf + (0 if self.tuning_until else 0.3)) & (fa < self.txf + (0.06 if self.tuning_until else 2.7))
                line[mk] = -30 - rng.uniform(0, 12, int(mk.sum()))
            line -= (20 if self.b_att.on else 0)
        else:
            line[:] = -150
        self.line = line
        self.wf[:, 1:] = self.wf[:, :-1]
        self.wf[:, 0] = np.clip((line - (self.noise - 21) + (20 if self.b_att.on else 0)) / 78.0 * 255, 0, 255).astype(np.uint8)

    # ----------------------------------------------------------------- audio
    def bg_audio(self, syn, n):
        if self.world.t < getattr(self, "burst_until", 0):
            return syn.fsk("hfdsc", n, 100, 1700.0, 170.0) * 0.5
        return None

    def audio(self, syn, n):
        if self.tx:
            return syn.alarm("hfal", n) * 0.3 if self.b_alarm.on else None
        if self.tuning_until:
            return syn.osc("hftune", 800.0, n) * 0.15
        if not self.rx_ok(True):
            return None
        out = syn.noise(n) * (0.25 + 0.3 * self.rf.val)
        for st, p, dm in self.active[:3]:
            g = min(1.0, 10 ** ((p["snr"] - 16) / 20.0)) * 1.4
            k, key = dm["kind"], "h" + st["key"]
            clip, pos = self.voice_pos(st) if k == "voice" else (None, 0)
            if clip is not None:
                cur = st.get("_cur")
                if cur is None or abs(cur - pos) > SR * 0.3:
                    cur = pos
                st["_cur"] = cur + n
                z = chunk(clip, cur, n)
                f = (3000.0 + dm["shift"]) if dm["inv"] else dm["shift"]
                ph = st.get("_ph2", 0.0) + 2 * np.pi * f / SR * np.arange(1, n + 1)
                st["_ph2"] = float(ph[-1] % (2 * np.pi))
                a = ((np.conj(z) if dm["inv"] else z) * np.exp(1j * ph)).real * 1.3
            elif k == "voice":
                a = syn.voice(key, n, dm["shift"], dm["inv"]) * 1.5
            elif k == "fax":
                a = syn.fax(key, n, dm["shift"])
            elif k == "wwv":
                a = syn.tick(key, n, dm["shift"])
            elif k == "bc":
                a = syn.music(key, n)
            elif k == "cw":
                a = syn.morse(key, st["text"], n, max(60.0, dm["pitch"]))
            else:
                a = syn.fsk(key, n, 100, max(100.0, dm["centre"]), 170.0)
            if dm.get("het", 0) > 30:
                a = a + syn.osc(key + "het", dm["het"], n) * 0.35
            out = out + a * g
        return out * self.af.val

    # ------------------------------------------------------------------ draw
    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if pygame.Rect(20, 392, 930, 468).collidepoint(pos):
            return ("SPECTRUM SCOPE + WATERFALL: 24 kHz around the dial. The shaded strip is the receiver "
                    "passband for the current mode. Click to tune. SSB voices sit ABOVE their carrier frequency (USB).")
        if pygame.Rect(960, 212, 630, 300).collidepoint(pos):
            return ("PROPAGATION: predicted signal vs frequency for the chosen station right now, and the "
                    "MUF over 24 h. Above the MUF the wave passes through the ionosphere; far below it the "
                    "daytime D-layer absorbs it. Work just below the MUF.")
        if pygame.Rect(960, 520, 630, 340).collidepoint(pos):
            return "RECEIVE MONITOR: caption/decoder output. Amber '~' text = not intelligible: check sideband, tuning (clarifier) and band."
        return ""

    def draw(self, s):
        w, h = self.world, self.world.hh
        ui.panel(s, (20, 54, 930, 330), "MF/HF SSB TRANSCEIVER  1.6 - 27.5 MHz  400 W PEP  +  AUTOMATIC ANTENNA TUNER")
        ui.panel(s, (20, 392, 930, 468), "SPECTRUM SCOPE / WATERFALL   span 24 kHz")
        ui.panel(s, (960, 54, 630, 150), "MF/HF DSC  -  6-FREQUENCY SCANNING WATCH RECEIVER")
        ui.panel(s, (960, 212, 630, 300), "PROPAGATION PREDICTION")
        ui.panel(s, (960, 520, 630, 340), "RECEIVE MONITOR / DECODER")
        fg = C["lcdfg"]
        l = ui.lcd(s, (36, 80, 430, 150))
        lock = h["synth"]
        ftxt = ("%9.2f" % (self.txf if self.tx else self.f)) if lock else " UNLOCK  "
        text(s, ftxt, (l.x + 10, l.y + 4), 52, fg if not self.tx else C["red"], bold=True)
        text(s, "kHz", (l.x + 318, l.y + 34), 16, fg, bold=True)
        text(s, "%s %s" % (self.mode.value, EMISSION[self.mode.value]), (l.x + 362, l.y + 10), 13, C["amber"], bold=True)
        text(s, "TX" if self.tx else "RX", (l.x + 362, l.y + 30), 16, C["red"] if self.tx else fg, bold=True)
        text(s, "TX %9.2f kHz  %s" % (self.txf, "DUPLEX" if self.split else "SIMPLEX"), (l.x + 12, l.y + 66), 13, fg)
        text(s, "CH %s" % (self.chan if self.chan else "---"), (l.x + 300, l.y + 66), 13, fg)
        tuned = self.atu_f and abs(self.txf - self.atu_f) / self.txf < 0.004
        text(s, "ATU " + ("TUNING.." if self.tuning_until else ("TUNED" if tuned else "TUNE REQUIRED")), (l.x + 12, l.y + 86), 13,
             fg if tuned else C["amber"], bold=True)
        text(s, "CLAR %+d Hz" % self.rit.val, (l.x + 200, l.y + 86), 13, fg)
        text(s, "PWR %s" % self.pwr.value.split()[1], (l.x + 320, l.y + 86), 13, fg)
        wl = 299792.458 / self.f
        text(s, "wavelength %.1f m   band noise %d dBm" % (wl, self.noise), (l.x + 12, l.y + 106), 11, C["dim"])
        text(s, "ENTRY> " + self.entry + ("_" if int(w.t * 2) % 2 else " "), (l.x + 12, l.y + 126), 14, C["yellow"], bold=True)
        # meter
        sel = self.meter_sel.value
        r = (478, 80, 180, 112)
        if sel == "S":
            ui.meter(s, r, s_units(self.s_dbm) / 15.0, "S-METER  %s" % s_text(self.s_dbm),
                     [(1 / 15, "1"), (3 / 15, "3"), (5 / 15, "5"), (7 / 15, "7"), (9 / 15, "9"), (11.5 / 15, "+20"), (14 / 15, "+40")], red_from=0.6)
        elif sel == "PO":
            ui.meter(s, r, self.po / 500.0, "FWD POWER  %d W" % self.po, [(0, "0"), (0.2, "100"), (0.4, "200"), (0.6, "300"), (0.8, "400"), (1, "500")])
        elif sel == "SWR":
            v = self.swr if (self.tx or self.tuning_until) else 1.0
            ui.meter(s, r, (v - 1) / 4.0, "SWR  %.1f : 1" % v, [(0, "1"), (0.125, "1.5"), (0.25, "2"), (0.5, "3"), (1, "5")], red_from=0.5)
        else:
            ic = self.po / 13.6 / 0.5 if self.po else (0.0)
            ui.meter(s, r, ic / 80.0, "PA CURRENT  %d A" % ic, [(0, "0"), (0.25, "20"), (0.5, "40"), (0.75, "60"), (1, "80")])
        ui.led(s, (674, 206), "red", self.tx and self.po > 1, "ON AIR", 5)
        ui.led(s, (674, 224), "amber", (self.tx or bool(self.tuning_until)) and self.swr > 3, "HI SWR", 5)
        # spectrum
        r = ui.crt(s, (36, 420, 896, 130), (3, 7, 10), (20, 40, 60))
        lo, hi = PASS[self.mode.value]
        rit = self.rit.val / 1000.0
        x0 = r.x + (lo + rit + SPAN / 2) / SPAN * r.w
        x1 = r.x + (hi + rit + SPAN / 2) / SPAN * r.w
        pygame.draw.rect(s, (30, 52, 40), (x0, r.y, max(2, x1 - x0), r.h))
        for i in range(-12, 13, 2):
            x = r.x + (i + SPAN / 2) / SPAN * r.w
            pygame.draw.line(s, (26, 36, 44), (x, r.y), (x, r.bottom), 1)
            ui.legend(s, "%g" % (self.f + i), (x, 836), 10)
        for db in (-120, -100, -80, -60):
            y = r.bottom - (db + 132) / 100.0 * r.h
            pygame.draw.line(s, (26, 36, 44), (r.x, y), (r.right, y), 1)
            text(s, "%d" % db, (r.x + 3, y - 12), 9, C["dim"])
        pts = [(r.x + (i + 0.5) / NB * r.w, r.bottom - max(0, min(1, (v + 132) / 100.0)) * r.h) for i, v in enumerate(self.line)]
        pygame.draw.lines(s, C["yellow"], False, pts, 1)
        cxm = r.x + r.w / 2
        pygame.draw.line(s, C["red"], (cxm, r.y), (cxm, r.bottom), 1)
        text(s, "DIAL (carrier)", (cxm + 4, r.y + 2), 9, C["red"], bold=True)
        text(s, "PASSBAND", (x0 + 2, r.bottom - 12), 9, C["green"], bold=True)
        ui.crt(s, (36, 556, 896, WH * 2), (2, 3, 8), (16, 24, 60), gain=110)
        pygame.surfarray.blit_array(self.wsurf, self.wf)
        s.blit(pygame.transform.scale(self.wsurf, (896, WH * 2)), (36, 556))
        pygame.draw.line(s, C["red"], (cxm, 556), (cxm, 556 + WH * 2), 1)
        for st, p in self.sigs:
            x = r.x + (st["f"] - self.f + SPAN / 2) / SPAN * r.w
            if r.x + 40 < x < r.right - 40 and p["snr"] > 3:
                text(s, st["name"].split(" (")[0][:16], (x, 560 + (hash(st["key"]) % 3) * 12), 9, C["white"], bold=True, align="c")
        # DSC
        l = ui.lcd(s, (976, 80, 360, 112))
        scan = HF_DSC[int(w.t * 2) % 6]
        text(s, "SCAN %7.1f kHz   MMSI %d" % (scan, w.mmsi), (l.x + 8, l.y + 5), 11, fg, bold=True)
        lines = self.dsc_log[-5:]
        if not lines:
            text(s, "WATCH: 2187.5 4207.5 6312 8414.5", (l.x + 8, l.y + 26), 11, C["dim"])
            text(s, "       12577 16804.5 kHz", (l.x + 8, l.y + 42), 11, C["dim"])
        for i, (tm, msg, col) in enumerate(lines):
            text(s, ("" if msg.startswith("  ") else tm + " ") + msg.strip()[:42], (l.x + 8, l.y + 24 + i * 17), 11, col, bold=True)
        text(s, "R/T %g" % HF_RT[self.dband.idx], (1466, 107), 9, C["dim"], bold=True)
        self._draw_pred(s)
        self.mon.draw(s, (976, 546, 598, 302), 12)
        super().draw(s)

    def _draw_pred(self, s):
        w = self.world
        name = PRED[self.pred_i]
        text(s, name, (1113, 247), 13, C["amber"], bold=True, align="m")
        sts = [st for st in HF_STATIONS if st["name"] == name]
        st0 = sts[0]
        if w.t - self._pt > 1.0:
            self._pt = w.t
            fs = np.arange(1.6, 26.01, 0.4)
            cur = [w.hf_path(st0["lat"], st0["lon"], f * 1000, st0["pkw"]) for f in fs]
            day = [w.hf_path(st0["lat"], st0["lon"], 8000, st0["pkw"], utc_h=hh)["muf"] for hh in range(25)]
            self._pred = (fs, cur, day, [w.hf_path(st["lat"], st["lon"], st["f"], st["pkw"]) for st in sts])
        fs, cur, day, own = self._pred
        r = ui.crt(s, (1012, 290, 560, 110), (3, 7, 10), (20, 40, 60))

        def fx(f):
            return r.x + (f - 1.6) / 24.4 * r.w

        def sy(dbm):
            return r.bottom - max(0, min(1, s_units(dbm) / 15.0)) * r.h

        muf = cur[0]["muf"]
        pygame.draw.rect(s, (34, 8, 8), (fx(min(26, muf)), r.y, r.right - fx(min(26, muf)), r.h))
        for sv, lab in ((1, "S1"), (5, "S5"), (9, "S9"), (12.33, "+20")):
            y = r.bottom - sv / 15.0 * r.h
            pygame.draw.line(s, (26, 36, 44), (r.x, y), (r.right, y), 1)
            text(s, lab, (r.x - 9, y - 6), 9, C["dim"], align="r")
        for f in (2, 4, 6, 8, 12, 16, 22):
            pygame.draw.line(s, (26, 36, 44), (fx(f), r.y), (fx(f), r.bottom), 1)
            text(s, "%d" % f, (fx(f), r.bottom - 12), 9, (90, 130, 150), align="c")
        text(s, "MHz", (r.right - 4, r.bottom - 12), 9, (90, 130, 150), align="r")
        pygame.draw.lines(s, (150, 70, 70), False, [(fx(f), sy(p["noise"])) for f, p in zip(fs, cur)], 1)
        pygame.draw.lines(s, C["green"], False, [(fx(f), sy(p["pr"])) for f, p in zip(fs, cur)], 2)
        if muf < 26:
            text(s, "MUF %.1f" % muf, (fx(muf) + 3, r.y + 2), 9, C["red"], bold=True)
        best = None
        for st, p in zip(sts, own):
            x, y = fx(st["f"] / 1000.0), sy(p["pr"])
            pygame.draw.circle(s, C["yellow"], (x, y), 4)
            if best is None or p["snr"] > best[1]["snr"]:
                best = (st, p)
        p0 = cur[0]
        text(s, "%d km  brg %03d°  %s  foF2 %.1f  %s" % (p0["d"], p0["brg"], "DAY PATH" if p0["day"] > 0 else "NIGHT PATH", p0["fof2"],
             "SSN %d" % w.ssn), (r.x, 270), 10, C["text"])
        # 24 h MUF strip
        r2 = ui.crt(s, (1012, 436, 560, 46), (3, 7, 10), (20, 40, 60))
        mx = 30.0
        pts = [(r2.x + hh / 24.0 * r2.w, r2.bottom - min(1, m / mx) * r2.h) for hh, m in enumerate(day)]
        pygame.draw.polygon(s, (24, 60, 44), pts + [(r2.right, r2.bottom), (r2.x, r2.bottom)])
        pygame.draw.lines(s, C["green"], False, pts, 2)
        x = r2.x + (w.utc_h % 24) / 24.0 * r2.w
        pygame.draw.line(s, C["yellow"], (x, r2.y), (x, r2.bottom), 2)
        for hh in range(0, 25, 6):
            text(s, "%02d" % (hh % 24), (r2.x + 10 + hh / 24.0 * (r2.w - 20), r2.bottom + 8), 9, C["dim"], align="c")
        text(s, "MUF over 24 h UTC (max %d MHz)" % max(day), (r2.x + 4, r2.y + 2), 9, C["dim"], bold=True)
        text(s, "30", (r2.x - 9, r2.y - 2), 9, C["dim"], align="r")
        if best:
            st, p = best
            col = C["green"] if p["snr"] > 12 else (C["amber"] if p["snr"] > 4 else C["red"])
            text(s, "BEST NOW: %g kHz  %s  SNR %d dB  %s" % (st["f"], s_text(p["pr"]), p["snr"], p["mode"]), (1012, 412), 11, col, bold=True)
