using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using ColossalFramework;
using ColossalFramework.UI;
using ColossalFramework.IO;
using ColossalFramework.Math;
using ICities;
using UnityEngine;

namespace M2WCity
{
    public partial class Host
    {
        IEnumerator Dispatch(string line)
        {
            var a = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
            switch (a[0])
            {
                case "dump": return CmdDump(a);
                case "terrain": return CmdTerrain(a);
                case "sea": return CmdSea(a);
                case "unlock": return CmdUnlock();
                case "cleartrees": ClearTrees(); return null;
                case "scatter": return CmdScatter(a);
                case "roads": return CmdRoads(a);
                case "objects": return CmdObjects(a);
                case "shot": return CmdShot(a);
                case "record": return CmdRecord(a, false);
                case "record&": StartCoroutine(CmdRecord(a, true)); return null;
                case "tour": return CmdTour(a);
                case "cine": return CmdCine(a);
                case "glow": return CmdGlow();
                case "watertex": return CmdWaterTex(a);
                case "cam": return CmdCam(a);
                case "time": SetHour(F(a[1])); return null;
                case "hold": holdHour = a.Length > 1 ? F(a[1]) : -1f; return null;
                case "speed": { var sm0 = Singleton<SimulationManager>.instance; sm0.ForcedSimulationPaused = false; sm0.SimulationPaused = a[1] == "0"; if (a[1] != "0") sm0.SelectedSimulationSpeed = int.Parse(a[1]); L("speed " + a[1] + ": paused " + sm0.SimulationPaused + " forced " + sm0.ForcedSimulationPaused + " final " + sm0.FinalSimulationSpeed); return null; }
                case "wait": return Wait(F(a[1]));
                case "name": SetName(line.Substring(5)); return null;
                case "save": return CmdSave(line.Substring(5));
                case "weather": return CmdWeather(a);
                case "signs": return CmdSigns(a);
                case "money": return CmdMoney();
                case "clearall": return CmdClearAll();
                case "watermap": return CmdWaterMap(a);
                case "waterinit": return CmdWaterInit();
                case "addsource": return CmdAddSource(a);
                case "waterfill": return CmdWaterFill(a);
                case "nosources": { var ws1 = Singleton<TerrainManager>.instance.WaterSimulation; for (ushort i = 1; i <= ws1.m_waterSources.m_size; i++) ws1.ReleaseWaterSource(i); L("water sources released"); return null; }
                case "sealevel": { var ws0 = Singleton<TerrainManager>.instance.WaterSimulation; ws0.m_nextSeaLevel = F(a[1]); ws0.m_currentSeaLevel = F(a[1]); ws0.m_resetWater = true; L("sea level set to " + a[1]); return null; }
                case "waterstat": return CmdWaterStat();
                case "enablewater": Singleton<TerrainManager>.instance.WaterSimulation.EnableWaterFlow(); L("EnableWaterFlow called"); return null;
                case "waterclear": return CmdWaterClear();
                case "wateri": return CmdWaterAt(a);
                case "paint": return CmdPaint(a);
                case "nograss": return CmdNoGrass(a);
                case "cleansurface": return CmdCleanSurface();
                case "findb": return CmdFindB(a);
                case "pave": return CmdPave(a);
                case "surface": return CmdSurface(a);
                case "grade": return CmdGrade(a);
                case "tint": return CmdTint(a);
                case "models": return CmdModels(a);
                case "quit": Application.Quit(); return null;
                case "closepanels": return CmdClosePanels();
                case "snap": return CmdSnap(a);
                case "clearobjects": return CmdClearObjects();
                case "fly": { var mm = memories.Find(x => x.id == a[1]); if (mm != null) Fly(mm); return null; }
                case "sky": { holdHour = -1f; if (a[1] == "sunset") { SetHour(SunsetHour); SetWeather(true); } else if (a[1] == "sunrise") { SetHour(SunriseHour); SetWeather(true); } else if (a[1] == "clear") { SetHour(12.5f); SetWeather(true); } else SetWeather(false); return null; }
                default: L("unknown command " + a[0]); return null;
            }
        }

        IEnumerator Wait(float s) { yield return new WaitForSeconds(s); }

