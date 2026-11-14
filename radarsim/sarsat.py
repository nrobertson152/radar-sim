"""COSPAS-SARSAT: 406 MHz EPIRB, radar SART, and the whole alerting chain.

LEOSAR satellites fly real (simplified circular) polar orbits. Each 406 MHz
burst received by a satellite in view is plotted as a Doppler measurement;
the S-curve's inflection is the time of closest approach and its slope gives
the cross-track distance - which is how a beacon WITHOUT GNSS is located,
with the classic two-sided ambiguity until a second pass.
"""
import math
import pygame
from . import ui
from .ui import C, text, Selector, Button, Toggle, Station
from .world import LEOSAR, RE, gc_dist, gc_bearing, gc_dest, fmt_lat, fmt_lon
from .worldmap import WorldMap

GEOSAR = [("GEO-W", -135.0), ("GEO-E", -75.0), ("GEO-0", 0.0), ("GEO-41E", 41.5), ("GEO-82E", 82.0), ("GEO-140E", 140.0)]
F0, ALT = 406.028e6, 850.0
FOOT = math.degrees(math.acos(RE / (RE + ALT) * math.cos(math.radians(5)))) - 5      # ~23.5 deg
WARPS = [1, 10, 60, 300]


def ecef(lat, lon, r):
    p, l = math.radians(lat), math.radians(lon)
    return r * math.cos(p) * math.cos(l), r * math.cos(p) * math.sin(l), r * math.sin(p)


