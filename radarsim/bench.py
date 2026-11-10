"""Circuits bench: signal-flow block diagrams of the radar transceiver and
the SSB transceiver with an oscilloscope/spectrum probe on every stage, and
a fault-finding game. Faults injected here also break the RADAR and MF/HF
stations, so you can go from operator symptom to faulty stage.
"""
import math
import numpy as np
import pygame
from . import ui
from .ui import C, text, Selector, Button, Station
from .radar import PULSES

BW, BH = 130, 56
N = 438

RADAR_BLK = [
    ("psu", "POWER SUPPLY", 40, 150, "Converts ship's mains to the LV rails and the HV for the modulator. Every stage depends on it. Healthy: steady DC with a little ripple."),
    ("trig", "TRIGGER GEN (PRF)", 215, 150, "Master timer. Emits one sharp trigger per transmitted pulse at the pulse repetition frequency (500-2000 Hz). It fires the modulator and starts the display timebase and the STC ramp together. Inhibited in STAND-BY."),
    ("mod", "MODULATOR", 390, 150, "A pulse-forming network charged to HV and discharged by a thyristor/thyratron through the pulse transformer. Produces a flat-topped negative pulse of about 12 kV on the magnetron cathode, lasting exactly the pulse length."),
    ("mag", "MAGNETRON", 565, 150, "Cross-field oscillator. For the duration of the modulator pulse it oscillates at about 9410 MHz (X) or 3050 MHz (S) with 25-30 kW peak power. Its frequency drifts with temperature - that is why the receiver needs tuning/AFC."),
    ("dup", "DUPLEXER (CIRCULATOR)", 740, 150, "Lets one antenna be shared: the transmitter pulse is routed to the scanner, and returning echoes are routed to the receiver. Scope here shows the full-power RF burst going to the antenna."),
    ("ant", "SCANNER + ROTARY JOINT", 915, 150, "Slotted waveguide array turning at 24 RPM. Forms the narrow horizontal beam (1.2 deg X / 1.9 deg S). Also sends the heading marker and bearing pulses to the display. If the motor stops, the picture is one stationary spoke."),
    ("trl", "TR LIMITER", 740, 300, "Protects the mixer diode. During the transmitted pulse it limits the leakage to a few milliwatts; afterwards it recovers within microseconds and passes the microvolt-level echoes. A failed limiter lets the mixer be damaged: weak echoes vanish."),
    ("mix", "MIXER", 565, 300, "Balanced mixer (MIC front end). Multiplies the echoes by the local oscillator and outputs the difference frequency, the 60 MHz IF. Receiver noise originates here - no mixer output means no 'grass' at any gain."),
    ("ifa", "IF AMPLIFIER 60 MHz", 390, 300, "Provides most of the receiver gain (about 100 dB) in a logarithmic chain with bandwidth matched to the pulse length. GAIN sets its gain, STC reduces it just after each pulse. Scope shows amplified 60 MHz bursts and noise."),
    ("det", "DETECTOR", 215, 300, "Rectifies the IF and removes the 60 MHz, leaving the pulse envelopes: this is raw video. Main bang at the left, then echoes in order of range."),
    ("vid", "VIDEO AMP + FTC", 40, 300, "Amplifies and limits the video for the display. The FTC (rain) differentiator sits here. When the radar is transmitting this test point shows the LIVE video along the EBL, exactly as the A-scan on the RADAR tab."),
    ("lo", "LOCAL OSCILLATOR", 565, 450, "Low-power Gunn or DRO oscillator running 60 MHz away from the magnetron. TUNE and the AFC voltage steer its frequency. Dead LO = no IF at all: no noise, no echoes, tuning bar at zero."),
    ("afc", "AFC DISCRIMINATOR", 390, 450, "Samples the IF during the main bang, measures how far it is from 60 MHz and returns a DC correction to the local oscillator. If it fails, AFC has no effect and the picture fades as the magnetron drifts; manual TUNE still works."),
    ("stc", "STC (SWEPT GAIN)", 215, 450, "Started by each trigger. Generates a control voltage that cuts IF gain hard at zero range and decays exponentially, so nearby sea clutter is suppressed while distant targets keep full gain. Amplitude follows the SEA knob."),
    ("dsp", "DISPLAY PROCESSOR", 40, 450, "Digitises the video on each trigger, converts range/bearing to screen coordinates (scan conversion), adds rings, EBL/VRM, heading line and ARPA. Needs video, trigger and antenna bearing."),
]
RADAR_WIRES = [
    ("psu", [(170, 178), (215, 178)]), ("trig", [(345, 178), (390, 178)]), ("mod", [(520, 178), (565, 178)]),
    ("mag", [(695, 178), (740, 178)]), ("dup", [(870, 178), (915, 178)]), ("dup", [(805, 206), (805, 300)]),
    ("trl", [(740, 328), (695, 328)]), ("mix", [(565, 328), (520, 328)]), ("ifa", [(390, 328), (345, 328)]),
    ("det", [(215, 328), (170, 328)]), ("vid", [(105, 356), (105, 450)]), ("lo", [(630, 450), (630, 356)]),
    ("ifa", [(455, 356), (455, 450)]), ("afc", [(520, 478), (565, 478)]),
    ("trig", [(330, 206), (330, 226), (367, 226), (367, 430), (300, 430), (300, 450)]),
    ("stc", [(345, 478), (378, 478), (378, 342), (390, 342)]),
    ("trig", [(240, 206), (240, 238), (26, 238), (26, 478), (40, 478)]),
    ("ant", [(980, 206), (980, 540), (105, 540), (105, 506)]),
]
RADAR_SYMPT = {
    "psu": "Display completely dead. No indications anywhere.",
    "trig": "Display lit and rings present, but no picture is painted and the MAG I bar reads zero in TX.",
    "mod": "Receiver noise ('grass') is normal with GAIN advanced, but there are no echoes and no main bang. MAG I reads zero.",
    "mag": "Receiver noise is normal but there are no echoes at all and no main bang. MAG I reads zero.",
    "dup": "No echoes and no noise on the display in TX.",
    "ant": "The picture is a single stationary spoke - the sweep is not rotating.",
    "trl": "Noise is normal and TUNE peaks, but only very large nearby echoes show; all weak targets have vanished.",
    "mix": "Blank picture: no noise at any GAIN setting, no echoes, TUNE bar at zero.",
    "lo": "Blank picture: no noise at any GAIN setting, no echoes, TUNE bar at zero.",
    "ifa": "Blank picture: no noise at any GAIN setting. TUNE bar at zero.",
    "det": "Blank picture: no noise and no echoes although the transmitter is clearly working.",
    "vid": "Blank picture: no noise and no echoes although the transmitter is clearly working.",
    "afc": "With AFC selected the picture slowly fades and the TUNE bar sags; switching AFC off and tuning manually restores it.",
    "stc": "The SEA anti-clutter control has no effect - clutter stays whatever its setting.",
    "dsp": "Display is dark although the transceiver status shows TX and MAG I is normal.",
}

