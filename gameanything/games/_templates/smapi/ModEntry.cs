using StardewModdingAPI;
using StardewModdingAPI.Events;
using StardewValley;

namespace {{Name}}
{
    // GameAnything smoke mod (SMAPI-style loader): logs on load and shows a HUD message when a save is loaded.
    public class ModEntry : Mod
    {
        public override void Entry(IModHelper helper)
        {
            Monitor.Log("[M2W-smoke] loaded", LogLevel.Info);
            helper.Events.GameLoop.SaveLoaded += (s, e) => Game1.addHUDMessage(new HUDMessage("[M2W-smoke] hello from GameAnything"));
        }
    }
}
