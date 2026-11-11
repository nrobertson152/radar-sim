"""Marine navigation radar (X/S band) with a physically-based picture.

Every antenna bearing produces a range profile from the radar equation:
targets (R^-4), land, sea clutter, rain clutter and rain attenuation,
receiver noise, tuning loss, then STC -> gain/threshold -> FTC, exactly in
the order the real receiver applies them. The profile is painted on a
decaying 'phosphor' buffer by the rotating sweep.
"""
import math
import numpy as np
import pygame
from . import ui, fx
from .ui import C, text, Knob, Selector, Button, Station
from .world import wrap180

RANGES = [0.25, 0.5, 0.75, 1.5, 3, 6, 12, 24, 48]
RINGS = {0.25: 0.05, 0.5: 0.1, 0.75: 0.25, 1.5: 0.25, 3: 0.5, 6: 1, 12: 2, 24: 4, 48: 8}
# pulse: (length us, PRF Hz, system constant dB, IF bandwidth MHz)
PULSES = {"SHORT": (0.08, 2000, 29.0, 12.0), "MEDIUM": (0.3, 1000, 35.0, 5.0), "LONG": (1.0, 500, 40.0, 3.0)}
HEALTH = ["psu", "trig", "mod", "mag", "dup", "ant", "trl", "mix", "lo", "ifa", "det", "vid", "afc", "stc", "dsp"]


