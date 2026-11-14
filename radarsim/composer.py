"""VHF message composer.

Build a radiotelephone message from the standard phrases, hold the PTT and
it is spoken in your own ship's voice. Release the PTT before the end and
only the part already spoken goes out. When you release, the message is
checked against the correct format for its kind (MAYDAY, PAN PAN, SECURITE,
radio check, false-alert cancellation, MAYDAY acknowledgement) and the
receiving station answers what it actually heard - including asking you to
say again whatever you left out.
"""
import pygame
from . import ui
from .ui import C, text, Button
from .world import CPS, Msg, fmt_lat, fmt_lon

PHON = {"A": "ALFA", "B": "BRAVO", "C": "CHARLIE", "D": "DELTA", "E": "ECHO", "F": "FOXTROT", "G": "GOLF",
        "H": "HOTEL", "I": "INDIA", "J": "JULIETT", "K": "KILO", "L": "LIMA", "M": "MIKE", "N": "NOVEMBER",
        "O": "OSCAR", "P": "PAPA", "Q": "QUEBEC", "R": "ROMEO", "S": "SIERRA", "T": "TANGO", "U": "UNIFORM",
        "V": "VICTOR", "W": "WHISKEY", "X": "X-RAY", "Y": "YANKEE", "Z": "ZULU"}
OWN_VOICE = "MV TRAINER"
CHIPS = [["MAYDAY", "PANPAN", "SECURITE", "ALLST", "THISIS", "NAME", "CALLSIGN"],
         ["MMSI", "STATION", "POSITION", "NATURE", "HAZARD", "ASSIST", "POB"],
         ["RCVD", "RCHECK", "CANCEL", "OVER", "OUT", "UNDO", "CLEAR"]]
KIND_NAME = {"DISTRESS": "DISTRESS CALL AND MESSAGE (MAYDAY)", "URGENCY": "URGENCY CALL (PAN PAN)",
             "SAFETY": "SAFETY CALL (SECURITE)", "CHECK": "RADIO CHECK", "CANCEL": "FALSE ALERT CANCELLATION",
             "ACK": "ACKNOWLEDGEMENT OF A MAYDAY", "ROUTINE": "ROUTINE CALL"}


def phonetic(s):
    return " ".join(PHON.get(c, c) for c in s.upper() if c.isalnum())


