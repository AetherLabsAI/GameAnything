using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using ColossalFramework;
using ColossalFramework.IO;
using ColossalFramework.UI;
using ICities;
using UnityEngine;

namespace M2WCity
{
    // One MonoBehaviour that lives for the whole session: starts the city (autostart), runs commands dropped into cmd.txt,
    // and draws the in-city memory buttons (IMGUI, so Chinese text works with an OS font).
    [DefaultExecutionOrder(32000)]   // LateUpdate runs after the game's CameraController (cine re-applies its pose there)
    public partial class Host : MonoBehaviour
    {
        public string dir, dataDir, shotDir;
        string autostart; float menuSince = -1f, lastNote; bool autostartDone;
        public bool inCity; public LoadMode mode;
        bool busy; float lastPoll;
        Queue<string> queue = new Queue<string>();

        // Every line also goes to <mod>/m2w.log (truncated at the first line of each game start, written and closed per line): Unity's Player.log on
        // Linux is written through a buffer, so the last lines can sit unflushed for minutes; tools read m2w.log instead. Thread-safe (the
        // simulation thread logs too); a failing write is ignored.
        static readonly object logLock = new object(); static string logPath; static bool logInit;
        public static void L(string s)
        {
            Debug.Log("[M2WCity] " + s);
            try
            {
                lock (logLock)
                {
                    if (!logInit)
                    {
                        logInit = true;
                        var p = Path.Combine(Path.Combine(Path.Combine(DataLocation.addonsPath, "Mods"), "M2WCity"), "m2w.log");
                        File.WriteAllText(p, ""); logPath = p;
                    }
                    if (logPath != null) File.AppendAllText(logPath, DateTime.Now.ToString("HH:mm:ss.fff", CultureInfo.InvariantCulture) + " [M2WCity] " + s + "\n");
                }
            }
            catch (Exception) { }
        }
        public static float F(string s) { return float.Parse(s, CultureInfo.InvariantCulture); }

        void Start()
        {
            dir = Path.Combine(Path.Combine(DataLocation.addonsPath, "Mods"), "M2WCity");
            dataDir = Path.Combine(dir, "data"); shotDir = Path.Combine(dir, "shots");
            try { Directory.CreateDirectory(shotDir); } catch { }
            var f = Path.Combine(dir, "autostart.txt");
            if (File.Exists(f)) autostart = File.ReadAllText(f).Trim();
            Application.runInBackground = true;
            L("started; autostart: " + (string.IsNullOrEmpty(autostart) ? "(none)" : autostart));
        }

        public void CityLoaded(LoadMode m)
        {
            mode = m; inCity = true;
            L("city loaded (" + m + ")");
            LoadMemories(); LoadWaterPlan();
            try { var cc = Singleton<CameraController>.instance; cc.m_unlimitedCamera = true; L("camera: maxDistance " + cc.m_maxDistance + ", maxTilt " + cc.m_maxTiltDistance + ", min " + cc.m_minDistance); } catch (Exception e) { L("camera: " + e.Message); }
            if (m == LoadMode.NewGame || m == LoadMode.LoadGame) { StartCoroutine(AfterLoad()); StartCoroutine(AutoApply()); }
        }
        public void CityUnloading() { inCity = false; DestroyModels(); L("city unloading"); }

        IEnumerator AfterLoad()
        {
            for (int i = 0; i < 5; i++) yield return null;
            var f = Path.Combine(dir, "onload.txt");     // commands to run right after the city is in (optional)
            if (File.Exists(f)) foreach (var l in File.ReadAllLines(f)) queue.Enqueue(l);
        }

        float lastModalCheck;
        // Error dialogs (ExceptionPanel) are closed automatically so they never block the user; each one is logged.
        void DismissErrorPanel()
        {
            if (Time.realtimeSinceStartup - lastModalCheck < 1f) return;
            lastModalCheck = Time.realtimeSinceStartup;
            try
            {
                var c = UIView.GetModalComponent();
                if (c != null && c.name == "ExceptionPanel")
                {
                    string msg = "";
                    try { var lbls = c.GetComponentsInChildren<UILabel>(); var sb = new StringBuilder(); foreach (var lb in lbls) if (!string.IsNullOrEmpty(lb.text)) sb.Append(lb.text.Replace("\n", " ")).Append(" | "); msg = sb.ToString(); if (msg.Length > 300) msg = msg.Substring(0, 300); } catch (Exception) { }
                    c.Hide(); UIView.PopModal();
                    L("closed an error dialog (ExceptionPanel): " + msg);
                }
            }
            catch (Exception e) { L("dismiss: " + e.Message); }
        }