        // ---------- information ----------
        IEnumerator CmdDump(string[] a)
        {
            var tm = Singleton<TerrainManager>.instance;
            var ws = tm.WaterSimulation;
            L("terrain: raw " + tm.RawHeights.Length + ", sea level " + ws.m_currentSeaLevel + ", water sources " + ws.m_waterSources.m_size);
            for (int i = 0; i < ws.m_waterSources.m_size; i++)
            {
                var s = ws.m_waterSources.m_buffer[i];
                L("  source " + (i + 1) + ": type " + s.m_type + " in " + s.m_inputPosition + " out " + s.m_outputPosition + " target " + s.m_target + " inRate " + s.m_inputRate + " outRate " + s.m_outputRate + " water " + s.m_water);
            }
            var bm = Singleton<BuildingManager>.instance; var nm = Singleton<NetManager>.instance; var tr = Singleton<TreeManager>.instance;
            L("objects: buildings " + bm.m_buildingCount + ", nodes " + nm.m_nodeCount + ", segments " + nm.m_segmentCount + ", trees " + tr.m_treeCount);
            var gm = Singleton<GameAreaManager>.instance;
            L("areas: unlocked " + gm.m_areaCount + " of " + gm.MaxAreaCount);
            L("money: " + Singleton<EconomyManager>.instance.LastCashAmount / 100);
            L("day hour " + Singleton<SimulationManager>.instance.m_currentDayTimeHour + " sunrise " + SimulationManager.SUNRISE_HOUR + " sunset " + SimulationManager.SUNSET_HOUR);
            if (a.Length > 1)
            {
                var sb = new StringBuilder();
                string what = a[1];
                if (what == "nets") { int n = PrefabCollection<NetInfo>.LoadedCount(); for (uint i = 0; i < n; i++) { var p = PrefabCollection<NetInfo>.GetLoaded(i); if (p != null) sb.Append(p.name + "; "); } }
                if (what == "buildings") { int n = PrefabCollection<BuildingInfo>.LoadedCount(); for (uint i = 0; i < n; i++) { var p = PrefabCollection<BuildingInfo>.GetLoaded(i); if (p != null && (a.Length < 3 || p.name.ToLower().Contains(a[2].ToLower()))) sb.Append(p.name + " [" + p.m_cellWidth + "x" + p.m_cellLength + " " + p.GetService() + "/" + p.GetSubService() + "]; "); } }
                if (what == "props") { int n = PrefabCollection<PropInfo>.LoadedCount(); for (uint i = 0; i < n; i++) { var p = PrefabCollection<PropInfo>.GetLoaded(i); if (p != null && (a.Length < 3 || p.name.ToLower().Contains(a[2].ToLower()))) sb.Append(p.name + "; "); } }
                if (what == "trees") { int n = PrefabCollection<TreeInfo>.LoadedCount(); for (uint i = 0; i < n; i++) { var p = PrefabCollection<TreeInfo>.GetLoaded(i); if (p != null) sb.Append(p.name + "; "); } }
                if (what == "heights") { var rh = Singleton<TerrainManager>.instance.RawHeights; var hb = new byte[rh.Length * 2]; Buffer.BlockCopy(rh, 0, hb, 0, hb.Length); File.WriteAllBytes(Path.Combine(dir, "dump_heights.raw"), hb); L("heights dumped: " + rh.Length + " cells (row 0 = south, uint16 LE, m*64)"); }
                L(what + ": " + sb.Length + " chars"); File.WriteAllText(Path.Combine(dir, "dump_" + what + ".txt"), sb.ToString().Replace("; ", "\n"));
            }
            yield return null;
        }

        // ---------- terrain and sea ----------
        void ClearTrees()
        {
            var tr = Singleton<TreeManager>.instance;
            int n = 0;
            for (uint i = 1; i < tr.m_trees.m_buffer.Length; i++)
                if ((tr.m_trees.m_buffer[i].m_flags & (ushort)TreeInstance.Flags.Created) != 0) { tr.ReleaseTree(i); n++; }
            L("trees removed: " + n);
        }

        IEnumerator CmdTerrain(string[] a)
        {
            var tm = Singleton<TerrainManager>.instance;
            var bytes = File.ReadAllBytes(Path.Combine(dataDir, a.Length > 1 ? a[1] : "terrain.raw"));
            if (bytes.Length != 1081 * 1081 * 2) { L("terrain.raw has " + bytes.Length + " bytes, expected " + 1081 * 1081 * 2); yield break; }
            ClearTrees();
            tm.SetRawHeightMap(bytes);
            L("heightmap written");
            yield return null; yield return null;
        }

        // sea x z : makes the ocean (one natural water source, level 40 m) at x,z
        IEnumerator CmdSea(string[] a)
        {
            var ws = Singleton<TerrainManager>.instance.WaterSimulation;
            for (ushort i = 1; i <= ws.m_waterSources.m_size; i++) ws.ReleaseWaterSource(i);
            float x = F(a[1]), z = F(a[2]);
            float level = a.Length > 3 ? F(a[3]) : 40f;
            for (int k = 0; k < (a.Length > 4 ? int.Parse(a[4]) : 1); k++)
            {
                var s = new WaterSource();
                s.m_type = WaterSource.TYPE_NATURAL;
                s.m_inputPosition = new Vector3(x, level, z + k * 600f);
                s.m_outputPosition = s.m_inputPosition;
                s.m_target = (ushort)((level + 26f) * 64f);
                s.m_inputRate = 32767; s.m_outputRate = 32767;
                ushort id = 0;
                bool ok = ws.CreateWaterSource(out id, s);
                L("sea source " + id + " " + ok);
            }
            yield return null;
        }

