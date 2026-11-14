"""GMDSS radio power panel.

The radio installation has three sources: the ship's MAIN switchboard, the
EMERGENCY switchboard (fed by an emergency generator that starts by itself
when the main supply fails) and the RESERVE source - a 24 V radio battery
that must run the GMDSS equipment for at least 1 hour (6 hours if there is
no emergency generator). AC-only loads such as the radar and the Fleet
satellite dish are not on the battery.

Every equipment position has a breaker here. Trip one (instructor) and that
station goes dead until you find and reset it; black the ship out and listen
to the console fall silent, the radios change over to the battery and the
emergency generator crank up.
"""
import math
import numpy as np
import pygame
from . import ui
from .ui import C, text, Knob, Selector, Button, Toggle, Station

# key, label, bus ('AC' = switchboard only, 'DC' = radio bus with battery backup), idle A, transmit A
LOADS = [
    ("RADAR", "RADAR", "AC", 9.0, 0.0),
    ("FLEET", "FLEET BB\nDISH", "AC", 3.5, 0.0),
    ("VHF", "VHF\nDSC", "DC", 1.2, 5.5),
    ("MFHF", "MF/HF\nDSC", "DC", 2.5, 32.0),
    ("SATC", "INMARSAT\n-C", "DC", 0.9, 3.8),
    ("SAT2", "IRIDIUM\nSSAS LRIT", "DC", 0.8, 2.5),
    ("NAVTEX", "NAVTEX", "DC", 0.5, 0.0),
    ("GPS", "GPS", "DC", 0.4, 0.0),
    ("GYRO", "GYRO\n+ LOG", "DC", 2.2, 0.0),
    ("AIS", "AIS", "DC", 0.9, 1.8),
    ("LIGHTS", "CONSOLE\nLIGHTING", "DC", 1.0, 0.0),
    ("CHARGER", "BATTERY\nCHARGER", "AC", 0.0, 0.0),
]
BUS = {k: b for k, _, b, _, _ in LOADS}
CAP_AH = 200.0
ALARMS = ["MAINS FAIL", "EM GEN\nRUNNING", "ON\nBATTERY", "BATTERY\nLOW", "CHARGER\nFAULT", "CHARGING",
          "EARTH\nFAULT +", "EARTH\nFAULT -", "BREAKER\nTRIPPED", "DC BUS\nFAIL", "EM GEN\nFAIL", "TEST\nLOAD"]
AUDIBLE = {"MAINS FAIL", "BATTERY\nLOW", "CHARGER\nFAULT", "EARTH\nFAULT +", "EARTH\nFAULT -",
           "BREAKER\nTRIPPED", "DC BUS\nFAIL", "EM GEN\nFAIL"}
ALARM_COL = {"EM GEN\nRUNNING": "amber", "ON\nBATTERY": "amber", "CHARGING": "green", "TEST\nLOAD": "cyan"}