class Sarsat(Station):
    name = "COSPAS-SARSAT"
    tab = "SARSAT"
    hint = ("Set the EPIRB to ON (or ARMED then IMMERSE) and raise SIM TIME to watch satellites pick "
            "up the bursts. Compare a beacon with and without GNSS, and with MEOSAR on and off.")
    pan, bg_pan = 0.0, 0.75

    def __init__(self, app):
        super().__init__(app)
        self.map = WorldMap((30, 80, 880, 440))
        self.st = 0.0                                  # satellite sim clock (s)
        self.flags = {}
        self.reset()
        self.sw = self.add(Selector(1000, 150, 26, "BEACON SWITCH", ["OFF", "ARMED", "TEST", "ON"], 0,
            "EPIRB switch. ARMED: stowed in its float-free bracket, activates automatically when the "
            "hydrostatic release lets go (1.5-4 m depth) and the sea-water contacts close. TEST: "
            "self-test burst that satellites ignore. ON: manual activation."))
        self.b_gnss = self.add(Button((1060, 214, 110, 34), "GNSS ENCODED", "Beacon with an internal GNSS "
            "receiver encodes its position in the 406 MHz message, so a GEOSAR satellite gives an "
            "immediate located alert. Off = position only from Doppler (LEOSAR) or MEOSAR.", toggle=True, on=True, size=10))
        self.b_imm = self.add(Button((946, 214, 108, 34), "IMMERSE", "Simulate the vessel sinking: the "
            "hydrostatic release frees the beacon. Only works when the switch is ARMED.", color="blue"))
        self.b_meo = self.add(Button((1176, 214, 100, 34), "MEOSAR", "MEOSAR: SAR repeaters on GPS, Galileo "
            "and GLONASS satellites give near-instant independent location. Off shows the classic "
            "LEOSAR / GEOSAR system.", toggle=True, size=10))
        self.sart = self.add(Selector(1000, 392, 24, "SART SWITCH", ["OFF", "TEST", "ON"], 0,
            "9 GHz radar SART. ON: stands by silently until an X-band radar pulse triggers it, then "
            "sweeps 9.2-9.5 GHz twelve times, painting 12 dots on that radar. Mount it at least 1 m "
            "above the sea. Check the RADAR tab with X-band on the 6 or 12 nm scale."))
        self.warp = self.add(Selector(1500, 392, 24, "SIM TIME x", ["x1", "x10", "x60", "x300"], 0,
            "Speed of the satellite clock. A LEOSAR pass lasts up to 15 minutes and the wait for one "
            "can exceed an hour - speed it up."))
        self.b_rst = self.add(Button((1404, 214, 170, 34), "RESET SCENARIO", "Switch the beacon off and clear the alert chain."))
        ti = "BEACON CARE (INSTRUCTOR): "
        self.reg = self.add(Toggle(990, 800, "REGISTERED", True, ti + "the beacon's 15-hex ID is registered with the "
            "owner's details. Unregistered: the MCC cannot tell who you are or who to call - the alert chain is much slower."))
        self.hru = self.add(Toggle(1090, 800, "HRU\nEXPIRED", False, ti + "the hydrostatic release unit is past its "
            "expiry date and seizes: the beacon does NOT float free when the ship sinks."))
        self.batt = self.add(Toggle(1190, 800, "BATTERY\nEXPIRED", False, ti + "battery past its expiry: the beacon "
            "transmits a few bursts and dies."))
        self.homer = self.add(Toggle(1290, 800, "121.5\nHOMER", True, ti + "the 121.5 MHz homing transmitter used "
            "by SAR aircraft for the final approach (heard on the air radio guard receiver)."))
        self.btype = self.add(Selector(1400, 806, 22, "TYPE", ["EPIRB", "PLB"], 0, ti + "EPIRB: float-free, 48 h "
            "battery, registered to the ship. PLB: personal beacon, manual only (cannot float free), 24 h battery."))

    def reset(self):
        self.active, self.t0, self.next_burst, self.nburst = False, None, None, 0
        self.passes = {}                 # sat name -> dict(aos, pts, maxel)
        self.done_passes = []
        self.events = []                 # (sim time, text, colour)
        self.sol, self.resolved = None, False
        self.geo_seen = self.meo_done = False
        self.t_loc = self.t_mcc = self.t_rcc = self.t_sar = None
        self.test_until = 0.0
        self.plot = None
        self.world.epirb_on = False

    # --------------------------------------------------------------- orbits
    def geom(self, sat, t):
        """Central angle (deg), elevation (deg), range (km) from beacon to sat."""
        la, lo = self.world.leo_pos(sat, t)
        g = gc_dist(self.blat, self.blon, la, lo) / RE
        rs = RE + ALT
        rng = math.sqrt(RE * RE + rs * rs - 2 * RE * rs * math.cos(g))
        el = math.degrees(math.atan2(math.cos(g) - RE / rs, math.sin(g) + 1e-9))
        return math.degrees(g), el, rng, la, lo

    def doppler(self, sat, t):
        r1 = self.geom(sat, t - 0.5)[2]
        r2 = self.geom(sat, t + 0.5)[2]
        return -F0 / 299792.458 * (r2 - r1)

    def ev(self, msg, col=None, t=None):
        self.events.append((self.st if t is None else t, msg, col or C["text"]))
        ui.sfx("blip", 0.5)

    def activate(self, how):
        if self.active:
            return
        w = self.world
        w.epirb_homer = self.homer.on
        self.active, self.t0, self.next_burst = True, self.st, self.st + 50.0
        self.blat, self.blon = w.lat, w.lon
        w.epirb_on = True
        self.flags["epirb_on"] = w.t
        ui.sfx("thunk")
        self.ev("BEACON ACTIVATED (%s) - 121.5 MHz homer on, strobe on" % how, C["red"])

    def _burst(self, t):
        if self.batt.on and self.nburst >= 3:
            if self.next_burst is not None:
                self.ev("BEACON BATTERY EXHAUSTED - TRANSMISSIONS STOPPED (battery past its expiry date)", C["red"], t)
                self.next_burst = None
                self.world.epirb_on = False
            return
        self.nburst += 1
        if self.app.station is self:
            ui.sfx("burst406", 0.6)
        gn = self.b_gnss.on
        if self.nburst == 1:
            self.ev("FIRST 406 MHz BURST - 5 W, 0.5 s, repeats every 50 s", C["amber"], t)
        if not self.geo_seen:
            vis = [n for n, lon in GEOSAR if gc_dist(self.blat, self.blon, 0, lon) / RE < math.radians(76)]
            if vis:
                self.geo_seen = True
                self.flags["geo"] = self.world.t
                if gn:
                    self.ev("GEOSAR %s: ALERT WITH ENCODED GNSS POSITION" % vis[0], C["green"], t)
                    self._located(t, "GNSS-encoded position via GEOSAR", True)
                else:
                    self.ev("GEOSAR %s: BEACON ID DETECTED - NO POSITION (geostationary = no Doppler)" % vis[0], C["yellow"], t)
        if self.b_meo.on and not self.meo_done and self.nburst >= 5:
            self.meo_done = True
            self.ev("MEOSAR: INDEPENDENT LOCATION FROM TDOA/FDOA, accuracy < 5 km", C["green"], t)
            self._located(t, "MEOSAR", True)
        for sat in LEOSAR:
            g, el, rng, la, lo = self.geom(sat, t)
            if el >= 5:
                p = self.passes.setdefault(sat[0], dict(sat=sat, aos=t, pts=[], maxel=0.0))
                if not p["pts"]:
                    self.ev("LEOSAR PASS BEGINS: %s receiving bursts" % sat[0], C["cyan"], t)
                p["pts"].append((t, self.doppler(sat, t)))
                if el > p["maxel"]:
                    p["maxel"], p["sub"] = el, (la, lo)
                self.plot = p

    def _located(self, t, how, unambiguous):
        if self.t_loc is None:
            self.t_loc = t
            self.t_mcc = t + 120
            self.flags["located"] = self.world.t
        if unambiguous:
            self.resolved = True

    def _end_pass(self, p, t):
        self.done_passes.append(p)
        if len(p["pts"]) < 4:
            self.ev("%s pass ended - only %d bursts, too few for a Doppler solution" % (p["sat"][0], len(p["pts"])), C["dim"], t)
            return
        sla, slo = p["sub"]
        brg = gc_bearing(sla, slo, self.blat, self.blon)
        ang = math.degrees(gc_dist(sla, slo, self.blat, self.blon) / RE)
        img = gc_dest(sla, slo, (brg + 180) % 360, ang)
        if self.sol is None:
            self.sol = dict(a=(self.blat + 0.02, self.blon - 0.03), b=img)
            self.flags["doppler"] = self.world.t
            self.ev("%s: DOPPLER LOCATION - two solutions A and B either side of the ground track "
                    "(max elevation %d°)" % (p["sat"][0], p["maxel"]), C["green"], t)
            self._located(t, "LEOSAR Doppler", False)
        elif not self.resolved:
            self.resolved = True
            self.ev("%s: SECOND PASS - AMBIGUITY RESOLVED, solution A confirmed" % p["sat"][0], C["green"], t)

    # --------------------------------------------------------------- update
    def update(self, dt):
        w = self.world
        if self.b_rst.pop():
            self.reset()
            self.sw.set(0)
        if self.b_imm.pop():
            if self.btype.value == "PLB":
                self.ev("A PLB cannot float free - it must be carried and switched on by hand.", C["amber"])
            elif self.hru.on:
                self.flags["hru_fail"] = w.t
                self.ev("HYDROSTATIC RELEASE FAILED (expired HRU) - THE BEACON WENT DOWN WITH THE SHIP. Check the "
                        "HRU expiry date on every inspection.", C["red"])
                self.mistake("EPIRB hydrostatic release past its expiry date - the beacon did not float free.")
            elif self.sw.value == "ARMED":
                self.activate("hydrostatic release")
            else:
                self.ev("Beacon immersed but switch is %s - it will NOT activate. Keep it ARMED at sea." % self.sw.value, C["amber"])
        sv = self.sw.value
        if sv == "ON":
            self.activate("manual")
        elif sv == "TEST" and getattr(self, "_sw", "") != "TEST":
            self.test_until = w.t + 4
            ui.sfx("beep2")
            self.ev("SELF-TEST: one inverted-sync burst, battery and 406/121.5 circuits OK. No alert generated.", C["cyan"])
            self.flags["epirb_test"] = w.t
        elif sv == "OFF" and self.active and getattr(self, "_sw", "") != "OFF":
            self.active = False
            w.epirb_on = False
            self.next_burst = None
            self.ev("BEACON SWITCHED OFF. If this was a false alert, TELL THE COASTGUARD/MRCC NOW.", C["amber"])
        self._sw = sv
        srt = self.sart.value
        w.own_sart = srt == "ON"
        if srt == "ON":
            self.flags["sart_on"] = w.t
        if srt == "TEST" and getattr(self, "_srt", "") != "TEST":
            self.flags["sart_test"] = w.t
            ui.sfx("sart", 0.8)
            self.ev("SART SELF-TEST: buzzer and lamp OK. Check its rings on your own X-band radar.", C["cyan"])
        self._srt = srt
        if self.active and self.app.station is self and int(w.t / 3.0) != getattr(self, "_strobe", -1):
            self._strobe = int(w.t / 3.0)
            ui.sfx("tick", 0.7, pan=0.2)
        self.st += dt * WARPS[self.warp.idx]
        if self.active:
            n = 0
            while self.next_burst is not None and self.st >= self.next_burst and n < 20:
                self._burst(self.next_burst)
                if self.next_burst is None:
                    break
                self.next_burst += 50.0
                n += 1
            for name, p in list(self.passes.items()):
                if self.geom(p["sat"], self.st)[1] < 5 and p["pts"]:
                    del self.passes[name]
                    self._end_pass(p, self.st)
            if self.t_mcc and self.st >= self.t_mcc and self.t_rcc is None:
                if self.reg.on:
                    self.t_rcc = self.t_mcc + 180
                    self.ev("LUT -> MISSION CONTROL CENTRE: alert validated against the beacon registration database", C["text"], self.t_mcc)
                else:
                    self.t_rcc = self.t_mcc + 2400
                    self.flags["unregistered"] = w.t
                    self.ev("MCC: BEACON NOT REGISTERED - no vessel or owner details. Confirmation needs a second "
                            "detection; SAR action delayed", C["amber"], self.t_mcc)
            if self.t_rcc and self.st >= self.t_rcc and self.t_sar is None:
                self.t_sar = self.t_rcc + 600
                self.ev("MCC -> RESCUE CO-ORDINATION CENTRE (MRCC PENHALE): owner contacted, broadcast to shipping", C["text"], self.t_rcc)
            if self.t_sar and self.st >= self.t_sar and "sar" not in self.flags:
                self.flags["sar"] = w.t
                self.ev("SAR UNITS TASKED: helicopter RESCUE 193 and lifeboat proceeding. They home on 121.5 MHz and your SART.", C["green"], self.t_sar)
                heli = w.by_name["RESCUE 193"]
                if not heli.home:
                    w.task_sar(heli, 16.0, 35.0)

    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if self.map.rect.collidepoint(pos):
            return ("Triangles = LEOSAR satellites (850 km, ~100 min polar orbits) with their 5°-elevation footprints. "
                    "Squares = GEOSAR. A LEOSAR satellite must pass within about 2600 km of the beacon to hear it.")
        if pygame.Rect(20, 532, 900, 328).collidepoint(pos):
            return ("DOPPLER CURVE: received frequency minus 406.028 MHz at each burst. Approaching = high, receding = low. "
                    "The zero crossing is the time of closest approach; a steep curve means the track passed nearly overhead.")
        if pygame.Rect(930, 470, 660, 250).collidepoint(pos):
            return "ALERT CHAIN: beacon -> satellite -> Local User Terminal (LUT) -> Mission Control Centre (MCC) -> Rescue Co-ordination Centre (RCC) -> SAR units."
        return ""

    # ----------------------------------------------------------------- draw
    def draw(self, s):
        w = self.world
        ui.panel(s, (20, 54, 900, 470), "COSPAS-SARSAT SPACE SEGMENT   sim clock T+%s   x%d" % (self._hms(self.st), WARPS[self.warp.idx]))
        ui.panel(s, (20, 532, 900, 328), "LEOSAR DOPPLER MEASUREMENTS  (406.028 MHz)")
        ui.panel(s, (930, 54, 660, 204), "406 MHz EPIRB  -  FLOAT-FREE, CATEGORY 1")
        ui.panel(s, (930, 266, 660, 196), "9 GHz RADAR SART   |   SIMULATION")
        ui.panel(s, (930, 470, 660, 250), "ALERT CHAIN TIMELINE")
        ui.panel(s, (930, 728, 660, 132), "BEACON CARE  -  INSTRUCTOR")
        ui.crt(s, self.map.rect, gain=80)
        self.map.draw(s)
        blat, blon = (self.blat, self.blon) if self.active else (w.lat, w.lon)
        for nm, lon in GEOSAR:
            self.map.marker(s, 0, lon, (120, 130, 150), nm, "sq", 3)
        for sat in LEOSAR:
            la, lo = w.leo_pos(sat, self.st)
            vis = self.active and self.geom(sat, self.st)[1] >= 5
            col = C["green"] if vis else (110, 170, 230)
            for k in range(1, 16):
                pa = w.leo_pos(sat, self.st + k * 120)
                pygame.draw.circle(s, (50, 80, 120), self.map.xy(*pa), 1)
            self.map.footprint(s, la, lo, FOOT, col, 10, 1)
            self.map.marker(s, la, lo, col, sat[0][-1], "tri", 5)
        if self.sol:
            self.map.marker(s, self.sol["a"][0], self.sol["a"][1], C["green"], "A", "x", 5)
            if not self.resolved:
                self.map.marker(s, self.sol["b"][0], self.sol["b"][1], C["amber"], "B?", "x", 5)
        x, y = self.map.marker(s, blat, blon, C["red"] if self.active else C["white"], None, "dot", 4)
        if self.active and (self.st - self.t0) % 50 < 3:
            pygame.draw.circle(s, C["red"], (x, y), 6 + int(((self.st - self.t0) % 50) * 5), 1)
        text(s, "EPIRB" if self.active else w.name, (x + 8, y + 4), 10, C["red"] if self.active else C["white"], bold=True)
        self._draw_doppler(s)
        # EPIRB panel
        fg = C["lcdfg"]
        l = ui.lcd(s, (1060, 80, 514, 124))
        st = "TRANSMITTING" if self.active else ("SELF TEST" if w.t < self.test_until else self.sw.value)
        rows = ["HEX ID  1D0C4A7B2CFFBFF   COUNTRY 232 (UK)",
                "STATE   %s" % st,
                "406.028 MHz 5 W digital burst / 121.5 MHz 50 mW homer",
                "NEXT BURST %s    BURSTS SENT %d" % (("%2d s" % max(0, self.next_burst - self.st)) if self.active else "--", self.nburst),
                "POS IN MESSAGE: %s" % ((fmt_lat(blat) + " " + fmt_lon(blon)) if self.b_gnss.on else "NONE (no GNSS)"),
                "BATTERY %s   HRU %s   %s" % ("EXPIRED 01/2024" if self.batt.on else "48 h, EXP 08/2030",
                                               "EXPIRED 03/2025" if self.hru.on else "EXP 03/2028",
                                               "REGISTERED" if self.reg.on else "NOT REGISTERED")]
        for i, r in enumerate(rows):
            text(s, r, (l.x + 10, l.y + 6 + i * 19), 12, C["red"] if (i == 1 and self.active) else fg, bold=i == 1)
        strobe = (self.active and (w.t % 3) < 0.12) or (w.t < self.test_until and int(w.t * 4) % 2 == 0)
        ui.led(s, (1310, 231), "white", strobe, "STROBE", 7)
        # SART panel
        l = ui.lcd(s, (1060, 292, 380, 158))
        srt = self.sart.value
        rad = self.app.radar
        trig = srt == "ON" and ((rad.tx_ok and rad.band.idx == 0) or any(c.kind == "ship" and c.active and w.rb(c)[0] < 8 for c in w.contacts))
        rows = ["SART  9.2 - 9.5 GHz  400 mW  12 sweeps/trigger",
                "STATE  %s" % ("OFF" if srt == "OFF" else "SELF TEST OK" if srt == "TEST" else
                               ("RESPONDING - X-BAND RADAR IN RANGE" if trig else "STANDBY - LISTENING")),
                "On a radar: 12 dots, 0.64 nm apart, leading",
                "away from the SART. Arcs then rings within 1 nm.",
                "Range to a ship's radar ~5 nm, aircraft ~30 nm.",
                "S-band radars do NOT trigger it.",
                "Battery: 96 h standby + 8 h responding."]
        for i, r in enumerate(rows):
            text(s, r, (l.x + 10, l.y + 6 + i * 21), 12, (C["red"] if trig else fg) if i == 1 else fg, bold=i == 1)
        ui.led(s, (956, 304), "red", trig and int(w.t * 6) % 2 == 0, "TRIGGERED", 6)
        if trig and w.t - getattr(self, "_bip", 0) > 1.6:                     # a SART beeps while a radar is painting it
            self._bip = w.t
            ui.sfx("sart", 0.6)
        # timeline
        y = 498
        if not self.events:
            ui.text_block(s, "No beacon activity. A registered 406 MHz EPIRB identifies the vessel, so register "
                             "it and keep the owner details current.\n \nTry: 1) GNSS ENCODED on, switch ON - located in "
                             "about a minute by GEOSAR.  2) RESET, GNSS off, MEOSAR off - you must wait for a LEOSAR "
                             "pass, then a second one to resolve the A/B ambiguity.  3) MEOSAR on.",
                          (946, y, 628, 250), 12, C["dim"], mono=False, lh=18)
        for tm, msg, col in self.events[-8:]:
            el = tm - (self.t0 if self.t0 is not None else tm)
            text(s, "T+" + self._hms(max(0, el)), (946, y), 12, C["dim"], bold=True)
            y = ui.text_block(s, msg, (1040, y, 536, 60), 12, col, lh=15, mono=False) + 5
            if y > 700:
                break
        if self.t_loc is not None and "sar" not in self.flags:
            nxt = self.t_sar or self.t_rcc or self.t_mcc
            text(s, "next step in %s" % self._hms(max(0, nxt - self.st)), (1574, 478), 10, C["amber"], bold=True, align="r")
        super().draw(s)

    @staticmethod
    def _hms(t):
        t = int(t)
        return "%02d:%02d:%02d" % (t // 3600, t // 60 % 60, t % 60)

    def _draw_doppler(self, s):
        r = ui.crt(s, (86, 566, 554, 256))
        for k in (-10, -5, 0, 5, 10):
            y = r.centery - k / 11.0 * r.h / 2
            pygame.draw.line(s, (40, 60, 84) if k == 0 else (22, 32, 44), (r.x, y), (r.right, y), 1)
            text(s, "%+d kHz" % k, (r.x - 10, y - 6), 9, C["dim"], align="r")
        p = self.plot
        x0 = 660
        if not p or not p["pts"]:
            text(s, "waiting for a LEOSAR satellite to rise above 5° over the active beacon", r.center, 12, C["dim"], align="m", mono=False)
            ui.text_block(s, "Each dot will be one 0.5 s burst.\n \nA geostationary satellite has no relative motion, so it "
                             "cannot locate a beacon by Doppler - it only relays the ID (and the GNSS position if encoded).",
                          (x0, 570, 246, 250), 12, C["dim"], mono=False, lh=17)
            return
        t0 = p["pts"][0][0]
        span = max(900.0, p["pts"][-1][0] - t0 + 60)
        pts = [(r.x + 10 + (t - t0) / span * (r.w - 20), r.centery - df / 11000.0 * r.h / 2) for t, df in p["pts"]]
        if len(pts) > 1:
            pygame.draw.lines(s, (60, 110, 80), False, pts, 1)
        for q in pts:
            pygame.draw.circle(s, C["green"], q, 3)
        for m in range(0, int(span / 60) + 1, 3):
            x = r.x + 10 + m * 60 / span * (r.w - 20)
            text(s, "%d min" % m, (x, r.bottom + 9), 9, C["dim"], align="c")
        dfs = [d for _, d in p["pts"]]
        tca = None
        for (ta, da), (tb, db) in zip(p["pts"], p["pts"][1:]):
            if da > 0 >= db:
                tca = ta + (tb - ta) * da / (da - db)
                x = r.x + 10 + (tca - t0) / span * (r.w - 20)
                pygame.draw.line(s, C["yellow"], (x, r.y), (x, r.bottom), 1)
                text(s, "TCA", (x + 3, r.y + 3), 10, C["yellow"], bold=True)
        info = ["SATELLITE   %s" % p["sat"][0], "BURSTS      %d" % len(p["pts"]), "MAX ELEV    %d°" % p["maxel"],
                "DOPPLER NOW %+.2f kHz" % (dfs[-1] / 1000), "SWING       %.1f kHz" % ((max(dfs) - min(dfs)) / 1000),
                "TCA         %s" % ("T+" + self._hms(tca - self.t0) if tca else "not yet")]
        for i, ln in enumerate(info):
            text(s, ln, (x0, 572 + i * 20), 12, C["lcdfg"], bold=True)
        ui.text_block(s, "The curve's slope at TCA gives the distance from the ground track, but not which SIDE - "
                         "hence solutions A and B until another pass (or Earth-rotation asymmetry) resolves it.",
                      (x0, 704, 246, 130), 11, C["dim"], mono=False, lh=15)
