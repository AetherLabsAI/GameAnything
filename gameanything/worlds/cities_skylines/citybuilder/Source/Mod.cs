// M2W city builder for Cities: Skylines 1 (macOS: built to a DLL with `m2w native build`; old C# on purpose).
// Generic: everything personal lives in the mod's data/ folder (heightmap, roads, objects, memories), never in this source.
using System;
using System.Collections.Generic;
using System.IO;
using ICities;
using ColossalFramework;
using ColossalFramework.IO;
using UnityEngine;

namespace M2WCity
{
    public class Mod : IUserMod
    {
        public string Name { get { return "M2W City Builder"; } }
        public string Description { get { return "Builds a city from your memories (GameAnything). Safe to remove."; } }
        public void OnEnabled()
        {
            Host.L("enabled");
            if (GameObject.Find("M2WCityHost") == null)
            {
                var go = new GameObject("M2WCityHost");
                UnityEngine.Object.DontDestroyOnLoad(go);
                go.AddComponent<Host>();
            }
        }
        public void OnDisabled() { }
    }

    public class Loading : LoadingExtensionBase
    {
        public override void OnLevelLoaded(LoadMode mode)
        {
            var host = GameObject.Find("M2WCityHost");
            if (host == null) return;
            var h = host.GetComponent<Host>();
            if (h != null) h.CityLoaded(mode);
        }
        public override void OnLevelUnloading()
        {
            var host = GameObject.Find("M2WCityHost");
            if (host == null) return;
            var h = host.GetComponent<Host>();
            if (h != null) h.CityUnloading();
        }
    }
}