        IEnumerator CmdUnlock()
        {
            var gm = Singleton<GameAreaManager>.instance;
            Singleton<SimulationManager>.instance.AddAction(() => { try { Singleton<UnlockManager>.instance.UnlockAllProgressionMilestones(); L("all progression milestones unlocked"); } catch (Exception e) { L("milestones: " + e.Message); } });
            yield return new WaitForSeconds(1f);
            gm.m_maxAreaCount = 25;
            var bf = BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance;
            var fUpd = typeof(GameAreaManager).GetField("m_areasUpdated", bf);
            for (int i = 0; i < 25; i++)
                if (gm.m_areaGrid[i] == 0) { gm.m_areaCount++; gm.m_areaGrid[i] = gm.m_areaCount; }
            if (fUpd != null) fUpd.SetValue(gm, true);
            L("areas unlocked: " + gm.m_areaCount);
            yield return null;
        }

        IEnumerator CmdMoney()
        {
            var em = Singleton<EconomyManager>.instance;
            em.AddResource(EconomyManager.Resource.RewardAmount, 2000000000, ItemClass.Service.None, ItemClass.SubService.None, ItemClass.Level.None);
            L("money now " + em.LastCashAmount / 100);
            yield return null;
        }

        IEnumerator CmdClearAll()
        {
            var bm = Singleton<BuildingManager>.instance; var nm = Singleton<NetManager>.instance; var pm = Singleton<PropManager>.instance;
            int nb = 0, ns = 0, nn = 0, np = 0;
            for (int i = 1; i < nm.m_segments.m_buffer.Length; i++) { try { if ((nm.m_segments.m_buffer[i].m_flags & NetSegment.Flags.Created) != 0) { nm.ReleaseSegment((ushort)i, true); ns++; } } catch (Exception) { } }
            for (int i = 1; i < nm.m_nodes.m_buffer.Length; i++) { try { if ((nm.m_nodes.m_buffer[i].m_flags & NetNode.Flags.Created) != 0) { nm.ReleaseNode((ushort)i); nn++; } } catch (Exception) { } }
            for (int i = 1; i < bm.m_buildings.m_buffer.Length; i++) { try { if ((bm.m_buildings.m_buffer[i].m_flags & Building.Flags.Created) != 0) { bm.ReleaseBuilding((ushort)i); nb++; } } catch (Exception) { } }
            for (int i = 1; i < pm.m_props.m_buffer.Length; i++) { try { if ((pm.m_props.m_buffer[i].m_flags & (ushort)PropInstance.Flags.Created) != 0) { pm.ReleaseProp((ushort)i); np++; } } catch (Exception) { } }
            ClearTrees();
            L("cleared: segments " + ns + ", nodes " + nn + ", buildings " + nb + ", props " + np);
            yield return null;
        }

        // paint : natural-resource cells follow the new land (grass on land, nothing under the sea)
        // nograss cx cz w l : clear fertility (the grass blades) and give sand in every natural-resource cell (33.75 m) touched by the rectangle, e.g. under a paved plaza
        IEnumerator CmdNoGrass(string[] a)
        {
            var nr = Singleton<NaturalResourceManager>.instance;
            float cx = float.Parse(a[1]), cz = float.Parse(a[2]), w = float.Parse(a[3]), l = float.Parse(a[4]);
            const int n = 512; int cnt = 0, x0 = n, z0 = n, x1 = 0, z1 = 0;
            for (int z = 0; z < n; z++)
                for (int x = 0; x < n; x++)
                {
                    float wx = (x - 256 + 0.5f) * 33.75f, wz = (z - 256 + 0.5f) * 33.75f;
                    if (Mathf.Abs(wx - cx) > w * 0.5f + 17f || Mathf.Abs(wz - cz) > l * 0.5f + 17f) continue;
                    var c = nr.m_naturalResources[z * n + x]; c.m_fertility = 0; c.m_sand = 255; c.m_tree = 0;
                    nr.m_naturalResources[z * n + x] = c; cnt++; x0 = Mathf.Min(x0, x); z0 = Mathf.Min(z0, z); x1 = Mathf.Max(x1, x); z1 = Mathf.Max(z1, z);
                }
            if (cnt > 0) nr.AreaModified(x0, z0, x1, z1);
            L("nograss: " + cnt + " natural-resource cells");
            yield return null;
        }

        IEnumerator CmdPaint(string[] a)
        {
            var nr = Singleton<NaturalResourceManager>.instance;
            int sea = a.Length > 1 ? int.Parse(a[1]) : 1;
            int n = 512; int land = 0;
            for (int z = 0; z < n; z++)
                for (int x = 0; x < n; x++)
                {
                    float wx = (x - 256 + 0.5f) * 33.75f, wz = (z - 256 + 0.5f) * 33.75f;
                    float h = Ground(wx, wz);
                    var c = nr.m_naturalResources[z * n + x];
                    c.m_ore = 0; c.m_oil = 0; c.m_sand = 0; c.m_forest = 0; c.m_fertility = 0;
                    if (h < 40.5f) { if (sea == 0) c.m_sand = 255; else if (sea == 2) c.m_ore = 255; else if (sea == 3) c.m_fertility = 255; else if (sea == 4) c.m_oil = 255; }
                    else if (h < 41.6f) c.m_sand = 200;
                    else c.m_fertility = 255; c.m_tree = 0; c.m_burned = 0; c.m_destroyed = 0;
                    if (h > 41f) land++;
                    nr.m_naturalResources[z * n + x] = c;
                }
            nr.AreaModified(0, 0, n - 1, n - 1);
            L("painted natural resources; land cells " + land);
            yield return null;
        }

