using BepInEx;
using UnityEngine;

namespace {{Name}}
{
    // GameAnything smoke plugin for {{title}} (BepInEx 5, a Unity Mono game): logs on load, draws a banner, keeps running unfocused.
    [BepInPlugin("memory2world.{{id}}.smoke", "{{Name}}", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        void Awake()
        {
            Application.runInBackground = true;                 // a native test goes on while she works in another window
            Logger.LogInfo("[M2W-smoke] loaded (runInBackground " + Application.runInBackground + ")");
        }

        void OnGUI() { GUI.Box(new Rect(Screen.width / 2 - 200, 60, 400, 40), "M2W smoke: plugin loaded"); }
    }
}
