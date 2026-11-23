"""M2W smoke mod: proves install -> Options.ini switches -> the game imported the script. Loaded: the log (Mods/<name>/<name>.log) gets
"[M2W-smoke] loaded"; in the cheat console (ctrl+shift+c) `m2w.hello` answers "m2w.hello: hello from M2W"."""
import sims4.commands

from m2w_smoke import log


@sims4.commands.Command("m2w.hello", command_type=sims4.commands.CommandType.Live)
def hello(_connection=None):
    sims4.commands.CheatOutput(_connection)("m2w.hello: hello from M2W")
    log.write("[M2W-smoke] m2w.hello ran")
    return True


log.write("[M2W-smoke] loaded")
