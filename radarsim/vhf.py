"""Marine VHF radiotelephone with Class-A DSC controller, plus a V/UHF
AM/FM transceiver (aeronautical 118-137 MHz, UHF 225-400 MHz, on-board UHF).

Signals follow a line-of-sight link budget, so antenna height and distance
decide what you can hear - shown live in the LINK BUDGET panel.
"""
import math
import numpy as np
import pygame
from . import ui
from .ui import C, text, Knob, Selector, Button, Guard, Station
from .world import vhf_channel, VHF_CHANNELS, VHF_USE, CPS, Src, Msg, fmt_lat, fmt_lon
from .radiocore import Monitor, garble
from .speech import SR, chunk
from .audio import speaker, place

NATURES = ["UNDESIGNATED", "FIRE, EXPLOSION", "FLOODING", "COLLISION", "GROUNDING",
           "LISTING, CAPSIZING", "SINKING", "DISABLED AND ADRIFT", "ABANDONING SHIP",
           "PIRACY / ARMED ATTACK", "MAN OVERBOARD"]
PRESETS = [(121.5, "GUARD"), (123.1, "SAR"), (118.05, "ATIS"), (243.0, "MIL GUARD"),
           (282.8, "SAR UHF"), (457.525, "ON-BOARD")]
ATIS = ("PENHALE INFORMATION BRAVO. RUNWAY 27 IN USE. WIND 240 DEGREES 18 KNOTS. VISIBILITY 8 "
        "KILOMETRES IN RAIN. CLOUD BROKEN 1200 FEET. QNH 1002. ACKNOWLEDGE INFORMATION BRAVO.     ")
BOOK = ["CG", "NORDIC STAR", "ATLANTIC PEARL", "PENHALE FERRY", "FV MORVORAN"]


