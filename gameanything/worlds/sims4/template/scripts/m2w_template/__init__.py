"""M2W example script mod (Python 3.7, imported once when the game starts).

Console command (cheat console: ctrl+shift+c):  m2w.template_hello  -> adds m2w_Buff_Hello (from the .package) to the active Sim.
Rename the folder m2w_template (the name of the module) to your own; keep one top-level module per script mod.
"""
import services
import sims4.commands
from sims4.resources import Types

from m2w_template import log

BUFF_NAME = "m2w_Buff_Hello"


def get_tuning(kind, name):
    """Look up loaded tuning by its name, e.g. get_tuning(Types.BUFF, 'm2w_Buff_Hello')."""
    mgr = services.get_instance_manager(kind)
    for t in mgr.types.values():
        if t.__name__ == name:
            return t
    return None


@sims4.commands.Command("m2w.template_hello", command_type=sims4.commands.CommandType.Live)
def hello(_connection=None):
    out = sims4.commands.CheatOutput(_connection)
    buff = get_tuning(Types.BUFF, BUFF_NAME)
    si = services.active_sim_info()
    if buff is None:
        out("m2w.template_hello: tuning %s not loaded (is the .package installed?)" % BUFF_NAME)
        return False
    si.add_buff_from_op(buff)
    log.write("hello: added %s to %s %s" % (BUFF_NAME, si.first_name, si.last_name))
    out("m2w.template_hello: added %s to %s %s" % (BUFF_NAME, si.first_name, si.last_name))
    return True


log.write("m2w_template loaded")