SSB_BLK = [
    ("mic", "MICROPHONE", 40, 150, "Converts speech to a few millivolts of audio. Only live while the PTT is pressed."),
    ("afa", "MIC AMP + ALC", 215, 150, "Amplifies and band-limits speech to 300-2700 Hz. Automatic level control stops over-driving, which would cause splatter on adjacent channels."),
    ("bal", "BALANCED MODULATOR", 390, 150, "Multiplies audio by the carrier. Output is double sideband with the CARRIER SUPPRESSED: two mirror-image sidebands and no energy at the carrier frequency. Look at SPECTRUM view."),
    ("sbf", "SIDEBAND FILTER (USB)", 565, 150, "Crystal filter 2.4 kHz wide that passes only the upper sideband. A single tone in gives a single steady RF carrier out - the definition of J3E single sideband."),
    ("txm", "TX MIXER", 740, 150, "Mixes the SSB signal at the IF with the synthesizer to translate it to the operating frequency (e.g. 8291 kHz)."),
    ("drv", "BAND-PASS + DRIVER", 915, 150, "Removes the unwanted mixer product and raises the level to a few watts to drive the power amplifier."),
    ("cosc", "CARRIER OSC / BFO", 390, 300, "Crystal oscillator at the IF. Feeds the balanced modulator on transmit and, as the beat-frequency oscillator, re-inserts the missing carrier in the product detector on receive. If it fails both TX and RX audio die."),
    ("synth", "SYNTHESIZER (PLL)", 740, 300, "Phase-locked loop that generates the injection frequency in 10 Hz steps from a reference crystal. If the loop loses lock the set shows UNLOCK and neither transmits nor receives."),
    ("pa", "POWER AMP + LPF", 915, 300, "Linear class-AB amplifier to 400 W PEP followed by low-pass filters that remove harmonics. Must be linear, or the two-tone envelope flat-tops and splatters."),
    ("atu", "ANTENNA TUNER", 915, 450, "Switched L-network at the antenna base. Transforms the whip's impedance to 50 ohm on each frequency. Faulty or untuned = high SWR, PA folds back, weak receive."),
    ("rxm", "RF AMP + RX MIXER", 740, 450, "Preselector, RF amplifier and mixer converting the wanted signal to the IF. The S-meter and spectrum scope are fed from here."),
    ("ifl", "IF FILTER + AGC AMP", 565, 450, "The 2.4 kHz crystal filter gives the selectivity; the AGC amplifier holds the level constant from S1 to S9+40."),
    ("pdet", "PRODUCT DETECTOR", 390, 450, "Mixes the IF with the BFO to translate the sideband back to audio. If the BFO is off-frequency by 100 Hz, every voice component comes out 100 Hz wrong - the reason for the clarifier."),
    ("afo", "AF AMPLIFIER", 215, 450, "Audio power amplifier with the volume control."),
    ("spk", "LOUDSPEAKER", 40, 450, "End of the receive chain."),
]
SSB_WIRES = [
    ("mic", [(170, 178), (215, 178)]), ("afa", [(345, 178), (390, 178)]), ("bal", [(520, 178), (565, 178)]),
    ("sbf", [(695, 178), (740, 178)]), ("txm", [(870, 178), (915, 178)]), ("cosc", [(455, 300), (455, 206)]),
    ("cosc", [(455, 356), (455, 450)]), ("synth", [(805, 300), (805, 206)]), ("synth", [(805, 356), (805, 450)]),
    ("drv", [(980, 206), (980, 300)]), ("pa", [(980, 356), (980, 450)]), ("atu", [(915, 478), (870, 478)]),
    ("rxm", [(740, 478), (695, 478)]), ("ifl", [(565, 478), (520, 478)]), ("pdet", [(390, 478), (345, 478)]),
    ("afo", [(215, 478), (170, 478)]),
]
SSB_SYMPT = {
    "mic": "Receive is normal. On PTT there is no RF output (PO meter stays at zero).",
    "afa": "Receive is normal. On PTT there is no RF output (PO meter stays at zero).",
    "bal": "Receive is normal. On PTT there is no RF output (PO meter stays at zero).",
    "sbf": "Receive is normal. On PTT there is no RF output (PO meter stays at zero).",
    "txm": "Receive is normal. On PTT there is no RF output (PO meter stays at zero).",
    "drv": "Receive is normal. On PTT there is no RF output (PO meter stays at zero).",
    "pa": "Receive is normal. On PTT there is no RF output (PO meter stays at zero).",
    "cosc": "No RF output on PTT, and the receiver is silent although the S-meter and spectrum scope still show signals.",
    "synth": "Frequency display shows UNLOCK. No transmit, no receive.",
    "atu": "SWR pegs high and TUNE never completes; received signals have disappeared.",
    "rxm": "Receiver completely dead: S-meter at zero, spectrum scope blank. Transmit is normal.",
    "ifl": "Receiver dead: S-meter at zero and no audio. Transmit is normal.",
    "pdet": "S-meter and spectrum scope show signals normally but there is no audio. Transmit is normal.",
    "afo": "S-meter and spectrum scope show signals normally but there is no audio. Transmit is normal.",
    "spk": "S-meter and spectrum scope show signals normally but there is no audio. Transmit is normal.",
}