class Power(Station):
    name = "RADIO POWER"
    tab = "POWER"
    hint = ("GMDSS radio power: sources, breakers for every equipment, the 24 V reserve battery and its charger. "
            "Daily check: battery voltage on and off load. Use the instructor faults to practise a blackout.")
    pan, bg_pan = 0.0, 0.35

    def __init__(self, app):
        super().__init__(app)
        self.rng = np.random.default_rng(31)
        self.soc, self.temp = 0.93, 22.0
        self.v, self.i = 25.4, 0.0
        self.gen, self.gen_t = "STOP", 0.0
        self.dc_from, self.ac_live, self.main_ok, self.emerg_ok = "AC", True, True, False
        self.active, self.acked = set(), set()
        self.test_res, self.test_t0, self.test_vmin, self.v_off = None, None, 99.0, 25.4
        self.ins = 25.0
        self.earth_side = "+"
        self.flags = {}
        self.loads_a = {}
        self.dc_a = 0.0
        tipb = ("CIRCUIT BREAKER for this equipment. Lamp above = supply present. A breaker that has tripped "
                "(orange flag) must be pushed to OFF and then ON again.")
        self.brk = {}
        for i, (k, lab, bus, _, _) in enumerate(LOADS):
            self.brk[k] = self.add(Toggle(70 + i * 88, 486, lab, True, tipb + "  Supplied from the %s." %
                                          ("SWITCHBOARD (AC) only - not backed by the battery" if bus == "AC" else
                                           "RADIO DC BUS: AC through the radio PSU, or the reserve battery"), style="breaker"))
        self.src = self.add(Selector(492, 128, 24, "RADIO SUPPLY", ["AUTO", "MAIN", "EMERG", "BATTERY"], 0,
            "RADIO SUPPLY CHANGEOVER: AUTO feeds the radio DC bus from the AC supply and changes over to the reserve "
            "battery the moment AC fails, without a break. MAIN / EMERG force that AC source (dead if it is off). "
            "BATTERY forces the reserve source - used for the weekly battery check."))
        self.gsel = self.add(Selector(492, 232, 22, "EM GENERATOR", ["AUTO", "TEST RUN", "STOP"], 0,
            "EMERGENCY GENERATOR control. AUTO: starts by itself within seconds of a blackout. TEST RUN: weekly "
            "test run off load. STOP: blocked - it will NOT start on a blackout (never leave it like this)."))
        self.dim = self.add(Knob(382, 316, 18, "PANEL LIGHTS", 0, 1, 1.0, "CONSOLE LIGHTING DIMMER: turn down "
            "at night to keep your dark adaptation. The displays keep their own brilliance controls."))
        self.chg = self.add(Selector(1450, 126, 24, "CHARGER", ["OFF", "FLOAT", "BOOST"], 1,
            "BATTERY CHARGER: FLOAT holds a charged battery at 27 V; BOOST (28.4 V) recharges it quickly after "
            "use - watch the temperature and return to FLOAT. OFF: the battery slowly loses charge."))
        self.b_test = self.add(Button((1390, 190, 186, 40), "ON-LOAD TEST\n(HOLD)", "BATTERY ON-LOAD TEST: hold to "
            "connect a 20 A test load. A healthy battery stays above 24 V; a failing one sags towards 21 V. "
            "Note the voltage off load and on load in the radio log every day.", color="cyan", size=10))
        self.b_ins = self.add(Button((1390, 240, 186, 36), "INSULATION TEST", "Measure the insulation resistance of "
            "the DC bus to the ship's hull. Below 1 MOhm there is an earth fault - find it before a second one "
            "makes a short circuit.", size=10))
        self.b_ack = self.add(Button((1146, 586, 140, 40), "ALARM\nACK", "Silence the buzzer and steady the "
            "flashing lamps. A lamp stays lit while the condition lasts.", color="red", size=10))
        self.b_lamp = self.add(Button((1294, 586, 140, 40), "LAMP\nTEST", "Hold: light every lamp to prove the bulbs.", size=10))
        self.b_reset = self.add(Button((1442, 586, 132, 40), "RESET\nMIN V", "Clear the stored on-load test result.", size=10))
        tipi = "INSTRUCTOR: "
        self.f_black = self.add(Toggle(84, 770, "BLACKOUT", False, tipi + "main switchboard fails. The emergency "
            "generator should start; until it does the AC loads (radar, Fleet dish) are dead and the radios run on the battery."))
        self.f_gen = self.add(Toggle(198, 770, "EM GEN\nFAIL", False, tipi + "emergency generator will not start. "
            "In a blackout everything that is not on the battery dies."))
        self.f_weak = self.add(Toggle(312, 770, "WEAK\nBATTERY", False, tipi + "aged battery: high internal "
            "resistance and little capacity. Shows up on the on-load test."))
        self.f_chg = self.add(Toggle(426, 770, "CHARGER\nFAULT", False, tipi + "charger output fails."))
        self.f_earth = self.add(Toggle(540, 770, "EARTH\nFAULT", False, tipi + "insulation breaks down on one "
            "side of the DC bus."))
        self.b_trip = self.add(Button((620, 742, 140, 40), "TRIP A\nBREAKER", tipi + "overload trips a random "
            "breaker. Find which equipment died and reset it here.", color="red", size=10))

    # ------------------------------------------------------------ services
    def state(self):
        return dict(ac=self.ac_live, dc=self.dc_from is not None, battery=self.dc_from == "BATT",
                    main=self.main_ok, emerg=self.emerg_ok)

    def ok(self, key):
        b = self.brk.get(key)
        if b is None:
            return True
        if not b.on:
            return False
        return self.ac_live if BUS[key] == "AC" else (self.dc_from is not None)

    @property
    def lights(self):
        """Console panel lighting level 0..1 (breaker and dimmer)."""
        return (0.15 + 0.85 * self.dim.val) if self.ok("LIGHTS") else 0.0

    # --------------------------------------------------------------- model
    def _tx_amps(self, key):
        a = self.app
        try:
            if key == "VHF":
                return 1.0 if a.vuhf.tx else 0.0
            if key == "MFHF":
                return min(1.0, a.hf.po / 400.0) if a.hf.tx else 0.0
            if key == "SATC":
                return 1.0 if (a.satcom.busy and "TRANSMIT" in a.satcom.busy[0]) else 0.0
            if key == "SAT2":
                return 1.0 if a.sat2.call == "CONNECTED" else 0.0
            if key == "AIS":
                return 0.15
        except AttributeError:
            pass
        return 0.0

    def update(self, dt):
        w = self.world
        t = w.t
        if self.b_trip.pop():
            cand = [k for k, b in self.brk.items() if b.on and k != "CHARGER"]
            if cand:
                k = cand[int(self.rng.integers(len(cand)))]
                self.brk[k].trip()
                self.flags["tripped"] = k
        if self.f_earth.pop() and self.f_earth.on:
            self.earth_side = "+" if self.rng.random() < 0.5 else "-"
        # sources
        main = not self.f_black.on
        gmode = self.gsel.value
        if self.f_gen.on or gmode == "STOP":
            if self.gen != "STOP":
                self.gen = "STOP"
        elif not main or gmode == "TEST RUN":
            if self.gen in ("STOP", "COOL"):
                if self.gen == "STOP":
                    self.gen, self.gen_t = "CRANK", t
                else:
                    self.gen = "RUN"
            elif self.gen == "CRANK" and t - self.gen_t > 6.0:
                self.gen, self.gen_t = "RUN", t
                ui.sfx("contactor", 0.8, pan=self.bg_pan)
        elif self.gen in ("CRANK", "RUN"):
            self.gen, self.gen_t = "COOL", t
        elif self.gen == "COOL" and t - self.gen_t > 12.0:
            self.gen = "STOP"
        emerg = self.gen in ("RUN", "COOL")
        ac = main or emerg
        if ac != self.ac_live:
            ui.sfx("breaker" if not ac else "contactor", 0.9, pan=self.bg_pan)
        self.main_ok, self.emerg_ok, self.ac_live = main, emerg, ac
        batt_ok = self.soc > 0.03
        s = self.src.value
        if s == "AUTO":
            dc = "AC" if ac else ("BATT" if batt_ok else None)
        elif s == "MAIN":
            dc = "AC" if main else None
        elif s == "EMERG":
            dc = "AC" if emerg else None
        else:
            dc = "BATT" if batt_ok else None
        if dc != self.dc_from:
            ui.sfx("relay", 0.9, pan=self.bg_pan)
            if dc is None and self.dc_from is not None and s != "AUTO":
                self.mistake("radio DC bus de-energised by the RADIO SUPPLY selector (%s not available)" % s)
            self.dc_from = dc
        # loads
        self.loads_a, dca = {}, 0.0
        for k, _, bus, idle, txa in LOADS:
            on = self.ok(k)
            a = (idle + txa * self._tx_amps(k)) if on else 0.0
            if k == "CHARGER":
                a = 0.0
            self.loads_a[k] = a
            if bus == "DC":
                dca += a
        self.dc_a = dca
        # battery
        testing = self.b_test.down
        if testing and self.test_t0 is None:
            self.test_t0, self.test_vmin, self.v_off = t, 99.0, self.v
            ui.sfx("contactor", 1.0)
        cap = CAP_AH * (0.2 if self.f_weak.on else 1.0)
        rint = 0.16 if self.f_weak.on else 0.012
        charging = (ac and self.ok("CHARGER") and self.chg.value != "OFF" and not self.f_chg.on and not testing)
        i = 0.0
        if self.dc_from == "BATT":
            i -= dca
        if testing:
            i -= 20.0
        if charging:
            boost = self.chg.value == "BOOST"
            i += min(25.0 if boost else 6.0, (1 - self.soc) * (140 if boost else 40) + (1.5 if boost else 0.3))
        self.soc = max(0.0, min(1.0, self.soc + i * dt / 3600.0 / cap))
        if self.chg.value == "OFF" or not ac:
            self.soc = max(0.0, self.soc - 0.00002 * dt)
        ocv = 22.8 + 2.8 * self.soc
        if charging:
            vset = 28.4 if self.chg.value == "BOOST" else 27.0
            v = min(vset, ocv + 0.08 * max(0.0, i) + 0.4)
        else:
            v = ocv + i * rint
        self.v += (v - self.v) * min(1.0, dt * 4)
        self.i = i
        self.temp += ((22.0 + (9.0 if charging and self.chg.value == "BOOST" and self.soc > 0.95 else 0.0)
                       + abs(i) * 0.05) - self.temp) * min(1.0, dt / 40.0)
        if testing:
            self.test_vmin = min(self.test_vmin, self.v)
        elif self.test_t0 is not None:
            held = t - self.test_t0
            ui.sfx("contactor", 0.8)
            if held >= 2.0:
                self.test_res = dict(off=self.v_off, on=self.test_vmin, ok=self.test_vmin >= 24.0, utc=w.utc_str()[:5])
                self.flags["load_test"] = t
                ui.sfx("ok" if self.test_res["ok"] else "error", 0.7)
            else:
                self.test_res = dict(off=self.v_off, on=self.test_vmin, ok=None, utc=w.utc_str()[:5])
            self.test_t0 = None
        if self.b_reset.pop():
            self.test_res = None
        if self.b_ins.pop():
            self.ins = (0.05 + float(self.rng.uniform(0, 0.15))) if self.f_earth.on else float(self.rng.uniform(12, 40))
            self.flags["ins_test"] = t
            ui.sfx("beep", 0.6)
        # alarms
        act = set()
        if not main:
            act.add("MAINS FAIL")
        if self.gen == "RUN":
            act.add("EM GEN\nRUNNING")
        if self.dc_from == "BATT":
            act.add("ON\nBATTERY")
        if (self.v < 23.2 and not charging) or self.soc < 0.3:
            act.add("BATTERY\nLOW")
        if self.f_chg.on or not self.ok("CHARGER"):
            act.add("CHARGER\nFAULT")
        if charging:
            act.add("CHARGING")
        if self.f_earth.on:
            act.add("EARTH\nFAULT +" if self.earth_side == "+" else "EARTH\nFAULT -")
        if any(b.tripped for b in self.brk.values()):
            act.add("BREAKER\nTRIPPED")
        if self.dc_from is None:
            act.add("DC BUS\nFAIL")
        if (self.f_gen.on or self.gsel.value == "STOP") and not main:
            act.add("EM GEN\nFAIL")
        if testing:
            act.add("TEST\nLOAD")
        new = (act - self.active) & AUDIBLE
        if new:
            self.acked -= new
        self.acked &= act
        self.active = act
        if self.b_ack.pop():
            if self.active & AUDIBLE - self.acked:
                self.flags["alarm_ack"] = t
            self.acked |= self.active
        self.alert = bool((self.active & AUDIBLE) - self.acked)

    def bg_audio(self, syn, n):
        out = None
        if self.alert:
            out = syn.buzzer("pwral", n, 410.0, 1.2) * 0.5
        if self.gen == "CRANK":
            t = syn._time(n)
            k = min(1.0, (self.world.t - self.gen_t) / 6.0)
            starter = syn.osc("stm", 150 + 60 * k, n) * 0.04 + syn.rumble("stn", n, 6) * 0.03
            chuff = (np.sin(2 * np.pi * (2.5 + 6 * k) * t) > 0.6) * syn.rumble("chf", n, 5) * 0.12 * k
            out = (0 if out is None else out) + starter + chuff
        elif self.gen in ("RUN", "COOL"):
            f = 22.0
            d = (syn.osc("g1", f, n) * 0.5 + syn.osc("g2", 2 * f, n) * 0.35 + syn.osc("g3", 3 * f, n) * 0.2
                 + syn.rumble("gn", n, 6) * 0.35) * 0.06
            out = (0 if out is None else out) + d
        if "CHARGING" in self.active:
            out = (0 if out is None else out) + syn.osc("chh", 100.0, n) * (0.006 if self.chg.value == "BOOST" else 0.003)
        if self.test_t0 is not None:
            out = (0 if out is None else out) + syn.rumble("tlf", n, 3) * 0.03
        return out

    # ---------------------------------------------------------------- draw
    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if pygame.Rect(36, 80, 400, 264).collidepoint(pos):
            return ("MIMIC DIAGRAM: lit lines are energised. Main and emergency switchboards feed the AC bus; the "
                    "radio PSU makes the 24 V radio bus, which the reserve battery holds up when AC fails.")
        if pygame.Rect(1130, 362, 460, 300).collidepoint(pos):
            return "ALARM PANEL: flashing = new alarm (buzzer), steady = acknowledged but still present."
        return ""

    def _seg(self, s, pts, live, col=None):
        c = (col or C["amber"]) if live else (64, 68, 74)
        pygame.draw.lines(s, (8, 9, 10), False, [(x + 1, y + 2) for x, y in pts], 5)
        pygame.draw.lines(s, c, False, pts, 4 if live else 3)
        if live:
            off = (self.world.t * 40) % 18
            d = off
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                ln = math.hypot(x1 - x0, y1 - y0)
                while d < ln:
                    pygame.draw.circle(s, (255, 240, 200), (x0 + (x1 - x0) * d / ln, y0 + (y1 - y0) * d / ln), 1)
                    d += 18
                d -= ln

    def _box(self, s, r, label, live):
        r = pygame.Rect(r)
        pygame.draw.rect(s, (10, 11, 12), r.move(2, 3), border_radius=4)
        pygame.draw.rect(s, (40, 44, 50) if not live else (60, 52, 30), r, border_radius=4)
        pygame.draw.rect(s, C["amber"] if live else (90, 94, 100), r, 1, border_radius=4)
        ui.text_block(s, label, (r.x + 6, r.y + 4, r.w - 8, r.h), 9, (230, 220, 190) if live else (150, 152, 150), lh=11, bold=True)

    def draw(self, s):
        w = self.world
        lamp = self.b_lamp.down
        ui.panel(s, (20, 54, 560, 300), "SUPPLY - MIMIC DIAGRAM")
        ui.panel(s, (590, 54, 1000, 300), "RESERVE SOURCE  -  24 V RADIO BATTERY  %d Ah  +  CHARGER" % CAP_AH)
        ui.panel(s, (20, 362, 1100, 300), "DISTRIBUTION  -  RADIO CIRCUIT BREAKERS")
        ui.panel(s, (1130, 362, 460, 300), "ALARM PANEL")
        ui.panel(s, (20, 670, 760, 190), "INSTRUCTOR: POWER FAULTS")
        ui.panel(s, (790, 670, 800, 190), "LOADS AND ENDURANCE")
        # mimic
        main, em, ac, dc = self.main_ok, self.emerg_ok, self.ac_live, self.dc_from
        pygame.draw.rect(s, (14, 16, 18), (36, 80, 404, 264), border_radius=6)
        self._box(s, (46, 92, 98, 30), "MAIN SWBD\n440 / 230 V", main)
        self._box(s, (46, 152, 98, 30), "EMERGENCY\nSWBD 230 V", em)
        gl = self.gen in ("RUN", "COOL")
        pygame.draw.circle(s, (60, 52, 30) if gl else (40, 44, 50), (95, 226), 18)
        pygame.draw.circle(s, C["amber"] if gl else (90, 94, 100), (95, 226), 18, 2)
        text(s, "G", (95, 226), 16, C["amber"] if gl else (150, 152, 150), bold=True, align="m")
        text(s, {"STOP": "STOPPED", "CRANK": "CRANKING", "RUN": "RUNNING", "COOL": "RUN-ON"}[self.gen], (95, 252), 9,
             C["amber"] if self.gen != "STOP" else C["dim"], bold=True, align="c")
        self._seg(s, [(95, 208), (95, 182)], gl)
        self._seg(s, [(144, 107), (210, 107), (210, 136)], main)
        self._seg(s, [(144, 167), (210, 167), (210, 136)], em)
        self._seg(s, [(210, 136), (430, 136)], ac)
        text(s, "AC 230 V BUS", (330, 120), 9, C["amber"] if ac else C["dim"], bold=True)
        self._box(s, (262, 176, 80, 30), "RADIO PSU\nAC / DC", ac and dc == "AC")
        self._seg(s, [(302, 136), (302, 176)], ac)
        self._box(s, (150, 196, 84, 30), "CHARGER\n%s" % self.chg.value, "CHARGING" in self.active)
        self._seg(s, [(240, 136), (240, 160), (192, 160), (192, 196)], ac and self.ok("CHARGER"))
        self._seg(s, [(192, 226), (192, 296), (170, 296)], "CHARGING" in self.active, C["green"])
        self._seg(s, [(302, 206), (302, 270)], dc == "AC")
        self._seg(s, [(60, 270), (430, 270)], dc is not None, C["green"])
        text(s, "DC 24 V RADIO BUS", (318, 254), 9, C["green"] if dc else C["dim"], bold=True)
        # battery symbol
        bx, by = 120, 300
        for k in range(4):
            x = bx + k * 10
            pygame.draw.line(s, (200, 200, 190), (x, by - 12), (x, by + 12), 2)
            pygame.draw.line(s, (200, 200, 190), (x + 5, by - 6), (x + 5, by + 6), 4)
        text(s, "BATTERY", (bx + 18, by + 18), 9, C["text"], bold=True, align="c")
        self._seg(s, [(120, 288), (120, 270)], dc == "BATT" or "CHARGING" in self.active, C["green"])
        ui.led(s, (232, 326), "green", dc == "BATT" or lamp, "ON BATTERY", 5, 9)
        # battery meters
        ui.meter(s, (606, 82, 176, 112), (self.v - 18) / 12.0, "BATT  %.1f V" % self.v,
                 [(0.25, "21"), (0.5, "24"), (0.75, "27")], red_from=None)
        ui.meter(s, (794, 82, 176, 112), 0.5 + self.i / 80.0, "BATT  %+.1f A" % self.i,
                 [(0.25, "-20"), (0.5, "0"), (0.75, "+20")])
        acv = 230 if ac else 0
        ui.meter(s, (982, 82, 176, 112), acv / 300.0, "AC BUS  %d V" % acv,
                 [(1 / 3, "100"), (2 / 3, "200")], red_from=None)
        ui.meter(s, (1170, 82, 176, 112), min(1.0, math.log10(max(0.01, self.ins) * 10) / 3.0), "INSUL  %.2f MOhm" % self.ins,
                 [(1 / 3, "1"), (2 / 3, "10")])
        l = ui.lcd(s, (606, 212, 740, 126))
        fg = C["lcdfg"]
        st = ("CHARGING %s %.1f A" % (self.chg.value, self.i)) if "CHARGING" in self.active else \
            ("DISCHARGING %.1f A" % -self.i if self.i < -0.05 else "IDLE (charger %s)" % self.chg.value)
        load = self.dc_a if dc == "BATT" else max(self.dc_a, 0.1)
        hrs = self.soc * CAP_AH * (0.2 if self.f_weak.on else 1.0) / max(0.1, load)
        rows = ["STATE    %s" % st,
                "CHARGE   %3d %%   TEMP %4.1f C   SOURCE NOW: %s" % (round(self.soc * 100), self.temp,
                                                                     {"AC": "AC VIA PSU", "BATT": "RESERVE BATTERY", None: "NONE"}[dc]),
                "RESERVE  %d h %02d min at the present radio load (%.1f A)" % (int(hrs), int(hrs * 60) % 60, load),
                ("LAST ON-LOAD TEST %s UTC: %.1f V off load, %.1f V on load  %s" %
                 (self.test_res["utc"], self.test_res["off"], self.test_res["on"],
                  {True: "PASS", False: "FAIL - REPLACE BATTERY", None: "(hold 2 s)"}[self.test_res["ok"]]))
                if self.test_res else "ON-LOAD TEST: not done this watch",
                "GMDSS: reserve must run the radios 1 h (6 h with no emergency generator)"]
        for k, r in enumerate(rows):
            col = fg
            if k == 3 and self.test_res and self.test_res["ok"] is False:
                col = C["red"]
            text(s, r, (l.x + 10, l.y + 8 + k * 22), 12, col, bold=k == 0)
        if self.test_t0 is not None:
            text(s, "TEST LOAD 20 A: %.1f V" % self.v, (l.right - 10, l.y + 8), 12, C["cyan"], bold=True, align="r")
        # breakers: supply lamps and currents
        for i, (k, lab, bus, _, _) in enumerate(LOADS):
            x = 70 + i * 88
            live = (self.ac_live if bus == "AC" else dc is not None)
            ui.led(s, (x, 410), "green" if bus == "DC" else "amber", (live and self.brk[k].on) or lamp, None, 6)
            text(s, bus, (x, 426), 8, C["dim"], bold=True, align="c")
            text(s, "%.1f A" % self.loads_a.get(k, 0.0), (x, 560), 11, C["lcdfg"] if self.loads_a.get(k) else C["dim"], bold=True, align="c")
        pygame.draw.line(s, (90, 94, 100), (40, 584), (1100, 584), 1)
        text(s, "AC (switchboard only)  |  DC (radio bus, battery-backed)", (40, 592), 10, C["dim"], bold=True)
        text(s, "DC BUS LOAD %.1f A   %s" % (self.dc_a, "FROM BATTERY" if dc == "BATT" else ("FROM AC" if dc else "BUS DEAD")),
             (1100, 592), 11, C["green"] if dc else C["red"], bold=True, align="r")
        # annunciators
        for j, lab in enumerate(ALARMS):
            r = pygame.Rect(1146 + (j % 4) * 108, 392 + (j // 4) * 58, 100, 48)
            on = lab in self.active or lamp
            unack = lab in AUDIBLE and lab in self.active and lab not in self.acked
            ui.annunciator(s, r, lab, ALARM_COL.get(lab, "red"), on, 9, flash=unack and not lamp)
        # load table
        l = ui.lcd(s, (806, 694, 768, 152))
        text(s, "EQUIPMENT      BUS  BREAKER  SUPPLY  AMPS", (l.x + 10, l.y + 6), 11, C["dim"], bold=True)
        for j, (k, lab, bus, _, _) in enumerate(LOADS):
            col, row = j // 6, j % 6
            b = self.brk[k]
            stt = "TRIP" if b.tripped else ("ON" if b.on else "OFF")
            ok = self.ok(k)
            text(s, "%-13s  %-3s  %-4s  %-4s  %4.1f" % (lab.replace("\n", " ")[:13], bus, stt, "LIVE" if ok else "DEAD",
                                                     self.loads_a.get(k, 0.0)),
                 (l.x + 10 + col * 380, l.y + 26 + row * 20), 11, fg if ok else (C["red"] if b.tripped else C["amber"]))
        super().draw(s)
