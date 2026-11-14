"""Application shell: window, station tabs, status bar, audio mixing."""
import os
import sys
import numpy as np
import pygame
from . import ui, fx
from .ui import C, text, W, H
from .world import World, Msg, VHF_SCRIPT, HF_STATIONS, fmt_lat, fmt_lon
from .speech import Speech
from .audio import Audio, place
from .ambience import Ambience

KEYS = ("F1 - F12 station   Ctrl+M mute   Ctrl+A monitor all receivers   PgUp / PgDn volume   "
        "Ctrl+F or Alt+Enter full screen   Ctrl+Tab next station")


class App:
    def __init__(self):
        pygame.mixer.pre_init(22050, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption("RADAR-SIM  |  Radar, Radio and GMDSS Console Trainer")
        try:
            self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
        except pygame.error:
            self.screen = pygame.display.set_mode((W, H))
        self.world = World()
        self.audio = Audio()
        self.speech = Msg.speech = Speech()
        self.mistakes, self._mist = [], None
        self.monitor_all = True
        for seq in VHF_SCRIPT:
            for _, who, txt in seq:
                if isinstance(txt, dict):
                    txt = txt.get("text", "")
                if txt:
                    self.speech.request(txt, self.world.srcs[who].name)
        for st in HF_STATIONS:
            if st["kind"] == "voice":
                self.speech.request(st["text"], st["name"])
        from .radar import Radar
        from .vhf import VUHF
        from .hf import HF
        from .satcom import Satcom
        from .sat2 import Sat2
        from .sarsat import Sarsat
        from .navtex import Navtex
        from .nav import Nav
        from .power import Power
        from .bench import Bench
        from .training import Training
        from .reference import Reference
        self.stations = []
        for cls in (Radar, VUHF, HF, Satcom, Sat2, Sarsat, Navtex, Nav, Power, Bench, Training, Reference):
            st = cls(self)
            self.stations.append(st)
            setattr(self, cls.__name__.lower(), st)
        self.amb = Ambience(self)
        self._cur = 0
        ui.SFX = self.audio.play
        self.clock = pygame.time.Clock()
        self.running = True
        self.fps = 60.0
        self.tabs = []
        tw, gap = 88, 3
        for i, st in enumerate(self.stations):
            self.tabs.append(pygame.Rect(166 + i * (tw + gap), 5, tw, 34))
        self.r_clock = pygame.Rect(self.tabs[-1].right + 8, 6, 170, 32)
        self.r_mon = pygame.Rect(self.r_clock.right + 8, 6, 82, 32)
        self.r_snd = pygame.Rect(self.r_mon.right + 6, 6, W - 8 - (self.r_mon.right + 6), 32)

    @property
    def cur(self):
        return self._cur

    @cur.setter
    def cur(self, i):
        if i != self._cur and 0 <= i < len(self.stations):
            self._cur = i
            ui.sfx("tab", 0.8)

    def goto(self, name):
        for i, st in enumerate(self.stations):
            if st.name == name or st.__class__.__name__.lower() == name.lower() or (st.tab or "") == name:
                self.cur = i

    @property
    def station(self):
        return self.stations[self.cur]

    # ------------------------------------------------------ shared services
    def powered(self, key):
        """Is the breaker / supply for `key` live? (POWER panel)"""
        p = getattr(self, "power", None)
        return True if (p is None or key is None) else p.ok(key)

    def power_state(self):
        p = getattr(self, "power", None)
        return p.state() if p is not None else dict(ac=True, dc=True, battery=False)

    def dsc_position(self):
        """(lat, lon, source, age s) fed to the DSC controllers, or None."""
        n = getattr(self, "nav", None)
        if n is None:
            return self.world.lat, self.world.lon, "GPS", 0.0
        return n.dsc_position()

    def mistake(self, msg):
        """Record an operating error (shown in the footer and the drill debrief)."""
        self.mistakes.append((self.world.t, self.station.name, msg))
        del self.mistakes[:-80]
        self._mist = (msg, self.world.t)

    def toggle_monitor(self):
        self.monitor_all = not self.monitor_all
        ui.sfx("toggle", 0.8, pan=0.7)

    def set_volume(self, d):
        self.audio.set_master(self.audio.master + d)
        ui.sfx("detent", 0.7, pan=0.85)

    # ---------------------------------------------------------------- loop
    def handle(self, ev):
        if ev.type == pygame.QUIT:
            self.running = False
            return
        if ev.type == pygame.MOUSEMOTION:
            ui.MOUSE[0], ui.MOUSE[1] = ev.pos
        if ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            ui.MOUSE[0], ui.MOUSE[1] = ev.pos
        if ev.type == pygame.KEYDOWN:
            ctrl = ev.mod & pygame.KMOD_CTRL
            if pygame.K_F1 <= ev.key <= pygame.K_F12:
                self.cur = ev.key - pygame.K_F1
                return
            if ctrl and ev.key == pygame.K_m:
                self.audio.mute = not self.audio.mute
                return
            if (ctrl and ev.key == pygame.K_f) or (ev.mod & pygame.KMOD_ALT and ev.key == pygame.K_RETURN):
                pygame.display.toggle_fullscreen()
                return
            if ctrl and ev.key == pygame.K_a:
                self.toggle_monitor()
                return
            if ctrl and ev.key == pygame.K_TAB:
                self.cur = (self.cur + (-1 if ev.mod & pygame.KMOD_SHIFT else 1)) % len(self.stations)
                return
            if ev.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
                self.set_volume(0.05 if ev.key == pygame.K_PAGEUP else -0.05)
                return
        if ev.type == pygame.MOUSEWHEEL and ui.MOUSE[1] < ui.TOP and self.r_snd.collidepoint(ui.MOUSE):
            self.set_volume(0.05 * (1 if ev.y > 0 else -1))
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and ev.pos[1] < ui.TOP:
            for i, r in enumerate(self.tabs):
                if r.collidepoint(ev.pos):
                    self.cur = i
            if self.r_snd.collidepoint(ev.pos):
                self.audio.mute = not self.audio.mute
            if self.r_mon.collidepoint(ev.pos):
                self.toggle_monitor()
            return
        self.station.handle(ev)

    def step(self, dt):
        self.world.update(dt)
        for st in self.stations:
            st.update(dt)
        self.amb.update(dt)

    def gen_audio(self, syn, n):
        """Stereo mix: ambience, the selected station in front of you, and the
        other equipment from its own place on the console."""
        out = self.amb(syn, n)
        cur = self.station
        for st in self.stations:
            fg = st is cur
            if fg or (self.monitor_all and st.bg_listen):
                a = st.audio(syn, n)
                if a is not None:
                    out += place(a, st.pan) if fg else place(a, st.bg_pan, st.bg_level, width=0.3)
            f = getattr(st, "bg_audio", None)
            if f:
                b = f(syn, n)
                if b is not None:
                    out += place(b, st.pan if fg else st.bg_pan)
        return out

    def header_tip(self, p):
        for i, (st, r) in enumerate(zip(self.stations, self.tabs)):
            if r.collidepoint(p):
                return "F%d  %s.  %s" % (i + 1, st.name, st.hint)
        if self.r_clock.collidepoint(p):
            return "Chronometer (UTC) and own-ship position from the GPS (NAV / AIS tab)."
        if self.r_mon.collidepoint(p):
            return ("MONITOR ALL RECEIVERS (Ctrl+A): lit = you also hear the VHF and MF/HF loudspeakers while working "
                    "on other tabs, quieter and from their own place on the console - like a real bridge.")
        if self.r_snd.collidepoint(p):
            return ("SOUND: click (or Ctrl+M) to mute. Mouse wheel here or PgUp / PgDn: master volume, now %d %%.   "
                    % round(self.audio.master * 100) + KEYS)
        return ""

    def draw(self):
        s = self.screen
        s.fill((7, 8, 9))                                   # shadowed chassis between the panels
        self.station.draw(s)
        pw = getattr(self, "power", None)
        lt = pw.lights if pw is not None else 1.0
        if lt < 0.99:                                       # console lighting dimmed / off: only displays glow
            if getattr(self, "_mask", None) is None:
                self._mask = pygame.Surface((W, ui.BOT - ui.TOP))
            k = int(255 * (0.28 + 0.72 * lt))
            m = self._mask
            m.fill((k, k, k))
            for r, kind, gain in ui.GLASS:
                m.fill((255, 255, 255), pygame.Rect(r).move(0, -ui.TOP))
            for r in ui.LIT:
                m.fill((255, 255, 255), pygame.Rect(r).move(0, -ui.TOP))
            s.blit(m, (0, ui.TOP), special_flags=pygame.BLEND_RGB_MULT)
        ui.finish(s)
        # header rail: nameplate, station selector buttons, chronometer
        s.blit(fx.strip((0, 0, W, ui.TOP - 2)), (0, 0))
        pygame.draw.line(s, (4, 4, 5), (0, ui.TOP - 2), (W, ui.TOP - 2), 2)
        pygame.draw.rect(s, (10, 10, 11), (8, 5, 150, 34), border_radius=3)
        pygame.draw.rect(s, (120, 100, 50), (8, 5, 150, 34), 1, border_radius=3)
        text(s, "RADAR-SIM", (16, 6), 18, (226, 190, 96), bold=True)
        text(s, "TYPE 86 TRAINING CONSOLE", (16, 27), 8, (150, 130, 80), bold=True)
        blink = int(self.world.t * 3) % 2 == 0
        for i, (st, r) in enumerate(zip(self.stations, self.tabs)):
            act = i == self.cur
            alert = st.alert and blink
            col = (255, 60, 46) if alert else C["amber"]
            lit = act or alert
            if lit:
                s.blit(fx.halo(r.w, r.h, col, 0.28), (r.x - 16, r.y - 16), special_flags=pygame.BLEND_RGB_ADD)
            s.blit(fx.button(r.w, r.h, col, lit, False), r)
            tc = (26, 16, 6) if lit else (200, 202, 198)
            text(s, "F%d" % (i + 1), (r.x + 5, r.y + 3), 8, tc if lit else C["dim"], bold=True)
            pk = st.power_key if isinstance(st.power_key, str) else None
            if pk and not self.powered(pk):
                tc = (120, 60, 50) if not lit else tc
            text(s, st.tab or st.name, (r.centerx + 5, r.centery + 2), 11, tc, bold=True, align="m")
        w = self.world
        cr = self.r_clock
        fx.draw_well(s, cr, (16, 4, 3), (70, 12, 6))
        text(s, "UTC " + w.utc_str(), (cr.x + 8, cr.y + 1), 14, (255, 70, 44), bold=True)
        text(s, fmt_lat(w.lat) + " " + fmt_lon(w.lon), (cr.x + 8, cr.y + 18), 10, (220, 60, 40))
        fx.finish_glass(s, cr, "lcd", 150)
        r = self.r_mon
        mon = self.monitor_all
        if mon:
            s.blit(fx.halo(r.w, r.h, C["cyan"], 0.18), (r.x - 16, r.y - 16), special_flags=pygame.BLEND_RGB_ADD)
        s.blit(fx.button(r.w, r.h, C["cyan"], mon, False), r)
        tc = (6, 20, 26) if mon else (200, 202, 198)
        text(s, "ALL RX" if mon else "SEL RX", (r.centerx, r.y + 6), 10, tc, bold=True, align="c")
        text(s, "CTRL+A", (r.centerx, r.y + 18), 8, tc, bold=True, align="c")
        r = self.r_snd
        mute = self.audio.mute or not self.audio.ok
        s.blit(fx.button(r.w, r.h, (70, 255, 120) if not mute else (255, 66, 56), True, False), r)
        text(s, "MUTED" if mute else "SOUND", (r.centerx, r.y + 4), 9, (10, 20, 10), bold=True, align="c")
        pygame.draw.rect(s, (10, 30, 14), (r.x + 8, r.y + 19, r.w - 16, 6))
        pygame.draw.rect(s, (10, 70, 30) if not mute else (90, 20, 14), (r.x + 8, r.y + 19, (r.w - 16) * self.audio.master, 6))
        # footer rail: operator's instruction strip
        s.blit(fx.strip((0, ui.BOT, W, H - ui.BOT), (30, 31, 33)), (0, ui.BOT))
        pygame.draw.line(s, (4, 4, 5), (0, ui.BOT), (W, ui.BOT), 2)
        m = ui.MOUSE
        tip = self.station.tip_at(m) if ui.TOP <= m[1] < ui.BOT else (self.header_tip(m) if m[1] < ui.TOP else "")
        if not tip and self.speech.error:
            tip = "NOTE: " + self.speech.error
        col = (226, 224, 210) if tip else (150, 152, 150)
        if self._mist and w.t - self._mist[1] < 5.0:
            tip, col = "OPERATING ERROR:  " + self._mist[0], C["red"]
        ui.text_block(s, tip or self.station.hint, (12, ui.BOT + 3, 1040, 32), 11, col, lh=14, mono=False)
        tr = getattr(self, "training", None)
        if tr is not None:
            tr.draw_status(s, pygame.Rect(1070, ui.BOT + 1, W - 1070, H - ui.BOT - 1))
        pygame.display.flip()

    def run(self):
        while self.running:
            dt = min(0.1, self.clock.tick(60) / 1000.0)
            for ev in pygame.event.get():
                self.handle(ev)
            self.step(dt)
            self.audio.pump(self.gen_audio)
            self.draw()
        pygame.quit()


def selftest(outdir):
    """Headless smoke test: run every station and save a screenshot of each."""
    os.makedirs(outdir, exist_ok=True)
    app = App()
    for i in range(len(app.stations)):
        app.cur = i
        for _ in range(120):
            app.step(1 / 30.0)
            a = app.gen_audio(app.audio.syn, 2208)
            assert a.shape == (2208, 2) and np.isfinite(a).all(), "bad audio buffer on %s" % app.station.name
            app.audio.syn.t += 2208
        app.draw()
        nm = (app.station.tab or app.station.name).lower().replace("/", "-").replace(" ", "_")
        pygame.image.save(app.screen, os.path.join(outdir, "%02d_%s.png" % (i + 1, nm)))
    print("selftest ok:", ", ".join(s.name for s in app.stations))


def main():
    if "--selftest" in sys.argv:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        i = sys.argv.index("--selftest")
        selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else "shots")
        return
    App().run()


if __name__ == "__main__":
    main()