        // waterclear : remove every bit of water left from the base map (the three water buffers and the "has water" bitsets)
        IEnumerator CmdWaterClear()
        {
            var ws = Singleton<TerrainManager>.instance.WaterSimulation;
            var bf = BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance;
            var t = typeof(WaterSimulation);
            int n = 0;
            ws.BeginRead();
            try
            {
                var bufs = t.GetField("m_waterBuffers", bf).GetValue(ws) as Array;
                foreach (var b in bufs) { var arr = b as Array; if (arr != null) { Array.Clear(arr, 0, arr.Length); n++; } }
                foreach (var name in new[] { "m_waterExists1", "m_waterExists2", "m_waterExists3" })
                { var arr = t.GetField(name, bf).GetValue(ws) as Array; if (arr != null) Array.Clear(arr, 0, arr.Length); }
            }
            finally { ws.EndRead(); }
            for (int pz = 0; pz < 9; pz++) for (int px = 0; px < 9; px++) { try { ws.UpdatePatch(px, pz); } catch (Exception e) { L("patch " + px + "," + pz + ": " + e.Message); } }
            L("water buffers cleared: " + n);
            yield return null;
        }

        // wateri x z x z ... : log ground and water level at points
        IEnumerator CmdWaterAt(string[] a)
        {
            var tm = Singleton<TerrainManager>.instance;
            for (int i = 1; i + 1 < a.Length; i += 2)
            {
                float x = F(a[i]), z = F(a[i + 1]);
                L("point " + x + "," + z + ": ground " + tm.SampleRawHeightSmooth(new Vector3(x, 0, z)) + ", water " + tm.WaterLevel(new Vector2(x, z)));
            }
            yield return null;
        }

        IEnumerator CmdWaterStat()
        {
            var ws = Singleton<TerrainManager>.instance.WaterSimulation; var bf = BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance; var t = typeof(WaterSimulation);
            var sm = Singleton<SimulationManager>.instance;
            L("sim frame " + sm.m_currentFrameIndex + ", forced " + sm.ForcedSimulationPaused + ", focus " + Application.isFocused + ", paused " + sm.SimulationPaused + ", speed " + sm.SelectedSimulationSpeed + ", final " + sm.FinalSimulationSpeed);
            foreach (var n in new[] { "m_simulationStatus", "m_simulationFrameIndex", "m_renderingFrameIndex", "m_waterFrameIndex", "m_waterFrameIndex2", "m_stepIndex", "m_readLockCount" })
            { var f = t.GetField(n, bf); L("  " + n + " = " + (f == null ? "?" : "" + f.GetValue(ws))); }
            var th = t.GetField("m_simulationThread", bf).GetValue(ws) as System.Threading.Thread; L("  thread alive " + (th != null && th.IsAlive));
            yield return null;
        }

        // ---------- sea and pools: written directly, topped up while the city runs (the game's water leaks a little) ----------
        class Pool { public float x, z, w, l, level; }
        List<Pool> pools = new List<Pool>(); float seaLevel = 40f; bool keepWater; float lastTop;

        void LoadWaterPlan()
        {
            pools.Clear(); seaLevel = 40f; keepWater = false;
            var f = Path.Combine(dataDir, "water.txt");          // S|level   P|cx|cz|w|l|level
            if (!File.Exists(f)) return;
            foreach (var line in File.ReadAllLines(f))
            {
                var p = line.Split('|');
                if (p[0] == "S" && p.Length > 1) { seaLevel = F(p[1]); keepWater = true; }
                else if (p[0] == "P" && p.Length > 5) pools.Add(new Pool { x = F(p[1]), z = F(p[2]), w = F(p[3]), l = F(p[4]), level = F(p[5]) });
            }
            L("water plan: sea " + seaLevel + ", pools " + pools.Count + ", keep " + keepWater);
        }

        // raise the water in every cell whose ground is under `level` (inside the rectangle if given) up to `level`; never lowers anything
        int TopUp(float level, bool useRect, float cx, float cz, float w, float l)
        {
            var tm = Singleton<TerrainManager>.instance; var ws = tm.WaterSimulation;
            var bf = BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance;
            var bufs = typeof(WaterSimulation).GetField("m_waterBuffers", bf).GetValue(ws) as WaterSimulation.Cell[][];
            var raw = tm.RawHeights; int lv = (int)(level * 64f); int changed = 0;
            int r0 = 0, r1 = 1080, c0 = 0, c1 = 1080;
            if (useRect) { c0 = Mathf.Max(0, Mathf.FloorToInt((cx - w / 2f) / 16f + 540f)); c1 = Mathf.Min(1080, Mathf.CeilToInt((cx + w / 2f) / 16f + 540f)); r0 = Mathf.Max(0, Mathf.FloorToInt((cz - l / 2f) / 16f + 540f)); r1 = Mathf.Min(1080, Mathf.CeilToInt((cz + l / 2f) / 16f + 540f)); }
            foreach (var b in bufs)
                for (int r = r0; r <= r1; r++)
                    for (int c = c0; c <= c1; c++)
                    {
                        int i = r * 1081 + c; if (i >= b.Length) continue;
                        int d = lv - raw[i];
                        if (d > 0 && b[i].m_height < d) { b[i].m_height = (ushort)Mathf.Min(d, 65535); if (b == bufs[0]) changed++; }
                    }
            foreach (var name in new[] { "m_waterExists1", "m_waterExists2", "m_waterExists3" })
            { var arr = typeof(WaterSimulation).GetField(name, bf).GetValue(ws) as ulong[]; if (arr != null) for (int i = 0; i < arr.Length; i++) arr[i] = ulong.MaxValue; }
            return changed;
        }

