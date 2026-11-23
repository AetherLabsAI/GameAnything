using BepInEx;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace M2WSmoke
{
    /// The smallest useful plugin (the lab's hello example): logs on load and on every scene change, and draws a banner on screen.
    /// It also keeps the game running while its window is not in front (Application.runInBackground), so a test in her own copy of the
    /// game (native mode) goes on while she works in another window, and m2w never has to bring the game to the front (本机模式少打扰).
    [BepInPlugin("memory2world.oc2.smoke", "M2WSmoke", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        GUIStyle style;

        void Awake()
        {
            Application.runInBackground = true;          // keep running unfocused (Unity pauses an unfocused player otherwise)
            Logger.LogInfo("[M2W-smoke] loaded (runInBackground " + Application.runInBackground + ")");
            SceneManager.activeSceneChanged += (a, b) => Logger.LogInfo("[M2W-smoke] scene -> " + b.name);
        }

        void OnGUI()
        {
            if (style == null)
            {
                style = new GUIStyle(GUI.skin.box) { fontSize = 28, fontStyle = FontStyle.Bold };
                style.normal.textColor = Color.yellow;
            }
            GUI.Box(new Rect(Screen.width / 2 - 260, 60, 520, 50), "M2W smoke: plugin loaded", style);
        }
    }
}
