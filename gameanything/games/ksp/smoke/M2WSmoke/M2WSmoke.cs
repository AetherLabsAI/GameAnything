using UnityEngine;

namespace M2WSmoke
{
    // GameAnything smoke plugin for Kerbal Space Program (the game's own AddonLoader, GameData/M2WSmoke/Plugins/M2WSmoke.dll):
    // logs when KSP starts it, keeps the game running when its window is not in front, and shows a message on the main menu.

    [KSPAddon(KSPAddon.Startup.Instantly, true)]
    public class Boot : MonoBehaviour
    {
        void Awake()
        {
            Application.runInBackground = true;                 // a native test goes on while she works in another window
            Debug.Log("[M2W-smoke] loaded (runInBackground " + Application.runInBackground + ")");
        }
    }

    [KSPAddon(KSPAddon.Startup.MainMenu, false)]
    public class Banner : MonoBehaviour
    {
        void Start()
        {
            Application.runInBackground = true;                 // KSP applies its settings while loading: set it again here
            ScreenMessages.PostScreenMessage("M2W smoke: plugin loaded", 600f, ScreenMessageStyle.UPPER_CENTER);
            Debug.Log("[M2W-smoke] main menu message shown (runInBackground " + Application.runInBackground + ")");
        }

        void OnGUI() { GUI.Box(new Rect(Screen.width / 2 - 200, 60, 400, 40), "M2W smoke: plugin loaded"); }
    }
}
