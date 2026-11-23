// M2W workshop helper for native mode (D19): subscribes to the Workshop items the user approved, so they don't have to click.
// subscribe.txt next to Source/ lists one published file id per line (# starts a comment); only models and props the user ticked
// in the approval card go there, never mods. Each launch it logs what is already subscribed, subscribes to what is missing,
// logs each finished download, and writes status.txt next to Source/ ("<id> subscribed|installed|requested|failed").
// Log lines start with "[M2W-ws]" (`m2w native log --game cities_skylines --grep M2W-ws`). Unsubscribing is a manual choice of the user.
// Old C# on purpose (C# 7.3, .NET 3.5 profile).
using System;
using System.Collections.Generic;
using System.IO;
using ColossalFramework.IO;
using ColossalFramework.PlatformServices;
using ICities;
using UnityEngine;

namespace M2WWorkshop
{
    public class Mod : IUserMod
    {
        public string Name { get { return "M2W workshop helper"; } }
        public string Description { get { return "GameAnything: subscribes to the Workshop items you approved. Safe to remove."; } }
        public void OnEnabled()
        {
            Debug.Log("[M2W-ws] enabled");
            if (GameObject.Find("M2WWorkshopHost") == null) { var go = new GameObject("M2WWorkshopHost"); UnityEngine.Object.DontDestroyOnLoad(go); go.AddComponent<Host>(); }
        }
        public void OnDisabled() { }
    }

    public class Host : MonoBehaviour
    {
        string dir; readonly List<ulong> wanted = new List<ulong>(); readonly Dictionary<ulong, string> state = new Dictionary<ulong, string>();
        float next; int tries; bool done;

        void Start()
        {
            dir = Path.Combine(Path.Combine(DataLocation.addonsPath, "Mods"), "M2WWorkshop");
            var f = Path.Combine(dir, "subscribe.txt");
            if (!File.Exists(f)) { Debug.Log("[M2W-ws] no subscribe.txt"); done = true; return; }
            foreach (var raw in File.ReadAllLines(f))
            {
                var line = raw.Split('#')[0].Trim(); ulong id;
                if (line.Length > 0 && ulong.TryParse(line, out id)) wanted.Add(id);
            }
            Debug.Log("[M2W-ws] wanted " + wanted.Count + " items");
        }

        void Update()
        {
            if (done || Time.realtimeSinceStartup < next) return;
            next = Time.realtimeSinceStartup + 5f;
            if (++tries > 60) { Debug.Log("[M2W-ws] gave up: the platform service never became ready"); done = true; return; }
            try { Run(); done = true; }
            catch (Exception e) { Debug.Log("[M2W-ws] not ready yet (" + tries + "): " + e.Message); }
        }

        void Run()
        {
            var ws = PlatformService.workshop;
            var have = new HashSet<ulong>();
            foreach (var p in ws.GetSubscribedItems()) have.Add(p.AsUInt64);
            Debug.Log("[M2W-ws] already subscribed to " + have.Count + " items");
            ws.eventWorkshopItemInstalled += OnInstalled;
            foreach (var id in wanted)
            {
                if (have.Contains(id)) { state[id] = "subscribed"; Debug.Log("[M2W-ws] " + id + " already subscribed"); continue; }
                bool ok = false;
                try { ok = ws.Subscribe(new PublishedFileId(id)); } catch (Exception e) { Debug.Log("[M2W-ws] " + id + " subscribe error: " + e.Message); }
                state[id] = ok ? "requested" : "failed";
                Debug.Log("[M2W-ws] " + id + " subscribe " + (ok ? "requested" : "FAILED"));
            }
            Write();
        }

        void OnInstalled(PublishedFileId id)
        {
            if (!state.ContainsKey(id.AsUInt64)) return;
            state[id.AsUInt64] = "installed"; Debug.Log("[M2W-ws] " + id.AsUInt64 + " installed"); Write();
        }

        void Write()
        {
            var lines = new List<string>();
            foreach (var kv in state) lines.Add(kv.Key + " " + kv.Value);
            try { File.WriteAllLines(Path.Combine(dir, "status.txt"), lines.ToArray()); } catch (Exception e) { Debug.Log("[M2W-ws] status write failed: " + e.Message); }
        }
    }
}