class VUHF(Station):
    name = "VHF / UHF"
    tab = "VHF/UHF"
    hint = ("Marine VHF + DSC on the left, air/UHF transceiver top right. Hold SPACE (or the PTT "
            "button) to transmit. Build a spoken message with the MESSAGE COMPOSER keys, then hold PTT to the end.")
    power_key = "VHF"
    pan, bg_pan, bg_listen, bg_level = 0.0, -0.4, True, 0.45

    def __init__(self, app):
        super().__init__(app)
        w = self.world
        self.ch, self.mon = 16, Monitor()
        self.rxs = {"M": {}, "A": {}, "G": {}}
        self.key_ptt, self.tx, self.tx_t0 = False, False, 0.0
        self.atx, self.atx_t0 = False, 0.0
        self.dsc_log, self.dsc_alarm, self.distress = [], False, None
        self.burst_until, self.work = 0.0, None
        self.pending, self.seen, self.flags = [], set(), {}
        self.af = 121.5
        self.last_rx = None
        self._was_open = {}
        self.incoming, self._ring_t = None, 0.0
        self.scan_hold, self._scan_t = 0.0, 0.0
        self.distress_utc = None
        self.txm = None
        self.spk_m, self.spk_a, self.spk_tx = speaker("vhf"), speaker("air"), speaker("vhf")
        self._mains = True
        tipdsc = "Digital Selective Calling runs on channel 70 through a separate watch receiver. "
        self.pwr = self.add(Button((36, 246, 64, 40), "PWR", "Radio power.", toggle=True, on=True, color="green"))
        self.b16 = self.add(Button((106, 246, 64, 40), "16", "Instant select channel 16 "
            "(156.800 MHz): international distress, safety and calling.", color="red"))
        self.dual = self.add(Button((176, 246, 64, 40), "DUAL\nWATCH", "DUAL WATCH: keeps sampling "
            "channel 16 while you listen on a working channel; 16 takes priority.", toggle=True, size=10))
        self.hilo = self.add(Button((246, 246, 64, 40), "1W\nLOW", "Transmit power: lit = LOW (1 W), "
            "off = HIGH (25 W). Use low power in harbour and for close-range working.", toggle=True, size=10))
        self.chdn = self.add(Button((316, 246, 56, 40), "CH -", "Previous channel."))
        self.chup = self.add(Button((378, 246, 56, 40), "CH +", "Next channel."))
        self.scan = self.add(Button((442, 246, 64, 40), "SCAN", "SCAN: steps through every channel (not 70) and "
            "stops on any channel that opens the squelch; resumes 3 s after it goes quiet. PTT or 16 stops it.",
            toggle=True, size=11))
        self.vol = self.add(Knob(490, 150, 22, "VOLUME", 0, 1, 0.7, "Loudspeaker volume."))
        self.sql = self.add(Knob(570, 150, 22, "SQUELCH", 0, 1, 0.3, "SQUELCH: mutes the receiver "
            "until a signal exceeds the threshold. Set it just past where the noise stops - too "
            "high and you miss weak stations."))
        self.chk = self.add(Knob(676, 150, 34, "CHANNEL", encoder=True, on_turn=self._turn,
            tip="Channel selector. International channels 1-28 and 60-88. Duplex channels "
            "transmit 4.6 MHz below the coast station frequency."))
        self.ptt = self.add(Button((600, 236, 160, 56), "PTT  (SPACE)", "PRESS TO TALK: hold to "
            "transmit, release to listen. Simplex means only one station can talk at a time.", color="red", size=13))
        self.guard = self.add(Guard((456, 392, 120, 96), "DISTRESS", tipdsc + "DISTRESS: lift "
            "the cover, then HOLD the button 3 seconds. Sends MMSI, position, time and nature of "
            "distress to all stations, then switches to channel 16 for the MAYDAY voice call."))
        self.nature = self.add(Selector(668, 444, 22, "NATURE OF DISTRESS", NATURES, 0, tipdsc +
            "Select the nature of distress before sending, if time allows. UNDESIGNATED is sent otherwise."))
        self.addr = self.add(Selector(500, 554, 20, "ADDRESS", BOOK, 0, "DSC address book: the "
            "station (by MMSI) for an individual call."))
        self.wch = self.add(Selector(590, 554, 20, "WORK CH", ["06", "08", "72", "77", "67"], 0,
            "Working channel proposed in the DSC call. Both radios switch to it on acknowledgement."))
        self.b_ind = self.add(Button((660, 506, 104, 36), "INDIVIDUAL\nCALL", tipdsc +
            "Routine call to one station by MMSI - replaces calling by voice on channel 16.", size=10))
        self.b_saf = self.add(Button((660, 548, 104, 36), "ALL SHIPS\nSAFETY", tipdsc +
            "Safety announcement (SECURITE) to all stations, followed by voice on channel 16.", size=10))
        self.b_urg = self.add(Button((660, 590, 104, 36), "ALL SHIPS\nURGENCY", tipdsc +
            "Urgency announcement (PAN PAN) to all stations, followed by voice on channel 16.", size=10))
        self.b_sil = self.add(Button((456, 612, 96, 38), "SILENCE\nACCEPT", "Silence the DSC alarm. For an "
            "incoming ROUTINE individual call this also ACCEPTS it: the radio acknowledges (able to comply) and "
            "moves to the proposed working channel.", size=10, color="green"))
        self.b_can = self.add(Button((558, 612, 96, 38), "CANCEL\nALERT", "FALSE ALERT: stops the "
            "automatic repetition. You must then cancel by voice on channel 16 to all stations.", size=10))
        # air / UHF radio
        self.amhz = self.add(Knob(1220, 140, 22, "MHz", encoder=True, on_turn=lambda n: self._atune(n * 1.0),
                                  tip="Coarse tuning, 1 MHz per click. 118-137 MHz AM air band, 156-174 FM marine, 225-400 AM UHF, 400-470 FM UHF."))
        self.akhz = self.add(Knob(1300, 140, 22, "kHz", encoder=True, on_turn=lambda n: self._atune(n * 0.025),
                                  tip="Fine tuning, 25 kHz per click."))
        self.avol = self.add(Knob(1380, 140, 22, "VOLUME", 0, 1, 0.7, "Loudspeaker volume."))
        self.asql = self.add(Knob(1460, 140, 22, "SQUELCH", 0, 1, 0.3, "Squelch threshold."))
        self.agrd = self.add(Selector(1540, 140, 22, "GUARD RX", ["OFF", "121.5", "243.0"], 1,
            "GUARD RECEIVER: a second receiver fixed on the emergency frequency (121.5 MHz civil, "
            "243.0 MHz military) regardless of the main frequency."))
        self.aptt = self.add(Button((1116, 84, 60, 102), "PTT", "Transmit on the air/UHF radio.", color="red"))
        self.apre = []
        for i, (f, nm) in enumerate(PRESETS):
            self.apre.append(self.add(Button((806 + i * 129, 240, 123, 38), "%.3f\n%s" % (f, nm),
                "Preset: %s %.3f MHz" % (nm, f), size=10)))
        from .composer import Composer
        self.comp = Composer(self, 806, 768)

    # ---------------------------------------------------------------- helpers
    def after(self, delay, fn):
        self.pending.append((self.world.t + delay, fn))

    def _turn(self, n):
        i = VHF_CHANNELS.index(self.ch)
        self.ch = VHF_CHANNELS[(i + n) % len(VHF_CHANNELS)]
        ui.sfx("kbeep", 0.5)

    @property
    def on(self):
        return self.pwr.on and self.powered

    def pos_str(self):
        p = self.app.dsc_position()
        if not p:
            return "POS UNKNOWN 9999999999 T8888"
        return "POS %s %s%s" % (fmt_lat(p[0]), fmt_lon(p[1]), " (MAN)" if p[2] == "MANUAL" else "")

    def _atune(self, d):
        f = round((self.af + d) / 0.025) * 0.025
        self.af = max(108.0, min(470.0, f))

    @property
    def amode(self):
        return "AM" if (self.af < 137 or 225 <= self.af < 400) else "FM"

    @property
    def power_w(self):
        return 1.0 if (self.hilo.on or self.ch in (15, 17, 75, 76)) else 25.0

    def log(self, msg, color=None):
        self.dsc_log.append((self.world.utc_str()[:5], msg, color or C["lcdfg"]))
        del self.dsc_log[:-40]

    def beacons(self):
        w = self.world
        out = [dict(f=118.05, src=w.srcs["ATIS"], kind="voice", text=ATIS, key="atis")]
        if w.epirb_on and getattr(w, "epirb_homer", True):
            out.append(dict(f=121.5, src=Src("406 EPIRB HOMER (OWN)", w.x + 0.02, w.y, 2, 0.05),
                            kind="sweep", text="[SWEEP TONE] ", key="epirb"))
        return out

    def _rx(self, rid, f, thr, label):
        w, st = self.world, self.rxs[rid]
        best = None
        for m in w.msgs:
            if m.kind == "voice" and m.active(w.t) and abs(m.f - f) < 0.004:
                l = w.los_link(m.src, m.f)
                if best is None or l["pr"] > best[1]["pr"]:
                    best = (m, l, True)
        for b in self.beacons():
            if abs(b["f"] - f) < 0.004:
                l = w.los_link(b["src"], f)
                if best is None or l["pr"] > best[1]["pr"]:
                    best = (b, l, False)
        st.update(sig=None, link=None, open=False, kind=None, thr=thr, f=f)
        if not best or best[1]["pr"] < -121:
            return st
        m, l, is_msg = best
        st.update(sig=m, link=l, open=l["pr"] > thr, kind=m.kind if is_msg else m["kind"])
        q = min(1.0, max(0.2, (l["pr"] + 121) / 12.0))
        src = m.src if is_msg else m["src"]
        hdr = "%s  %s  %s  %d dBm" % (w.utc_str(), label, src.name, l["pr"])
        if is_msg:
            m.clip()
            n = m.chars(w.t)
            p = m.prog.get(rid, 0)
            if st["open"]:
                for i in range(p, n):
                    self.mon.feed((rid, id(m)), hdr, garble(m.text[i], q, i))
                if n > p:
                    self.flags["heard:" + src.name] = w.t
            m.prog[rid] = n
        elif st["open"]:
            txt = m["text"]
            clip = Msg.speech.get(txt, src.name) if (Msg.speech and Msg.speech.ok and m["kind"] == "voice") else None
            if clip is not None:
                L = len(clip) + SR
                i = int(min(1.0, (int(w.t * SR) % L) / float(len(clip))) * len(txt.rstrip()))
            else:
                i = int(w.t * CPS) % len(txt)
            last = st.get("bi", i)
            if i < last:
                last = 0
                self.mon.key = None
            for j in range(last, i):
                self.mon.feed((rid, m["key"]), hdr, garble(txt[j], q, j))
            st["bi"] = i
        return st

    # ------------------------------------------------------------------ DSC
    def send_distress(self):
        w = self.world
        nat = self.nature.value
        self.distress = dict(t0=w.t, nature=nat, acked=False, voiced=False, cancelled=False)
        self.distress_utc = w.utc_str()[:5]
        self.flags["distress_sent"] = w.t
        self.flags["distress_nature"] = nat
        self.burst_until = w.t + 0.8
        self.ch = 16
        self.scan.on = False
        self.hilo.on = False
        self.log("TX DISTRESS ALERT  %s" % nat, C["red"])
        self.log("  " + self.pos_str(), C["red"])
        if not self.app.dsc_position():
            self.mistake("DSC distress alert sent with NO POSITION - GPS lost and no manual position entered.")
        self.log("  AUTO CH16 - AWAIT ACKNOWLEDGEMENT", C["red"])
        d = self.distress

        def ack():
            if d is self.distress and not d["cancelled"]:
                if w.los_link(w.srcs["CG"], 156.525)["pr"] > -112:
                    d["acked"] = True
                    self.flags["distress_acked"] = w.t
                    self.log("RX DISTRESS ACK FROM 002320777", C["yellow"])
                    self.log("  PENHALE COASTGUARD (MRCC)", C["yellow"])
                    self.dsc_alarm = True
                else:
                    self.log("NO ACK - ALERT REPEATS AUTOMATICALLY", C["amber"])
                    self.after(20, ack)
        self.after(7, ack)

    def dsc_call(self, kind):
        w = self.world
        self.burst_until = w.t + 0.6
        if kind == "IND":
            who = self.addr.value
            src = w.srcs[who]
            wc = int(self.wch.value)
            self.log("TX INDIVIDUAL ROUTINE > %09d" % src.mmsi)
            self.log("  %s  PROPOSE CH%02d" % (src.name, wc))
            self.flags["indiv_sent"] = w.t

            def ack():
                if w.los_link(src, 156.525)["pr"] > -112 and getattr(src, "active", True):
                    use = 67 if who == "CG" else wc
                    self.log("RX ACK < %09d ABLE TO COMPLY CH%02d" % (src.mmsi, use), C["yellow"])
                    self.ch, self.work = use, (use, src)
                    self.flags["indiv_acked"] = w.t
                    w.say(use, src, "%s, THIS IS %s. RECEIVED YOUR D-S-C CALL. GO AHEAD. OVER." % (w.name, src.name), 2.0)
                else:
                    self.log("NO ACKNOWLEDGEMENT (OUT OF RANGE?)", C["amber"])
            self.after(4, ack)
        else:
            self.log("TX ALL SHIPS %s  WORK CH16" % kind, C["amber"])
            self.flags["allships_" + kind.lower()] = w.t
            self.ch = 16

    def _dsc_rx(self):
        w = self.world
        for m in w.msgs:
            if m.kind == "dsc" and m.t0 <= w.t and id(m) not in self.seen:
                self.seen.add(id(m))
                if not self.on or w.los_link(m.src, 156.525)["pr"] < -112:
                    continue
                d = m.dsc
                if d["cat"] == "INDIVIDUAL":
                    if d.get("to") == w.mmsi and not self.distress and not self.dsc_alarm and not self.incoming:
                        self.incoming = dict(src=m.src, ch=d["ch"], text=d["text"], t=w.t)
                        self.log("RX INDIVIDUAL ROUTINE FROM %09d" % m.src.mmsi, C["cyan"])
                        self.log("  %s" % m.src.name, C["cyan"])
                        self.log("  PROPOSES CH%02d - PRESS ACCEPT" % d["ch"], C["cyan"])
                        self.flags["indiv_rx"] = w.t
                        self._ring_t = 0.0
                    continue
                col = C["red"] if d["cat"] in ("DISTRESS", "DISTRESS RELAY") else C["yellow"]
                self.log("RX %s FROM %09d" % (d["cat"], m.src.mmsi), col)
                self.log("  %s" % m.src.name, col)
                if d.get("nature"):
                    self.log("  NATURE: %s" % d["nature"], col)
                if d.get("pos"):
                    self.log("  POS %s" % d["pos"], col)
                self.log("  LISTEN CH16. DO NOT ACK BY DSC.", col)
                self.dsc_alarm = True
                ui.sfx("fsk", 0.5)
                self.flags["dsc_rx_" + d["cat"].lower()] = w.t
                self.last_rx = m

    # --------------------------------------------------------------- update
    def handle(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key == pygame.K_SPACE:
            self.key_ptt = True
            return True
        if ev.type == pygame.KEYUP and ev.key == pygame.K_SPACE:
            self.key_ptt = False
            return True
        return super().handle(ev)

    def update(self, dt):
        w = self.world
        for item in list(self.pending):
            if w.t >= item[0]:
                self.pending.remove(item)
                item[1]()
        if self.pwr.pop():
            ui.sfx("pwron" if self.pwr.on else "pwroff", 0.8)
        if self.powered != self._mains:
            self._mains = self.powered
            if self.pwr.on:
                ui.sfx("pwron" if self._mains else "pwroff", 0.7, pan=self.bg_pan)
        if self.b16.pop():
            self.ch = 16
            self.scan.on = False
            ui.sfx("kbeep", 0.5)
        if self.chdn.pop():
            self._turn(-1)
        if self.chup.pop():
            self._turn(1)
        for b, (f, _) in zip(self.apre, PRESETS):
            if b.pop():
                self.af = f
        self.comp.refresh()
        self.comp.update(w.t)
        on = self.on
        if self.guard.pop_fired() and on:
            self.send_distress()
        if self.b_ind.pop() and on:
            self.dsc_call("IND")
        if self.b_saf.pop() and on:
            self.dsc_call("SAFETY")
        if self.b_urg.pop() and on:
            self.dsc_call("URGENCY")
        if self.b_sil.pop():
            if self.dsc_alarm:
                self.flags["alarm_silenced"] = w.t
            self.dsc_alarm = False
            inc = self.incoming
            if inc and on:
                self.incoming = None
                self.ch, self.work = inc["ch"], (inc["ch"], inc["src"])
                self.scan.on = False
                self.flags["indiv_accept"] = w.t
                self.log("TX ACK > %09d ABLE TO COMPLY CH%02d" % (inc["src"].mmsi, inc["ch"]), C["cyan"])
                self.burst_until = w.t + 0.5
                w.say(inc["ch"], inc["src"], inc["text"], 3.0)
        if self.incoming:
            if w.t - self.incoming["t"] > 45:
                self.log("CALL FROM %s NOT ACCEPTED" % self.incoming["src"].name[:20], C["amber"])
                self.incoming = None
            elif w.t > self._ring_t:
                self._ring_t = w.t + 2.5
                ui.sfx("ringin", 0.7, pan=self.pan if self.app.station is self else self.bg_pan)
        if self.b_can.pop() and self.distress and not self.distress["cancelled"]:
            self.distress["cancelled"] = True
            self.flags["distress_cancelled"] = w.t
            self.log("ALERT REPETITION STOPPED", C["amber"])
            self.log("  NOW CANCEL BY VOICE ON CH16", C["amber"])
        self._dsc_rx()
        self.alert = self.dsc_alarm or bool(self.incoming)
        # marine PTT
        tx = on and (self.ptt.down or (self.key_ptt and self.app.station is self))
        if tx != self.tx:
            ui.sfx("relay", 0.9)
        if tx and not self.tx:
            self.tx_t0 = w.t
            self.scan.on = False
            self.txm = self.comp.begin(w.t) if self.ch != 70 else None
        if self.tx and not tx:
            sent = self.comp.finish(w.t) if self.txm else None
            self.txm = None
            if sent is not None and sent["keys"]:
                self._released_msg(w.t - self.tx_t0, sent)
            else:
                if sent is not None:
                    self.mon.note(w.utc_str(), "[PTT RELEASED BEFORE THE FIRST PHRASE WAS SPOKEN - NOTHING SENT]", C["amber"])
                    self.mistake("PTT released before the composed message had started.")
                self._released(w.t - self.tx_t0)
        self.tx = tx
        atx = self.aptt.down
        if atx != self.atx:
            ui.sfx("relay", 0.9)
        if atx and not self.atx:
            self.atx_t0 = w.t
        if self.atx and not atx:
            self._a_released(w.t - self.atx_t0)
        self.atx = atx
        # receivers
        thr = -124 + 40 * self.sql.val
        if on and not self.tx:
            st = self._rx("M", vhf_channel(self.ch)[1], thr, "CH%02d" % self.ch)
            if self.scan.on:
                if st["open"]:
                    self.scan_hold = w.t + 3.0
                elif w.t > self.scan_hold and w.t > self._scan_t:
                    self._scan_t = w.t + 0.12
                    i = VHF_CHANNELS.index(self.ch)
                    self.ch = VHF_CHANNELS[(i + 1) % len(VHF_CHANNELS)]
                    if self.ch == 70:
                        self.ch = VHF_CHANNELS[(i + 2) % len(VHF_CHANNELS)]
            if self.dual.on and self.ch != 16:
                g = self._rx("G", 156.8, thr, "CH16 (DW)")
                if g["open"]:
                    self.rxs["M"] = dict(g)
                    self.rxs["G"] = {}
        else:
            self.rxs["M"] = dict(open=False, sig=None, link=None, thr=thr)
        athr = -124 + 40 * self.asql.val
        if not self.atx:
            st = self._rx("A", self.af, athr, "%.3f %s" % (self.af, self.amode))
            if not st["open"] and self.agrd.idx:
                gf = float(self.agrd.value)
                self._rx("A", gf, athr, "GUARD %.1f" % gf)
        else:
            self.rxs["A"] = dict(open=False, sig=None, link=None, thr=athr)

        for rid in ("M", "A"):                       # squelch crash on a carrier, tail when it drops
            now = bool(self.rxs[rid].get("open"))
            vol = self.vol.val if rid == "M" else self.avol.val
            hear = self.app.station is self or self.app.monitor_all
            pan = (-0.5 if rid == "M" else 0.5) if self.app.station is self else self.bg_pan
            k = 1.0 if self.app.station is self else self.bg_level
            if self._was_open.get(rid) and not now and hear:
                ui.sfx("sqtail", 0.5 * vol * k, pan=pan)
            if now and not self._was_open.get(rid) and hear:
                ui.sfx("sqopen", 0.45 * vol * k, pan=pan)
            self._was_open[rid] = now

    def _released(self, dur):
        w = self.world
        if self.ch == 70:
            self.mon.note(w.utc_str() + "  CH70", "[CHANNEL 70 IS DSC ONLY - VOICE TRANSMISSION INHIBITED]", C["red"])
            return
        if dur < 1.2:
            return
        self.mon.note("%s  TX CH%02d  %d W" % (w.utc_str(), self.ch, self.power_w),
                      "[YOU TRANSMITTED FOR %.0f s]" % dur, C["cyan"])
        self.flags["tx_ch%d" % self.ch] = w.t
        cg = w.srcs["CG"]
        ok = w.los_link(cg, 156.8, pw=self.power_w)["pr"] > -110
        d = self.distress
        if self.ch == 16 and d and not d["voiced"] and dur >= 4:
            if d["cancelled"]:
                self.flags["cancel_voiced"] = w.t
                if ok:
                    w.say(16, cg, "%s, THIS IS PENHALE COASTGUARD. YOUR CANCELLATION OF THE FALSE "
                          "DISTRESS ALERT IS RECEIVED. OUT." % w.name, 2.5)
                self.distress = None
                return
            d["voiced"] = True
            self.flags["mayday_voiced"] = w.t
            if ok:
                self._cg_mayday()
        elif self.ch == 16 and dur >= 3 and not d and self.last_rx and w.t - self.last_rx.t0 < 400:
            src = self.last_rx.src
            self.flags["mayday_ack_voiced"] = w.t
            w.say(16, src, "MAYDAY. %s, THIS IS %s. THANK YOU FOR YOUR ACKNOWLEDGEMENT. FIRE IS IN THE ENGINE ROOM, "
                  "21 PERSONS ON BOARD. REQUEST YOU STAND BY TO ASSIST AND RELAY TO THE COASTGUARD. OVER." % (w.name, src.name), 2.5)
            self.last_rx = None
        elif self.ch == 16 and dur >= 2.5 and not d:
            if ok:
                self.flags["radio_check"] = w.t
                w.say(16, cg, "STATION CALLING PENHALE COASTGUARD, THIS IS PENHALE COASTGUARD. YOU ARE "
                      "LOUD AND CLEAR. FOR ROUTINE TRAFFIC USE CHANNEL 67. OUT.", 2.5)
            else:
                self.mon.note(w.utc_str(), "[NO REPLY - YOU ARE BEYOND RADIO RANGE AT THIS POWER]", C["amber"])
        elif self.work and self.ch == self.work[0] and dur >= 2:
            src = self.work[1]
            self.flags["work_voiced"] = w.t
            w.say(self.ch, src, "%s, %s. ROGER, ALL COPIED. BACK TO CHANNEL 16. OUT." % (w.name, src.name), 2.0)
            self.work = None
        elif self._b2b_reply(dur):
            pass

    def _cg_mayday(self, nature=None):
        w = self.world
        cg = w.srcs["CG"]
        w.say(16, cg, "MAYDAY. %s, %s, %s. THIS IS PENHALE COASTGUARD, PENHALE COASTGUARD. "
              "RECEIVED MAYDAY. RESCUE HELICOPTER 193 IS TASKED TO YOUR POSITION, ESTIMATED "
              "10 MINUTES. ACTIVATE YOUR SART AND EPIRB. OVER." % (w.name, w.name, w.name), 3.0)
        heli = w.by_name["RESCUE 193"]
        if not heli.home:
            w.task_sar(heli, 16.0, 35.0)
        self.after(22, lambda: w.say(16, heli, "%s, THIS IS RESCUE 193. AIRBORNE AND PROCEEDING "
                   "TO YOUR POSITION. REQUEST YOU STAND BY 123 DECIMAL 1 AND FIRE A FLARE ON "
                   "REQUEST. OVER." % w.name))

    def _b2b_reply(self, dur, composed=False):
        """Answer a ship that called you about a close-quarters situation."""
        w = self.world
        c = w.b2b_call
        if not c or c["answered"] or w.t - c["t"] > 240 or self.ch not in (16, 13, 6) or (dur < 2 and not composed):
            return False
        c["answered"] = True
        src = c["src"]
        cp, tc, rng, _ = w.cpa(src)
        turned = ((w.hdg - c["hdg0"] + 540) % 360) - 180
        self.flags["b2b_answered"] = w.t
        if cp > 1.0 or turned > 15:
            txt = ("%s, %s. ROGER, I SEE YOU ALTERING TO STARBOARD. I AM MAINTAINING MY COURSE AND SPEED. "
                   "THANK YOU. OUT." % (w.name, src.name))
        else:
            txt = ("%s, %s. ROGER. I AM MAINTAINING MY COURSE AND SPEED. YOUR CPA IS LESS THAN HALF A MILE - "
                   "TAKE EARLY AND SUBSTANTIAL ACTION IN ACCORDANCE WITH THE COLLISION REGULATIONS. OUT." % (w.name, src.name))
        w.say(self.ch, src, txt, 2.0)
        return True

    def _released_msg(self, dur, sent):
        """A composed message went out: check it and let the other station answer what it heard."""
        w = self.world
        comp = self.comp
        kind, chk, miss = comp.evaluate(sent)
        cg = w.srcs["CG"]
        ok = w.los_link(cg, 156.8, pw=self.power_w)["pr"] > -110
        ch = self.ch
        self.mon.note("%s  TX CH%02d  %d W  (%d s)" % (w.utc_str(), ch, self.power_w, dur),
                      "[YOU SAID] " + (sent["text"] or "-"), C["cyan"])
        self.flags["tx_ch%d" % ch] = w.t
        self.flags["composed_" + (kind or "none").lower()] = w.t
        note = ""
        d = self.distress
        if kind in ("DISTRESS", "URGENCY", "SAFETY", "CANCEL") and ch != 16:
            chk.append((False, "%s traffic is called on CH16" % kind.lower(), False))
            note = "Nobody answers: the coastguard keeps its distress and safety watch on CH16."
        elif not ok and kind in ("DISTRESS", "URGENCY", "CHECK", "CANCEL"):
            note = "No reply - beyond radio range of the coast station at this power."
        elif kind == "DISTRESS":
            if miss:
                who = w.name if "NAME" not in miss else "STATION CALLING MAYDAY"
                w.say(16, cg, "MAYDAY. %s, THIS IS PENHALE COASTGUARD. RECEIVED MAYDAY. SAY AGAIN YOUR %s. OVER."
                      % (who, " AND ".join(miss)), 2.5)
                note = "The coastguard asks for what was missing - send the whole message again."
            else:
                if d is None:
                    self.distress = d = dict(t0=w.t, nature=self.nature.value, acked=True, voiced=False, cancelled=False)
                    self.distress_utc = w.utc_str()[:5]
                    chk.append((False, "no DSC alert first - it repeats automatically and alerts every station", False))
                d["voiced"] = True
                self.flags["mayday_voiced"] = w.t
                self.flags["mayday_composed_ok"] = w.t
                self._cg_mayday()
        elif kind == "URGENCY":
            if miss:
                who = w.name if "NAME" not in miss else "STATION CALLING PAN PAN"
                w.say(16, cg, "PAN PAN. %s, THIS IS PENHALE COASTGUARD. SAY AGAIN YOUR %s. OVER." % (who, " AND ".join(miss)), 2.5)
            else:
                self.flags["panpan_voiced"] = w.t
                w.say(16, cg, "PAN PAN. %s, THIS IS PENHALE COASTGUARD. RECEIVED PAN PAN. WHAT ASSISTANCE DO YOU "
                      "REQUIRE? STAND BY ON CHANNEL 16. OVER." % w.name, 2.5)
        elif kind == "SAFETY":
            if not miss:
                self.flags["securite_voiced"] = w.t
            note = "No reply expected (OUT). Normally only the SECURITE announcement goes on CH16 - the message " \
                   "itself is read on a working channel."
        elif kind == "CHECK":
            if not miss and ch in (16, 67):
                self.flags["radio_check"] = w.t
                pr = w.los_link(cg, 156.8, pw=self.power_w)["pr"]
                rd = "LOUD AND CLEAR" if pr > -85 else ("READABLE" if pr > -100 else "WEAK BUT READABLE")
                w.say(ch, cg, "%s, PENHALE COASTGUARD. I READ YOU %s.%s OUT." % (
                    w.name, rd, " FOR ROUTINE TRAFFIC USE CHANNEL 67." if ch == 16 else ""), 2.5)
            elif miss:
                note = "The coastguard cannot tell who is asking - give your name and the request."
        elif kind == "CANCEL":
            if not miss:
                self.flags["cancel_voiced"] = w.t
                if d:
                    if not d["cancelled"]:
                        chk.append((False, "stop the DSC repetition first with CANCEL ALERT", False))
                    w.say(16, cg, "%s, THIS IS PENHALE COASTGUARD. YOUR CANCELLATION OF THE FALSE DISTRESS ALERT "
                          "IS RECEIVED. OUT." % w.name, 2.5)
                    self.distress = None
                else:
                    w.say(16, cg, "%s, PENHALE COASTGUARD. WE HOLD NO DISTRESS ALERT FROM YOU. OUT." % w.name, 2.5)
        elif kind == "ACK":
            m = self.last_rx
            target = w.srcs[self.addr.value].name
            if m and w.t - m.t0 < 400 and target == m.src.name and not miss:
                self.flags["mayday_ack_voiced"] = w.t
                w.say(16, m.src, "MAYDAY. %s, THIS IS %s. THANK YOU FOR YOUR ACKNOWLEDGEMENT. FIRE IS IN THE ENGINE "
                      "ROOM, 21 PERSONS ON BOARD. REQUEST YOU STAND BY TO ASSIST AND RELAY TO THE COASTGUARD. OVER."
                      % (w.name, m.src.name), 2.5)
                self.last_rx = None
            elif m and target != m.src.name:
                chk.append((False, "the vessel in distress is %s (set ADDRESS)" % m.src.name, True))
        elif self.work and ch == self.work[0]:
            src = self.work[1]
            self.flags["work_voiced"] = w.t
            w.say(ch, src, "%s, %s. ROGER, ALL COPIED. BACK TO CHANNEL 16. OUT." % (w.name, src.name), 2.0)
            self.work = None
        else:
            self._b2b_reply(dur, True)
        comp.set_debrief(kind, chk, ch, sent, note)

    def _a_released(self, dur):
        w = self.world
        if dur < 1.2:
            return
        self.mon.note("%s  TX %.3f MHz %s" % (w.utc_str(), self.af, self.amode), "[YOU TRANSMITTED FOR %.0f s]" % dur, C["cyan"])
        self.flags["atx_%.3f" % self.af] = w.t
        heli = w.by_name["RESCUE 193"]
        if abs(self.af - 123.1) < 0.004 and heli.active and w.los_link(heli, 123.1)["pr"] > -112:
            w.say(123.1, heli, "%s, RESCUE 193 ON 123 DECIMAL 1. READING YOU FIVE. I HAVE YOUR SART ON "
                  "RADAR, VISUAL IN TWO MINUTES. PREPARE TO RECEIVE THE WINCHMAN ON YOUR PORT QUARTER. OVER." % w.name, 2.0)

    # ----------------------------------------------------------------- audio
    def _radio_audio(self, syn, n, st, vol, sql_open, key, spk=None):
        a = self._radio_raw(syn, n, st, vol, sql_open, key)
        if a is None:
            return None
        return spk(a) if spk is not None else a

    def _radio_raw(self, syn, n, st, vol, sql_open, key):
        w = self.world
        if st.get("open") and st.get("sig") is not None:
            if st["kind"] == "sweep":
                return syn.sweep(key, n) * vol
            sig = st["sig"]
            is_msg = hasattr(sig, "src")
            src = sig.src if is_msg else sig["src"]
            weak = max(0.0, min(1.0, (-104 - st["link"]["pr"]) / 16.0))
            hiss = syn.noise(n) * (0.05 + weak)
            clip = sig.clip() if is_msg else (Msg.speech.get(sig["text"], src.name) if Msg.speech and Msg.speech.ok else None)
            if clip is None:                       # speech not available: old speech-shaped noise
                return (syn.voice(key + src.name, n) * 1.6 + hiss) * vol
            L = len(clip) + SR
            exp = int((w.t - sig.t0) * SR) if is_msg else int(w.t * SR) % L
            cur = st.get("cur")
            if st.get("cur_id") != id(sig) or cur is None or abs(cur - exp) > SR * 0.3:
                cur = exp
            st["cur_id"], st["cur"] = id(sig), (cur + n) if is_msg else (cur + n) % L
            return (chunk(clip, cur, n).real * 1.25 + hiss) * vol
        if sql_open:
            return syn.noise(n) * 0.5 * vol
        return None

    def audio(self, syn, n):
        """Stereo: the marine set's loudspeaker on the left, the air radio's on the right."""
        out = None
        if self.on and not self.tx:
            a = self._radio_audio(syn, n, self.rxs["M"], self.vol.val, self.sql.val < 0.12, "vm", self.spk_m)
            if a is not None:
                if self.dual.on and self.ch != 16:               # dual watch: brief gaps while it samples CH16
                    t = syn._time(n)
                    a = a * ~((t % 2.0) < 0.11)
                out = place(a, -0.5)
        if self.tx and self.txm and self.txm.get("clip") is not None:    # hear yourself in the microphone monitor
            c = self.txm["clip"]
            cur = int((self.world.t - self.txm["t0"]) * SR)
            x = self.spk_tx(chunk(c, cur, n).real * 0.45 * (0.4 + 0.6 * self.vol.val))
            out = place(x, -0.5) if out is None else out + place(x, -0.5)
        if not self.atx:
            a = self._radio_audio(syn, n, self.rxs["A"], self.avol.val, self.asql.val < 0.12, "va", self.spk_a)
            if a is not None:
                out = place(a, 0.5) if out is None else out + place(a, 0.5)
        return out

    def bg_audio(self, syn, n):
        out = None
        if self.world.t < self.burst_until:
            out = syn.fsk("dscv", n, 1200, 1700.0, 800.0) * 0.5
        if self.dsc_alarm:
            out = (0 if out is None else out) + syn.alarm("dscal", n) * 0.35
        return out

    # ------------------------------------------------------------------ draw
    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        if pygame.Rect(790, 298, 800, 170).collidepoint(pos):
            return ("LINK BUDGET: received power = TX power + antenna gains - free-space loss - "
                    "diffraction loss beyond the radio horizon. Horizon (nm) = 2.22 x (sqrt(h1) + sqrt(h2)), heights in metres.")
        if pygame.Rect(790, 476, 800, 210).collidepoint(pos):
            return "RECEIVE MONITOR: a caption of the loudspeaker. '~' marks syllables lost to a weak signal."
        if pygame.Rect(790, 694, 800, 70).collidepoint(pos):
            return ("MESSAGE COMPOSER: the message you will speak. Hold PTT until it has all been spoken (cyan = sent). "
                    "Release early and the rest never goes out. The check of your last transmission appears in the PROMPTER.")
        if pygame.Rect(20, 670, 760, 190).collidepoint(pos):
            return "PROCEDURE PROMPTER: the correct spoken procedure for the current situation, filled in with your ship's details."
        return ""

    def draw(self, s):
        w = self.world
        on = self.on
        ui.panel(s, (20, 54, 760, 300), "MARINE VHF RADIOTELEPHONE  156-162 MHz  FM (G3E)")
        ui.panel(s, (20, 362, 760, 300), "DSC CONTROLLER  CLASS A  -  CH70 WATCH RECEIVER")
        ui.panel(s, (20, 670, 760, 190), "PROCEDURE PROMPTER")
        ui.panel(s, (790, 54, 800, 236), "V/UHF AM-FM TRANSCEIVER  108-470 MHz  (AIR BAND / UHF / ON-BOARD)")
        ui.panel(s, (790, 298, 800, 170), "LINK BUDGET  -  LINE OF SIGHT")
        ui.panel(s, (790, 476, 800, 210), "RECEIVE MONITOR (LOUDSPEAKER CAPTION)")
        ui.panel(s, (790, 694, 800, 166), "MICROPHONE  -  MESSAGE COMPOSER")
        fg = C["lcdfg"]
        # --- marine LCD
        l = ui.lcd(s, (36, 80, 400, 150))
        st = self.rxs["M"]
        if on:
            tx_f, rx_f, dup = vhf_channel(self.ch)
            text(s, "%02d" % self.ch, (l.x + 14, l.y + 2), 76, fg, bold=True)
            text(s, "%.3f MHz" % (tx_f if self.tx else rx_f), (l.x + 130, l.y + 12), 22, fg, bold=True)
            text(s, ("DUPLEX  TX %.3f" % tx_f) if dup else "SIMPLEX", (l.x + 130, l.y + 42), 13, fg)
            text(s, "%d W %s" % (self.power_w, "LOW" if self.power_w < 2 else "HIGH"), (l.x + 130, l.y + 60), 13, fg)
            text(s, VHF_USE.get(self.ch, "PUBLIC CORRESPONDENCE" if dup else "INTERSHIP / PORT"), (l.x + 130, l.y + 78), 11, C["amber"], bold=True)
            pr = st["link"]["pr"] if st.get("link") else -130
            text(s, "SIG", (l.x + 14, l.y + 102), 11, fg, bold=True)
            ui.bar(s, (l.x + 46, l.y + 102, 190, 12), 1.0 if self.tx else (pr + 122) / 60.0,
                   "red" if self.tx else "green")
            text(s, "GPS %s %s  UTC %s" % (fmt_lat(w.lat), fmt_lon(w.lon), w.utc_str()[:5]), (l.x + 14, l.y + 126), 11, fg)
            ui.led(s, (l.x + 300, l.y + 107), "red", self.tx, "TX", 5)
            ui.led(s, (l.x + 340, l.y + 107), "green", bool(st.get("open")), "BUSY", 5)
            if self.dual.on:
                text(s, "DW 16", (l.x + 340, l.y + 60), 12, C["amber"], bold=True)
            if self.scan.on:
                text(s, "SCAN", (l.x + 340, l.y + 42), 12, C["amber"] if int(w.t * 3) % 2 else fg, bold=True)
        elif self.pwr.on:
            text(s, "NO POWER - CHECK BREAKER", (l.x + 14, l.y + 60), 16, (90, 120, 100), bold=True)
        # --- DSC LCD
        l = ui.lcd(s, (36, 390, 400, 256))
        if on:
            text(s, "DSC  MMSI %09d  WATCH CH70" % w.mmsi, (l.x + 10, l.y + 6), 12, fg, bold=True)
            ui.led(s, (l.right - 16, l.y + 14), "red" if self.dsc_alarm else "green",
                   not self.dsc_alarm or int(w.t * 4) % 2 == 0, None, 5)
            pygame.draw.line(s, (40, 80, 60), (l.x + 8, l.y + 26), (l.right - 8, l.y + 26), 1)
            lines = self.dsc_log[-13:]
            if not lines:
                text(s, "NO CALLS RECEIVED", (l.x + 10, l.y + 36), 12, C["dim"])
            for i, (tm, msg, col) in enumerate(lines):
                text(s, tm if not msg.startswith("  ") else "", (l.x + 10, l.y + 34 + i * 16), 11, C["dim"])
                text(s, msg[:44], (l.x + 52, l.y + 34 + i * 16), 11, col, bold=True)
            if self.incoming:
                pygame.draw.rect(s, (10, 60, 80), (l.x + 4, l.bottom - 24, l.w - 8, 20))
                text(s, "INDIVIDUAL CALL - %s - CH%02d - ACCEPT?" % (self.incoming["src"].name[:16], self.incoming["ch"]),
                     (l.centerx, l.bottom - 14), 11, C["white"], bold=True, align="m")
            d = self.distress
            if d and not d["cancelled"]:
                msg = "DISTRESS ACKNOWLEDGED - VOICE MAYDAY ON CH16" if d["acked"] else \
                    "DISTRESS ALERT ACTIVE - NEXT REPEAT %3d s" % (240 - (w.t - d["t0"]) % 240)
                pygame.draw.rect(s, (120, 20, 16), (l.x + 4, l.bottom - 24, l.w - 8, 20))
                text(s, msg, (l.centerx, l.bottom - 14), 11, C["white"], bold=True, align="m")
        text(s, "1. LIFT   2. HOLD 3 s", (516, 492), 9, C["dim"], bold=True, align="c")
        # --- prompter (or the check of your last composed transmission)
        db = self.comp.debrief
        if db and w.t - db["t"] < 60:
            from .composer import KIND_NAME
            nbad = sum(1 for ok, _, _ in db["chk"] if not ok)
            text(s, "TRANSMISSION CHECK  -  %s  -  CH%02d   %s" % (KIND_NAME.get(db["kind"], "?"), db["ch"],
                 "ALL CORRECT" if not nbad else "%d POINT%s TO FIX" % (nbad, "S" if nbad > 1 else "")),
                 (36, 694), 12, C["green"] if not nbad else C["amber"], bold=True)
            items = db["chk"]
            for i, (ok, txt, ess) in enumerate(items):
                col = C["green"] if ok else (C["red"] if ess else C["amber"])
                x, y = (44, 714 + i * 15) if i < 9 else (414, 714 + (i - 9) * 15)
                text(s, ("+ " if ok else ("x " if ess else "- ")) + txt[:56], (x, y), 11, col, bold=not ok)
            if db["note"]:
                ny = 714 + max(0, len(items) - 9) * 15 + 4
                ui.text_block(s, db["note"], (414, ny, 352, 856 - ny), 11, C["cyan"], lh=14, mono=False)
        else:
            ui.text_block(s, self.prompt(), (36, 694, 730, 162), 12, C["text"], lh=16)
        # --- air radio LCD
        l = ui.lcd(s, (806, 80, 300, 110))
        sa = self.rxs["A"]
        text(s, "%07.3f" % self.af, (l.x + 12, l.y + 6), 44, fg, bold=True)
        text(s, "MHz  %s" % self.amode, (l.x + 214, l.y + 14), 14, fg, bold=True)
        band = ("VHF AIR BAND" if self.af < 137 else "VHF MARINE/LAND" if self.af < 225 else
                "UHF MILITARY AIR" if self.af < 400 else "UHF LAND / ON-BOARD")
        text(s, band, (l.x + 12, l.y + 62), 12, C["amber"], bold=True)
        pr = sa["link"]["pr"] if sa.get("link") else -130
        ui.bar(s, (l.x + 12, l.y + 86, 180, 12), 1.0 if self.atx else (pr + 122) / 60.0, "red" if self.atx else "green")
        ui.led(s, (l.x + 214, l.y + 91), "red", self.atx, "TX", 5)
        ui.led(s, (l.x + 254, l.y + 91), "green", bool(sa.get("open")), "RX", 5)
        if self.agrd.idx:
            text(s, "G " + self.agrd.value, (l.x + 214, l.y + 62), 12, C["red"], bold=True)
        # --- link budget
        self._draw_link(s)
        self.mon.draw(s, (806, 500, 768, 176), 12)
        self.comp.draw(s, (806, 721, 768, 40))
        super().draw(s)

    def _draw_link(self, s):
        w = self.world
        x, y = 806, 322
        cols = [0, 96, 300, 372, 452, 528, 604, 690]
        for c, h in zip(cols, ["RADIO", "SOURCE", "DIST nm", "HORIZ nm", "FSPL dB", "RX dBm", "SQL dBm", "STATE"]):
            text(s, h, (x + c, y), 10, C["dim"], bold=True)
        show = None
        for i, (rid, nm) in enumerate((("M", "MARINE VHF"), ("A", "AIR / UHF"))):
            st = self.rxs[rid]
            yy = y + 18 + i * 18
            text(s, nm, (x, yy), 12, C["text"], bold=True)
            if st.get("link"):
                l = st["link"]
                src = st["sig"].src if hasattr(st["sig"], "src") else st["sig"]["src"]
                show = show or (l, src)
                beyond = l["over"] > 0
                vals = [src.name[:22], "%.1f" % l["d"], "%.1f" % l["horizon"], "%.1f" % l["fspl"], "%.0f" % l["pr"],
                        "%.0f" % st["thr"], ("OPEN" if st["open"] else "SQUELCHED") + (" (BEYOND HORIZON)" if beyond else "")]
                for c, v in zip(cols[1:], vals):
                    text(s, v, (x + c, yy), 12, C["green"] if st["open"] else C["amber"])
            else:
                text(s, "no carrier on frequency", (x + cols[1], yy), 12, C["dim"])
                if "thr" in st:
                    text(s, "%.0f" % st["thr"], (x + cols[6], yy), 12, C["dim"])
        # geometry sketch
        gx, gy, gw = 830, 458, 730
        pts = [(gx + gw * i / 40, gy - 16 * (1 - ((i - 20) / 20.0) ** 2)) for i in range(41)]
        pygame.draw.lines(s, C["blue"], False, pts, 2)
        a, b = pts[3], pts[37]
        h1 = 6 + min(14, w.h_ant * 0.5)
        pygame.draw.line(s, C["text"], a, (a[0], a[1] - h1), 2)
        text(s, "OWN ANT %d m" % w.h_ant, (a[0] + 8, a[1] - h1 - 6), 10, C["dim"], bold=True)
        if show:
            l, src = show
            h2 = 6 + min(30, math.sqrt(src.h) * 2.4)
            pygame.draw.line(s, C["text"], b, (b[0], b[1] - h2), 2)
            text(s, "%s %d m" % (src.name[:20], src.h), (b[0] - 8, b[1] - h2 - 6), 10, C["dim"], bold=True, align="r")
            col = C["green"] if l["over"] <= 0 else C["red"]
            pygame.draw.line(s, col, (a[0], a[1] - h1), (b[0], b[1] - h2), 1)
            text(s, "%.1f nm  -  radio horizon %.1f nm  -  %s" % (l["d"], l["horizon"],
                 "LINE OF SIGHT" if l["over"] <= 0 else "%.1f nm BEYOND HORIZON (diffraction loss)" % l["over"]),
                 (gx + gw / 2, 380), 11, col, bold=True, align="c")
        else:
            text(s, "Radio horizon (nm) = 2.22 x ( \u221ah1 + \u221ah2 )   heights in metres", (gx + gw / 2, 380), 11, C["dim"], align="c")

    def prompt(self):
        w = self.world
        pos = "%s %s" % (fmt_lat(w.lat), fmt_lon(w.lon))
        d = self.distress
        if self.incoming:
            return ("INCOMING DSC ROUTINE CALL from %s proposing CH%02d. Press SILENCE / ACCEPT: the radio acknowledges "
                    "'able to comply' and moves to CH%02d, where they will speak first. Reply with PTT (2 s or more, or "
                    "a composed message) and end with OVER or OUT." % (self.incoming["src"].name, self.incoming["ch"], self.incoming["ch"]))
        c = w.b2b_call
        if c and not c["answered"] and w.t - c["t"] < 240:
            return ("%s HAS CALLED YOU ON CH16 about a close-quarters situation. Answer on CH16 (or 13): give your "
                    "intentions - and act on the Collision Regulations: VHF agreements do not replace them. If she is "
                    "on your starboard side you are the give-way vessel: alter boldly to starboard. Then hold PTT 2 s "
                    "to reply." % c["src"].name)
        if d and d["cancelled"]:
            return ("FALSE ALERT CANCELLATION - hold PTT on CH16 and say:\n"
                    "ALL STATIONS, ALL STATIONS, ALL STATIONS. THIS IS %s, %s, %s, CALL SIGN %s, MMSI %d, "
                    "POSITION %s. CANCEL MY DISTRESS ALERT OF %s UTC. OVER." % (w.name, w.name, w.name, w.cs, w.mmsi, pos, w.utc_str()[:5]))
        if d:
            head = ("DSC ALERT ACKNOWLEDGED. " if d["acked"] else "DSC ALERT SENT - do not wait for the ack. ")
            if d["voiced"]:
                return ("MAYDAY CALL AND MESSAGE SENT. Keep watch on CH16, follow the coastguard's "
                        "instructions, prepare SART and EPIRB (see COSPAS-SARSAT tab). Use the "
                        "air radio on 123.100 MHz for the helicopter.")
            return (head + "Hold PTT on CH16 (4 s or more) and say:\n"
                    "MAYDAY, MAYDAY, MAYDAY. THIS IS %s, %s, %s. CALL SIGN %s, MMSI %d.\n"
                    "MAYDAY %s. MY POSITION IS %s. %s. I REQUIRE IMMEDIATE ASSISTANCE. "
                    "(number of persons on board, any other information). OVER."
                    % (w.name, w.name, w.name, w.cs, w.mmsi, w.name, pos, d["nature"]))
        m = self.last_rx
        if self.dsc_alarm and m:
            return ("DSC %s RECEIVED. 1) Silence the alarm. 2) Listen on CH16 for the voice message - "
                    "do NOT acknowledge by DSC (the coast station does that). 3) Log it. 4) If no "
                    "coast station responds and you can assist, acknowledge BY VOICE on CH16:\n"
                    "MAYDAY. %s (x3), THIS IS %s (x3). RECEIVED MAYDAY." % (m.dsc["cat"], m.src.name, w.name))
        if self.work:
            return ("DSC individual call acknowledged. Both radios are now on CH%02d. Hold PTT and pass "
                    "your message to %s, ending with OVER." % (self.work[0], self.work[1].name))
        return ("COMPOSER: e.g. MAYDAY x3, THIS IS, name x3, CALL SIGN, MMSI, MAYDAY, name, POSITION, NATURE, "
                "ASSISTANCE, POB, OVER - then hold PTT until it is all spoken. "
                "ROUTINE: call a known station with a DSC INDIVIDUAL CALL (pick ADDRESS and WORK CH) "
                "instead of hailing on CH16. RADIO CHECK: hold PTT on CH16 for 3 s.\n"
                "DISTRESS (grave and imminent danger only): select NATURE if time allows, lift the "
                "cover, hold DISTRESS for 3 s. The radio sends the alert on CH70 and moves to CH16. "
                "Then speak the MAYDAY call and message. Priorities: MAYDAY (distress) > PAN PAN "
                "(urgency) > SECURITE (safety) > routine.")