        public void TopUpAll()
        {
            if (!keepWater && pools.Count == 0) return;
            int n = 0; var ws = Singleton<TerrainManager>.instance.WaterSimulation;
            ws.BeginRead();
            try { if (keepWater) n += TopUp(seaLevel, false, 0, 0, 0, 0); foreach (var p in pools) n += TopUp(p.level, true, p.x, p.z, p.w, p.l); }
            finally { ws.EndRead(); }
            lastTop = Time.realtimeSinceStartup;
        }

        // waterfill : load data/water.txt and write the water now (then re-apply the terrain so the render patches refresh)
        IEnumerator CmdWaterFill(string[] a)
        {
            LoadWaterPlan(); TopUpAll();
            L("water written: sea " + seaLevel + ", pools " + pools.Count);
            yield return null;
        }

        // addsource x z level [rate] : one more natural water source (kept for experiments)
        IEnumerator CmdAddSource(string[] a)
        {
            var ws = Singleton<TerrainManager>.instance.WaterSimulation;
            var s = new WaterSource(); float x = F(a[1]), z = F(a[2]), level = F(a[3]);
            s.m_type = WaterSource.TYPE_NATURAL; s.m_inputPosition = new Vector3(x, level, z); s.m_outputPosition = s.m_inputPosition;
            s.m_target = (ushort)((level + 26f) * 64f); uint rate = a.Length > 4 ? uint.Parse(a[4]) : 32767u; s.m_inputRate = rate; s.m_outputRate = rate;
            ushort id; bool ok = ws.CreateWaterSource(out id, s); L("source " + id + " at " + x + "," + z + " " + ok);
            yield return null;
        }

        // cleansurface : wipe the old map's painted surfaces (sand / gravel / pavement patches)
        IEnumerator CmdCleanSurface()
        {
            var tm = Singleton<TerrainManager>.instance;
            var surf = tm.RawSurface; Array.Clear(surf, 0, surf.Length);
            MarkWholeSurface(); FlushSurface();
            L("surface cleared (" + surf.Length + " cells)");
            yield return null;
        }

        // findb x z r : list buildings near a point
        IEnumerator CmdFindB(string[] a)
        {
            var bm = Singleton<BuildingManager>.instance; float x = F(a[1]), z = F(a[2]), r = F(a[3]); int n = 0, tot = 0;
            for (int i = 1; i < bm.m_buildings.m_buffer.Length; i++)
            {
                var b = bm.m_buildings.m_buffer[i];
                if ((b.m_flags & Building.Flags.Created) == 0) continue; tot++;
                if (Mathf.Abs(b.m_position.x - x) > r || Mathf.Abs(b.m_position.z - z) > r) continue;
                if (n++ < 40) L("  b" + i + " " + b.Info.name + " flags " + b.m_flags + " at " + b.m_position);
            }
            L("findb: " + n + " near, " + tot + " total");
            yield return null;
        }

        // buildings placed by the mod carry the Original flag; the game demolishes unzoned private buildings once a zone update touches them,
        // so the ZonesUpdated / Demolishing bits are cleared on them every few frames
        float lastKeep;
        void KeepBuildings()
        {
            if (!inCity || Time.realtimeSinceStartup - lastKeep < 0.15f) return;
            lastKeep = Time.realtimeSinceStartup;
            var bm = Singleton<BuildingManager>.instance; var buf = bm.m_buildings.m_buffer;
            const Building.Flags bad = Building.Flags.ZonesUpdated | Building.Flags.Demolishing;
            for (int i = 1; i < buf.Length; i++)
                if ((buf[i].m_flags & (Building.Flags.Created | Building.Flags.Original)) == (Building.Flags.Created | Building.Flags.Original) && (buf[i].m_flags & bad) != 0)
                    buf[i].m_flags &= ~bad;
        }

        IEnumerator CmdClearObjects()
        {
            var bm = Singleton<BuildingManager>.instance; var pm = Singleton<PropManager>.instance; int nb = 0, np = 0;
            for (int i = 1; i < bm.m_buildings.m_buffer.Length; i++) if ((bm.m_buildings.m_buffer[i].m_flags & (Building.Flags.Created | Building.Flags.Original)) == (Building.Flags.Created | Building.Flags.Original)) { bm.ReleaseBuilding((ushort)i); nb++; }
            for (int i = 1; i < pm.m_props.m_buffer.Length; i++) if ((pm.m_props.m_buffer[i].m_flags & (ushort)PropInstance.Flags.Created) != 0) { pm.ReleaseProp((ushort)i); np++; }
            ClearTrees();
            L("objects cleared: buildings " + nb + ", props " + np);
            yield return null;
        }

