"""Navigation sensors and the AIS transponder.

GPS feeds position to the DSC controllers, Inmarsat-C and AIS. When it
loses its fix, every DSC alert goes out with the 'position unknown' code
unless you enter the position by hand here - and keep it up to date.

The gyro compass feeds heading to the radar. Its speed / latitude correction
knobs must match the ship: a mismatch leaves a real gyro error (about a
degree at 10 knots) that turns every radar bearing by that amount. After
switch-on it has to settle. If it fails the radar loses north-up.

The speed log feeds ARPA. A calibration error does not change CPA (that
comes from relative motion) but makes every target's TRUE course and speed
wrong.
"""
import math
import numpy as np
import pygame
from . import ui, fx
from .ui import C, text, Knob, Selector, Button, Toggle, Station, thumbs, thumb_str
from .world import fmt_lat, fmt_lon, wrap180

DATUMS = ["WGS84", "ED50", "OSGB36", "TOKYO"]
DATUM_SHIFT = {"WGS84": (0.0, 0.0), "ED50": (0.00085, 0.0013), "OSGB36": (-0.00045, 0.0017), "TOKYO": (-0.0028, 0.0031)}
NAVSTAT = ["UNDER WAY USING ENGINE", "AT ANCHOR", "NOT UNDER COMMAND", "RESTRICTED MANOEUVRABILITY",
           "CONSTRAINED BY DRAUGHT", "MOORED", "AGROUND", "ENGAGED IN FISHING", "UNDER WAY SAILING"]
NAVSHORT = ["UNDERWAY ENG", "AT ANCHOR", "NUC", "RESTR MAN", "CBD", "MOORED", "AGROUND", "FISHING", "SAILING"]
DESTS = ["PENHALE", "FALMOUTH", "ROTTERDAM", "BREST", "CORK", "FOR ORDERS"]
SAR_DEV = {"AIS-SART": (970, "SART"), "MOB": (972, "MOB"), "EPIRB-AIS": (974, "EPIRB")}
PAGES = ["TARGETS", "DETAIL", "OWN", "VOYAGE", "SRM", "ALARMS"]