class Radar(Station):
    name = "RADAR"
    hint = ("Drag knobs or use the wheel (SHIFT = fine). Click a target on the PPI to acquire it "
            "(ARPA), right-click to drop. Hover any control for an explanation.")
    CX, CY, R = 384, 456, 340

    def __init__(self, app):
        super().__init__(app)
        w = self.world
        if not hasattr(w, "rh"):
            w.rh = {k: True for k in HEALTH}
        self.rng = np.random.default_rng(11)
        self.NR = self.R
        self._build_lut()
        self.ri = 5
        self.ang = 0.0
        self.warm = 0.0
        self.drift, self.afc_corr = 4.0, 0.0
        self.tune_ind = 0.0
        self.tracks, self.sel = [], None
        self.ascan = (np.zeros(self.NR), np.zeros(self.NR))
        self.iph = 0
        self.cpa_alarm = False
        self.tinfo = []
        self.last_power = "OFF"

        y = 132
        self.power = self.add(Selector(820, y, 22, "POWER", ["OFF", "STBY", "TX"], 0,
            "POWER: OFF / STAND-BY / TRANSMIT. From OFF the magnetron heater needs a warm-up "
            "(3 min on a real set, 20 s here) before TX is allowed."))
        self.band = self.add(Selector(905, y, 22, "BAND", ["X 9410", "S 3050"], 0,
            "BAND: X-band (3 cm, 9410 MHz): sharper bearing discrimination, sees SARTs, but more sea "
            "and rain clutter. S-band (10 cm, 3050 MHz): penetrates rain, less clutter, cannot trigger a SART."))
        self.pulse = self.add(Selector(990, y, 22, "PULSE", ["SHORT", "MEDIUM", "LONG"], 1,
            "PULSE LENGTH: SHORT 0.08 us (best range discrimination and minimum range, least clutter), "
            "LONG 1.0 us (most energy on target = longest detection range, but smears echoes and more clutter)."))
        self.tune = self.add(Knob(1075, y, 22, "TUNE", 0, 1, 0.5,
            "TUNE: sets the local oscillator so the mixer output sits on the 60 MHz IF. Peak the "
            "TUNE bar. The magnetron drifts as it warms, so re-check, or switch AFC on."))
        self.afc = self.add(Button((1120, 112, 54, 40), "AFC", "AFC: automatic frequency control "
            "locks the local oscillator to the magnetron. Manual TUNE is ignored while AFC is on.", toggle=True))
        y = 290
        self.gain = self.add(Knob(820, y, 22, "GAIN", 0, 1, 0.25,
            "GAIN: IF amplifier gain. Correct setting = a light background speckle of noise just "
            "visible. Too low loses weak targets, too high floods the picture with noise."))
        self.stc = self.add(Knob(905, y, 22, "SEA (STC)", 0, 1, 0.0,
            "ANTI-CLUTTER SEA (Sensitivity Time Control): reduces gain at short range, recovering "
            "with range. Use just enough to break up sea clutter - too much erases close targets."))
        self.ftc = self.add(Knob(990, y, 22, "RAIN (FTC)", 0, 1, 0.0,
            "ANTI-CLUTTER RAIN (Fast Time Constant): differentiates the video so only the leading "
            "edge of long echoes survives. Breaks up rain blocks to reveal targets inside them."))
        self.brill = self.add(Knob(1075, y, 22, "BRILL", 0.2, 1.6, 1.0, "BRILLIANCE: display brightness only."))
        bx, bw_, st = 1130, 52, 57
        self.ir = self.add(Button((bx, 250, bw_, 36), "IR", "INTERFERENCE REJECTION: removes the "
            "spiral dotted pattern caused by other radars on the same band.", toggle=True))
        self.es = self.add(Button((bx + st, 250, bw_, 36), "ES", "ECHO STRETCH: lengthens echoes in "
            "range so small targets are easier to see (reduces range discrimination).", toggle=True))
        self.eav = self.add(Button((bx + 2 * st, 250, bw_, 36), "EAV", "ECHO AVERAGING: averages successive "
            "sweeps. Sea clutter changes from sweep to sweep and fades; a real target is there every time "
            "and stays bright. Slows the response to fast targets.", toggle=True))
        self.trails = self.add(Button((bx + 3 * st, 250, bw_, 36), "TRAILS", "TARGET TRAILS: afterglow "
            "showing where echoes have been - shows relative motion at a glance.", toggle=True, size=10))
        self.rings = self.add(Button((bx + 4 * st, 250, bw_, 36), "RINGS", "Fixed RANGE RINGS on/off.",
                                     toggle=True, on=True, size=10))
        self.hl = self.add(Button((bx + 5 * st, 250, bw_, 36), "HL\nOFF", "HEADING LINE OFF: hold to "
            "blank the heading line and check for a small target hidden under it.", size=10))
        self.ebl_on = self.add(Button((bx, 294, bw_, 36), "EBL", "Electronic Bearing Line on/off.",
                                      toggle=True, on=True))
        self.vrm_on = self.add(Button((bx + st, 294, bw_, 36), "VRM", "Variable Range Marker on/off.",
                                      toggle=True, on=True))
        self.nup = self.add(Button((bx + 2 * st, 294, bw_, 36), "N UP", "Orientation: lit = NORTH-UP "
            "(gyro stabilised, true bearings). Off = HEAD-UP (unstabilised, relative bearings; the "
            "picture smears when the ship yaws).", toggle=True))
        self.pi_b = self.add(Button((bx + 3 * st, 294, bw_, 36), "CLEAR", "Clear the picture memory (trails and averaging).", size=10))
        self.drop = self.add(Button((bx + 4 * st, 294, bw_, 36), "DROP\nALL", "Cancel all ARPA tracked targets.", size=10))
        self.ack = self.add(Button((bx + 5 * st, 294, bw_, 36), "ALARM\nACK", "Acknowledge the CPA/TCPA "
                                   "collision alarm.", size=10, color="red"))
        self.rdn = self.add(Button((1480, 250, 48, 80), "RANGE\n-", "Decrease range scale."))
        self.rup = self.add(Button((1534, 250, 48, 80), "RANGE\n+", "Increase range scale."))
        y = 448
        self.ebl = self.add(Knob(820, y, 22, "EBL", 0, 360, 45, "EBL: rotate the electronic bearing "
            "line through a target to read its bearing. The A-SCAN below shows the video along this line.",
            wrap=True, fmt=lambda v: "%05.1f°" % v))
        self.vrm = self.add(Knob(905, y, 22, "VRM", 0, 1, 0.5, "VRM: adjust the range marker to "
            "the NEAR edge of an echo to read its range.",
            fmt=lambda v: "%.2f nm" % (v * RANGES[self.ri])))
        self.hdg = self.add(Knob(1030, y, 22, "HEADING", 0, 360, w.hdg, "Own ship heading (helm). "
            "Alter course and watch relative motion change.", wrap=True, step=1,
            fmt=lambda v: "%03d°" % v))
        self.spd = self.add(Knob(1115, y, 22, "SPEED", 0, 30, w.spd, "Own ship speed (knots).",
                                 step=0.5, fmt=lambda v: "%.1f kn" % v))
        self.sea = self.add(Knob(1240, y, 22, "SEA STATE", 0, 7, w.sea, "INSTRUCTOR: sea state "
            "0 (calm) to 7 (high). Sea clutter is strongest close in and to windward.", step=1,
            fmt=lambda v: "SS %d" % v))
        self.rain_b = self.add(Button((1300, 410, 82, 34), "RAIN", "INSTRUCTOR: put rain squalls "
            "in the area. Rain returns are strong on X-band and attenuate what lies behind them.", toggle=True))
        self.sart_b = self.add(Button((1300, 452, 82, 34), "SART", "INSTRUCTOR: activate a Search "
            "And Rescue Transponder nearby. It answers X-band radar pulses with a line of 12 dots.",
            toggle=True, color="red"))
        self.int_b = self.add(Button((1390, 410, 82, 34), "INTERF", "INSTRUCTOR: another radar on "
            "the same band causes interference. Remove it with IR.", toggle=True))
        self.sol_b = self.add(Button((1390, 452, 82, 34), "NAMES", "INSTRUCTOR: label the true "
            "position of every contact (training aid).", toggle=True))

    # ------------------------------------------------------------- display
    def _build_lut(self):
        R = self.R
        D = self.D = 2 * R + 1
        xx, yy = np.mgrid[0:D, 0:D]
        dx, dy = xx - R, yy - R
        rr = np.sqrt(dx * dx + dy * dy)
        b = ((np.degrees(np.arctan2(dx, -dy)) % 360) * 2).astype(np.int32) % 720
        idx = np.flatnonzero((rr < R).ravel())
        bb = b.ravel()[idx]
        order = np.argsort(bb, kind="stable")
        self.pix = idx[order]
        self.prb = rr.ravel()[idx][order].astype(np.int32)
        self.starts = np.searchsorted(bb[order], np.arange(721))
        self.E = np.zeros((D, D), dtype=np.float32)
        self.T = np.zeros((D, D), dtype=np.float32)
        self.Ef, self.Tf = self.E.reshape(-1), self.T.reshape(-1)
        self.surf = pygame.Surface((D, D), 0, 8)
        pal = []
        bg = np.array([2, 9, 6.0])
        for i in range(256):                      # P7-style phosphor: white-hot flash, green afterglow
            e, t = (i & 63) / 63.0, (i >> 6) / 3.0
            col = bg + np.array([10, 46, 74.0]) * t * 0.9
            glow = np.array([30, 235, 96.0]) * e ** 0.85 + np.array([150, 20, 90.0]) * e ** 4.0
            pal.append(tuple(int(min(255, v)) for v in col * (1 - e ** 0.7) + glow))
        self.surf.set_palette(pal)
        # cast housing with a raised, edge-lit bearing ring
        hw, hh = 768, ui.BOT - ui.TOP
        cx, cy = self.CX, self.CY - ui.TOP
        bz = fx.radar_housing(hw, hh, cx, cy, R, ui.TOP).copy()
        lay = pygame.Surface((hw, hh), pygame.SRCALPHA)
        ink = (255, 214, 150)
        for d in range(0, 360):
            a = math.radians(d)
            ln = 11 if d % 10 == 0 else (7 if d % 5 == 0 else 4)
            pygame.draw.line(lay, ink, (cx + math.sin(a) * (R + 9), cy - math.cos(a) * (R + 9)),
                             (cx + math.sin(a) * (R + 9 + ln), cy - math.cos(a) * (R + 9 + ln)), 2 if d % 10 == 0 else 1)
            if d % 30 == 0:
                text(lay, "%03d" % d, (cx + math.sin(a) * (R + 27), cy - math.cos(a) * (R + 27)),
                     10, ink, bold=True, align="m")
        soft = pygame.transform.smoothscale(pygame.transform.smoothscale(lay, (hw // 4, hh // 4)), (hw, hh))
        soft.fill((255, 120, 40, 150), special_flags=pygame.BLEND_RGBA_MULT)
        bz.blit(soft, (0, 0))
        bz.blit(lay, (0, 0))
        for i, (px, py) in enumerate(((16, 130), (752, 130), (16, 700), (752, 700), (384, 14), (384, hh - 14))):
            sc = fx.screw(i)
            bz.blit(sc, (px - 6, py - 6))
        flat = pygame.Surface((hw, hh))
        flat.fill((255, 0, 255))
        flat.blit(bz, (0, 0))
        flat = fx._fast(flat)
        flat.set_colorkey((255, 0, 255), pygame.RLEACCEL)     # tube opening: fast colour-keyed hole
        self.bezel = flat

    def clear(self):
        self.E[:] = 0
        self.T[:] = 0

    @property
    def rmax(self):
        return RANGES[self.ri]

    @property
    def rot(self):
        return 0.0 if self.nup.on else self.world.hdg

    def to_xy(self, rng, brg):
        a = math.radians(brg - self.rot)
        k = rng / self.rmax * self.R
        return self.CX + math.sin(a) * k, self.CY - math.cos(a) * k

    def from_xy(self, pos):
        dx, dy = pos[0] - self.CX, pos[1] - self.CY
        return math.hypot(dx, dy) / self.R * self.rmax, (math.degrees(math.atan2(dx, -dy)) + self.rot) % 360

    # --------------------------------------------------------------- state
    @property
    def transmitting(self):
        return self.power.value == "TX" and self.warm <= 0

    @property
    def tx_ok(self):
        h = self.world.rh
        return self.transmitting and all(h[k] for k in ("psu", "trig", "mod", "mag", "dup"))

    @property
    def rx_ok(self):
        h = self.world.rh
        return all(h[k] for k in ("psu", "dup", "mix", "lo", "ifa", "det", "vid"))

    @property
    def disp_ok(self):
        h = self.world.rh
        return self.power.value != "OFF" and h["psu"] and h["dsp"]

    def handle(self, ev):
        if super().handle(ev):
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3):
            if math.hypot(ev.pos[0] - self.CX, ev.pos[1] - self.CY) < self.R and self.transmitting:
                best, bd = None, 16
                for c, rng, brg in self.tinfo:
                    if c.kind == "sart" or rng > self.rmax:
                        continue
                    x, y = self.to_xy(rng, brg)
                    d = math.hypot(x - ev.pos[0], y - ev.pos[1])
                    if d < bd:
                        best, bd = c, d
                if best:
                    tr = next((t for t in self.tracks if t["c"] is best), None)
                    if ev.button == 3:
                        if tr:
                            self.tracks.remove(tr)
                            self.sel = None if self.sel is tr else self.sel
                    elif tr:
                        self.sel = tr
                    elif len(self.tracks) < 10:
                        ui.sfx("acquire")
                        self.sel = dict(c=best, t0=self.world.t, n=1 + max([t["n"] for t in self.tracks] + [0]))
                        self.tracks.append(self.sel)
                return True
        return False

    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if math.hypot(pos[0] - self.CX, pos[1] - self.CY) < self.R:
            return ("PPI: bright yellow = echoes, blue = trails. Left-click an echo to ACQUIRE it "
                    "(ARPA plots it for ~10 s then shows course, speed, CPA and TCPA). Right-click to drop.")
        if pygame.Rect(770, 520, 500, 340).collidepoint(pos):
            return ("A-SCAN: receiver video along the EBL. Grey = signal before the threshold (dB "
                    "above noise), orange = gain reduction applied by STC, green = final video sent to the display.")
        return ""

    # -------------------------------------------------------------- update
    def update(self, dt):
        w, h = self.world, self.world.rh
        p = self.power.value
        if p != self.last_power:
            if self.last_power == "OFF":
                self.warm = 20.0
            if p != "TX":
                self.clear()
            self.last_power = p
        if p == "OFF":
            self.warm = 20.0
        elif self.warm > 0 and h["psu"]:
            self.warm -= dt
            if self.warm <= 0:
                ui.sfx("warm")
        if self.transmitting != getattr(self, "_was_tx", False):
            self._was_tx = self.transmitting
            ui.sfx("relay", 1.0)
        w.hdg, w.spd, w.sea = self.hdg.val % 360, self.spd.val, int(self.sea.val)
        w.interference = self.int_b.on
        if self.rain_b.pop():
            w.rain = [[w.x + 3.5, w.y - 1.5, 2.2, 14.0, -6.0, 3.0],
                      [w.x - 6.0, w.y - 6.5, 3.0, 30.0, 8.0, 4.0]] if self.rain_b.on else []
        if self.sart_b.pop():
            self.world.by_name["SART"].active = self.sart_b.on
        self.sart_b.on = self.world.by_name["SART"].active
        if self.rdn.pop() and self.ri > 0:
            self.ri -= 1
            self.clear()
        if self.rup.pop() and self.ri < len(RANGES) - 1:
            self.ri += 1
            self.clear()
        if self.nup.pop():
            self.clear()
        if self.pi_b.pop():
            self.clear()
        if self.drop.pop():
            self.tracks, self.sel = [], None
        if self.ack.pop():
            self.cpa_alarm = False
        if not self.trails.on:
            self.T[:] = 0
        # magnetron drift and tuning
        self.drift += float(self.rng.normal(0, 0.12)) * math.sqrt(dt) - (self.drift - 3.0) * 0.004 * dt
        self.drift = max(-9.0, min(9.0, self.drift))
        knob = (self.tune.val - 0.5) * 40.0
        if self.afc.on and h["afc"] and self.tx_ok:
            self.afc_corr += ((self.drift - knob) - self.afc_corr) * min(1.0, dt * 3)
        elif not self.afc.on:
            self.afc_corr = 0.0
        err = knob + self.afc_corr - self.drift
        bw = PULSES[self.pulse.value][3]
        loss = min(60.0, 3.0 * (err / (bw / 2)) ** 2)
        self.sig_gain = 10 ** (-loss / 10) * (1.0 if h["trl"] else 1e-3)
        self.tune_ind = 10 ** (-loss / 20) if (self.tx_ok and self.rx_ok) else 0.0
        self.r = (np.arange(self.NR) + 0.5) / self.NR * self.rmax
        self.dr = self.rmax / self.NR
        self.tinfo = [(c,) + w.rb(c) for c in w.contacts if c.active]
        # tracks
        danger = False
        for t in list(self.tracks):
            c = t["c"]
            rng, brg = w.rb(c)
            if not c.active or rng > 60:
                self.tracks.remove(t)
                continue
            t["rng"], t["brg"] = rng, brg
            t["ready"] = (w.t - t["t0"]) > 10
            a, b = math.radians(c.cog), math.radians(w.hdg)
            vx, vy = c.sog * math.sin(a) - w.spd * math.sin(b), c.sog * math.cos(a) - w.spd * math.cos(b)
            dx, dy = c.x - w.x, c.y - w.y
            v2 = vx * vx + vy * vy
            tc = -(dx * vx + dy * vy) / v2 if v2 > 1e-6 else 0.0
            t["tcpa"] = tc * 60
            t["cpa"] = math.hypot(dx + vx * tc, dy + vy * tc) if tc > 0 else rng
            t["danger"] = t["ready"] and t["cpa"] < 0.5 and 0 < t["tcpa"] < 20
            danger = danger or t["danger"]
        if danger and not getattr(self, "_was_danger", False):
            self.cpa_alarm = True
        self._was_danger = danger
        self.alert = self.cpa_alarm
        # sweep
        self.E *= math.exp(-dt / 12.0)
        if self.transmitting and h["trig"] and self.disp_ok:
            if h["ant"]:
                new = self.ang + 144.0 * dt
            else:
                new = self.ang + 1e-9
            steps = min(40, int(new * 2) - int(self.ang * 2)) if h["ant"] else 1
            base = int(self.ang * 2)
            for i in range(1, steps + 1):
                azr = ((base + i) / 2.0) % 360
                azt = (azr + w.hdg) % 360
                self.paint(azt, azr)
            self.ang = new % 360

    def bg_audio(self, syn, n):
        """Transformer hum, scanner motor, the modulator singing at the PRF, alarms."""
        k = 1.0 if self.app.station is self else 0.3
        out = None
        if self.power.value != "OFF" and self.world.rh["psu"]:
            out = syn.osc("rxf", 100.0, n) * 0.005 * k
            if self.transmitting:
                if self.world.rh["ant"]:
                    out = out + (syn.rumble("rmot", n, 26) * 0.05 + syn.osc("rmot2", 87.0, n) * 0.012) * k
                if self.tx_ok:
                    out = out + syn.whine("prf", PULSES[self.pulse.value][1], n) * 0.012 * k
        if self.cpa_alarm:
            out = (0 if out is None else out) + syn.beep("cpa", n, 2300.0, 3.0) * 0.3
        return out

    def paint(self, azt, azr):
        v = self.ray(azt, azr)
        b = int(((azt - self.rot) % 360) * 2) % 720
        sl = slice(self.starts[b], self.starts[b + 1])
        pix, vals = self.pix[sl], v[self.prb[sl]]
        if self.eav.on:
            self.Ef[pix] = self.Ef[pix] * 0.68 + vals * 0.42
        else:
            self.Ef[pix] = vals
        if self.trails.on:
            self.Tf[pix] = np.maximum(self.Tf[pix] * 0.975, vals > 0.4)

    def ray(self, azt, azr):
        """Range profile (0..1 video) for one antenna bearing."""
        w, h, NR, r, dr = self.world, self.world.rh, self.NR, self.r, self.dr
        tau, prf, Cdb, bwif = PULSES[self.pulse.value]
        X = self.band.idx == 0
        bw = 1.2 if X else 1.9
        if not X:
            Cdb -= 1.0
        pl = tau * 0.0809
        rng = self.rng
        P = np.zeros(NR)
        tx = self.tx_ok
        if tx:
            th = math.radians(azt)
            s, c_ = math.sin(th), math.cos(th)
            sx, sy = w.x + r * s, w.y + r * c_
            att = np.zeros(NR)
            for cx, cy, rad, rate, _, _ in w.rain:
                d2 = ((sx - cx) ** 2 + (sy - cy) ** 2) / (rad * rad)
                rr = rate * np.clip(1 - d2, 0, 1)
                if rr.max() <= 0.2:
                    continue
                att += np.cumsum((0.012 * rr ** 1.2 if X else 0.0006 * rr) * dr * 1.852)
                rdb = Cdb - 14 + 16 * np.log10(rr + 1e-6) + 10 * math.log10(tau / 0.08) \
                    - 20 * np.log10(r) - (0 if X else 14)
                P += np.where(rr > 0.2, 10 ** (rdb / 10), 0) * rng.exponential(1.0, NR)
            land = w.land_at(sx, sy)
            if land.any():
                depth = np.cumsum(land) * dr
                ldb = Cdb + 18 - 30 * np.log10(np.maximum(r, 0.05)) - depth * 22 - np.maximum(r - 26, 0) * 3
                P += land * 10 ** (ldb / 10) * (0.4 + 0.6 * rng.exponential(1.0, NR))
            if w.sea > 0:
                up = 1 + 0.6 * math.cos(math.radians(azt - w.wind))
                sdb = Cdb - 22 + 7 * w.sea - (0 if X else 8) + 7 * math.log10(tau / 0.08) \
                    - 30 * np.log10(np.maximum(r, 0.02) / 0.5) - (r / (0.5 + 0.45 * w.sea)) ** 2 * 6
                P += 10 ** (np.minimum(sdb, 90) / 10) * up * rng.exponential(1.0, NR)
            hroot = math.sqrt(w.h_ant)
            for c, trng, tbrg in self.tinfo:
                daz = wrap180(tbrg - azt)
                if c.kind == "sart":
                    if not X or trng > 2.21 * (hroot + 1) or trng > self.rmax:
                        continue
                    if abs(daz) < bw * (1 + 4 / max(trng, 0.05)) / 2 or trng < 0.15:
                        for k in range(12):
                            r0 = trng + 0.02 + k * 0.64
                            i0 = int(r0 / dr)
                            if i0 < NR:
                                P[i0:int((r0 + 0.12 + pl) / dr) + 1] += 3000.0
                    continue
                a = abs(daz)
                g = math.exp(-2.77 * (a / bw) ** 2) + (0.0025 if a < 12 else (0.0006 if a < 60 else 0.0001))
                i0 = int(trng / dr)
                if i0 >= NR:
                    continue
                hz = 2.21 * (hroot + math.sqrt(c.h))
                snr = Cdb + 10 * math.log10(c.rcs) - 40 * math.log10(max(trng, 0.03)) + 20 * math.log10(g)
                if trng > hz:
                    snr -= (trng - hz) * 8
                if snr < -6:
                    continue
                span = max(1, int((pl + c.length / 1852.0 * 0.6) / dr) + 1)
                P[i0:i0 + span] += 10 ** (snr / 10) * (0.35 + 0.65 * rng.exponential(1.0))
                if c.kind == "racon" and a < bw * 0.8 and (w.t % 30) < 20:
                    u = max(0.15, self.rmax / 40)
                    pos = trng + u * 0.6
                    for sym in c.racon:
                        ln = u * (3 if sym == "-" else 1)
                        P[int(pos / dr):int((pos + ln) / dr) + 1] += 2000.0
                        pos += ln + u
            if X and getattr(w, "own_sart", False):   # our own SART alongside: concentric rings
                for k in range(12):
                    i0 = int((0.03 + k * 0.64) / dr)
                    if i0 < NR:
                        P[i0:int((0.15 + k * 0.64 + pl) / dr) + 1] += 3000.0
            P *= 10 ** (-0.2 * att) * self.sig_gain
            if abs(wrap180(azr - 180)) < 5:
                P *= 0.01                         # blind sector astern (mast/funnel shadow)
            P[r < pl] = 0.0                       # receiver blanked during the transmitted pulse
            if w.interference and not self.ir.on:
                self.iph = (self.iph + 3) % 53
                if (int(azr * 2) * 7) % 5 < 2:
                    P[self.iph::53] += 2500.0
        if not self.rx_ok:
            v = np.zeros(NR)
            vdb = v
        else:
            tot = P + rng.exponential(1.0, NR)
            if tx:
                tot[r < pl + dr] += 1e7           # main bang
            vdb = 10 * np.log10(tot)
            if h["stc"] and self.stc.val > 0:
                vdb = vdb - self.stc.val * 65 * np.exp(-r / (0.6 + 2.4 * self.stc.val))
            v = np.clip((vdb - (16 - 22 * self.gain.val)) / 18.0, 0, 1)
            f = self.ftc.val
            if f > 0.02:
                k = max(3, int(2 * pl / dr) + 2)
                cs = np.cumsum(np.concatenate(([0.0], v)))
                i = np.arange(NR)
                lo = np.maximum(i - k, 0)
                v = np.clip(v - f * 1.25 * (cs[i] - cs[lo]) / np.maximum(i - lo, 1), 0, 1)
            if self.es.on:
                v = np.maximum(v, np.maximum(np.concatenate(([0.0], v[:-1])), np.concatenate(([0.0, 0.0], v[:-2]))))
        ab = self.ebl.val if self.ebl_on.on else w.hdg
        if abs(wrap180(azt - ab)) < 0.3:
            self.ascan = (vdb.copy(), v.copy())
        return v.astype(np.float32)

    # ---------------------------------------------------------------- draw
    def draw(self, s):
        w, h = self.world, self.world.rh
        cx, cy, R = self.CX, self.CY, self.R
        on = self.disp_ok
        if on and self.transmitting:
            e = np.minimum(self.E * (self.brill.val * 63), 63).astype(np.uint8)
            if self.trails.on:
                e |= (np.minimum(self.T * 3.99, 3).astype(np.uint8) << 6)
            pygame.surfarray.blit_array(self.surf, e)
            s.blit(self.surf, (cx - R, cy - R))
        else:
            pygame.draw.circle(s, (2, 9, 6) if on else (5, 8, 7), (cx, cy), R)
        if on:
            dim = tuple(int(c * min(1, self.brill.val)) for c in (24, 96, 52))
            if self.rings.on:
                n = int(round(self.rmax / RINGS[self.rmax]))
                for i in range(1, n + 1):
                    pygame.draw.circle(s, dim, (cx, cy), int(R * i / n), 1)
            if not self.hl.down:
                p = self.to_xy(self.rmax, w.hdg)
                pygame.draw.line(s, (90, 255, 150), (cx, cy), p, 1)
            if not self.nup.on:
                a = math.radians(-w.hdg)
                pygame.draw.polygon(s, C["cyan"], [(cx + math.sin(a) * (R - 2), cy - math.cos(a) * (R - 2)),
                                                   (cx + math.sin(a + 0.02) * (R - 14), cy - math.cos(a + 0.02) * (R - 14)),
                                                   (cx + math.sin(a - 0.02) * (R - 14), cy - math.cos(a - 0.02) * (R - 14))])
            if self.ebl_on.on:
                a = math.radians(self.ebl.val - self.rot)
                for i in range(0, R, 12):
                    pygame.draw.line(s, C["cyan"], (cx + math.sin(a) * i, cy - math.cos(a) * i),
                                     (cx + math.sin(a) * (i + 7), cy - math.cos(a) * (i + 7)), 1)
            if self.vrm_on.on and self.vrm.val > 0.005:
                rr = self.vrm.val * R
                for i in range(0, 360, 4):
                    a0 = math.radians(i)
                    a1 = math.radians(i + 2)
                    pygame.draw.line(s, C["cyan"], (cx + math.sin(a0) * rr, cy - math.cos(a0) * rr),
                                     (cx + math.sin(a1) * rr, cy - math.cos(a1) * rr), 1)
            if self.transmitting:
                self._draw_tracks(s)
                if h["trig"]:
                    a = math.radians(self.ang + w.hdg - self.rot)
                    pygame.draw.line(s, (70, 200, 110), (cx, cy), (cx + math.sin(a) * R, cy - math.cos(a) * R), 2)
                if self.sol_b.on:
                    for c, rng, brg in self.tinfo:
                        if rng < self.rmax:
                            x, y = self.to_xy(rng, brg)
                            pygame.draw.circle(s, C["red"], (x, y), 3, 1)
                            text(s, c.name, (x + 6, y - 14), 10, C["red"], bold=True)
            else:
                msg = "STAND-BY" if self.power.value == "STBY" and self.warm <= 0 else "WARMING UP  %02d" % max(0, math.ceil(self.warm))
                if not h["psu"]:
                    msg = ""
                text(s, msg, (cx, cy - 40), 34, (120, 255, 190), bold=True, align="m")
                if self.power.value == "TX" and self.warm > 0:
                    text(s, "TX INHIBITED UNTIL MAGNETRON IS WARM", (cx, cy + 10), 14, C["amber"], bold=True, align="m")
        pr = pygame.Rect(cx - R, cy - R, self.D, self.D)
        if on:
            fx.bloom(s, pr, 170)
        s.blit(self.bezel, (0, ui.TOP))
        mult, add = fx.round_glass(R)
        s.blit(mult, pr, special_flags=pygame.BLEND_RGB_MULT)
        s.blit(add, pr, special_flags=pygame.BLEND_RGB_ADD)
        for wr in ((12, 52, 170, 60), (598, 52, 158, 60), (12, 820, 200, 40), (588, 820, 168, 40)):
            ui.lcd(s, wr)
        if on:
            g = (120, 255, 190)
            tau, prf, _, _ = PULSES[self.pulse.value]
            text(s, "RANGE %g NM" % self.rmax, (20, 56), 15, g, bold=True)
            text(s, "RINGS %g NM" % RINGS[self.rmax], (20, 76), 12, g)
            text(s, "%s-BAND  %s" % (self.band.value[0], self.pulse.value[0] + "P"), (20, 92), 12, g)
            text(s, "N UP  RM" if self.nup.on else "H UP  RM", (750, 56), 15, g, bold=True, align="r")
            text(s, "HDG %05.1f°" % w.hdg, (750, 76), 12, g, align="r")
            text(s, "SPD %4.1f kn" % w.spd, (750, 92), 12, g, align="r")
            if self.ebl_on.on:
                rel = (self.ebl.val - w.hdg) % 360
                text(s, "EBL %05.1f°T  %05.1f°R" % (self.ebl.val, rel), (18, 823), 12, C["cyan"], bold=True)
            if self.vrm_on.on:
                text(s, "VRM %6.3f NM" % (self.vrm.val * self.rmax), (18, 840), 12, C["cyan"], bold=True)
            m = ui.MOUSE
            if math.hypot(m[0] - cx, m[1] - cy) < R:
                rng, brg = self.from_xy(m)
                text(s, "CURSOR %05.1f°T" % brg, (750, 823), 12, g, align="r")
                text(s, "%6.3f NM" % rng, (750, 840), 12, g, align="r")
            if self.cpa_alarm and int(w.t * 2) % 2:
                text(s, "COLLISION ALARM - CPA/TCPA", (cx, 50), 15, C["red"], bold=True, align="c")

        # panels
        ui.panel(s, (770, 52, 820, 150), "TRANSCEIVER")
        ui.panel(s, (770, 208, 820, 150), "RECEIVER / DISPLAY")
        ui.panel(s, (770, 364, 820, 150), "MEASUREMENT            OWN SHIP (HELM)            "
                                          "INSTRUCTOR: ENVIRONMENT")
        ui.panel(s, (770, 520, 500, 340), "A-SCAN  -  RECEIVER VIDEO ALONG " + ("EBL" if self.ebl_on.on else "HEADING LINE"))
        ui.panel(s, (1278, 520, 312, 340), "ARPA TARGET DATA")
        for x in (970, 1178):
            pygame.draw.line(s, C["edge"], (x, 388), (x, 502), 1)
        # status LCD
        l = ui.lcd(s, (1195, 72, 385, 122))
        tau, prf, _, _ = PULSES[self.pulse.value]
        X = self.band.idx == 0
        st = self.power.value
        if st == "TX" and self.warm > 0:
            st = "WARM-UP"
        if not h["psu"]:
            st = "NO POWER"
        fg = C["lcdfg"]
        text(s, "STATE  %-8s" % st, (l.x + 10, l.y + 8), 13, fg, bold=True)
        text(s, "FREQ   %s MHz  %s" % ("9410" if X else "3050", "25 kW" if X else "30 kW"), (l.x + 10, l.y + 26), 13, fg)
        text(s, "PULSE  %.2f us  PRF %d Hz" % (tau, prf), (l.x + 10, l.y + 44), 13, fg)
        text(s, "BEAM   %.1f° H   24 RPM" % (1.2 if X else 1.9), (l.x + 10, l.y + 62), 13, fg)
        text(s, "TUNE", (l.x + 10, l.y + 82), 12, fg, bold=True)
        ui.bar(s, (l.x + 60, l.y + 82, 200, 13), self.tune_ind, "green")
        text(s, "MAG I", (l.x + 10, l.y + 100), 12, fg, bold=True)
        magi = {"SHORT": 0.35, "MEDIUM": 0.5, "LONG": 0.68}[self.pulse.value] if self.tx_ok else 0.0
        ui.bar(s, (l.x + 60, l.y + 100, 200, 13), magi, "amber")
        ui.led(s, (l.x + 300, l.y + 20), "red", self.tx_ok and int(w.t * 4) % 2 == 0, "TX")
        ui.led(s, (l.x + 300, l.y + 44), "green", self.warm <= 0 and st != "NO POWER" and self.power.value != "OFF", "READY")
        ui.led(s, (l.x + 300, l.y + 68), "amber", self.afc.on, "AFC")
        ui.led(s, (l.x + 300, l.y + 92), "red", self.cpa_alarm, "ALARM")
        super().draw(s)
        self._draw_ascan(s)
        self._draw_arpa(s)

    def _draw_tracks(self, s):
        w = self.world
        for t in self.tracks:
            if "rng" not in t or t["rng"] > self.rmax:
                continue
            c = t["c"]
            x, y = self.to_xy(t["rng"], t["brg"])
            col = C["red"] if t.get("danger") else (C["green"] if t is self.sel else (150, 255, 200))
            if not t.get("ready"):
                pygame.draw.rect(s, col, (x - 9, y - 9, 18, 18), 1)
            else:
                if t.get("danger") and int(w.t * 3) % 2:
                    pygame.draw.polygon(s, col, [(x, y - 13), (x + 12, y + 9), (x - 12, y + 9)], 2)
                else:
                    pygame.draw.circle(s, col, (x, y), 9, 1)
                k = self.R / self.rmax * 0.1                 # 6-minute true vector
                a = math.radians(c.cog - self.rot)
                pygame.draw.line(s, col, (x, y), (x + math.sin(a) * c.sog * k, y - math.cos(a) * c.sog * k), 2)
            text(s, str(t["n"]), (x + 11, y - 16), 11, col, bold=True)

    def _draw_ascan(self, s):
        r = ui.crt(s, (792, 556, 458, 254))
        for i in range(1, 5):
            pygame.draw.line(s, (26, 42, 44), (r.x + r.w * i / 5, r.y), (r.x + r.w * i / 5, r.bottom), 1)
            pygame.draw.line(s, (26, 42, 44), (r.x, r.y + r.h * i / 5), (r.right, r.y + r.h * i / 5), 1)
        for i in range(6):
            text(s, "%g" % (self.rmax * i / 5), (r.x + r.w * i / 5, r.bottom + 9), 10, C["dim"], align="c")
        text(s, "nm", (r.right - 2, r.bottom + 9), 10, C["dim"], align="r") if False else None
        text(s, "+80 dB", (r.x + 6, r.y + 4), 9, (60, 110, 80))
        if self.disp_ok and self.transmitting:
            vdb, v = self.ascan
            xs = r.x + (np.arange(self.NR) + 0.5) / self.NR * r.w
            raw = r.bottom - np.clip((vdb + 10) / 90.0, 0, 1) * r.h
            pygame.draw.lines(s, (95, 100, 108), False, list(zip(xs, raw)), 1)
            if self.stc.val > 0 and self.world.rh["stc"]:
                rr = (np.arange(self.NR) + 0.5) / self.NR * self.rmax
                a = self.stc.val * 65 * np.exp(-rr / (0.6 + 2.4 * self.stc.val))
                pygame.draw.lines(s, C["amber"], False, list(zip(xs, r.y + a / 90.0 * r.h)), 1)
            thr = 16 - 22 * self.gain.val
            ty = r.bottom - (thr + 10) / 90.0 * r.h
            pygame.draw.line(s, (150, 60, 60), (r.x, ty), (r.right, ty), 1)
            text(s, "threshold", (r.right - 4, ty - 13), 9, (190, 90, 90), align="r")
            pygame.draw.lines(s, C["green"], False, list(zip(xs, r.bottom - 1 - v * (r.h * 0.42))), 2)
            if self.vrm_on.on:
                x = r.x + self.vrm.val * r.w
                pygame.draw.line(s, C["cyan"], (x, r.y), (x, r.bottom), 1)
        ui.led(s, (800, 842), (95, 100, 108), True, "RAW dB", 4)
        ui.led(s, (890, 842), "amber", True, "STC CUT", 4)
        ui.led(s, (990, 842), "green", True, "VIDEO OUT", 4)
        ui.led(s, (1100, 842), "cyan", True, "VRM", 4)

    def _draw_arpa(self, s):
        x, y = 1296, 552
        l = ui.lcd(s, (1292, 550, 284, 184))
        fg = C["lcdfg"]
        t = self.sel if self.sel in self.tracks else None
        if not t or "rng" not in t:
            ui.text_block(s, "NO TARGET SELECTED\n \nClick an echo on the PPI to acquire. Up to 10 "
                             "targets are tracked.", (x + 6, y + 6, 270, 170), 12, fg)
        else:
            c, w = t["c"], self.world
            text(s, "TARGET %d %s" % (t["n"], "" if t["ready"] else "(ACQUIRING)"), (x + 6, y + 4), 14, fg, bold=True)
            rows = [("BRG", "%05.1f° T" % t["brg"]), ("RNG", "%.2f NM" % t["rng"])]
            if t["ready"]:
                rows += [("CRS", "%05.1f° T" % c.cog), ("SPD", "%.1f kn" % c.sog),
                         ("CPA", "%.2f NM" % t["cpa"]),
                         ("TCPA", "%.1f min" % t["tcpa"] if t["tcpa"] > 0 else "PAST")]
            else:
                rows += [("CRS", "---"), ("SPD", "---"), ("CPA", "---"), ("TCPA", "---")]
            for i, (k, v) in enumerate(rows):
                col = C["red"] if t.get("danger") and k in ("CPA", "TCPA") else fg
                text(s, k, (x + 6, y + 30 + i * 24), 15, col, bold=True)
                text(s, v, (x + 270, y + 30 + i * 24), 15, col, bold=True, align="r")
        ui.text_block(s, "CPA limit 0.5 NM / TCPA limit 20 min. Vectors are TRUE, 6 minutes long. "
                         "Tracked: %d/10. Minimum range with this pulse: %d m." %
                      (len(self.tracks), int(PULSES[self.pulse.value][0] * 150) + 15),
                      (1292, 744, 286, 110), 11, C["dim"], mono=False)
