"""Wheelhouse ambience, mixed under everything else in stereo:

  - room tone: equipment fans and the 400 Hz ship's supply hum (only while
    the ship has AC power - a blackout really goes quiet)
  - the main engine, whose firing rate follows the SPEED you set
  - wind in the rigging and the swell, scaled by sea state; hull slams and
    a howl in the rigging in heavy weather
  - rain drumming on the wheelhouse windows when a squall is over the ship
  - the rescue helicopter, panned by its bearing and Doppler-shifted
  - the steering-gear pump whenever the helm is moved
"""
import math
import numpy as np
from . import ui
from .audio import place, SR


class Ambience:
    def __init__(self, app):
        self.app = app
        self.last_hdg = None
        self.steer = 0.0
        self.rng = np.random.default_rng(99)
        self._slam_t = 0.0

    def update(self, dt):
        """Occasional one-shots: hull slams in a heavy sea."""
        w = self.app.world
        if w.sea >= 5 and w.t > self._slam_t:
            self._slam_t = w.t + float(self.rng.uniform(6.0, 22.0)) / (w.sea - 3.5)
            ui.sfx("slam", min(1.0, 0.25 + 0.12 * (w.sea - 4)), pan=float(self.rng.uniform(-0.3, 0.3)))

    def __call__(self, syn, n):
        app, w = self.app, self.app.world
        out = np.zeros((n, 2))
        t = syn._time(n)
        pw = app.power_state()
        if pw["ac"]:
            room = syn.rumble("fan", n, 10) * 0.035 + syn.osc("hum", 400.0, n) * 0.006 + syn.osc("hum2", 800.0, n) * 0.002
            out += place(room, 0.0)
        elif pw["dc"]:                                    # on the battery: only the console's DC fans
            out += place(syn.rumble("fan", n, 7) * 0.012, 0.0)
        # main engine: firing rate follows the ship's speed, with combustion roughness
        spd = w.spd
        fa = syn.glide("eng", 6.0 + 2.3 * spd, n, 2.4)
        lvl = 0.010 + 0.0024 * min(spd, 25.0)
        eng = (syn.osc("e1", fa, n) * 0.5 + syn.osc("e2", 2 * fa, n) * 0.4 + syn.osc("e3", 3 * fa, n) * 0.25
               + syn.osc("e4", 4 * fa, n) * 0.15)
        fire = (0.5 + 0.5 * syn.osc("ef", fa, n)) ** 8
        eng = eng + syn.rumble("en", n, 4) * (0.15 + 0.85 * fire) * 0.6
        out += place(eng * lvl, 0.0)
        # wind and sea
        s = w.sea
        if s > 0:
            g = 0.62 + 0.38 * np.sin(2 * np.pi * t / 9.3 + 0.7) * np.sin(2 * np.pi * t / 3.9)
            a = 0.0045 * s ** 1.45
            low = syn.rumble("wlow", n, 16)
            out[:, 0] += (syn.rumble("wl", n, 4) * 0.55 + low * 0.5) * a * g
            out[:, 1] += (syn.rumble("wr", n, 4) * 0.55 + low * 0.5) * a * g
            swell = syn.rumble("swell", n, 48) * (0.55 + 0.45 * np.sin(2 * np.pi * t / 7.5)) * 0.006 * s
            out += place(swell, 0.0)
            if s >= 5:
                wf = 640 + 170 * np.sin(2 * np.pi * t * 0.11) + 55 * np.sin(2 * np.pi * t * 0.43)
                out += place(syn.osc("whis", wf, n) * np.clip(g - 0.55, 0, 1) * 0.012 * (s - 4), -0.3)
        # rain on the windows
        rate = w.rain_here()
        if rate > 0.2:
            a = min(0.07, 0.011 * math.sqrt(rate))
            dl = syn.clicks("rdl", n, 25 + 9 * rate, 0.0012)
            dr = syn.clicks("rdr", n, 25 + 9 * rate, 0.0012)
            out[:, 0] += (np.diff(syn.white(n + 1)) * 0.3 + dl * 0.8) * a
            out[:, 1] += (np.diff(syn.white(n + 1)) * 0.3 + dr * 0.8) * a
        # the rescue helicopter
        heli = w.by_name.get("RESCUE 193")
        if heli is not None and heli.active:
            rng, brg = w.rb(heli)
            if rng < 5.0:
                lvl = min(0.30, 0.028 / (rng + 0.07) ** 1.2)
                rel = math.radians(brg - w.hdg)
                ux, uy = (w.x - heli.x) / max(rng, 1e-3), (w.y - heli.y) / max(rng, 1e-3)
                ha, oa = math.radians(heli.cog), math.radians(w.hdg)
                vx = heli.sog * math.sin(ha) - w.spd * math.sin(oa)
                vy = heli.sog * math.cos(ha) - w.spd * math.cos(oa)
                vr = (vx * ux + vy * uy) * 0.5144                  # closing speed m/s
                dop = 343.0 / max(200.0, 343.0 - vr)
                env = (0.5 + 0.5 * syn.osc("rbp", 18.4, n)) ** 3
                rotor = syn.rumble("rot", n, 5) * (0.3 + 0.7 * env) + syn.osc("rlo", 55.2, n) * 0.35 * env
                turb = syn.osc("tb1", 1840 * dop, n) * 0.05 + syn.osc("tb2", 3680 * dop, n) * 0.02
                out += place((rotor + turb) * lvl, math.sin(rel) * 0.85)
        # steering gear pump when the helm moves
        if self.last_hdg is not None and abs(((w.hdg - self.last_hdg) + 180) % 360 - 180) > 0.05:
            self.steer = 1.0
        self.last_hdg = w.hdg
        if self.steer > 0.01:
            pump = (syn.osc("st1", 290.0, n) + 0.5 * syn.osc("st2", 580.0, n) + 0.35 * syn.rumble("stn", n, 3)) * 0.016 * self.steer
            out += place(pump, 0.15)
            self.steer *= math.exp(-n / SR / 0.6)
        return out
