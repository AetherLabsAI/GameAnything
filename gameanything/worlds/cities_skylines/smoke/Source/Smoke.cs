// M2W smoke test for native mode (D19): proves the chain install -> switched on -> compiled by the game -> loaded -> in a city,
// without mouse or keyboard. Log lines start with "[M2W-smoke]" (`m2w native log --game cities_skylines --grep M2W-smoke`).
// If autostart.txt next to Source/ holds "new:<map name>", the mod starts a new city on that map once the main menu is up and the
// menu has been idle for 60 s (starting 3 s after the menu appeared left the prefab collections empty: NullReferenceException in
// PrefabCollection.GetPrefab, the level-loaded handlers broke off and loading never finished; seen on macOS 2026-10-17. At the
// menu LoadingManager's m_essentialScenesLoaded / m_loadingComplete stay false, so they cannot tell when the menu is ready).
// Old C# on purpose (the game's own compiler): no => members, no ?., no string interpolation.
using System;
using System.IO;
using System.Reflection;
using ColossalFramework;
using ColossalFramework.IO;
using ColossalFramework.UI;
using ICities;
using UnityEngine;

namespace M2WSmoke
{
    public class Mod : IUserMod
    {
        public string Name { get { return "M2W smoke test"; } }
        public string Description { get { return "GameAnything native-mode check. Safe to remove."; } }
        public void OnEnabled()
        {
            Application.runInBackground = true;          // keep running while its window is not in front (native mode: no focus stealing)
            Debug.Log("[M2W-smoke] enabled (runInBackground " + Application.runInBackground + ")");
            if (GameObject.Find("M2WSmokeHost") == null) { var go = new GameObject("M2WSmokeHost"); UnityEngine.Object.DontDestroyOnLoad(go); go.AddComponent<Host>(); }
        }
        public void OnDisabled() { }
    }

    public class Loading : LoadingExtensionBase
    {
        public override void OnLevelLoaded(LoadMode mode)
        {
            Debug.Log("[M2W-smoke] city loaded (" + mode + "), money " + Singleton<EconomyManager>.instance.LastCashAmount / 100);
        }
    }

    public class Host : MonoBehaviour
    {
        string start; float menuSince = -1f, lastNote; bool done;

        void Start()
        {
            var f = Path.Combine(Path.Combine(Path.Combine(DataLocation.addonsPath, "Mods"), "M2WSmoke"), "autostart.txt");
            if (File.Exists(f)) start = File.ReadAllText(f).Trim();
            Debug.Log("[M2W-smoke] autostart: " + (string.IsNullOrEmpty(start) ? "(none)" : start));
        }

        void Update()
        {
            if (done || string.IsNullOrEmpty(start) || !start.StartsWith("new:")) return;
            var lm = Singleton<LoadingManager>.instance;
            bool hasMenu = FindObjectOfType<MainMenu>() != null;
            if (Time.realtimeSinceStartup - lastNote > 10f)
            {
                lastNote = Time.realtimeSinceStartup;
                Debug.Log("[M2W-smoke] waiting: menu " + hasMenu + ", loading " + lm.m_currentlyLoading + ", essential " + lm.m_essentialScenesLoaded
                          + ", complete " + lm.m_loadingComplete + ", menu for " + (menuSince < 0 ? 0f : Time.realtimeSinceStartup - menuSince) + " s");
            }
            bool menu = hasMenu && !lm.m_currentlyLoading;
            if (!menu) { menuSince = -1f; return; }
            if (menuSince < 0) { menuSince = Time.realtimeSinceStartup; return; }
            if (Time.realtimeSinceStartup - menuSince < 60f) return;
            done = true;
            try { NewCity(start.Substring(4)); }
            catch (Exception e) { Debug.Log("[M2W-smoke] autostart failed: " + e); }
        }

        // Through the game's own New Game panel, like a player: open it, pick the map, press Start (OnStartNewGame). Calling
        // LoadingManager.LoadLevel directly (as the lab bridge does) skipped what the panel's StartNewGameRoutine prepares and
        // the city never finished loading (empty prefab collections), seen on macOS 2026-10-17.
        void NewCity(string map) { StartCoroutine(NewCityRoutine(map)); }

        System.Collections.IEnumerator NewCityRoutine(string map)
        {
            UIView.library.ShowModal("NewGamePanel");
            yield return new WaitForSeconds(2f);
            var panel = FindObjectOfType<NewGamePanel>();         // ShowModal<T> returned null here (macOS, 2026-10-17)
            if (panel == null) { Debug.Log("[M2W-smoke] autostart failed: the New Game panel did not open"); yield break; }
            var f = typeof(NewGamePanel).GetField("m_FileList", BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance);
            var list = f == null ? null : f.GetValue(panel) as UIListBox;
            if (list == null) { Debug.Log("[M2W-smoke] autostart failed: no map list in the New Game panel"); yield break; }
            int idx = Array.IndexOf(list.items, map);
            if (idx < 0) { Debug.Log("[M2W-smoke] no map '" + map + "'; maps: " + string.Join("; ", list.items)); yield break; }
            list.selectedIndex = idx;
            yield return new WaitForSeconds(2f);
            Debug.Log("[M2W-smoke] starting a new city on " + map + " (New Game panel)");
            panel.OnStartNewGame();
        }
    }
}