        // snap name : screenshot of the screen as it is, with the game's UI and the memory buttons
        IEnumerator CmdSnap(string[] a)
        {
            yield return new WaitForEndOfFrame();
            Application.CaptureScreenshot(Path.Combine(shotDir, a[1] + ".png"));
            yield return new WaitForSeconds(1.5f);
            L("snap " + a[1]);
        }

        // closepanels : close any modal dialog (the "Congratulations" milestone window opens after the unlock and blocks the Save panel)
        IEnumerator CmdClosePanels()
        {
            for (int i = 0; i < 6; i++)
            {
                try { if (UIView.HasModalInput()) { var mc = UIView.GetModalComponent(); L("closing modal " + (mc == null ? "?" : mc.name)); if (mc != null) mc.Hide(); UIView.PopModal(); } } catch (Exception e) { L("popmodal: " + e.Message); }
                yield return new WaitForSeconds(0.3f);
            }
            foreach (var n in new[] { "UnlockingPanel", "MilestonesPanel", "ChirpPanel" }) { try { UIView.library.Hide(n); } catch (Exception) { } }
            yield return null;
        }

        IEnumerator CmdWaterInit()
        {
            var tm = Singleton<TerrainManager>.instance;
            tm.WaterSimulation.Initialize(tm.RawHeights);
            L("water simulation re-initialised");
            yield return null;
        }

        // watermap name : 270x270 picture of the whole map: blue = water (darker = deeper), green = land (lighter = higher)
        IEnumerator CmdWaterMap(string[] a)
        {
            var tm = Singleton<TerrainManager>.instance; int n = 270; float step = 17280f / n;
            var tex = new Texture2D(n, n, TextureFormat.RGB24, false); int wet = 0;
            for (int j = 0; j < n; j++)
                for (int i = 0; i < n; i++)
                {
                    float x = -8640f + (i + 0.5f) * step, z = -8640f + (j + 0.5f) * step;
                    float g = tm.SampleRawHeightSmooth(new Vector3(x, 0, z));
                    float w = tm.WaterLevel(new Vector2(x, z));
                    float depth = w - g; Color c;
                    if (depth > 0.1f) { wet++; float d = Mathf.Clamp01(depth / 40f); c = new Color(0.1f, 0.3f - d * 0.15f, 0.9f - d * 0.5f); }
                    else { float k = Mathf.Clamp01((g - 40f) / 250f); c = new Color(0.2f + k * 0.7f, 0.55f + k * 0.3f, 0.2f + k * 0.2f); }
                    tex.SetPixel(i, j, c);
                }
            tex.Apply();
            File.WriteAllBytes(Path.Combine(shotDir, a[1] + ".png"), tex.EncodeToPNG()); Destroy(tex);
            L("watermap " + a[1] + ": wet cells " + wet + " of " + n * n);
            yield return null;
        }

        float Height(float x, float z) { return Singleton<TerrainManager>.instance.SampleRawHeightSmoothWithWater(new Vector3(x, 0, z), false, 0f); }
        float Ground(float x, float z) { return Singleton<TerrainManager>.instance.SampleRawHeightSmooth(new Vector3(x, 0, z)); }

        // scatter treeName count seed minAbove maxAbove : trees on land (above sea level by min..max metres)
        IEnumerator CmdScatter(string[] a)
        {
            var info = PrefabCollection<TreeInfo>.FindLoaded(a[1]);
            if (info == null) { L("no tree " + a[1]); yield break; }
            int count = int.Parse(a[2]); var rnd = new System.Random(int.Parse(a[3]));
            float lo = F(a[4]), hi = F(a[5]); int placed = 0;
            var tr = Singleton<TreeManager>.instance;
            var r = new Randomizer(1);
            for (int i = 0; i < count * 4 && placed < count; i++)
            {
                float x = (float)(rnd.NextDouble() * 2 - 1) * 8000f, z = (float)(rnd.NextDouble() * 2 - 1) * 8000f;
                float g = Ground(x, z) - 40f;
                if (g < lo || g > hi) continue;
                uint id;
                if (tr.CreateTree(out id, ref r, info, new Vector3(x, Ground(x, z), z), false)) placed++;
            }
            L("scattered " + placed + " x " + a[1]);
            yield return null;
        }

