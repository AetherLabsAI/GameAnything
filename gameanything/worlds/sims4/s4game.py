"""Read-only access to the Sims 4 game's own resources (used as templates; nothing is ever written to the game).

The game stores resources in Data/Client/Client{Full,Delta}Build*.package and Delta/<pack>/ClientDeltaBuild*.package.
Later packages override earlier ones; a delta entry with compression 0xFFE0 deletes a resource.
Some pack delta packages are 96-byte stubs (pack not installed) and are skipped.
"""
import glob
import os

from gameanything.native.s4pkg import Package

DEFAULT_APP = "/Applications/EA Games/The Sims 4.app"

T_OBJD, T_COBJ, T_MODL, T_MLOD, T_FTPT = 0xC0DB5AE7, 0x319E4F1D, 0x01661233, 0x01D10F34, 0xD382BF57
T_DDS, T_RIG, T_SLOT, T_STBL = 0x00B2D882, 0x8EAF13DE, 0xD3044521, 0x220557DA
WANTED = {T_OBJD, T_COBJ, T_MODL, T_FTPT, T_DDS, T_RIG, T_SLOT}


class Game:
    def __init__(self, app=None):
        app = app or DEFAULT_APP
        self.base = os.path.join(app, "Contents")
        if not os.path.isdir(os.path.join(self.base, "Data", "Client")):
            raise FileNotFoundError(f"Sims 4 client data not found under {app} (use --game /path/to/The Sims 4.app)")
        self.index = {t: {} for t in WANTED}
        self._pk = {}
        files = sorted(glob.glob(os.path.join(self.base, "Data", "Client", "ClientFullBuild*.package")))
        files += sorted(glob.glob(os.path.join(self.base, "Delta", "*", "ClientDeltaBuild*.package")))
        files += sorted(glob.glob(os.path.join(self.base, "Data", "Client", "ClientDeltaBuild*.package")))
        for f in files:
            try:
                P = Package(f)
            except Exception:
                continue  # empty pack stub
            self._pk[f] = P
            for e in P.entries:
                if e[0] not in WANTED:
                    continue
                if e[6] == 0xFFE0:
                    self.index[e[0]].pop((e[1], e[2]), None)
                else:
                    self.index[e[0]][(e[1], e[2])] = (f, e)

    def has(self, t, g, i):
        return (g, i) in self.index.get(t, {})

    def read(self, t, g, i):
        f, e = self.index[t][(g, i)]
        return self._pk[f].read(e)

    def where(self, t, g, i):
        return os.path.basename(self.index[t][(g, i)][0])

    def close(self):
        for p in self._pk.values():
            p.close()
