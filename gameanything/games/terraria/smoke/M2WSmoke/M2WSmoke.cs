// GameAnything's smoke mod for Terraria (tModLoader 1.4.4+): proves the native round trip. The game's log (tModLoader-Logs/client.log)
// gets "[M2W-smoke] loaded" when the mod loads, the chat shows a yellow line when a world is entered.
// Keeping full speed while the window is unfocused (InactiveSleepTime) is from Universal Modder's Terraria notes (MIT, (c) 2026 Rehan
// and universal-modder contributors).
using System;
using Terraria;
using Terraria.ModLoader;

namespace M2WSmoke
{
    public class M2WSmoke : Mod
    {
        public override void Load()
        {
            Logger.Info("[M2W-smoke] loaded");
            if (!Main.dedServ) Main.instance.InactiveSleepTime = TimeSpan.Zero;     // keep running at full speed in the background
        }
    }

    public class SmokePlayer : ModPlayer
    {
        public override void OnEnterWorld()
        {
            Main.NewText("[M2W-smoke] hello from GameAnything", 255, 220, 80);
            Mod.Logger.Info("[M2W-smoke] entered world " + Main.worldName);
        }
    }
}