def pos_words(lat, lon):
    """Position in the words you would speak: 49 DEGREES 50 DECIMAL 0 MINUTES NORTH ..."""
    def part(v, pos, neg, wd):
        d = abs(v)
        deg = int(d)
        m10 = int(round((d - deg) * 600))
        if m10 >= 600:
            deg, m10 = deg + 1, 0
        return "%0*d DEGREES %02d DECIMAL %d MINUTES %s" % (wd, deg, m10 // 10, m10 % 10, pos if v >= 0 else neg)
    return "%s, %s" % (part(lat, "NORTH", "SOUTH", 2), part(lon, "EAST", "WEST", 3))


class Composer:
    def __init__(self, st, x0=806, y0=768):
        self.st = st
        self.items = []                     # (key, text)
        self.txm, self.debrief = None, None
        self._req, self._chg = None, 0.0
        self.btn = {}
        for j, row in enumerate(CHIPS):
            for i, k in enumerate(row):
                b = st.add(Button((x0 + i * 110, y0 + j * 30, 104, 26), k, "", size=9,
                                  color="red" if k in ("MAYDAY", "PANPAN", "SECURITE") else "amber"))
                b.on_click = (lambda kk: (lambda _b: self.add(kk)))(k)
                b.snd = "key"
                self.btn[k] = b

    # ------------------------------------------------------------ phrases
    def phrase(self, k):
        st, w = self.st, self.st.world
        if k == "MAYDAY":
            return "MAYDAY,"
        if k == "PANPAN":
            return "PAN PAN,"
        if k == "SECURITE":
            return "SECURITE,"
        if k == "ALLST":
            return "ALL STATIONS,"
        if k == "THISIS":
            return "THIS IS"
        if k == "NAME":
            return w.name + ","
        if k == "CALLSIGN":
            return "CALL SIGN %s," % phonetic(w.cs)
        if k == "MMSI":
            return "MMSI %09d," % w.mmsi
        if k == "STATION":
            return st.world.srcs[st.addr.value].name + ","
        if k == "POSITION":
            return "MY POSITION IS %s." % pos_words(w.lat, w.lon)
        if k == "NATURE":
            n = st.nature.value
            return ("%s." % n) if n != "UNDESIGNATED" else "I AM IN DISTRESS."
        if k == "HAZARD":
            return "NAVIGATIONAL WARNING. LARGE CONTAINER ADRIFT, DANGER TO SHIPPING."
        if k == "ASSIST":
            return "I REQUIRE IMMEDIATE ASSISTANCE."
        if k == "POB":
            return "%d PERSONS ON BOARD." % w.pob
        if k == "RCVD":
            return "RECEIVED MAYDAY."
        if k == "RCHECK":
            return "RADIO CHECK ON CHANNEL %d." % st.ch
        if k == "CANCEL":
            d = st.distress
            tm = st.distress_utc if (d and getattr(st, "distress_utc", None)) else w.utc_str()[:5]
            return "PLEASE CANCEL MY DISTRESS ALERT OF %s UTC." % tm.replace(":", "")
        if k == "OVER":
            return "OVER."
        if k == "OUT":
            return "OUT."
        return ""

    def label(self, k):
        st, w = self.st, self.st.world
        return {"MAYDAY": "MAYDAY", "PANPAN": "PAN PAN", "SECURITE": "SECURITE", "ALLST": "ALL STATIONS",
                "THISIS": "THIS IS", "NAME": w.name, "CALLSIGN": "CALL SIGN", "MMSI": "MMSI",
                "STATION": "TO: " + st.world.srcs[st.addr.value].name.replace("PENHALE COASTGUARD", "PENHALE CG")[:11],
                "POSITION": "POSITION", "NATURE": "NATURE", "HAZARD": "HAZARD", "ASSIST": "ASSISTANCE",
                "POB": "%d ON BOARD" % w.pob, "RCVD": "RCVD MAYDAY", "RCHECK": "RADIO CHECK",
                "CANCEL": "CANCEL ALERT", "OVER": "OVER", "OUT": "OUT", "UNDO": "UNDO", "CLEAR": "CLEAR"}[k]

    def refresh(self):
        for k, b in self.btn.items():
            b.label = self.label(k)
            if k in ("UNDO", "CLEAR"):
                b.tip = "Remove the last phrase." if k == "UNDO" else "Clear the whole message."
            else:
                b.tip = "MESSAGE COMPOSER: adds '%s'" % self.phrase(k)
                if k == "STATION":
                    b.tip += "  (pick the station with the ADDRESS selector on the DSC panel)"
                if k == "NATURE":
                    b.tip += "  (set with NATURE OF DISTRESS on the DSC panel)"

    # ------------------------------------------------------------ editing
    def add(self, k):
        if self.txm:
            return
        if k == "UNDO":
            if self.items:
                self.items.pop()
        elif k == "CLEAR":
            self.items = []
        else:
            self.items.append((k, self.phrase(k)))
        self._chg = self.st.world.t
        self.debrief = None if k == "CLEAR" else self.debrief

    @property
    def keys(self):
        return [k for k, _ in self.items]

    def text(self):
        return " ".join(t for _, t in self.items)

    def update(self, t):
        txt = self.text()
        if txt and txt != self._req and t - self._chg > 0.35 and Msg.speech is not None:
            self._req = txt
            Msg.speech.request(txt, OWN_VOICE)
        if self.txm and self.txm["clip"] is None and Msg.speech is not None and Msg.speech.ok:
            c = Msg.speech.get(self.txm["text"], OWN_VOICE)
            if c is not None:
                self.txm["clip"] = c
                self.txm["dur"] = len(c) / 22050.0 + 0.3

    # ------------------------------------------------------- transmission
    def begin(self, t):
        txt = self.text()
        if not txt:
            return None
        clip = Msg.speech.get(txt, OWN_VOICE) if (Msg.speech is not None and Msg.speech.ok) else None
        ends, n = [], 0
        for _, tt in self.items:
            n += len(tt) + 1
            ends.append(n)
        dur = (len(clip) / 22050.0 + 0.3) if clip is not None else len(txt) / CPS + 0.5
        self.txm = dict(text=txt, keys=self.keys, ends=ends, t0=t, clip=clip, dur=dur)
        return self.txm

    def progress(self, t):
        m = self.txm
        if not m:
            return 0.0
        return max(0.0, min(1.0, (t - m["t0"]) / max(0.5, m["dur"] - 0.25)))

    def finish(self, t):
        m = self.txm
        self.txm = None
        if not m:
            return None
        f = (t - m["t0"]) / max(0.5, m["dur"] - 0.25)
        n = f * len(m["text"])
        keys = [k for k, e in zip(m["keys"], m["ends"]) if e <= n + 3]
        return dict(keys=keys, all=m["keys"], truncated=len(keys) < len(m["keys"]),
                    text=m["text"][:int(min(len(m["text"]), n))], full=m["text"])

    # ---------------------------------------------------------- checking
    @staticmethod
    def classify(keys):
        if not keys:
            return None
        if "CANCEL" in keys:
            return "CANCEL"
        if keys[0] == "MAYDAY":
            return "ACK" if "RCVD" in keys else "DISTRESS"
        if keys[0] == "PANPAN":
            return "URGENCY"
        if keys[0] == "SECURITE":
            return "SAFETY"
        if "RCHECK" in keys:
            return "CHECK"
        if "RCVD" in keys:
            return "ACK"
        return "ROUTINE"

    def evaluate(self, sent):
        """(kind, checks [(ok, text, essential)], missing essentials [words])"""
        keys = sent["keys"]
        allk = sent["all"]
        kind = self.classify(allk)
        st = self.st

        def lead(k):
            n = 0
            for x in keys:
                if x != k:
                    break
                n += 1
            return n

        def cnt(k):
            return keys.count(k)

        def has(k):
            return k in keys

        nat_ok = has("NATURE") and st.nature.value != "UNDESIGNATED"
        chk = []
        if kind == "DISTRESS":
            chk = [(lead("MAYDAY") == 3, "distress signal MAYDAY spoken three times", False),
                   (has("THISIS"), "'THIS IS' before your identity", False),
                   (has("NAME"), "ship's name", True),
                   (cnt("NAME") >= 3, "name spoken three times in the call", False),
                   (has("CALLSIGN") or has("MMSI"), "call sign and/or MMSI", False),
                   (cnt("MAYDAY") >= 4, "message opened with MAYDAY + name again", False),
                   (has("POSITION"), "position", True),
                   (nat_ok, "nature of distress (set NATURE, not UNDESIGNATED)", True),
                   (has("ASSIST"), "assistance required", False),
                   (has("POB"), "persons on board", False),
                   (bool(keys) and keys[-1] == "OVER", "ended with OVER", False)]
        elif kind == "URGENCY":
            chk = [(lead("PANPAN") == 3, "PAN PAN spoken three times", False),
                   (has("ALLST") or has("STATION"), "addressed to ALL STATIONS (or one station)", False),
                   (has("THISIS"), "'THIS IS'", False),
                   (has("NAME"), "ship's name", True),
                   (has("POSITION"), "position", True),
                   (has("NATURE"), "nature of the urgency", True),
                   (has("ASSIST"), "assistance required", False),
                   (bool(keys) and keys[-1] == "OVER", "ended with OVER", False)]
        elif kind == "SAFETY":
            chk = [(lead("SECURITE") == 3, "SECURITE spoken three times", False),
                   (cnt("ALLST") >= 1, "ALL STATIONS (three times is correct)", False),
                   (has("THISIS"), "'THIS IS'", False),
                   (has("NAME"), "ship's name", True),
                   (has("HAZARD"), "the safety message itself", True),
                   (has("POSITION"), "position of the hazard", False),
                   (bool(keys) and keys[-1] == "OUT", "ended with OUT - no reply expected", False)]
        elif kind == "CHECK":
            chk = [(bool(keys) and keys[0] == "STATION", "called the station first", False),
                   (has("THISIS"), "'THIS IS'", False),
                   (has("NAME"), "ship's name", True),
                   (has("RCHECK"), "asked for a radio check", True),
                   (bool(keys) and keys[-1] == "OVER", "ended with OVER", False)]
        elif kind == "CANCEL":
            chk = [(cnt("ALLST") >= 3, "ALL STATIONS three times", False),
                   (has("THISIS"), "'THIS IS'", False),
                   (has("NAME"), "ship's name", True),
                   (has("CALLSIGN") or has("MMSI"), "call sign and MMSI", False),
                   (has("POSITION"), "position", False),
                   (has("CANCEL"), "'cancel my distress alert of ... UTC'", True),
                   (bool(keys) and keys[-1] == "OVER", "ended with OVER", False)]
        elif kind == "ACK":
            chk = [(bool(keys) and keys[0] == "MAYDAY", "opened with MAYDAY", False),
                   (has("STATION"), "name of the vessel in distress", True),
                   (has("THISIS"), "'THIS IS'", False),
                   (has("NAME"), "your ship's name", True),
                   (has("RCVD"), "RECEIVED MAYDAY", True)]
        else:
            chk = [(has("STATION") or has("ALLST"), "called a station", False),
                   (has("THISIS"), "'THIS IS'", False),
                   (has("NAME"), "ship's name", True),
                   (bool(keys) and keys[-1] in ("OVER", "OUT"), "ended with OVER or OUT", False)]
        if sent["truncated"]:
            chk.append((False, "PTT released early: last %d phrase%s never sent"
                        % (len(allk) - len(keys), "s" if len(allk) - len(keys) > 1 else ""), False))
        miss = []
        for ok, txt, ess in chk:
            if ess and not ok:
                if "name" in txt and "vessel" not in txt:
                    miss.append("NAME")
                elif "position" in txt:
                    miss.append("POSITION")
                elif "nature" in txt:
                    miss.append("NATURE OF DISTRESS" if kind == "DISTRESS" else "NATURE OF YOUR URGENCY")
                elif "safety message" in txt:
                    miss.append("SAFETY MESSAGE")
                elif "radio check" in txt:
                    miss.append("REQUEST")
                elif "vessel in distress" in txt:
                    miss.append("NAME OF THE VESSEL IN DISTRESS")
                elif "cancel" in txt:
                    miss.append("CANCELLATION")
                elif "RECEIVED" in txt:
                    miss.append("ACKNOWLEDGEMENT")
        return kind, chk, miss

    def set_debrief(self, kind, chk, ch, sent, note=""):
        self.debrief = dict(t=self.st.world.t, kind=kind, chk=chk, ch=ch, note=note, text=sent["text"])
        for ok, txt, ess in chk:
            if not ok and (ess or txt.startswith("PTT released")):
                self.st.mistake("%s: %s missing or wrong" % (KIND_NAME.get(kind, kind).split(" (")[0], txt))

    # --------------------------------------------------------------- draw
    def draw(self, s, rect):
        st, w = self.st, self.st.world
        l = ui.lcd(s, rect)
        txt = self.text()
        m = self.txm
        if not txt:
            ui.text_block(s, "Build a message with the phrase keys below, then hold PTT until it has all been spoken. "
                             "Empty = PTT just keys the transmitter (as before).", (l.x + 8, l.y + 5, l.w - 16, l.h), 11,
                          (70, 120, 90), lh=14, mono=False)
            return
        rows = ui.wrap(txt, 11, l.w - 120)
        if m:
            n = int(self.progress(w.t) * len(txt))
            text(s, "TX %4.1f/%4.1f s" % (min(w.t - m["t0"], m["dur"]), m["dur"]), (l.right - 8, l.y + 4), 11,
                 C["red"], bold=True, align="r")
        else:
            n = -1
            text(s, "~%d s" % (len(txt) / CPS), (l.right - 8, l.y + 4), 11, C["dim"], bold=True, align="r")
        # show the last two lines, the part already transmitted in cyan
        start = sum(len(r) + 1 for r in rows[:-2]) if len(rows) > 2 else 0
        for i, row in enumerate(rows[-2:]):
            y = l.y + 5 + i * 17
            if n < 0:
                text(s, row, (l.x + 8, y), 11, C["lcdfg"])
            else:
                done = max(0, min(len(row), n - start))
                if done:
                    text(s, row[:done], (l.x + 8, y), 11, C["cyan"], bold=True)
                if done < len(row):
                    fw = ui.font(11).size(row[:done])[0]
                    text(s, row[done:], (l.x + 8 + fw, y), 11, (80, 110, 90))
            start += len(row) + 1
