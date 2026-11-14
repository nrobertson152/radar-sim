"""SATCOM 2: Iridium GMDSS terminal, Ship Security Alert System, LRIT and
Fleet Broadband data.

Iridium is a low-earth-orbit constellation (66 satellites, six near-polar
planes, 780 km) and has been a recognised GMDSS provider since 2020. Unlike
Inmarsat it covers the poles, and the satellite serving you changes every
few minutes (a 'handoff') - listen for it.

SSAS sends a COVERT alert to the company security officer and the flag
state through the Inmarsat-C transceiver: nothing on board must show or
sound. LRIT reports the ship's position to its flag state's data centre,
normally every 6 hours. Fleet Broadband data only flows while the Inmarsat
dish on the INMARSAT tab is locked on the satellite.
"""
import math
import numpy as np
import pygame
from . import ui, fx
from .ui import C, text, Knob, Selector, Button, Guard, Toggle, Station
from .world import RE, gc_dist, gc_bearing, fmt_lat, fmt_lon, wrap180
from .worldmap import WorldMap
from .radiocore import Monitor, Voice
from .vhf import NATURES

IR_ALT, IR_PER, IR_INC = 780.0, 6024.0, 86.4
IRIDIUM = []
for _p in range(6):
    for _k in range(11):
        IRIDIUM.append(("IR%d%02d" % (_p + 1, _k + 1), IR_INC, _p * 31.6, _k * 32.73 + (_p % 2) * 16.36, IR_PER))
INTERVALS = ["15 MIN", "30 MIN", "1 H", "3 H", "6 H"]
INT_S = [900, 1800, 3600, 10800, 21600]
FILES = {"GRIB": ("GRIB WEATHER", 1.8), "MAIL": ("E-MAIL SYNC", 0.45), "CHART": ("ENC CHART UPDATE", 12.0)}