class Nav(Station):
    name = "NAV SENSORS / AIS"
    tab = "NAV/AIS"
    hint = ("GPS, gyro compass, speed log, manual position for DSC, and the AIS transponder. These sensors feed the "
            "radar, the DSC controllers and Inmarsat-C - break one with the instructor faults and see what fails.")
    power_key = "GPS"
    pan, bg_pan = 0.0, 0.45

    def __init__(self, app):
        super().__init__(app)
        w = self.world
        self.rng = np.random.default_rng(57)
        # GPS satellites: PRN, azimuth, elevation, drift rates
        self.sats = [dict(prn=int(p), az=float(self.rng.uniform(0, 360)), el=float(self.rng.uniform(8, 85)),
                          daz=float(self.rng.uniform(-0.02, 0.02)), del_=float(self.rng.uniform(-0.01, 0.01)), snr=0.0)
                     for p in self.rng.choice(np.arange(1, 33), 11, replace=False)]
        for s_ in self.sats:
            s_["snr"] = 30 + 18 * math.sin(math.radians(s_["el"]))
        self.gy_acked = False
        self.gps_t0 = -40.0                    # time the receiver was powered (fix after ~35 s cold)
        self.jam = 0.0
        self.fix, self.nsat, self.hdop = "3D", 9, 1.0
        self.gps_lat, self.gps_lon = w.lat, w.lon
        self.mob = None
        self.page_gps = "POS"
        self.gyro_state, self.gyro_t0 = "RUN", -999.0
        self.gyro_out = w.hdg
        self.trip = 0.0
        self.man = None                        # manual DSC position (lat, lon, sim time)
        self.flags = {}
        self.alarms_gps, self.ack_gps = set(), set()
        self.alarms_ais, self.ack_ais = set(), set()
        self.page, self.cur_i, self.sel_mmsi = "TARGETS", 0, None
        self.srm_in, self.srm_out = [], []
        self._srm_next = 70.0
        self.ais_tx_count, self._ais_last_tx = 0, 0.0
        self._silent_since, self._silent_called = None, False
        self.dest_i = 0
        # ---------------------------------------------------------------- GPS
        tg = "GPS NAVIGATOR: "
        self.gps_pwr = self.add(Toggle(62, 308, "POWER", True, tg + "receiver power. After switch-on it needs about "
            "35 s to collect satellites (cold start) before there is a position fix."))
        self.gps_mode = self.add(Selector(150, 310, 20, "MODE", ["GPS", "DGPS", "SBAS"], 1, tg + "DGPS uses "
            "corrections from a coast beacon (or SBAS satellites) for a few metres accuracy instead of ~10 m."))
        self.gps_datum = self.add(Selector(236, 310, 20, "DATUM", DATUMS, 0, tg + "horizontal datum of the "
            "position output. It MUST match the chart (WGS84 for modern charts and for DSC/AIS); a wrong datum shifts "
            "the position by up to hundreds of metres."))
        self.gps_pages = {}
        for i, p in enumerate(("POS", "SKY", "MOB")):
            self.gps_pages[p] = self.add(Button((290 + i * 58, 290, 54, 30), p, tg + "display page: position, satellite "
                                                "sky view, or range and bearing back to the man-overboard mark.", size=10))
        self.gps_mob = self.add(Button((470, 290, 66, 30), "MOB", tg + "MAN OVERBOARD: stores the position at once "
            "and shows range and bearing back to it (also plotted on the radar).", color="red", size=11))
        self.gps_ack = self.add(Button((542, 290, 66, 30), "ACK", tg + "acknowledge GPS alarms (no fix, HDOP, DGPS).", size=10))
        self.gps_dim = self.add(Knob(650, 308, 17, "DIMMER", 0.2, 1.0, 1.0, tg + "display brightness."))
        self.gps_hold = self.add(Toggle(726, 306, "AUTO\nOUT", True, tg + "position output to DSC, Inmarsat-C and AIS. "
            "OFF = those units get no GPS position.", up="ON", down="OFF"))
        # --------------------------------------------------------------- gyro
        tgy = "GYRO COMPASS: "
        self.gy_pwr = self.add(Toggle(262, 414, "MAIN", True, tgy + "main switch. After switch-on the gyro must SETTLE "
            "(hours on a real ship, about a minute here); its heading wanders until it has."))
        self.gy_lat = self.add(Knob(262, 540, 19, "LAT CORR", -80, 80, 50, tgy + "latitude correction: set to the "
            "ship's latitude.", step=1, fmt=lambda v: "%d°%s" % (abs(v), "N" if v >= 0 else "S")))
        self.gy_spd = self.add(Knob(346, 540, 19, "SPEED CORR", 0, 30, 10, tgy + "speed correction: set to the ship's "
            "speed. A mismatch leaves a north-steaming (speed) error of about 0.06° per knot divided by cos(latitude).",
            step=1, fmt=lambda v: "%d kn" % v))
        self.gy_ack = self.add(Button((236, 600, 74, 30), "ACK", tgy + "acknowledge gyro alarms.", size=10))
        self.gy_test = self.add(Button((316, 600, 74, 30), "TEST", tgy + "lamp and alarm test.", size=10))
        # ---------------------------------------------------------------- log
        tl = "SPEED LOG: "
        self.log_mode = self.add(Selector(470, 572, 20, "MODE", ["WATER", "BOTTOM"], 0, tl + "WATER track = speed "
            "through the water (what ARPA wants for collision avoidance); BOTTOM track = speed over ground in shallow water."))
        self.log_cal = self.add(Knob(560, 572, 19, "CAL %", -10, 10, 0, tl + "calibration. An error here makes ARPA "
            "work out every target's TRUE course and speed wrongly (CPA is unaffected).", step=0.5, fmt=lambda v: "%+.1f%%" % v))
        self.log_rst = self.add(Button((620, 556, 140, 30), "TRIP RESET", tl + "reset the distance run.", size=10))
        # ---------------------------------------------------- DSC position
        tp = ("MANUAL POSITION for the DSC controllers and Inmarsat-C, used only when there is no GPS. Set the "
              "wheels (click top / bottom or use the wheel), then ENTER. Update it at least every 4 hours.")
        self.th_lat = thumbs(self, 52, 726, "4950.0N", tp)
        self.th_lon = thumbs(self, 236, 726, "00529.8W", tp)
        self.th_utc = thumbs(self, 440, 726, "0000", tp)
        self.b_enter = self.add(Button((560, 702, 100, 30), "ENTER", tp, color="green", size=10))
        self.b_auto = self.add(Button((560, 738, 100, 30), "USE GPS", "Return the DSC position source to the GPS "
            "(automatic).", size=10))
        self.b_load = self.add(Button((666, 702, 100, 30), "LOAD DR", "Load the wheels with the dead-reckoning "
            "position from the chart (true position) and the time now - then press ENTER.", size=10))
        self.b_clr = self.add(Button((666, 738, 100, 30), "CLEAR", "Clear the manual position.", size=10))
        # ---------------------------------------------------------------- AIS
        ta = "AIS MKD: "
        self.ais_keys = {}
        for i, p in enumerate(PAGES):
            self.ais_keys[p] = self.add(Button((806 + i * 90, 390, 86, 30), p, ta + "show the %s page." % p, size=10))
        self.ais_up = self.add(Button((1358, 84, 60, 32), "▲", ta + "move the cursor up the list."))
        self.ais_dn = self.add(Button((1358, 122, 60, 32), "▼", ta + "move the cursor down."))
        self.ais_ent = self.add(Button((1358, 160, 60, 32), "ENT", ta + "select the target under the cursor (DETAIL page).", size=10))
        self.ais_back = self.add(Button((1358, 198, 60, 32), "BACK", ta + "back to the target list.", size=10))
        self.ais_nav = self.add(Selector(1505, 136, 22, "NAV STATUS", NAVSHORT, 0, ta + "navigational status "
            "broadcast in every position report. Keep it right: at anchor, NUC, restricted, fishing..."))
        self.ais_draught = self.add(Knob(1450, 228, 18, "DRAUGHT", 2.0, 16.0, 7.4, ta + "present static draught.",
                                         step=0.1, fmt=lambda v: "%.1f m" % v))
        self.ais_pob = self.add(Knob(1540, 228, 18, "POB", 1, 40, 12, ta + "persons on board (voyage data) - also used "
            "by the coastguard in a distress.", step=1, fmt=lambda v: "%d" % v))
        self.ais_pwr = self.add(Selector(1450, 340, 18, "TX POWER", ["12.5 W", "2 W"], 0, ta + "transmit power. "
            "LOW (2 W) is used by tankers alongside and in some harbours."))
        self.ais_silent = self.add(Toggle(1540, 336, "SILENT", False, ta + "SILENT MODE: transmitter off, receive "
            "only. Only at the master's discretion (e.g. piracy areas); the coastguard will notice.", up="TX OFF", down="NORMAL"))
        self.ais_dest = self.add(Button((1356, 390, 110, 30), "DEST", ta + "cycle the destination in the voyage data.", size=10))
        self.ais_ack = self.add(Button((1472, 390, 106, 30), "ACK", ta + "acknowledge AIS alarms (AIS-SART, TX fault, "
            "lost target, new safety message).", color="red", size=10))
        ts = ta + "send a broadcast SAFETY RELATED MESSAGE (text) to all AIS stations around: "
        self.srm_b = {}
        for i, (k, t_) in enumerate((("MOB", "MAN OVERBOARD IN MY POSITION, KEEP SHARP LOOKOUT"),
                                     ("NUC", "NOT UNDER COMMAND, ENGINE FAILURE, KEEP CLEAR"),
                                     ("PIRACY", "SUSPICIOUS CRAFT APPROACHING, ALL SHIPS KEEP WATCH"),
                                     ("ICE", "GROWLERS SIGHTED IN MY POSITION"))):
            self.srm_b[k] = (self.add(Button((900 + i * 112, 436, 106, 30), "SRM " + k, ts + t_, size=10)), t_)
        # --------------------------------------------------------- instructor
        ti = "INSTRUCTOR: "
        self.f_ant = self.add(Toggle(830, 636, "GPS ANT\nFAIL", False, ti + "GPS antenna cable fault: no satellites."))
        self.f_jam = self.add(Toggle(910, 636, "GPS\nJAMMING", False, ti + "radio interference on L1: signals sink "
            "into the noise one by one and the fix is lost."))
        self.f_gyro = self.add(Toggle(990, 636, "GYRO\nFAIL", False, ti + "gyro follow-up failure: heading output freezes."))
        self.f_log = self.add(Toggle(1070, 636, "LOG\nFAIL", False, ti + "speed log fails: ARPA has no own-ship speed."))
        self.f_ais = self.add(Toggle(1150, 636, "AIS TX\nFAULT", False, ti + "AIS transmitter fault (antenna VSWR)."))
        self.dev_sel = self.add(Selector(1250, 640, 20, "SAR DEVICE", list(SAR_DEV), 0, ti + "AIS search-and-rescue "
            "device type: AIS-SART (MMSI 970...), MOB device (972...), EPIRB-AIS (974...)."))
        self.dev_on = self.add(Toggle(1340, 636, "DEVICE\nACTIVE", False, ti + "switch the device on 2-4 NM from the ship "
            "(at the radar SART if that is active). It appears on the AIS display and the radar AIS overlay."))

    # ------------------------------------------------------------ outputs
    @property
    def gps_on(self):
        return self.gps_pwr.on and self.app.powered("GPS")

    def gps_fix(self):
        return self.gps_on and self.fix in ("2D", "3D")

    def gps_position(self):
        """(lat, lon) on the selected datum, or None."""
        if not self.gps_fix():
            return None
        dla, dlo = DATUM_SHIFT[self.gps_datum.value]
        return self.gps_lat + dla, self.gps_lon + dlo

    def dsc_position(self):
        p = self.gps_position() if self.gps_hold.on else None
        if p:
            return p[0], p[1], "GPS", 0.0
        if self.man:
            return self.man[0], self.man[1], "MANUAL", self.world.t - self.man[2]
        return None

    @property
    def gyro_ok(self):
        return self.gyro_state in ("RUN", "SETTLING") and not self.f_gyro.on and self.gy_pwr.on and self.app.powered("GYRO")

    def gyro_error(self):
        """Heading error of the gyro output (deg, output - true)."""
        return wrap180(self.gyro_out - self.world.hdg)

    def log_speed(self):
        if self.f_log.on or not self.app.powered("GYRO"):
            return None
        return self.world.spd * (1 + self.log_cal.val / 100.0)

    @property
    def ais_tx(self):
        return self.app.powered("AIS") and not self.ais_silent.on and not self.f_ais.on

    def _speed_error(self, v, lat, crs):
        c = math.cos(math.radians(max(-85, min(85, lat))))
        return 0.0634 * v * math.cos(math.radians(crs)) / max(0.1, c)

    # --------------------------------------------------------------- update
    def update(self, dt):
        w, t = self.world, self.world.t
        # ---- GPS
        if self.gps_pwr.pop() and self.gps_pwr.on:
            self.gps_t0 = t
        if not self.gps_on:
            self.gps_t0 = t
        for p, b in self.gps_pages.items():
            if b.pop():
                self.page_gps = p
            b.on = self.page_gps == p
        self.jam += ((1.0 if self.f_jam.on else 0.0) - self.jam) * min(1.0, dt / 8.0)
        warm = t - self.gps_t0
        n = 0
        for i, s_ in enumerate(self.sats):
            s_["az"] = (s_["az"] + s_["daz"] * dt) % 360
            s_["el"] = max(3.0, min(88.0, s_["el"] + s_["del_"] * dt))
            if s_["el"] in (3.0, 88.0):
                s_["del_"] = -s_["del_"]
            base = 30 + 18 * math.sin(math.radians(s_["el"])) + 2 * math.sin(t * 0.3 + i)
            if self.f_ant.on or not self.gps_on or warm < 3 + i * 3:
                base = 0.0
            snr = max(0.0, base - self.jam * (28 + 4 * (i % 4)))
            s_["snr"] += (snr - s_["snr"]) * min(1.0, dt * 2)
            if s_["snr"] > 28:
                n += 1
        self.nsat = n
        fix = "3D" if n >= 4 and warm > 32 else ("2D" if n == 3 and warm > 32 else "NO FIX")
        if fix != self.fix:
            ui.sfx("ok" if fix != "NO FIX" else "unlock", 0.6, pan=self.bg_pan)
        self.fix = fix
        self.hdop = 0.7 + 6.0 / max(1, n)
        if self.gps_fix():
            jit = (0.00002 if self.gps_mode.value != "GPS" else 0.00008) * (1 + self.hdop)
            self.gps_lat = w.lat + float(self.rng.normal(0, jit))
            self.gps_lon = w.lon + float(self.rng.normal(0, jit * 1.5))
        if self.gps_mob.pop():
            if self.gps_fix():
                self.mob = dict(lat=self.gps_lat, lon=self.gps_lon, x=w.x, y=w.y, t=t, utc=w.utc_str()[:5])
                self.page_gps = "MOB"
                self.flags["mob"] = t
                ui.sfx("beep2", 0.9)
            else:
                ui.sfx("error", 0.6)
                self.mistake("MOB pressed with no GPS fix - no position stored. Note the time and use the radar / DR.")
        ag = set()
        if self.gps_on and self.fix == "NO FIX" and warm > 40:
            ag.add("NO FIX")
        if self.gps_fix() and self.hdop > 2.5:
            ag.add("HDOP HIGH")
        if self.gps_on and self.gps_mode.value == "DGPS" and self.jam > 0.3:
            ag.add("DGPS LOST")
        if self.gps_datum.value != "WGS84":
            ag.add("DATUM NOT WGS84")
        self.ack_gps &= ag
        if self.gps_ack.pop():
            self.ack_gps |= ag
        self.alarms_gps = ag
        # ---- manual DSC position
        if self.b_enter.pop():
            s_lat, s_lon, s_t = thumb_str(self.th_lat), thumb_str(self.th_lon), thumb_str(self.th_utc)
            try:
                la = int(s_lat[0:2]) + float(s_lat[2:6]) / 60.0
                lo = int(s_lon[0:3]) + float(s_lon[3:7]) / 60.0
                la = la if s_lat[-1] == "N" else -la
                lo = lo if s_lon[-1] == "E" else -lo
                hh, mm = int(s_t[:2]), int(s_t[2:])
                assert la <= 90 and abs(lo) <= 180 and hh < 24 and mm < 60 and float(s_lat[2:6]) < 60 and float(s_lon[3:7]) < 60
                age = ((w.utc_h * 60 - (hh * 60 + mm)) % 1440) * 60.0
                self.man = (la, lo, t - age)
                self.flags["manual_pos"] = t
                ui.sfx("ok", 0.7)
                err = math.hypot((la - w.lat) * 60, (lo - w.lon) * 60 * math.cos(math.radians(w.lat)))
                if err > 3:
                    self.mistake("manual DSC position is %.0f NM from the ship - check the wheels." % err)
            except (ValueError, AssertionError):
                ui.sfx("error", 0.7)
                self.mistake("manual position rejected - check degrees (<90/<180), minutes (<60) and time.")
        if self.b_auto.pop():
            self.gps_hold.on = True
        if self.b_clr.pop():
            self.man = None
        if self.b_load.pop():
            la, lo = abs(w.lat), abs(w.lon)
            s = "%02d%04.1f%s" % (int(la), (la % 1) * 60, "N" if w.lat >= 0 else "S")
            for wh, ch in zip([x for x in self.th_lat if x], s.replace(".", "")):
                wh.set(ch)
            s = "%03d%04.1f%s" % (int(lo), (lo % 1) * 60, "E" if w.lon >= 0 else "W")
            for wh, ch in zip([x for x in self.th_lon if x], s.replace(".", "")):
                wh.set(ch)
            h = w.utc_h % 24
            for wh, ch in zip(self.th_utc, "%02d%02d" % (int(h), int(h * 60) % 60)):
                wh.set(ch)
            ui.sfx("thumb", 0.8)
        # ---- gyro
        if self.gy_pwr.pop() and self.gy_pwr.on:
            self.gyro_t0 = t
        powered = self.gy_pwr.on and self.app.powered("GYRO")
        if not powered:
            self.gyro_state = "OFF"
        elif self.gyro_state == "OFF":
            self.gyro_state, self.gyro_t0 = "SETTLING", t
        elif self.gyro_state == "SETTLING" and t - self.gyro_t0 > 60:
            self.gyro_state = "RUN"
            ui.sfx("ok", 0.5, pan=self.bg_pan)
        galarm = self.gy_pwr.on and (self.f_gyro.on or not self.app.powered("GYRO"))
        if self.gy_ack.pop() and galarm:
            self.gy_acked = True
            self.flags["gyro_ack"] = t
        if not galarm:
            self.gy_acked = False
        self.gyro_alarm = galarm
        if self.gyro_ok:
            st = t - self.gyro_t0
            settle = 24.0 * math.exp(-st / 16.0) * math.cos(2 * math.pi * st / 38.0) if self.gyro_state == "SETTLING" else 0.0
            err = self._speed_error(w.spd, w.lat, w.hdg) - self._speed_error(self.gy_spd.val, self.gy_lat.val, w.hdg)
            self.gyro_out = (w.hdg + settle + err) % 360
        # ---- log
        ls = self.log_speed()
        if ls is not None:
            self.trip += ls * dt / 3600.0
        if self.log_rst.pop():
            self.trip = 0.0
        # ---- AIS
        for p, b in self.ais_keys.items():
            if b.pop():
                self.page = p
            b.on = self.page == p
        tg = self.targets()
        if self.ais_up.pop():
            self.cur_i = max(0, self.cur_i - 1)
        if self.ais_dn.pop():
            self.cur_i = min(max(0, len(tg) - 1), self.cur_i + 1)
        if self.ais_ent.pop() and tg:
            self.sel_mmsi = tg[min(self.cur_i, len(tg) - 1)]["mmsi"]
            self.page = "DETAIL"
        if self.ais_back.pop():
            self.page = "TARGETS"
        if self.ais_dest.pop():
            self.dest_i = (self.dest_i + 1) % len(DESTS)
        w.pob = int(self.ais_pob.val)
        if self.ais_tx and t - self._ais_last_tx > (10.0 if w.spd < 14 else 6.0):
            self._ais_last_tx = t
            self.ais_tx_count += 1
        # silent too long -> the coastguard calls
        if not self.ais_tx and self.app.powered("AIS"):
            if self._silent_since is None:
                self._silent_since = t
            elif t - self._silent_since > 150 and not self._silent_called and w.radio_chatter:
                self._silent_called = True
                w.say(16, w.srcs["CG"], "%s, %s, THIS IS PENHALE COASTGUARD. WE HAVE LOST YOUR AIS SIGNAL. "
                      "PLEASE CHECK YOUR AIS TRANSPONDER AND REPORT ON CHANNEL 67. OVER." % (w.name, w.name), 1.5)
                self.flags["cg_ais_call"] = t
        else:
            self._silent_since, self._silent_called = None, False
        for k, (b, txt) in self.srm_b.items():
            if b.pop():
                if self.ais_tx:
                    self.srm_out.append((w.utc_str()[:5], "ALL", txt))
                    self.flags["srm_sent"] = t
                    ui.sfx("sbd", 0.6)
                else:
                    ui.sfx("error", 0.6)
                    self.mistake("SRM not sent - the AIS transmitter is off (silent mode / fault / breaker).")
        if t > self._srm_next and self.app.powered("AIS"):
            self._srm_next = t + 190.0
            self.srm_in.append((w.utc_str()[:5], "002320777 PENHALE CG", "SAFETY: FAIRWAY BUOY RACON UNRELIABLE. "
                                "SURVEY VESSEL WORKING 2 NM SW OF PENHALE HEAD, GIVE WIDE BERTH."))
            self.alarms_ais.add("NEW SRM")
            self.ack_ais.discard("NEW SRM")
            ui.sfx("beep2", 0.5, pan=self.bg_pan)
        # SAR device (instructor)
        if self.dev_on.pop() or self.dev_sel.idx != getattr(self, "_dev_idx", 0):
            self._dev_idx = self.dev_sel.idx
            if self.dev_on.on:
                sart = w.by_name.get("SART")
                if sart is not None and sart.active:
                    x, y = sart.x, sart.y
                else:
                    a = float(self.rng.uniform(0, 2 * math.pi))
                    d = float(self.rng.uniform(2.0, 4.0))
                    x, y = w.x + d * math.sin(a), w.y + d * math.cos(a)
                pre, kind = SAR_DEV[self.dev_sel.value]
                w.ais_device = dict(on=True, kind=kind, mmsi=pre * 1000000 + 123456, x=x, y=y,
                                    label="%s ACTIVE" % ("SART" if kind == "SART" else kind))
                self.srm_in.append((w.utc_str()[:5], "%09d" % (pre * 1000000 + 123456), "%s ACTIVE" % kind))
            else:
                w.ais_device = None
        aa = set(a for a in self.alarms_ais if a == "NEW SRM")
        if w.ais_device and w.ais_device.get("on") and self.app.powered("AIS"):
            aa.add("%s ACTIVE" % w.ais_device["kind"])
            self.flags["ais_sart_seen"] = t
        if self.f_ais.on and self.app.powered("AIS"):
            aa.add("TX MALFUNCTION")
        if not (self.gps_fix() and self.gps_hold.on) and self.app.powered("AIS"):
            aa.add("NO SENSOR POSITION")
        new = aa - self.alarms_ais
        self.ack_ais -= new
        self.ack_ais &= aa
        if self.ais_ack.pop():
            if aa - self.ack_ais:
                self.flags["ais_ack"] = t
            self.ack_ais |= aa
            self.alarms_ais.discard("NEW SRM")
            aa.discard("NEW SRM")
        self.alarms_ais = aa
        self.alert = bool((self.alarms_gps - self.ack_gps) or (self.alarms_ais - self.ack_ais) or
                          (getattr(self, "gyro_alarm", False) and not self.gy_acked))

    def targets(self):
        """AIS targets heard, sorted by range."""
        w = self.world
        if not self.app.powered("AIS"):
            return []
        out = []
        for m, r in w.ais.items():
            dx, dy = r["x"] - w.x, r["y"] - w.y
            rng = math.hypot(dx, dy)
            brg = math.degrees(math.atan2(dx, dy)) % 360
            cpa = tcpa = None
            if r["c"] is not None:
                cpa, tcpa, _, _ = w.cpa(r["c"])
            out.append(dict(r, rng=rng, brg=brg, cpa=cpa, tcpa=tcpa, age=w.t - r["t"]))
        out.sort(key=lambda d: d["rng"])
        return out

    def bg_audio(self, syn, n):
        unack = (self.alarms_ais - self.ack_ais) - {"NEW SRM", "NO SENSOR POSITION"}
        out = None
        if unack:
            out = syn.beep("aisal", n, 2600.0, 2.0) * 0.18
        if (self.alarms_gps - self.ack_gps) & {"NO FIX", "DGPS LOST"}:
            out = (0 if out is None else out) + syn.beep("gpsal", n, 3100.0, 1.0) * 0.12
        if getattr(self, "gyro_alarm", False) and not self.gy_acked:
            out = (0 if out is None else out) + syn.buzzer("gyal", n, 520.0, 1.0) * 0.25
        return out

    # ----------------------------------------------------------------- draw
    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if pygame.Rect(384, 80, 176, 176).collidepoint(pos):
            return "GPS SKY VIEW: satellites by azimuth and elevation, coloured by signal strength. Four good ones give a 3D fix."
        if pygame.Rect(36, 400, 190, 190).collidepoint(pos):
            return "GYRO REPEATER: the card turns under the lubber line; the window shows the gyro heading sent to the radar."
        if pygame.Rect(806, 80, 540, 300).collidepoint(pos):
            return "AIS MINIMUM KEYBOARD DISPLAY. Targets are AIS reports - remember small craft may carry no AIS, and AIS lags the radar by its reporting interval."
        return ""

    def draw(self, s):
        w, t = self.world, self.world.t
        ui.panel(s, (20, 54, 760, 300), "GPS NAVIGATOR  -  L1 C/A 12 CH  -  DGPS / SBAS")
        ui.panel(s, (20, 362, 380, 300), "GYRO COMPASS")
        ui.panel(s, (410, 362, 370, 300), "SPEED LOG (DOPPLER)")
        ui.panel(s, (20, 670, 760, 190), "POSITION FOR DSC / INMARSAT-C  -  MANUAL ENTRY")
        ui.panel(s, (790, 54, 800, 470), "AIS CLASS A TRANSPONDER  -  MINIMUM KEYBOARD DISPLAY")
        ui.panel(s, (790, 532, 800, 328), "INSTRUCTOR: SENSOR FAULTS  +  AIS SAR DEVICES")
        self._draw_gps(s)
        self._draw_gyro(s)
        self._draw_log(s)
        self._draw_pos(s)
        self._draw_ais(s)
        self._draw_instr(s)
        super().draw(s)

    def _draw_gps(self, s):
        w, t = self.world, self.world.t
        l = ui.lcd(s, (36, 80, 336, 160), (14, 20, 12), (60, 80, 40))
        k = self.gps_dim.val
        fg = tuple(int(c * k) for c in (190, 230, 120))
        dim = tuple(int(c * k) for c in (90, 120, 70))
        if not self.gps_on:
            text(s, "NO POWER" if self.gps_pwr.on else "OFF", (l.centerx, l.centery), 18, dim, bold=True, align="m")
        else:
            warm = t - self.gps_t0
            pg = self.page_gps
            text(s, "%s  %s  %d SAT  HDOP %.1f" % (self.gps_mode.value, self.fix, self.nsat, self.hdop), (l.x + 8, l.y + 6), 12, fg, bold=True)
            if pg == "POS":
                p = self.gps_position()
                if p:
                    text(s, fmt_lat(p[0]), (l.x + 8, l.y + 28), 24, fg, bold=True)
                    text(s, fmt_lon(p[1]), (l.x + 8, l.y + 58), 24, fg, bold=True)
                else:
                    text(s, "ACQUIRING %d s" % int(warm) if warm < 40 else "NO POSITION FIX", (l.x + 8, l.y + 40), 18, dim, bold=True)
                sog = w.spd if p else 0
                text(s, "SOG %4.1f kn  COG %05.1f°" % (sog, w.hdg if p else 0), (l.x + 8, l.y + 94), 13, fg)
                text(s, "UTC %s   DATUM %s" % (w.utc_str(), self.gps_datum.value), (l.x + 8, l.y + 114), 12, fg)
                al = sorted(self.alarms_gps)
                if al:
                    un = set(al) - self.ack_gps
                    text(s, "ALARM: " + ", ".join(al), (l.x + 8, l.y + 136), 11,
                         C["red"] if un and int(t * 3) % 2 else fg, bold=True)
            elif pg == "SKY":
                for i, s_ in enumerate(self.sats):
                    text(s, "%02d %03d %02d %2d" % (s_["prn"], s_["az"], s_["el"], s_["snr"]),
                         (l.x + 8 + (i // 6) * 162, l.y + 28 + (i % 6) * 20), 12, fg if s_["snr"] > 28 else dim)
            else:
                m = self.mob
                if not m:
                    text(s, "NO MOB MARK", (l.x + 8, l.y + 40), 18, dim, bold=True)
                else:
                    dx, dy = m["x"] - w.x, m["y"] - w.y
                    rng, brg = math.hypot(dx, dy), math.degrees(math.atan2(dx, dy)) % 360
                    text(s, "MOB %s UTC" % m["utc"], (l.x + 8, l.y + 28), 14, C["red"], bold=True)
                    text(s, "BRG %05.1f°  RNG %.2f NM" % (brg, rng), (l.x + 8, l.y + 52), 18, fg, bold=True)
                    text(s, fmt_lat(m["lat"]) + " " + fmt_lon(m["lon"]), (l.x + 8, l.y + 82), 12, fg)
                    text(s, "ELAPSED %d s - turn back (Williamson turn)" % (t - m["t"]), (l.x + 8, l.y + 104), 11, fg)
        # sky plot
        cx, cy, R = 472, 168, 86
        pygame.draw.circle(s, (4, 10, 6), (cx, cy), R)
        for rr in (R, R * 2 // 3, R // 3):
            pygame.draw.circle(s, (30, 60, 40), (cx, cy), rr, 1)
        for d, lab in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
            a = math.radians(d)
            text(s, lab, (cx + math.sin(a) * (R + 9), cy - math.cos(a) * (R + 9)), 9, C["dim"], bold=True, align="m")
        if self.gps_on:
            for s_ in self.sats:
                a = math.radians(s_["az"])
                k = R * (90 - s_["el"]) / 90.0
                p = (cx + math.sin(a) * k, cy - math.cos(a) * k)
                col = C["green"] if s_["snr"] > 36 else (C["amber"] if s_["snr"] > 28 else (90, 90, 90))
                pygame.draw.circle(s, col, p, 5, 0 if s_["snr"] > 28 else 1)
                text(s, "%d" % s_["prn"], (p[0] + 6, p[1] - 6), 8, col, bold=True)
        mult, add = fx.round_glass(R)
        s.blit(mult, (cx - R, cy - R), special_flags=pygame.BLEND_RGB_MULT)
        s.blit(add, (cx - R, cy - R), special_flags=pygame.BLEND_RGB_ADD)
        pygame.draw.circle(s, (14, 15, 17), (cx, cy), R + 3, 4)
        # SNR bars
        r = ui.crt(s, (580, 80, 186, 160))
        for i, s_ in enumerate(self.sats):
            x = r.x + 6 + i * 16
            hh = (r.h - 30) * min(1.0, s_["snr"] / 50.0) if self.gps_on else 0
            col = C["green"] if s_["snr"] > 36 else (C["amber"] if s_["snr"] > 28 else (80, 80, 80))
            pygame.draw.rect(s, col, (x, r.bottom - 18 - hh, 11, hh))
            text(s, "%d" % (s_["prn"] % 100), (x + 5, r.bottom - 14), 8, C["dim"], align="c")
        yt = r.bottom - 18 - (r.h - 30) * 28 / 50.0
        pygame.draw.line(s, (150, 60, 60), (r.x, yt), (r.right, yt), 1)
        text(s, "SNR dB-Hz  (28 = track)", (r.x + 4, r.y + 3), 8, C["dim"], bold=True)
        ui.led(s, (60, 252), "green", self.gps_fix(), "FIX", 5, 9)
        ui.led(s, (120, 252), "amber", self.gps_on and self.gps_mode.value != "GPS" and self.jam < 0.3, "DIFF", 5, 9)
        ui.led(s, (190, 252), "red", bool(self.alarms_gps - self.ack_gps) and int(t * 3) % 2 == 0, "ALARM", 5, 9)

    def _draw_gyro(self, s):
        w, t = self.world, self.world.t
        cx, cy, R = 128, 498, 90
        pygame.draw.circle(s, (8, 8, 9), (cx, cy), R + 6)
        pygame.draw.circle(s, (22, 22, 24), (cx, cy), R)
        on = self.gyro_state != "OFF"
        hdg = self.gyro_out if on else 0.0
        for d in range(0, 360, 5):
            a = math.radians(d - hdg)
            ln = 12 if d % 30 == 0 else (8 if d % 10 == 0 else 4)
            col = (230, 226, 210) if on else (100, 100, 96)
            pygame.draw.line(s, col, (cx + math.sin(a) * (R - 2), cy - math.cos(a) * (R - 2)),
                             (cx + math.sin(a) * (R - 2 - ln), cy - math.cos(a) * (R - 2 - ln)), 2 if d % 30 == 0 else 1)
            if d % 30 == 0:
                lab = {0: "N", 90: "E", 180: "S", 270: "W"}.get(d, "%d" % (d // 10))
                text(s, lab, (cx + math.sin(a) * (R - 24), cy - math.cos(a) * (R - 24)), 11 if d % 90 == 0 else 9,
                     C["red"] if d == 0 else col, bold=True, align="m")
        pygame.draw.polygon(s, C["amber"], [(cx, cy - R + 1), (cx - 6, cy - R - 8), (cx + 6, cy - R - 8)])
        pygame.draw.line(s, C["amber"], (cx, cy - R + 1), (cx, cy - R + 16), 2)
        pygame.draw.circle(s, (40, 42, 46), (cx, cy), 26)
        mult, add = fx.round_glass(R)
        s.blit(mult, (cx - R, cy - R), special_flags=pygame.BLEND_RGB_MULT)
        s.blit(add, (cx - R, cy - R), special_flags=pygame.BLEND_RGB_ADD)
        pygame.draw.circle(s, (14, 15, 17), (cx, cy), R + 4, 5)
        l = ui.lcd(s, (90, 482, 76, 30), (20, 6, 4), (70, 20, 8))
        text(s, ("%05.1f" % hdg) if on else "---.-", (l.centerx, l.centery), 16, (255, 90, 50), bold=True, align="m")
        st = self.gyro_state if not self.f_gyro.on else "FAIL"
        ui.led(s, (318, 394), "green", self.gyro_state == "RUN" and not self.f_gyro.on, "RUN", 5, 9)
        ui.led(s, (318, 414), "amber", self.gyro_state == "SETTLING" and int(t * 2) % 2 == 0, "SETTLE", 5, 9)
        ui.led(s, (318, 434), "red", (self.f_gyro.on or (self.gy_pwr.on and not self.app.powered("GYRO"))) or self.gy_test.down,
               "ALARM", 5, 9)
        ui.led(s, (318, 454), "red", not self.app.powered("GYRO") or self.gy_test.down, "PWR FAIL", 5, 9)
        err = self.gyro_error() if self.gyro_ok else 0.0
        text(s, "STATE %s" % st, (236, 638), 10, C["text"], bold=True)
        text(s, "ERROR %+.1f° %s" % (err, "(compass check)" if abs(err) > 0.3 else ""), (36, 638), 10,
             C["amber"] if abs(err) > 0.3 else C["dim"], bold=True)

    def _draw_log(self, s):
        w = self.world
        l = ui.lcd(s, (426, 388, 338, 128), (6, 12, 20), (20, 40, 70))
        ls = self.log_speed()
        fg = (130, 200, 255)
        if ls is None:
            text(s, "LOG FAIL" if self.f_log.on else "NO POWER", (l.centerx, l.y + 40), 22, C["red"], bold=True, align="m")
        else:
            text(s, "%s  %4.1f" % ("STW" if self.log_mode.idx == 0 else "SOG", ls), (l.x + 10, l.y + 6), 34, fg, bold=True)
            text(s, "kn", (l.x + 270, l.y + 26), 14, fg, bold=True)
            text(s, "TRIP %7.2f NM" % self.trip, (l.x + 10, l.y + 56), 15, fg)
            text(s, "%s TRACK   CAL %+.1f %%" % (self.log_mode.value, self.log_cal.val), (l.x + 10, l.y + 80), 12, fg)
            text(s, "to ARPA: %s" % ("OK" if abs(self.log_cal.val) < 0.6 else "SPEED %+.1f kn IN ERROR" % (ls - w.spd)),
                 (l.x + 10, l.y + 100), 12, C["green"] if abs(self.log_cal.val) < 0.6 else C["amber"], bold=True)
        ui.led(s, (632, 534), "green", ls is not None, "LOG OK", 5, 9)
        ui.text_block(s, "Water track for collision avoidance: ARPA true vectors are only as good as the log and gyro.",
                      (426, 626, 340, 36), 10, C["dim"], mono=False, lh=13)

    def _draw_pos(self, s):
        w, t = self.world, self.world.t
        text(s, "LATITUDE", (52, 706), 9, C["dim"], bold=True)
        text(s, "LONGITUDE", (236, 706), 9, C["dim"], bold=True)
        text(s, "AT UTC", (440, 706), 9, C["dim"], bold=True)
        for wh in (self.th_lat, self.th_lon):
            for a, b in zip(wh, wh[1:]):
                if b is None and a is not None:
                    pygame.draw.circle(s, (230, 230, 220), (a.rect.right + 4, a.rect.bottom - 4), 2)
        text(s, "°", (95, 721), 11, C["text"], bold=True)
        text(s, "°", (301, 721), 11, C["text"], bold=True)
        l = ui.lcd(s, (52, 776, 714, 72))
        p = self.dsc_position()
        fg = C["lcdfg"]
        if p:
            la, lo, src, age = p
            col = fg if (src == "GPS" or age < 4 * 3600) else C["amber"]
            text(s, "DSC POSITION  %s %s  SOURCE %s" % (fmt_lat(la), fmt_lon(lo), src), (l.x + 10, l.y + 8), 13, col, bold=True)
            text(s, ("AGE %d h %02d min" % (age // 3600, age // 60 % 60)) if src == "MANUAL" else "AUTOMATIC FROM GPS",
                 (l.x + 10, l.y + 30), 12, col)
        else:
            text(s, "DSC POSITION  UNKNOWN - alerts will carry 9999999999 / time 8888", (l.x + 10, l.y + 8), 13,
                 C["red"] if int(t * 2) % 2 else fg, bold=True)
            text(s, "No GPS fix and no manual position: set the wheels and press ENTER.", (l.x + 10, l.y + 30), 12, fg)
        text(s, "GPS %s  |  output %s" % (self.fix if self.gps_on else "OFF", "ON" if self.gps_hold.on else "OFF"),
             (l.x + 10, l.y + 50), 11, C["dim"])

    def _draw_ais(self, s):
        w, t = self.world, self.world.t
        l = ui.lcd(s, (806, 80, 540, 300), (10, 14, 22), (30, 44, 70))
        fg, dim, hi = (160, 210, 255), (80, 110, 150), (255, 230, 120)
        on = self.app.powered("AIS")
        if not on:
            text(s, "NO POWER", l.center, 20, dim, bold=True, align="m")
            return
        tx = "TX OFF (SILENT)" if self.ais_silent.on else ("TX FAULT" if self.f_ais.on else "TX %s" % self.ais_pwr.value)
        text(s, "AIS  %s   CH A 87B / CH B 88B   %s" % (self.page, tx), (l.x + 8, l.y + 6), 12,
             C["amber"] if not self.ais_tx else fg, bold=True)
        pygame.draw.line(s, (40, 60, 90), (l.x + 6, l.y + 24), (l.right - 6, l.y + 24), 1)
        tg = self.targets()
        y = l.y + 32
        if self.page == "TARGETS":
            text(s, "   NAME                MMSI       RNG    BRG   CPA   TCPA", (l.x + 8, y), 11, dim, bold=True)
            for i, d in enumerate(tg[:12]):
                cur = i == self.cur_i
                col = C["red"] if d["cls"] in ("SART", "MOB", "EPIRB") else (hi if cur else fg)
                cpa = ("%5.2f" % d["cpa"]) if d["cpa"] is not None else "  -  "
                tc = ("%5.1f" % d["tcpa"]) if d["tcpa"] is not None and d["tcpa"] > 0 else "  -  "
                text(s, "%s %-18s %09d %5.2f  %03d  %s %s" % (">" if cur else " ", d["name"][:18], d["mmsi"], d["rng"],
                                                            d["brg"], cpa, tc), (l.x + 8, y + 18 + i * 18), 11, col, bold=cur)
            if not tg:
                text(s, "NO TARGETS", (l.x + 8, y + 20), 12, dim)
            text(s, "%d targets  (KITTIWAKE-type small craft without AIS do not appear)" % len(tg), (l.x + 8, l.bottom - 20), 10, dim)
        elif self.page == "DETAIL":
            d = next((x for x in tg if x["mmsi"] == self.sel_mmsi), None)
            if not d:
                text(s, "NO TARGET SELECTED - use TARGETS, cursor, ENT", (l.x + 8, y + 4), 12, dim)
            else:
                rows = [("NAME", d["name"]), ("MMSI", "%09d  (%s)" % (d["mmsi"], self._mmsi_kind(d["mmsi"]))),
                        ("CALL SIGN", d["cs"] or "-"), ("CLASS", d["cls"]),
                        ("COG / SOG", "%05.1f° / %.1f kn" % (d["cog"], d["sog"])),
                        ("POSITION", "%s %s" % (fmt_lat(w.latlon_of(d["x"], d["y"])[0]), fmt_lon(w.latlon_of(d["x"], d["y"])[1]))),
                        ("RNG / BRG", "%.2f NM / %05.1f°" % (d["rng"], d["brg"])),
                        ("CPA / TCPA", ("%.2f NM / %.1f min" % (d["cpa"], d["tcpa"])) if d["cpa"] is not None else "-"),
                        ("LAST REPORT", "%d s ago" % d["age"]), ("LENGTH", "%d m" % d["length"] if d["length"] else "-")]
                for i, (k, v) in enumerate(rows):
                    text(s, k, (l.x + 10, y + i * 24), 13, dim, bold=True)
                    text(s, v, (l.x + 170, y + i * 24), 13, fg, bold=True)
        elif self.page == "OWN":
            rows = [("NAME", w.name), ("MMSI", "%09d" % w.mmsi), ("CALL SIGN", w.cs), ("IMO", "9123457"),
                    ("TYPE", "CARGO, ALL SHIPS OF THIS TYPE"), ("DIMENSIONS", "A 110 B 22 C 8 D 12  (GPS ANT)"),
                    ("POSITION", ("%s %s" % (fmt_lat(self.gps_position()[0]), fmt_lon(self.gps_position()[1])))
                     if self.gps_position() else "NOT AVAILABLE (91° / 181°)"),
                    ("REPORTS SENT", "%d" % self.ais_tx_count)]
            for i, (k, v) in enumerate(rows):
                text(s, k, (l.x + 10, y + i * 28), 13, dim, bold=True)
                text(s, v, (l.x + 170, y + i * 28), 13, fg, bold=True)
        elif self.page == "VOYAGE":
            rows = [("NAV STATUS", NAVSTAT[self.ais_nav.idx]), ("DRAUGHT", "%.1f m" % self.ais_draught.val),
                    ("DESTINATION", DESTS[self.dest_i]), ("ETA", "%02d:%02d UTC" % ((int(w.utc_h) + 5) % 24, 30)),
                    ("PERSONS ON BOARD", "%d" % self.ais_pob.val), ("CARGO", "GENERAL CARGO, NON HAZARDOUS")]
            for i, (k, v) in enumerate(rows):
                text(s, k, (l.x + 10, y + i * 30), 13, dim, bold=True)
                text(s, v, (l.x + 200, y + i * 30), 13, hi if i == 0 and self.ais_nav.idx not in (0, 8) else fg, bold=True)
            text(s, "Set with NAV STATUS, DRAUGHT, POB and DEST at the right.", (l.x + 10, l.bottom - 20), 10, dim)
        elif self.page == "SRM":
            items = [("RX", a, b, c) for a, b, c in self.srm_in] + [("TX", a, b, c) for a, b, c in self.srm_out]
            items.sort(key=lambda r: r[1])
            yy = y
            for io, tm, frm, msg in items[-7:]:
                text(s, "%s %s  %s" % (io, tm, frm), (l.x + 8, yy), 11, hi if io == "RX" else C["cyan"], bold=True)
                yy = ui.text_block(s, msg, (l.x + 30, yy + 14, l.w - 40, 40), 11, fg, lh=14) + 4
            if not items:
                text(s, "NO SAFETY RELATED MESSAGES", (l.x + 8, y + 4), 12, dim)
        else:
            al = sorted(self.alarms_ais)
            for i, a in enumerate(al):
                un = a not in self.ack_ais
                text(s, ("!! " if un else "   ") + a, (l.x + 10, y + i * 24), 14,
                     C["red"] if un and int(t * 3) % 2 else hi, bold=True)
            if not al:
                text(s, "NO ACTIVE ALARMS", (l.x + 10, y + 4), 13, dim)
        ui.led(s, (812, 486), "green", self.ais_tx and int(t * 2) % 5 == 0, "TX", 5, 9)
        ui.led(s, (862, 486), "green", bool(tg), "RX", 5, 9)
        ui.led(s, (912, 486), "red", bool(self.alarms_ais - self.ack_ais) and int(t * 3) % 2 == 0, "ALARM", 5, 9)
        text(s, "SEND:", (806, 444), 10, C["dim"], bold=True)
        text(s, "%d targets" % len(tg), (1574, 486), 10, C["dim"], bold=True, align="r")

    @staticmethod
    def _mmsi_kind(m):
        s = "%09d" % m
        if s.startswith("970"):
            return "AIS-SART"
        if s.startswith("972"):
            return "MOB DEVICE"
        if s.startswith("974"):
            return "EPIRB-AIS"
        if s.startswith("111"):
            return "SAR AIRCRAFT"
        if s.startswith("00"):
            return "COAST STATION"
        if s.startswith("99"):
            return "AID TO NAVIGATION"
        return "SHIP"

    def _draw_instr(self, s):
        l = ui.lcd(s, (1392, 560, 182, 140))
        rows = ["MMSI FORMATS", "2-7xx..  ship", "00xx..   coast stn", "111xx..  SAR aircraft",
                "970xx..  AIS-SART", "972xx..  MOB device", "974xx..  EPIRB-AIS"]
        for i, r in enumerate(rows):
            text(s, r, (l.x + 8, l.y + 6 + i * 18), 11, C["amber"] if i == 0 else C["lcdfg"], bold=i == 0)
        d = self.world.ais_device
        ui.text_block(s, ("DEVICE: %s at %.1f NM" % (d["label"], math.hypot(d["x"] - self.world.x, d["y"] - self.world.y)))
                      if d else "No SAR device active. Faults are only visible to you through their symptoms - "
                                "watch the radar, DSC display and alarms.", (812, 712, 760, 60), 11, C["dim"], mono=False, lh=15)
        ui.text_block(s, "Dependencies: GPS -> DSC position, Inmarsat-C, AIS position.  GYRO -> radar north-up, ARPA, "
                         "Inmarsat dish stabilisation.  LOG -> ARPA true vectors.", (812, 780, 760, 60), 11, C["dim"], mono=False, lh=15)
