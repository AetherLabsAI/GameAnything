// GameAnything smoke mod for {{title}} (tModLoader): logs on load, a chat line when a world is entered.
using Terraria;
using Terraria.ModLoader;

namespace {{Name}}
{
    public class {{Name}} : Mod
    {
        public override void Load() { Logger.Info("[M2W-smoke] loaded"); }
    }

    public class SmokePlayer : ModPlayer
    {
        public override void OnEnterWorld() { Main.NewText("[M2W-smoke] hello from GameAnything", 255, 220, 80); }
    }
}