        // ---------- roads: lines "R|NetInfoName|x,z x,z x,z" ----------
        IEnumerator CmdRoads(string[] a)
        {
            var nm = Singleton<NetManager>.instance; var sm = Singleton<SimulationManager>.instance;
            var file = Path.Combine(dataDir, a.Length > 1 ? a[1] : "roads.txt");
            var nodes = new Dictionary<long, ushort>();
            var infos = new Dictionary<string, NetInfo>();
            int segs = 0, skipped = 0, nds = 0, lines = 0; var r = new Randomizer(7);
            foreach (var line in File.ReadAllLines(file))
            {
                var f = line.Split('|');
                if (f.Length < 3 || f[0] != "R") continue;
                NetInfo info;
                if (!infos.TryGetValue(f[1], out info)) { info = PrefabCollection<NetInfo>.FindLoaded(f[1]); infos[f[1]] = info; if (info == null) L("no net " + f[1]); }
                if (info == null) { skipped++; continue; }
                var pts = new List<Vector2>();
                foreach (var p in f[2].Split(' ')) { var c = p.Split(','); pts.Add(new Vector2(F(c[0]), F(c[1]))); }
                for (int i = 0; i < pts.Count; i++)
                {
                    float ty = Height(pts[i].x, pts[i].y);
                }
                ushort prev = 0; Vector2 prevP = Vector2.zero; int prevI = -1;
                for (int i = 0; i < pts.Count; i++)
                {
                    var p = pts[i];
                    if (Height(p.x, p.y) < 40.6f) { prev = 0; prevI = -1; continue; }          // under water: break the road here
                    long key = ((long)Mathf.RoundToInt(p.x * 2f)) * 1000003L + Mathf.RoundToInt(p.y * 2f);
                    ushort n;
                    if (!nodes.TryGetValue(key, out n))
                    {
                        if (!nm.CreateNode(out n, ref r, info, new Vector3(p.x, Height(p.x, p.y), p.y), sm.m_currentBuildIndex)) { prev = 0; prevI = -1; skipped++; continue; }
                        sm.m_currentBuildIndex++; nodes[key] = n; nds++;
                    }
                    if (prev != 0 && prev != n)
                    {
                        Vector2 d0 = TangentAt(pts, prevI), d1 = TangentAt(pts, i);
                        var sd = new Vector3(d0.x, 0, d0.y); var ed = new Vector3(-d1.x, 0, -d1.y);
                        ushort seg;
                        if (nm.CreateSegment(out seg, ref r, info, prev, n, sd, ed, sm.m_currentBuildIndex, sm.m_currentBuildIndex, false)) { segs++; sm.m_currentBuildIndex++; }
                        else skipped++;
                    }
                    prev = n; prevI = i;
                }
                if (++lines % 40 == 0) yield return null;
            }
            L("roads: " + lines + " lines, " + nds + " nodes, " + segs + " segments, skipped " + skipped);
            yield return null;
        }

        static Vector2 TangentAt(List<Vector2> pts, int i)
        {
            Vector2 d;
            if (i <= 0) d = pts[1] - pts[0]; else if (i >= pts.Count - 1) d = pts[i] - pts[i - 1]; else d = pts[i + 1] - pts[i - 1];
            return d.normalized;
        }

        // ---------- objects: B|prefab|x|z|angleDeg   P|prop|x|z|angleDeg   T|tree|x|z ----------
        IEnumerator CmdObjects(string[] a)
        {
            var file = Path.Combine(dataDir, a.Length > 1 ? a[1] : "objects.txt");
            var bm = Singleton<BuildingManager>.instance; var pm = Singleton<PropManager>.instance; var tm = Singleton<TreeManager>.instance; var sm = Singleton<SimulationManager>.instance;
            var r = new Randomizer(11); int nb = 0, np = 0, nt = 0, bad = 0, k = 0;
            foreach (var line in File.ReadAllLines(file))
            {
                var f = line.Split('|');
                if (f.Length < 4) continue;
                float x = F(f[2]), z = F(f[3]); float ang = f.Length > 4 ? F(f[4]) * Mathf.Deg2Rad : 0f;
                float y = f.Length > 5 && f[5].Length > 0 ? F(f[5]) : Ground(x, z);
                if (f[0] == "B")
                {
                    var info = PrefabCollection<BuildingInfo>.FindLoaded(f[1]);
                    if (info == null) { L("no building " + f[1]); bad++; continue; }
                    ushort id;
                    if (bm.CreateBuilding(out id, ref r, info, new Vector3(x, y, z), ang, info.m_cellLength, sm.m_currentBuildIndex))
                    {
                        sm.m_currentBuildIndex++; nb++;
                        bm.m_buildings.m_buffer[id].m_flags |= Building.Flags.Original | Building.Flags.Completed;
                    }
                    else { L("building failed " + f[1] + " at " + x + "," + z); bad++; }
                }
                else if (f[0] == "P")
                {
                    var info = PrefabCollection<PropInfo>.FindLoaded(f[1]);
                    if (info == null) { L("no prop " + f[1]); bad++; continue; }
                    ushort id;
                    if (pm.CreateProp(out id, ref r, info, new Vector3(x, y, z), ang, true)) np++; else bad++;
                }
                else if (f[0] == "T")
                {
                    var info = PrefabCollection<TreeInfo>.FindLoaded(f[1]);
                    if (info == null) { L("no tree " + f[1]); bad++; continue; }
                    uint id;
                    if (tm.CreateTree(out id, ref r, info, new Vector3(x, y, z), true)) nt++; else bad++;
                }
                if (++k % 50 == 0) yield return null;
            }
            L("objects: buildings " + nb + ", props " + np + ", trees " + nt + ", failed " + bad);
            yield return null;
        }