        void Update()
        {
            DismissErrorPanel();
            if (!inCity) { MenuAutostart(); return; }
            if (!busy && queue.Count > 0) StartCoroutine(Run(queue.Dequeue()));
            if (!busy && Time.realtimeSinceStartup - lastPoll > 1f)
            {
                lastPoll = Time.realtimeSinceStartup;
                var c = Path.Combine(dir, "cmd.txt");
                if (File.Exists(c))
                {
                    string[] lines;
                    try { lines = File.ReadAllLines(c); var dn = Path.Combine(dir, "cmd.done.txt"); if (File.Exists(dn)) File.Delete(dn); File.Move(c, dn); }
                    catch (Exception e) { L("cmd.txt: " + e.Message); lines = new string[0]; try { File.Delete(c); } catch { } }
                    foreach (var l in lines) queue.Enqueue(l);
                }
            }
            HoldTimeTick(); KeepBuildings();
            try { MoversTick(); } catch (Exception e) { L("movers: " + e.Message); movers.Clear(); }
            if (inCity && (keepWater || pools.Count > 0) && Time.realtimeSinceStartup - lastTop > 20f) { try { TopUpAll(); } catch (Exception e) { L("topup: " + e.Message); lastTop = Time.realtimeSinceStartup; } }
        }

        IEnumerator Run(string line)
        {
            busy = true;
            line = line.Trim();
            if (line.Length > 0 && !line.StartsWith("#"))
            {
                L("> " + line);
                IEnumerator it = null;
                try { it = Dispatch(line); } catch (Exception e) { L("ERR " + line + ": " + e); }
                if (it != null)
                {
                    while (true)
                    {
                        bool more;
                        try { more = it.MoveNext(); } catch (Exception e) { L("ERR " + line + ": " + e); break; }
                        if (!more) break;
                        yield return it.Current;
                    }
                }
                L("< done " + line.Split(' ')[0]);
            }
            busy = false;
        }

        // ---------- main menu: start the city through the New Game panel (same recipe as the smoke mod) ----------
        void MenuAutostart()
        {
            if (autostartDone || string.IsNullOrEmpty(autostart) || !(autostart.StartsWith("new:") || autostart.StartsWith("load:"))) return;
            var lm = Singleton<LoadingManager>.instance;
            bool hasMenu = FindObjectOfType<MainMenu>() != null;
            if (Time.realtimeSinceStartup - lastNote > 15f) { lastNote = Time.realtimeSinceStartup; L("menu " + hasMenu + ", loading " + lm.m_currentlyLoading + ", for " + (menuSince < 0 ? 0f : Time.realtimeSinceStartup - menuSince) + " s"); }
            bool menu = hasMenu && !lm.m_currentlyLoading;
            if (!menu) { menuSince = -1f; return; }
            if (menuSince < 0) { menuSince = Time.realtimeSinceStartup; return; }
            if (Time.realtimeSinceStartup - menuSince < 60f) return;
            autostartDone = true;
            if (autostart.StartsWith("load:")) StartCoroutine(LoadCityRoutine(autostart.Substring(5)));
            else StartCoroutine(NewCityRoutine(autostart.Substring(4)));
        }

        // load:<save name> : the same way a player does it (Load panel, pick the save, press Load)
        IEnumerator LoadCityRoutine(string name)
        {
            UIView.library.ShowModal("LoadPanel");
            yield return new WaitForSeconds(3f);
            var panel = FindObjectOfType<LoadPanel>();
            if (panel == null) { L("autostart failed: the Load panel did not open"); yield break; }
            var f = typeof(LoadPanel).GetField("m_SaveList", BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance);
            var list = f == null ? null : f.GetValue(panel) as UIListBox;
            if (list == null) { L("autostart failed: no save list"); yield break; }
            var items = list.items;
            L("saves: " + string.Join("; ", items));
            int idx = -1;
            for (int i = 0; i < items.Length; i++) if (items[i] == name || items[i].Contains(name)) { idx = i; break; }
            if (idx < 0) { L("no save '" + name + "'"); yield break; }
            list.selectedIndex = idx;
            yield return new WaitForSeconds(2f);
            L("loading save " + items[idx]);
            panel.OnLoad();
        }

        IEnumerator NewCityRoutine(string map)
        {
            UIView.library.ShowModal("NewGamePanel");
            yield return new WaitForSeconds(2f);
            var panel = FindObjectOfType<NewGamePanel>();
            if (panel == null) { L("autostart failed: New Game panel did not open"); yield break; }
            var f = typeof(NewGamePanel).GetField("m_FileList", BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance);
            var list = f == null ? null : f.GetValue(panel) as UIListBox;
            if (list == null) { L("autostart failed: no map list"); yield break; }
            int idx = -1;
            for (int i = 0; i < list.items.Length; i++) if (list.items[i] == map || list.items[i].EndsWith(map)) { idx = i; break; }
            if (idx < 0) { L("no map '" + map + "'"); yield break; }
            list.selectedIndex = idx;
            yield return new WaitForSeconds(2f);
            L("starting a new city on " + map);
            panel.OnStartNewGame();
        }
    }
}
