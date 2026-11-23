// A GameAnything mod for Cities: Skylines 1 (Unity 5.6 Mono, .NET 3.5 profile: C# 7.3, no async, no ValueTuple).
// The game finds the IUserMod class (Name / Description in Content Manager > Mods) and the ICities extension classes:
// LoadingExtensionBase (OnLevelLoaded), ThreadingExtensionBase (OnUpdate every frame), ...
// Change simulation data only on the simulation thread: Singleton<SimulationManager>.instance.AddAction(() => { ... }).
// Debug.Log lines land in the game's log (`m2w native log --game cities_skylines --grep "[M2W]"`).
using ICities;
using UnityEngine;

namespace Memory2World
{
    public class Mod : IUserMod
    {
        public string Name { get { return "GameAnything"; } }
        public string Description { get { return "Places from your memories."; } }
        public void OnEnabled()
        {
            Application.runInBackground = true;          // keep running while its window is not in front: tests in her own game never need focus
            Debug.Log("[M2W] enabled");
        }
        public void OnDisabled() { }
    }

    public class Loading : LoadingExtensionBase
    {
        public override void OnLevelLoaded(LoadMode mode)
        {
            if (mode != LoadMode.NewGame && mode != LoadMode.LoadGame) return;
            Debug.Log("[M2W] city loaded (" + mode + ")");
        }
    }
}