class Sat2(Station):
    name = "SATCOM 2"
    tab = "SATCOM 2"
    hint = ("Iridium GMDSS (works at the poles), the covert Ship Security Alert System, LRIT position reporting and "
            "Fleet Broadband data (needs the Inmarsat dish locked on the INMARSAT tab).")
    power_key = "SAT2"
    pan, bg_pan = 0.0, 0.6

    def __init__(self, app):
        super().__init__(app)
        self.map = WorldMap((30, 80, 880, 440))
        self.mon = Monitor(60)
        self.voice = Voice("phone")
        self.flags, self.pending = {}, []
        self.serving, self.sv_el, self.bars, self._sats = None, 0.0, 0, []
        self.reg, self.reg_t = "OFF", 0.0
        self.handoffs = 0
        self.dial, self.call = "", None
        self.distress = None
        self.sbd_n = 20
        self.next_msi = 120.0
        self.ssas = None                       # active real alert
        self.ssas_log = []
        self.lrit_last, self.lrit_next = None, None
        self.lrit_log = []
        self.fbb_mb, self.fbb_cost, self.fbb_t = 0.0, 0.0, 0.0
        self.xfer = None
        self._lrit_off_t = None
        # Iridium terminal
        ti = "IRIDIUM GMDSS TERMINAL: "
        self.pwr = self.add(Toggle(576, 600, "POWER", True, ti + "power. After switch-on it searches for a satellite and registers."))
        self.guard = self.add(Guard((420, 562, 112, 96), "DISTRESS", ti + "lift the cover and hold 3 s. Sends an alert with "
            "position and nature to the Iridium-designated rescue co-ordination centre, which calls you back by voice."))
        self.nature = self.add(Selector(476, 772, 22, "NATURE", NATURES, 0, ti + "nature of distress sent with the alert."))
        self.b_can = self.add(Button((420, 664, 112, 30), "CANCEL DIST", ti + "cancel a distress alert sent in error "
            "(and tell the RCC by voice).", size=10))
        self.keys = ui.keypad(self, 620, 560, [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"], ["*", "0", "#"]], 44, 28, 4,
                              snd="dtmf", tip=ti + "handset keypad. Dial a number and press CALL.")
        self.b_call = self.add(Button((620, 690, 68, 30), "CALL", ti + "place a voice call.", color="green", size=10))
        self.b_end = self.add(Button((694, 690, 68, 30), "END", ti + "end the call / clear the digits.", color="red", size=10))
        self.b_safety = self.add(Button((780, 602, 122, 32), "SAFETY CALL", ti + "priority maritime safety voice call "
            "to the rescue co-ordination centre (e.g. to report a hazard or ask for medical help).", size=10, color="amber"))
        self.b_pos = self.add(Button((780, 640, 122, 30), "SBD POS RPT", ti + "send a short burst data position report "
            "to the company.", size=10))
        self.b_well = self.add(Button((780, 676, 122, 30), "SBD ALL WELL", ti + "send the 'all well' SBD message.", size=10))
        self.vol = self.add(Knob(842, 760, 18, "VOLUME", 0, 1, 0.75, ti + "handset volume."))
        # SSAS
        ts = "SHIP SECURITY ALERT SYSTEM: "
        self.ssas1 = self.add(Guard((950, 84, 104, 92), "SSAS 1", ts + "covert alert button (bridge). Lift the cover and "
            "hold 2 s. NOTHING on board sounds or lights - the alert goes silently via Inmarsat-C to the company "
            "security officer and the flag state.", hold_s=2.0))
        self.ssas2 = self.add(Guard((1064, 84, 104, 92), "SSAS 2", ts + "second covert alert button (another location).", hold_s=2.0))
        self.ssas_mode = self.add(Selector(1220, 150, 22, "SSAS MODE", ["OPERATE", "TEST"], 1, ts + "TEST: the alert "
            "is marked as a test and only the CSO answers. OPERATE: a real alert - authorities are informed. "
            "Always agree a test with the CSO first."))
        self.ssas_rst = self.add(Button((950, 190, 218, 32), "SSAS RESET / CANCEL", ts + "stop the alert repeating. A "
            "real alert must also be cancelled with the CSO by telephone with the code word.", size=10))
        # LRIT
        tl = "LRIT: "
        self.lrit_on = self.add(Toggle(966, 420, "LRIT\nENABLE", True, tl + "Long Range Identification and Tracking. "
            "Must stay on at sea - only the flag administration may switch it off."))
        self.lrit_int = self.add(Selector(1060, 424, 22, "INTERVAL", INTERVALS, 4, tl + "report interval. Normally 6 h; "
            "the data centre can command a shorter one."))
        self.lrit_test = self.add(Button((1110, 404, 110, 32), "TEST RPT", tl + "send a test report to the data centre.", size=10))
        self.lrit_poll = self.add(Button((1110, 442, 110, 32), "INSTR POLL", "INSTRUCTOR: the LRIT data centre polls "
            "the ship for an immediate position report.", size=9))
        # Fleet Broadband data
        tf = "FLEET BROADBAND (IP DATA): "
        self.fbb_con = self.add(Toggle(966, 650, "DATA\nCONNECT", False, tf + "open a background IP data session. Needs "
            "the Fleet dish locked on the satellite (INMARSAT tab) and its breaker on."))
        self.fbb_stream = self.add(Selector(1060, 654, 22, "STREAMING", ["OFF", "32k", "64k", "128k", "256k"], 0,
            tf + "guaranteed-rate streaming class for video or a doctor's video call. Charged per minute."))
        self.b_grib = self.add(Button((1110, 618, 110, 30), "GET GRIB", tf + "download a weather GRIB file (1.8 MB).", size=10))
        self.b_mail = self.add(Button((1110, 652, 110, 30), "MAIL SYNC", tf + "synchronise e-mail (0.45 MB).", size=10))
        self.b_chart = self.add(Button((1110, 686, 110, 30), "ENC UPDATE", tf + "download the weekly chart update (12 MB).", size=10))

    # -------------------------------------------------------------- helpers
    def after(self, delay, fn):
        self.pending.append((self.world.t + delay, fn))

    def geom(self, sat, t):
        w = self.world
        la, lo = w.leo_pos(sat, t)
        g = gc_dist(w.lat, w.lon, la, lo) / RE
        rs = RE + IR_ALT
        el = math.degrees(math.atan2(math.cos(g) - RE / rs, math.sin(g) + 1e-9))
        return el, gc_bearing(w.lat, w.lon, la, lo), la, lo

    @property
    def on(self):
        return self.pwr.on and self.powered

    @property
    def registered(self):
        return self.reg == "REGISTERED"

    def fbb_link(self):
        """Fleet Broadband link quality 0..1 (needs the Inmarsat dish)."""
        sc = getattr(self.app, "satcom", None)
        if sc is None or not self.app.powered("FLEET"):
            return 0.0
        return max(0.0, min(1.0, (sc.cn0 - 44.0) / 10.0))

    def satc_ready(self):
        sc = getattr(self.app, "satcom", None)
        return bool(sc is not None and sc.logged and self.app.powered("SATC"))

    def _note(self, hdr, msg, col=None):
        self.mon.note("%s  %s" % (self.world.utc_str(), hdr), msg, col)

    def _pos_text(self):
        p = self.app.dsc_position()
        return ("%s %s" % (fmt_lat(p[0]), fmt_lon(p[1]))) if p else "POSITION UNKNOWN"

    # --------------------------------------------------------------- update
    def update(self, dt):
        w, t = self.world, self.world.t
        for item in list(self.pending):
            if t >= item[0]:
                self.pending.remove(item)
                item[1]()
        # constellation and serving satellite (4 Hz)
        if t - getattr(self, "_gt", -9) > 0.25:
            self._gt = t
            vis = []
            for sat in IRIDIUM:
                el, az, la, lo = self.geom(sat, t)
                if el > 8.2:
                    vis.append((el, az, sat[0]))
            self._sats = vis
            vis.sort(reverse=True)
            cur = next((v for v in vis if v[2] == self.serving), None)
            if vis and (cur is None or cur[0] < 10.0 or vis[0][0] - cur[0] > 18.0):
                if self.serving is not None and vis[0][2] != self.serving and self.on:
                    self.handoffs += 1
                    if self.app.station is self:
                        ui.sfx("handoff", 0.5, pan=-0.3)
                self.serving = vis[0][2]
                cur = vis[0]
            if not vis:
                self.serving, cur = None, None
            if cur:
                self.sv_el = cur[0]
                rel = (cur[1] - w.hdg) % 360
                blocked = abs(wrap180(rel - 180)) < 15 and cur[0] < 20
                q = (cur[0] - 6) / 10.0 + 1 - (2.5 if blocked else 0.0)
                self.bars = max(0, min(5, int(q)))
            else:
                self.sv_el, self.bars = 0.0, 0
        # registration
        if not self.on:
            self.reg = "OFF"
            if self.call:
                self.call = None
                self.voice.text = None
        elif self.reg == "OFF":
            self.reg, self.reg_t = "SEARCHING", t
        elif self.reg == "SEARCHING" and t - self.reg_t > 8 and self.bars > 0:
            self.reg = "REGISTERED"
            ui.sfx("lock", 0.5, pan=self.bg_pan)
            self._note("IRIDIUM", "REGISTERED ON THE IRIDIUM NETWORK. GMDSS SERVICES AVAILABLE.", C["green"])
        elif self.reg == "REGISTERED" and self.bars == 0:
            self.reg, self.reg_t = "SEARCHING", t
            if self.call:
                self.call = None
                self.voice.text = None
                self._note("IRIDIUM", "CALL DROPPED - NO SATELLITE (BLOCKAGE OR HANDOFF FAILURE).", C["red"])
        # terminal
        if self.guard.pop_fired():
            self._distress()
        if self.b_can.pop() and self.distress and not self.distress.get("cancelled"):
            self.distress["cancelled"] = True
            self.flags["ir_cancel"] = t
            self._note("IRIDIUM DISTRESS", "CANCELLATION SENT. CONFIRM BY VOICE WITH THE RCC.", C["amber"])
            ui.sfx("sbd", 0.6)
        for k, b in self.keys.items():
            if b.pop() and len(self.dial) < 16 and not self.call:
                self.dial += k
        if self.b_end.pop():
            self.dial, self.call = "", None
            self.voice.text = None
        if self.b_call.pop() and self.dial and not self.call:
            self._place(self.dial, "PENHALE SHIPPING OPERATIONS, GOOD DAY. WE HEAR YOU CLEARLY THROUGH IRIDIUM. GO AHEAD.")
        if self.b_safety.pop() and not self.call:
            self.dial = "SAFETY"
            self._place("SAFETY", "MRCC PENHALE, SAFETY LINE. THIS IS A RECORDED LINE. STATE YOUR SHIP'S NAME, POSITION "
                                  "AND THE SAFETY MATTER YOU WISH TO REPORT.", priority=True)
        for b, label, txt in ((self.b_pos, "POSITION REPORT", None), (self.b_well, "ALL WELL", None)):
            if b.pop():
                if self.registered:
                    self.sbd_n += 1
                    ui.sfx("sbd", 0.7)
                    self.flags["sbd"] = t
                    self._note("SBD SENT", "MOMSN %d  %s  %s" % (self.sbd_n, label, self._pos_text()), C["cyan"])
                else:
                    ui.sfx("error", 0.6)
                    self._note("SBD", "NOT SENT - NOT REGISTERED ON THE NETWORK.", C["red"])
        if self.registered and t > self.next_msi:
            self.next_msi = t + 150
            self._note("IRIDIUM SAFETYCAST (MSI)", "NAVAREA I WARNING 244/26. DERELICT BARGE ADRIFT 49-05N 006-50W. "
                       "VESSELS KEEP CLEAR.", C["lcdfg"])
            ui.sfx("printer", 0.4, pan=self.bg_pan)
        # SSAS
        for g, nm in ((self.ssas1, "1 (BRIDGE)"), (self.ssas2, "2 (CABIN)")):
            if g.pop_fired():
                self._ssas(nm)
        if self.ssas and self.ssas.get("real") and t >= self.ssas["next"]:
            self.ssas["next"] = t + 60.0
            if self.satc_ready():
                self.ssas["sent"] += 1
                self.ssas_log.append((w.utc_str()[:5], "ALERT REPEAT %d SENT (SILENT)" % self.ssas["sent"]))
        if self.ssas_rst.pop() and self.ssas:
            real = self.ssas.get("real")
            self.ssas_log.append((w.utc_str()[:5], "RESET - %s" % ("CANCEL SENT TO CSO" if real else "TEST CLOSED")))
            if real:
                self.flags["ssas_cancel"] = t
                self.mistake("a REAL SSAS alert was sent and cancelled - phone the CSO with the code word at once.")
                self._satc_print("FROM CSO", "SSAS CANCELLATION RECEIVED. CALL THE CSO ON THE AGREED NUMBER AND GIVE THE CODE WORD.")
            self.ssas = None
        # LRIT
        iv = INT_S[self.lrit_int.idx]
        if self.lrit_on.pop():
            if not self.lrit_on.on:
                self._lrit_off_t = t
                self.mistake("LRIT switched off at sea - only the flag administration may authorise that.")
            else:
                self._lrit_off_t = None
        if self.lrit_next is None:
            self.lrit_next = t + 30.0
        if self.lrit_on.on and t >= self.lrit_next:
            self._lrit_report("SCHEDULED")
            self.lrit_next = t + iv
        if getattr(self, "lrit_queued", 0) and self.satc_ready() and self.lrit_on.on:
            self.lrit_queued = 0
            self._lrit_report("QUEUED REPORT")
        if self.lrit_test.pop():
            self._lrit_report("TEST")
        if self.lrit_poll.pop():
            self.flags["lrit_poll"] = t
            if self.lrit_on.on:
                self.after(3.0, lambda: self._lrit_report("POLL RESPONSE"))
            else:
                self.lrit_log.append((w.utc_str()[:5], "POLL RECEIVED - LRIT DISABLED, NO RESPONSE"))
        # Fleet Broadband
        q = self.fbb_link()
        if self.fbb_con.pop():
            if self.fbb_con.on and q <= 0.05:
                self.fbb_con.on = False
                ui.sfx("error", 0.6)
                self._note("FLEET BB", "PDP CONTEXT REFUSED - NO SATELLITE LINK. POINT AND LOCK THE DISH ON THE INMARSAT TAB.", C["red"])
            elif self.fbb_con.on:
                ui.sfx("connect", 0.6)
                self.flags["fbb_on"] = t
                self._note("FLEET BB", "BACKGROUND IP SESSION OPEN (UP TO 432 kbit/s).", C["green"])
        if self.fbb_con.on:
            self.fbb_t += dt
            st = self.fbb_stream.idx
            if st and q > 0.3:
                self.fbb_cost += dt / 60.0 * (0, 1.9, 3.4, 6.5, 12.0)[st]
                self.fbb_mb += dt * (0, 32, 64, 128, 256)[st] / 8000.0
            for key, b in (("GRIB", self.b_grib), ("MAIL", self.b_mail), ("CHART", self.b_chart)):
                if b.pop() and not self.xfer:
                    self.xfer = dict(key=key, done=0.0, size=FILES[key][1], t0=t)
            x = self.xfer
            if x:
                rate = 0.054 * q * (0.5 if self.fbb_stream.idx >= 3 else 1.0)        # MB/s
                x["done"] = min(x["size"], x["done"] + rate * dt)
                self.fbb_mb += rate * dt
                self.fbb_cost += rate * dt * 5.5
                if x["done"] >= x["size"]:
                    self._note("FLEET BB", "%s COMPLETE: %.2f MB in %d s." % (FILES[x["key"]][0], x["size"], t - x["t0"]), C["green"])
                    self.flags["fbb_file:" + x["key"]] = t
                    ui.sfx("chime", 0.6)
                    self.xfer = None
            if q <= 0.05 and not getattr(self, "_lost", False):
                self._lost = True
                ui.sfx("unlock", 0.6, pan=self.bg_pan)
                self._note("FLEET BB", "SATELLITE LINK LOST - TRANSFER PAUSED.", C["amber"])
            elif q > 0.05:
                self._lost = False
        else:
            for b in (self.b_grib, self.b_mail, self.b_chart):
                if b.pop():
                    ui.sfx("error", 0.5)
                    self._note("FLEET BB", "NOT CONNECTED - SWITCH DATA CONNECT ON FIRST.", C["amber"])
        self.alert = bool(self.distress and not self.distress.get("acked") and not self.distress.get("cancelled"))

    def _place(self, num, reply, priority=False):
        w = self.world
        if not self.registered:
            ui.sfx("busy", 0.7)
            self._note("IRIDIUM CALL", "CALL FAILED - NOT REGISTERED (%s)." % self.reg, C["red"])
            self.mistake("Iridium call attempted with the terminal not registered on a satellite.")
            return
        self.call = "DIALLING"
        ui.sfx("ring", 0.6)

        def conn():
            if self.call != "DIALLING":
                return
            self.call = "CONNECTED"
            self.flags["ir_call:" + num] = w.t
            ui.sfx("connect", 0.5)
            self.voice.say(reply, "MRCC PENHALE" if priority else "PENHALE SHIPPING", w.t, 0.5)
            self._note("IRIDIUM VOICE  %s" % num, reply, C["cyan"])
        self.after(2.5 if priority else 4.0, conn)

    def _distress(self):
        w = self.world
        if not self.registered:
            ui.sfx("error", 0.7)
            self._note("IRIDIUM DISTRESS", "ALERT NOT SENT - TERMINAL NOT REGISTERED. USE ANOTHER MEANS.", C["red"])
            return
        nat = self.nature.value
        self.distress = dict(t0=w.t, acked=False, nature=nat)
        self.flags["ir_distress"] = w.t
        ui.sfx("sbd", 0.8)
        self._note("IRIDIUM DISTRESS ALERT SENT", "IMEI 300434060123450  %s  %s  NATURE: %s" % (w.name, self._pos_text(), nat), C["red"])
        d = self.distress

        def ack():
            if d is not self.distress or d.get("cancelled"):
                return
            d["acked"] = True
            self.flags["ir_distress_acked"] = w.t
            ui.sfx("beep2", 0.8)
            self._note("RCC ACKNOWLEDGEMENT", "DISTRESS ALERT RECEIVED BY MRCC PENHALE. STAND BY FOR A VOICE CALL.", C["yellow"])

            def cb():
                self.call = "CONNECTED"
                self.dial = "MRCC"
                txt = ("%s, THIS IS MRCC PENHALE ON IRIDIUM. WE HAVE YOUR DISTRESS ALERT, %s. CONFIRM YOUR POSITION, "
                       "THE NUMBER OF PERSONS ON BOARD AND WHETHER YOU ARE ABANDONING SHIP. OVER." % (w.name, nat))
                self.voice.say(txt, "MRCC PENHALE", w.t, 0.4)
                ui.sfx("ring", 0.5)
                self._note("IRIDIUM VOICE  MRCC", txt, C["cyan"])
            self.after(4.0, cb)
        self.after(9.0, ack)

    def _satc_print(self, hdr, msg):
        sc = getattr(self.app, "satcom", None)
        if sc is not None:
            sc.mon.note("%s  %s" % (self.world.utc_str(), hdr), msg, C["lcdfg"])

    def _ssas(self, where):
        w = self.world
        test = self.ssas_mode.value == "TEST"
        if not self.app.powered("SAT2"):
            return
        ok = self.satc_ready()
        self.ssas_log.append((w.utc_str()[:5], "%s ALERT BUTTON %s %s" % ("TEST" if test else "SSAS", where,
                                                                         "SENT VIA SAT-C" if ok else "- NO SAT-C LOGIN, QUEUED")))
        self.flags["ssas_test" if test else "ssas_alert"] = w.t
        if not ok:
            self.mistake("SSAS activated while Inmarsat-C was not logged in - the alert could not go out.")
            return
        if test:
            self.after(8.0, lambda: (self._satc_print("FROM CSO PENHALE SHIPPING", "SSAS TEST ALERT FROM %s RECEIVED "
                                                     "%s UTC. TEST SATISFACTORY. NO ACTION TAKEN." % (w.name, w.utc_str()[:5])),
                                     self.flags.__setitem__("ssas_test_ack", w.t),
                                     self.ssas_log.append((w.utc_str()[:5], "CSO CONFIRMS TEST RECEIVED"))))
            self.ssas = dict(real=False, t0=w.t, next=w.t + 1e9, sent=1)
        else:
            self.ssas = dict(real=True, t0=w.t, next=w.t + 60.0, sent=1)
            self.after(12.0, lambda: self._satc_print("FROM CSO PENHALE SHIPPING", "SSAS ALERT RECEIVED FROM %s. FLAG STATE "
                                                      "INFORMED. IF THIS IS A FALSE ALERT, CALL THE CSO IMMEDIATELY AND "
                                                      "GIVE THE CODE WORD." % w.name))

    def _lrit_report(self, kind):
        w = self.world
        if not self.app.powered("SAT2"):
            return
        if not self.satc_ready():
            self.lrit_log.append((w.utc_str()[:5], "%s - NO SAT-C LINK, QUEUED" % kind))
            self.lrit_queued = getattr(self, "lrit_queued", 0) + 1
            return
        self.lrit_last = w.t
        self.flags["lrit_" + kind.split()[0].lower()] = w.t
        self.lrit_log.append((w.utc_str()[:5], "%s  %s  ACCEPTED BY DC" % (kind, self._pos_text())))
        del self.lrit_log[:-12]
        if self.app.station is self:
            ui.sfx("data", 0.25)

    # ----------------------------------------------------------------- audio
    def audio(self, syn, n):
        v = self.voice.chunk(n, self.world.t, self.vol.val * 1.1)
        if v is not None and self.call:
            return v + syn.noise(n) * 0.012
        return None

    def bg_audio(self, syn, n):
        if self.alert and int(self.world.t * 2) % 2 == 0:
            return syn.beep("irdal", n, 2400.0, 4.0) * 0.18
        return None

    # ------------------------------------------------------------------ draw
    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if self.map.rect.collidepoint(pos):
            return ("IRIDIUM: 66 satellites in six near-polar planes, 780 km up, each crossing the sky in about 10 "
                    "minutes. Green = in view above 8°, ringed = the one serving you. Note the coverage at the poles (Sea Area A4).")
        return ""

    def draw(self, s):
        w, t = self.world, self.world.t
        ui.panel(s, (20, 54, 900, 470), "IRIDIUM CONSTELLATION  -  66 LEO SATELLITES, 6 PLANES, 780 km, 100 min")
        ui.panel(s, (20, 532, 900, 328), "IRIDIUM GMDSS TERMINAL")
        ui.panel(s, (930, 54, 660, 260), "SHIP SECURITY ALERT SYSTEM (SSAS)")
        ui.panel(s, (930, 322, 660, 220), "LRIT  -  LONG RANGE IDENTIFICATION AND TRACKING")
        ui.panel(s, (930, 550, 660, 310), "FLEET BROADBAND  -  IP DATA")
        ui.crt(s, self.map.rect, gain=80)
        self.map.draw(s)
        if t - getattr(self, "_trk_t", -99) > 2.0:                 # orbital plane ground tracks (cached)
            self._trk_t = t
            self._trk = []
            for pl in range(6):
                sat = IRIDIUM[pl * 11]
                self._trk.append([self.map.xy(*w.leo_pos(sat, t + k * IR_PER / 72.0)) for k in range(72)])
        for pts in self._trk:
            for x, y in pts:
                pygame.draw.circle(s, (58, 100, 138), (x, y), 1)
        vis_names = set(v[2] for v in self._sats)
        for sat in IRIDIUM:
            la, lo = w.leo_pos(sat, t)
            vis = sat[0] in vis_names
            x, y = self.map.xy(la, lo)
            pygame.draw.circle(s, C["green"] if vis else (130, 180, 235), (x, y), 4 if vis else 3)
            pygame.draw.circle(s, (8, 16, 28), (x, y), 4 if vis else 3, 1)
        if self.serving:
            sat = next(x for x in IRIDIUM if x[0] == self.serving)
            la, lo = w.leo_pos(sat, t)
            self.map.footprint(s, la, lo, 18.0, C["amber"], 8, 1)
            sx, sy = self.map.xy(la, lo)
            shx, shy = self.map.xy(w.lat, w.lon)
            if abs(sx - shx) < 400:
                pygame.draw.line(s, C["amber"], (shx, shy), (sx, sy), 1)
            pygame.draw.circle(s, C["amber"], (sx, sy), 7, 1)
            text(s, self.serving, (sx + 8, sy - 6), 9, C["amber"], bold=True)
        x, y = self.map.marker(s, w.lat, w.lon, C["white"], None, "tri", 6)
        text(s, w.name, (x + 9, y - 5), 10, C["white"], bold=True)
        # terminal LCD
        l = ui.lcd(s, (36, 558, 368, 140), (12, 16, 10), (50, 70, 40))
        fg, dim = (190, 230, 120), (90, 120, 70)
        if not self.on:
            text(s, "NO POWER" if self.pwr.on else "OFF", l.center, 18, dim, bold=True, align="m")
        else:
            text(s, "IRIDIUM  %s" % self.reg, (l.x + 8, l.y + 6), 13, fg if self.registered else C["amber"], bold=True)
            ui.bar(s, (l.right - 96, l.y + 8, 84, 12), self.bars / 5.0, "green", 5)
            rows = ["SAT %s  EL %2d°  HANDOFFS %d" % (self.serving or "----", self.sv_el, self.handoffs),
                    "POS %s" % self._pos_text(),
                    "CALL %s  %s" % (self.call or "IDLE", self.dial[-12:]),
                    ("DISTRESS %s" % ("CANCELLED" if self.distress.get("cancelled") else
                                      ("ACKNOWLEDGED BY RCC" if self.distress["acked"] else "SENT - AWAITING ACK")))
                    if self.distress else "DISTRESS  READY",
                    "SBD MOMSN %d" % self.sbd_n]
            for i, r in enumerate(rows):
                text(s, r, (l.x + 8, l.y + 28 + i * 21), 12, C["red"] if (i == 3 and self.distress and not self.distress.get("cancelled")) else fg)
        self.mon.draw(s, (36, 706, 368, 144), 11)
        text(s, "1. LIFT  2. HOLD 3 s", (476, 700), 9, C["dim"], bold=True, align="c")
        ui.led(s, (790, 580), "green", self.registered, "REG", 5, 9)
        ui.led(s, (850, 580), "green", self.call == "CONNECTED", "CALL", 5, 9)
        # SSAS
        l = ui.lcd(s, (1290, 80, 284, 140))
        rows = ["SSAS  MODE %s" % self.ssas_mode.value,
                "VIA INMARSAT-C: %s" % ("READY" if self.satc_ready() else "NOT LOGGED IN"),
                "STATUS: %s" % ("ALERT ACTIVE (SILENT)" if (self.ssas and self.ssas.get("real")) else
                                ("TEST SENT" if self.ssas else "IDLE")),
                "TO: CSO PENHALE SHIPPING", "    FLAG STATE MRCC"]
        for i, r in enumerate(rows):
            text(s, r, (l.x + 8, l.y + 8 + i * 22), 12, C["lcdfg"])
        ui.led(s, (1280, 232), "red", bool(self.ssas) and int(t * 2) % 7 == 0, "TX", 3, 9)
        ll = ui.lcd(s, (950, 232, 624, 70))
        for i, (tm, msg) in enumerate(self.ssas_log[-3:]):
            text(s, "%s %s" % (tm, msg[:70]), (ll.x + 8, ll.y + 6 + i * 20), 11, C["lcdfg"])
        if not self.ssas_log:
            ui.text_block(s, "Covert alert: no alarm, light or sound on board. Test only by prior arrangement with the CSO.",
                          (ll.x + 8, ll.y + 8, ll.w - 16, 60), 11, C["dim"], mono=False, lh=15)
        # LRIT
        l = ui.lcd(s, (1236, 346, 338, 184))
        nx = (self.lrit_next - t) if self.lrit_next else 0
        rows = ["LRIT %s   ASP via INMARSAT-C" % ("ENABLED" if self.lrit_on.on else "DISABLED"),
                "INTERVAL %s  NEXT IN %d:%02d:%02d" % (self.lrit_int.value, nx // 3600, nx // 60 % 60, nx % 60),
                "LINK: %s" % ("SAT-C LOGGED IN" if self.satc_ready() else "NO SAT-C - REPORTS QUEUED")]
        for i, r in enumerate(rows):
            text(s, r, (l.x + 8, l.y + 6 + i * 18), 11, C["lcdfg"] if self.lrit_on.on else C["amber"], bold=i == 0)
        for i, (tm, msg) in enumerate(self.lrit_log[-6:]):
            text(s, "%s %s" % (tm, msg[:40]), (l.x + 8, l.y + 64 + i * 19), 10, C["lcdfg"])
        ui.text_block(s, "Flag-state data centre gets your position every interval.",
                      (946, 500, 280, 40), 10, C["dim"], mono=False, lh=13)
        # Fleet Broadband
        q = self.fbb_link()
        l = ui.lcd(s, (1236, 576, 338, 270))
        rows = ["LINK  %s  (dish C/N0 %.0f)" % ("UP" if q > 0.05 else "DOWN", getattr(self.app.satcom, "cn0", 0)),
                "SESSION %s  %02d:%02d" % ("OPEN" if self.fbb_con.on else "CLOSED", self.fbb_t // 60, self.fbb_t % 60),
                "STREAM  %s" % self.fbb_stream.value,
                "DATA    %.2f MB" % self.fbb_mb,
                "COST    $ %.2f" % self.fbb_cost]
        for i, r in enumerate(rows):
            text(s, r, (l.x + 8, l.y + 8 + i * 22), 12, C["lcdfg"] if q > 0.05 else C["amber"])
        ui.bar(s, (l.x + 8, l.y + 128, 320, 12), q, "green", 20)
        text(s, "link quality", (l.x + 8, l.y + 144), 9, C["dim"])
        x = self.xfer
        if x:
            f = x["done"] / x["size"]
            pygame.draw.rect(s, (20, 40, 30), (l.x + 8, l.y + 170, 320, 20))
            pygame.draw.rect(s, (60, 160, 100), (l.x + 8, l.y + 170, 320 * f, 20))
            text(s, "%s %d%%  %.2f/%.1f MB" % (FILES[x["key"]][0], f * 100, x["done"], x["size"]), (l.x + 168, l.y + 180), 10,
                 C["white"], bold=True, align="m")
        ui.text_block(s, "Fleet Broadband rides on the stabilised dish of the INMARSAT tab: no lock, no data.",
                      (l.x + 8, l.y + 206, 320, 60), 10, C["dim"], mono=False, lh=13)
        ui.led(s, (950, 740), "green", q > 0.05, "SAT LINK", 5, 9)
        ui.led(s, (950, 762), "amber", bool(self.fbb_con.on and (self.xfer or self.fbb_stream.idx)), "DATA", 5, 9)
        super().draw(s)