class Bench(Station):
    name = "CIRCUITS"
    hint = ("Click any block to put the scope probe on its output. INJECT a fault, read the symptom, "
            "trace the signal stage by stage, select the first dead stage and DECLARE it.")

    def __init__(self, app):
        super().__init__(app)
        self.rng = np.random.default_rng(21)
        self.sel = {"R": "mag", "S": "bal"}
        self.fault = {"R": None, "S": None}
        self.probes, self.score, self.result = 0, 0, ""
        self.flags = {}
        self.b_r = self.add(Button((40, 84, 190, 32), "RADAR TRANSCEIVER", "Show the marine radar transmitter/receiver signal flow.", toggle=True, on=True))
        self.b_s = self.add(Button((238, 84, 190, 32), "SSB TRANSCEIVER", "Show the MF/HF single-sideband transceiver signal flow.", toggle=True))
        self.b_key = self.add(Button((470, 84, 110, 32), "KEY TX", "SSB bench: key the transmitter (same as holding PTT) so the transmit chain carries signal. Unkeyed, the receive chain is live.", toggle=True, color="red"))
        self.sig = self.add(Selector(650, 104, 14, "", ["1 kHz TONE", "TWO-TONE", "VOICE"], 0,
            "SSB bench audio test signal. A single tone shows SSB as one steady carrier; the two-tone test (700 + 1900 Hz) is the standard linearity and PEP measurement."))
        self.b_spec = self.add(Button((1460, 318, 114, 26), "SPECTRUM", "Scope display: time domain, or frequency spectrum (FFT of the same signal).", toggle=True, size=10))
        self.b_ref = self.add(Button((1340, 318, 114, 26), "REFERENCE", "Overlay the healthy 'service manual' waveform in grey for comparison.", toggle=True, on=True, size=10))
        self.b_inj = self.add(Button((40, 650, 200, 40), "INJECT RANDOM FAULT", "Instructor: break one stage of the equipment shown. The RADAR / MF-HF station is affected too.", color="red"))
        self.b_dec = self.add(Button((40, 698, 200, 40), "DECLARE SELECTED\nBLOCK FAULTY", "Commit to your diagnosis: the selected block is the faulty stage.", color="green", size=10))
        self.b_fix = self.add(Button((40, 746, 200, 40), "REPAIR ALL / GIVE UP", "Clear every fault (reveals the answer)."))

    @property
    def which(self):
        return "R" if self.b_r.on else "S"

    @property
    def blocks(self):
        return RADAR_BLK if self.which == "R" else SSB_BLK

    @property
    def health(self):
        return self.world.rh if self.which == "R" else self.world.hh

    # ---------------------------------------------------------- signal flow
    def alive_radar(self, h):
        tx = self.app.radar.transmitting
        a = {"psu": h["psu"]}
        a["trig"] = a["psu"] and h["trig"] and tx
        a["mod"] = a["trig"] and h["mod"]
        a["mag"] = a["mod"] and h["mag"]
        a["dup"] = a["mag"] and h["dup"]
        a["ant"] = a["dup"]
        a["echo"] = a["dup"] and h["trl"]
        a["trl"] = a["psu"] and h["dup"]
        a["lo"] = a["psu"] and h["lo"]
        a["mix"] = a["lo"] and h["mix"]
        a["ifa"] = a["mix"] and h["ifa"]
        a["det"] = a["ifa"] and h["det"]
        a["vid"] = a["det"] and h["vid"]
        a["dsp"] = a["psu"] and h["dsp"]
        a["afc"] = a["ifa"] and h["afc"] and a["mag"]
        a["stc"] = a["trig"] and h["stc"]
        return a

    def alive_ssb(self, h):
        key = self.b_key.on or self.app.hf.tx
        a = {"key": key}
        a["mic"] = key and h["mic"]
        a["afa"] = a["mic"] and h["afa"]
        a["cosc"] = h["cosc"]
        a["bal"] = a["afa"] and a["cosc"] and h["bal"]
        a["sbf"] = a["bal"] and h["sbf"]
        a["synth"] = h["synth"]
        a["txm"] = a["sbf"] and a["synth"] and h["txm"]
        a["drv"] = a["txm"] and h["drv"]
        a["pa"] = a["drv"] and h["pa"]
        a["atu"] = h["atu"] and (a["pa"] if key else True)
        a["rxm"] = (not key) and h["atu"] and h["rxm"] and a["synth"]
        a["ifl"] = a["rxm"] and h["ifl"]
        a["pdet"] = a["ifl"] and a["cosc"] and h["pdet"]
        a["afo"] = a["pdet"] and h["afo"]
        a["spk"] = a["afo"] and h["spk"]
        return a

    def wave_radar(self, bid, a):
        rad = self.app.radar
        x = np.linspace(0, 2, N, endpoint=False)
        ph = x % 1
        pw = {"SHORT": 0.012, "MEDIUM": 0.03, "LONG": 0.07}[rad.pulse.value]
        pulse = (ph < pw).astype(float)
        env = np.zeros(N)
        for p, am in ((0.18, 0.9), (0.33, 0.5), (0.52, 0.7), (0.74, 0.3)):
            env += am * ((ph > p) & (ph < p + pw))
        nz = self.rng.normal(0, 0.03, N)
        if not a.get(bid):
            return nz * 0.25
        echo = env * (1.0 if a["echo"] else 0.0) * (1.0 if a["dup"] else 0.0)
        leak = pulse * (1.0 if a["mag"] and a["dup"] else 0.0)
        stcv = rad.stc.val if a["stc"] else 0.0
        g = 1 - stcv * np.exp(-ph / 0.15)
        gain = 0.4 + rad.gain.val
        if bid == "psu":
            return 0.6 + 0.015 * np.sin(2 * np.pi * 12 * x) + nz * 0.1
        if bid == "trig":
            return (ph < 0.008) * 0.9
        if bid == "mod":
            return -0.85 * pulse
        if bid in ("mag", "dup"):
            return pulse * 0.9 * np.sin(2 * np.pi * 90 * x)
        if bid == "ant":
            return (pulse * 0.9 + env * 0.05) * np.sin(2 * np.pi * 90 * x)
        if bid == "trl":
            return (leak * 0.14 + echo * 0.28) * np.sin(2 * np.pi * 90 * x) + nz * 0.2
        if bid == "lo":
            return 0.5 * np.sin(2 * np.pi * 60 * x)
        if bid == "mix":
            return (leak * 0.14 + echo * 0.25) * np.sin(2 * np.pi * 24 * x) + nz
        if bid == "ifa":
            return np.clip(((leak + echo) * g * np.sin(2 * np.pi * 24 * x) + nz * 3) * gain, -1, 1)
        det = np.clip(((leak + echo) * g + np.abs(nz) * 3) * gain, 0, 1)
        if bid == "det":
            return det
        if bid in ("vid", "dsp"):
            if rad.transmitting and a["mag"]:
                v = rad.ascan[1][np.minimum((ph * rad.NR).astype(int), rad.NR - 1)] * 0.9
            else:
                v = np.clip(det * 1.4 - 0.12, 0, 0.9)
            if bid == "dsp":
                v = v * 0.8 - (ph < 0.012) * 0.5
            return v
        if bid == "stc":
            return -0.85 * rad.stc.val * np.exp(-ph / 0.15)
        if bid == "afc":
            return np.full(N, max(-0.9, min(0.9, rad.afc_corr / 12.0))) + nz * 0.1
        return nz

    def comps(self):
        t = self.world.t
        k = self.sig.idx
        if k == 0:
            return [(1.0, 4.0)]
        if k == 1:
            return [(0.5, 2.8), (0.5, 7.6)]
        e = 0.3 + 0.7 * abs(math.sin(t * 3.1))
        return [(0.45 * e, 1.4 + 0.5 * math.sin(t * 1.7)), (0.3 * e, 3.3 + math.sin(t * 2.3)),
                (0.2 * e, 6.1 + 1.2 * math.sin(t * 1.1)), (0.12 * e, 9.2)]

    def wave_ssb(self, bid, a):
        x = np.linspace(0, 1, N, endpoint=False)
        nz = self.rng.normal(0, 0.02, N)
        if not a.get(bid):
            return nz * 0.3
        cs = self.comps()
        tw = 2 * np.pi * x
        aud = sum(am * np.sin(tw * f) for am, f in cs)

        def ssb(fc):
            return sum(am * np.sin(tw * (fc + f)) for am, f in cs)

        if bid == "mic":
            return aud * 0.3 + nz
        if bid == "afa":
            return aud * 0.85
        if bid == "cosc":
            return 0.7 * np.sin(tw * 60)
        if bid == "synth":
            return 0.7 * np.sin(tw * 85)
        if bid == "bal":
            return aud * np.sin(tw * 60) * 0.9
        if bid == "sbf":
            return ssb(60) * 0.8
        if bid == "txm":
            return ssb(110) * 0.5
        if bid == "drv":
            return ssb(110) * 0.7
        if bid == "pa":
            return ssb(110) * 0.95
        if bid == "atu":
            return ssb(110) * (0.95 if a["key"] else 0.15) + nz * (0 if a["key"] else 2)
        if bid == "rxm":
            return ssb(60) * 0.2 + nz * 3
        if bid == "ifl":
            return ssb(60) * 0.75 + nz
        if bid == "pdet":
            return aud * 0.5 + nz
        return aud * 0.9

    # --------------------------------------------------------------- events
    def handle(self, ev):
        if super().handle(ev):
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for b in self.blocks:
                if pygame.Rect(b[2], b[3], BW, BH).collidepoint(ev.pos):
                    if self.sel[self.which] != b[0] and self.fault[self.which]:
                        self.probes += 1
                    self.sel[self.which] = b[0]
                    return True
        return False

    def update(self, dt):
        w = self.world
        if self.b_r.pop():
            self.b_r.on, self.b_s.on = True, False
        if self.b_s.pop():
            self.b_r.on, self.b_s.on = False, True
        k = self.which
        self.b_key.visible = self.sig.visible = k == "S"
        self.b_spec.visible = k == "S"
        if self.b_inj.pop():
            self.repair(k)
            ids = [b[0] for b in self.blocks]
            f = ids[int(self.rng.integers(len(ids)))]
            self.inject(k, f)
        if self.b_fix.pop():
            f = self.fault[k]
            self.repair(k)
            self.result = ("Repaired. The fault was in: %s." % self.label(k, f)) if f else "No fault present. All stages healthy."
        if self.b_dec.pop():
            f = self.fault[k]
            if not f:
                self.result = "There is no fault injected on this equipment."
            elif f == self.sel[k]:
                pts = max(10, 100 - 8 * max(0, self.probes - 4))
                self.score += pts
                self.flags["diagnosed_" + k] = w.t
                self.result = "CORRECT - %s was faulty. Found in %d probes: +%d points. Stage replaced, equipment restored." % (self.label(k, f), self.probes, pts)
                self.repair(k)
            else:
                self.score -= 20
                ok = (self.alive_radar(self.world.rh) if k == "R" else self.alive_ssb(self.world.hh)).get(self.sel[k])
                self.result = "WRONG (-20). %s %s Find the FIRST stage whose inputs are good but whose output is dead." % (
                    self.label(k, self.sel[k]), "is producing a normal output." if ok else "has no output, but is its INPUT present? A stage with no input is not faulty.")

    def label(self, k, bid):
        return next(b[1] for b in (RADAR_BLK if k == "R" else SSB_BLK) if b[0] == bid)

    def inject(self, k, f):
        (self.world.rh if k == "R" else self.world.hh)[f] = False
        self.fault[k] = f
        self.probes = 0
        self.flags.pop("diagnosed_" + k, None)
        self.result = ""

    def repair(self, k):
        h = self.world.rh if k == "R" else self.world.hh
        for key in h:
            h[key] = True
        self.fault[k] = None

    def tip_at(self, pos):
        t = super().tip_at(pos)
        if t:
            return t
        for b in self.blocks:
            if pygame.Rect(b[2], b[3], BW, BH).collidepoint(pos):
                return b[1] + ": " + b[4]
        return ""

    # ----------------------------------------------------------------- draw
    def draw(self, s):
        w, k = self.world, self.which
        ui.panel(s, (20, 54, 1090, 560), "SIGNAL FLOW")
        ui.panel(s, (1120, 54, 470, 250), "TEST POINT")
        ui.panel(s, (1120, 312, 470, 302), "OSCILLOSCOPE")
        ui.panel(s, (20, 622, 1570, 238), "FAULT FINDING")
        alive = self.alive_radar(w.rh) if k == "R" else self.alive_ssb(w.hh)
        wires = RADAR_WIRES if k == "R" else SSB_WIRES
        off = (w.t * 70) % 22
        learn = self.fault[k] is None            # hide the live indications while a fault is being hunted
        for src, pts in wires:
            pygame.draw.lines(s, (84, 92, 104), False, pts, 2)
            ex, ey = pts[-1]
            px, py = pts[-2]
            a = math.atan2(ey - py, ex - px)
            pygame.draw.polygon(s, (130, 140, 154), [(ex, ey), (ex - 9 * math.cos(a - 0.45), ey - 9 * math.sin(a - 0.45)),
                                                     (ex - 9 * math.cos(a + 0.45), ey - 9 * math.sin(a + 0.45))])
            if alive.get(src) and learn:
                d = off
                for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                    ln = math.hypot(x1 - x0, y1 - y0)
                    while d < ln:
                        pygame.draw.circle(s, C["amber"], (x0 + (x1 - x0) * d / ln, y0 + (y1 - y0) * d / ln), 2)
                        d += 22
                    d -= ln
        if k == "S":
            pygame.draw.lines(s, (84, 92, 104), False, [(1045, 478), (1072, 478), (1072, 420)], 2)
            pygame.draw.lines(s, C["text"], False, [(1058, 396), (1072, 420), (1086, 396)], 2)
            pygame.draw.line(s, C["text"], (1072, 420), (1072, 390), 2)
            text(s, "WHIP", (1072, 374), 9, C["dim"], bold=True, align="c")
            text(s, "TRANSMIT CHAIN  →", (40, 128), 10, C["dim"], bold=True)
            text(s, "←  RECEIVE CHAIN", (40, 516), 10, C["dim"], bold=True)
            text(s, "state: %s" % ("TRANSMIT (keyed)" if alive["key"] else "RECEIVE"), (760, 92), 12, C["red"] if alive["key"] else C["green"], bold=True)
        else:
            text(s, "TRANSMITTER  →", (40, 128), 10, C["dim"], bold=True)
            text(s, "←  RECEIVER", (40, 282), 10, C["dim"], bold=True)
            rad = self.app.radar
            st = "TRANSMITTING" if rad.transmitting else "STAND-BY / OFF - transmitter inhibited (switch the RADAR tab to TX)"
            text(s, "radar state: " + st, (470, 92), 12, C["green"] if rad.transmitting else C["amber"], bold=True)
            text(s, "bearing + heading marker", (540, 526), 9, C["dim"])
            text(s, "sync", (120, 224), 9, C["dim"])
        for i, b in enumerate(self.blocks):
            r = pygame.Rect(b[2], b[3], BW, BH)
            selb = self.sel[k] == b[0]
            pygame.draw.rect(s, (10, 11, 13), r.move(2, 3), border_radius=6)
            pygame.draw.rect(s, (62, 70, 82) if selb else C["panel2"], r, border_radius=6)
            pygame.draw.rect(s, C["amber"] if selb else (C["green"] if (learn and alive.get(b[0])) else C["edge"]), r, 2 if selb else 1, border_radius=6)
            lines = ui.wrap(b[1], 11, BW - 12, bold=True)
            y = r.centery - len(lines) * 7 + 1
            for ln in lines:
                text(s, ln, (r.centerx, y), 11, C["white"], bold=True, align="c")
                y += 14
            text(s, "TP%d" % (i + 1), (r.x + 4, r.y + 2), 8, C["dim"], bold=True)
            if learn:
                ui.led(s, (r.right - 9, r.y + 9), "green", bool(alive.get(b[0])), None, 3)
        # test point info
        blk = next(b for b in self.blocks if b[0] == self.sel[k])
        tp = [b[0] for b in self.blocks].index(blk[0]) + 1
        text(s, "TP%d  %s" % (tp, blk[1]), (1136, 78), 15, C["amber"], bold=True)
        ui.text_block(s, blk[4], (1136, 104, 440, 150), 12, C["text"], lh=17, mono=False)
        if k == "R":
            tau, prf, _, _ = PULSES[self.app.radar.pulse.value]
            text(s, "pulse %.2f us  PRF %d Hz  PRI %.2f ms  duty %.4f" % (tau, prf, 1000.0 / prf, tau * 1e-6 * prf), (1136, 278), 11, C["cyan"])
        else:
            hf = self.app.hf
            text(s, "dial %.2f kHz  IF 455 kHz  synth %.2f kHz" % (hf.f, hf.f + 455), (1136, 278), 11, C["cyan"])
        # scope
        r = pygame.Rect(1136, 350, 438, 226)
        pygame.draw.rect(s, (5, 14, 10), r)
        for i in range(1, 8):
            pygame.draw.line(s, (22, 44, 34), (r.x + r.w * i / 8, r.y), (r.x + r.w * i / 8, r.bottom), 1)
        for i in range(1, 6):
            pygame.draw.line(s, (22, 44, 34), (r.x, r.y + r.h * i / 6), (r.right, r.y + r.h * i / 6), 1)
        fn = self.wave_radar if k == "R" else self.wave_ssb
        yv = fn(blk[0], alive)
        spec = k == "S" and self.b_spec.on
        xs = r.x + np.arange(N)

        def plot(v, col, wd):
            if spec:
                m = np.abs(np.fft.rfft(v * np.hanning(N)))[:160] / (N / 4)
                db = np.clip(20 * np.log10(m + 1e-4), -60, 0)
                px = r.x + np.arange(160) * (r.w / 160.0)
                pygame.draw.lines(s, col, False, list(zip(px, r.bottom - 4 - (db + 60) / 60.0 * (r.h - 10))), wd)
            else:
                pygame.draw.lines(s, col, False, list(zip(xs, r.centery - np.clip(v, -1.05, 1.05) * (r.h / 2 - 8))), wd)

        if self.b_ref.on:
            hall = {key: True for key in self.health}
            ra = self.alive_radar(hall) if k == "R" else self.alive_ssb(hall)
            st = self.rng.bit_generator.state
            plot(fn(blk[0], ra), (70, 84, 78), 1)
            self.rng.bit_generator.state = st
        plot(yv, C["green"], 2)
        pygame.draw.rect(s, C["edge"], r, 1)
        if spec:
            for kk, lab in ((60, "455 kHz IF"), (85, "SYNTH"), (110, "RF")):
                x = r.x + kk * (r.w / 160.0)
                pygame.draw.line(s, (120, 60, 60), (x, r.y), (x, r.y + 12), 1)
                text(s, lab, (x, r.y + 13), 8, (190, 110, 110), bold=True, align="c")
            text(s, "0 dB top, 10 dB/div. Frequency axis: audio at left; carriers not to scale", (r.x, r.bottom + 5), 10, C["dim"], mono=False)
        elif k == "R":
            text(s, "timebase: 2 pulse periods (pulse width exaggerated). grey = healthy reference", (r.x, r.bottom + 5), 10, C["dim"], mono=False)
        else:
            text(s, "timebase: 4 ms (RF cycles not to scale). grey = healthy reference", (r.x, r.bottom + 5), 10, C["dim"], mono=False)
        ui.led(s, (1246, 324), "green", bool(alive.get(blk[0])), "SIGNAL" if alive.get(blk[0]) else "NO SIGNAL", 5)
        # fault panel
        f = self.fault[k]
        x = 262
        text(s, "EQUIPMENT: %s" % ("MARINE RADAR TRANSCEIVER" if k == "R" else "MF/HF SSB TRANSCEIVER"), (x, 650), 13, C["text"], bold=True)
        text(s, "SCORE %d    PROBES USED %d" % (self.score, self.probes), (1574, 650), 13, C["amber"], bold=True, align="r")
        if f:
            sym = (RADAR_SYMPT if k == "R" else SSB_SYMPT)[f]
            text(s, "OPERATOR'S REPORT:", (x, 676), 12, C["red"], bold=True)
            ui.text_block(s, sym + "  (Go and look at the %s tab to see it for yourself.)" % ("RADAR" if k == "R" else "MF / HF SSB"),
                          (x, 694, 1290, 40), 13, C["white"], mono=False, lh=18)
        else:
            text(s, "No fault injected. All stages healthy - explore the test points to learn what 'good' looks like.", (x, 676), 12, C["green"], bold=True, mono=False)
        ui.text_block(s, self.result, (x, 740, 1290, 40), 13, C["yellow"], mono=False, lh=18, bold=True)
        ui.text_block(s, "METHOD: 1) Confirm the symptom at the operator's position. 2) Check the power supply. 3) Split the chain in "
                         "half and probe: signal present = fault is downstream, absent = upstream. 4) Check side inputs (trigger, "
                         "local oscillator, BFO, synthesizer) - a mixer with no oscillator is not the faulty stage. 5) The faulty "
                         "block is the FIRST one with good inputs and a bad output.", (x, 790, 1300, 64), 12, C["dim"], mono=False, lh=16)
        super().draw(s)