        // ---------- camera and screenshots ----------
        public static void Cam(Vector3 pos, float dist, float yaw, float pitch)
        {
            var cc = Singleton<CameraController>.instance;
            cc.m_targetPosition = pos; cc.m_currentPosition = pos;
            cc.m_targetSize = dist; cc.m_currentSize = dist;
            cc.m_targetAngle = new Vector2(yaw, pitch); cc.m_currentAngle = new Vector2(yaw, pitch);
            camP = pos; camDist = dist; camYaw = yaw; camPitch = pitch; camEye = false; camPoseSet = true;   // while CamLift() is active Host.LateUpdate applies this pose to the transform directly
        }

        IEnumerator CmdCam(string[] a)
        {
            float x = F(a[1]), z = F(a[2]);
            Cam(new Vector3(x, Ground(x, z), z), F(a[3]), F(a[4]), F(a[5]));
            yield return null;
        }

        // shot name x z dist yaw pitch [ui]
        IEnumerator CmdShot(string[] a)
        {
            float x = F(a[2]), z = F(a[3]);
            bool ui = a.Length > 7 && a[7] == "ui";
            CamLift();                                       // close views (dist < 40, low pitch) are not clamped by the game while the shot is taken
            try
            {
                Cam(new Vector3(x, Ground(x, z), z), F(a[4]), F(a[5]), F(a[6]));
                yield return new WaitForSeconds(2.5f);
                var path = Path.Combine(shotDir, a[1] + ".png");
                if (ui) { Application.CaptureScreenshot(path); yield return new WaitForSeconds(1.5f); }
                else
                {
                    yield return new WaitForEndOfFrame();
                    int W = 1920, Hh = 1080;
                    var cam = Singleton<CameraController>.instance.GetComponent<Camera>();
                    var rt = MakeCaptureRT(W, Hh, 8); var old = cam.targetTexture;
                    cam.targetTexture = rt; cam.Render(); cam.targetTexture = old;
                    RenderTexture.active = rt;
                    var tex = new Texture2D(W, Hh, TextureFormat.RGB24, false);
                    tex.ReadPixels(new Rect(0, 0, W, Hh), 0, 0); tex.Apply();
                    File.WriteAllBytes(path, tex.EncodeToPNG());
                    RenderTexture.active = null; Destroy(rt); Destroy(tex);
                }
                L("shot " + path);
            }
            finally { CamUnlift(); }
        }
        bool hideGui;

        // ---------- time and weather ----------
        float holdHour = -1f;
        public void SetHour(float hour)
        {
            var sm = Singleton<SimulationManager>.instance;
            uint total = SimulationManager.DAYTIME_FRAMES;
            uint target = (uint)(hour * SimulationManager.DAYTIME_HOUR_TO_FRAME) % total;
            sm.m_dayTimeOffsetFrames = (target + total - (sm.m_currentFrameIndex % total)) % total;
            sm.m_dayTimeFrame = target;
            sm.m_currentDayTimeHour = hour;
            L("hour set to " + hour);
        }
        void HoldTimeTick() { if (holdHour >= 0f && inCity) { var sm = Singleton<SimulationManager>.instance; if (Mathf.Abs(sm.m_currentDayTimeHour - holdHour) > 0.02f) SetHour(holdHour); } }

        public void SetWeather(bool clear)
        {
            var w = Singleton<WeatherManager>.instance;
            if (clear) { w.m_enableWeather = false; w.m_currentRain = w.m_targetRain = 0f; w.m_currentFog = w.m_targetFog = 0f; w.m_currentCloud = w.m_targetCloud = 0f; w.m_groundWetness = 0f; }
            else w.m_enableWeather = true;
        }
        IEnumerator CmdWeather(string[] a) { SetWeather(a[1] == "clear"); yield return null; }

        void SetName(string name) { Singleton<SimulationManager>.instance.m_metaData.m_CityName = name; L("city name " + name); }

        IEnumerator CmdSave(string name)
        {
            SetName(name);
            for (int i = 0; i < 6; i++) { try { if (UIView.HasModalInput()) { var mc = UIView.GetModalComponent(); if (mc != null) mc.Hide(); UIView.PopModal(); } } catch (Exception) { } yield return new WaitForSeconds(0.2f); }
            SavePanel panel = null;
            UIComponent comp = null;
            try { comp = UIView.library.ShowModal("SavePanel"); } catch (Exception e) { L("ShowModal: " + e.Message); }
            for (int i = 0; i < 40 && panel == null; i++)
            {
                yield return new WaitForSeconds(0.5f);
                panel = FindObjectOfType<SavePanel>();
                if (panel == null && comp != null) panel = comp.GetComponent<SavePanel>();
                if (panel == null) { try { var c2 = UIView.library.Get("SavePanel"); if (c2 != null) panel = c2.GetComponent<SavePanel>(); } catch (Exception) { } }
            }
            if (panel == null) { L("save failed: no SavePanel"); yield break; }
            bool ok = panel.SaveGame(name);
            L("SaveGame requested: " + ok);
            yield return new WaitForSeconds(15f);
            L("save window over; saves folder: " + DataLocation.saveLocation);
        }
    }
}
