"""Application shell: window, station tabs, status bar, audio mixing."""
import os
import sys
import numpy as np
import pygame
from . import ui, fx
from .ui import C, text, W, H
from .world import World, Msg, VHF_SCRIPT, HF_STATIONS, fmt_lat, fmt_lon
from .speech import Speech
from .audio import Audio


class App:
    def __init__(self):
        pygame.mixer.pre_init(22050, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption("RADAR-SIM  |  Radar, Radio and GMDSS Console Trainer")
        try:
            self.screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
        except pygame.error:
            self.screen = pygame.display.set_mode((W, H))
        self.world = World()
        self.audio = Audio()
        self.speech = Msg.speech = Speech()
        for seq in VHF_SCRIPT:
            for _, who, txt in seq:
                self.speech.request(txt, self.world.srcs[who].name)
        for st in HF_STATIONS:
            if st["kind"] == "voice":
                self.speech.request(st["text"], st["name"])
        from .radar import Radar
        from .vhf import VUHF
        from .hf import HF
        from .satcom import Satcom
        from .sarsat import Sarsat
        from .bench import Bench
        from .training import Training
        from .reference import Reference
        self.stations = []
        for cls in (Radar, VUHF, HF, Satcom, Sarsat, Bench, Training, Reference):
            st = cls(self)
            self.stations.append(st)
            setattr(self, cls.__name__.lower(), st)
        self._cur = 0
        ui.SFX = self.audio.play
        self.clock = pygame.time.Clock()
        self.running = True
        self.fps = 60.0
        self.tabs = []
        tw = 130
        for i, st in enumerate(self.stations):
            self.tabs.append(pygame.Rect(232 + i * (tw + 5), 5, tw, 34))

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
            if st.name == name or st.__class__.__name__.lower() == name.lower():
                self.cur = i

    @property
    def station(self):
        return self.stations[self.cur]

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
            if pygame.K_F1 <= ev.key <= pygame.K_F8:
                self.cur = ev.key - pygame.K_F1
                return
            if ev.key == pygame.K_F10:
                self.audio.mute = not self.audio.mute
                return
            if ev.key == pygame.K_F11:
                pygame.display.toggle_fullscreen()
                return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and ev.pos[1] < ui.TOP:
            for i, r in enumerate(self.tabs):
                if r.collidepoint(ev.pos):
                    self.cur = i
            if pygame.Rect(W - 62, 6, 54, 32).collidepoint(ev.pos):
                self.audio.mute = not self.audio.mute
            return
        self.station.handle(ev)

    def step(self, dt):
        self.world.update(dt)
        for st in self.stations:
            st.update(dt)

    def gen_audio(self, syn, n):
        # room tone: cooling fans and the 400 Hz ship's supply hum
        out = syn.rumble("fan", n, 10) * 0.035 + syn.osc("hum", 400.0, n) * 0.006 + syn.osc("hum2", 800.0, n) * 0.002
        a = self.station.audio(syn, n)
        if a is not None:
            out += a
        for st in self.stations:
            f = getattr(st, "bg_audio", None)
            if f:
                b = f(syn, n)
                if b is not None:
                    out += b
        return out

    def draw(self):
        s = self.screen
        s.fill((7, 8, 9))                                   # shadowed chassis between the panels
        self.station.draw(s)
        ui.finish(s)
        # header rail: nameplate, station selector buttons, chronometer
        s.blit(fx.strip((0, 0, W, ui.TOP - 2)), (0, 0))
        pygame.draw.line(s, (4, 4, 5), (0, ui.TOP - 2), (W, ui.TOP - 2), 2)
        pygame.draw.rect(s, (10, 10, 11), (8, 5, 214, 34), border_radius=3)
        pygame.draw.rect(s, (120, 100, 50), (8, 5, 214, 34), 1, border_radius=3)
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
            text(s, "F%d" % (i + 1), (r.x + 7, r.y + 5), 8, tc if lit else C["dim"], bold=True)
            text(s, st.name, r.center, 12, tc, bold=True, align="m")
        w = self.world
        x = self.tabs[-1].right + 16
        cr = pygame.Rect(x, 6, 178, 32)
        fx.draw_well(s, cr, (16, 4, 3), (70, 12, 6))
        text(s, "UTC " + w.utc_str(), (cr.x + 8, cr.y + 1), 14, (255, 70, 44), bold=True)
        text(s, fmt_lat(w.lat) + " " + fmt_lon(w.lon), (cr.x + 8, cr.y + 18), 10, (220, 60, 40))
        fx.finish_glass(s, cr, "lcd", 150)
        r = pygame.Rect(W - 62, 6, 54, 32)
        mute = self.audio.mute or not self.audio.ok
        s.blit(fx.button(r.w, r.h, (70, 255, 120) if not mute else (255, 66, 56), True, False), r)
        text(s, "MUTED" if mute else "SOUND", (r.centerx, r.y + 6), 9, (10, 20, 10), bold=True, align="c")
        text(s, "F10", (r.centerx, r.y + 17), 9, (10, 20, 10), bold=True, align="c")
        # footer rail: operator's instruction strip
        s.blit(fx.strip((0, ui.BOT, W, H - ui.BOT), (30, 31, 33)), (0, ui.BOT))
        pygame.draw.line(s, (4, 4, 5), (0, ui.BOT), (W, ui.BOT), 2)
        tip = self.station.tip_at(ui.MOUSE) if ui.TOP <= ui.MOUSE[1] < ui.BOT else ""
        if not tip and self.speech.error:
            tip = "NOTE: " + self.speech.error
        ui.text_block(s, tip or self.station.hint, (12, ui.BOT + 3, 1040, 32), 11,
                      (226, 224, 210) if tip else (150, 152, 150), lh=14, mono=False)
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
            app.gen_audio(app.audio.syn, 2208)
            app.audio.syn.t += 2208
        app.draw()
        pygame.image.save(app.screen, os.path.join(outdir, "%d_%s.png" % (i + 1, app.station.name.lower().replace("/", "-").replace(" ", "_"))))
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
