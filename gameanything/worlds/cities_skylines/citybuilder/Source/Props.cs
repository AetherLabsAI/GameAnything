// Surface painting, look (colour grading / material tints) and procedural 3D props. Generic: all positions come from data/*.txt.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using ColossalFramework;
using ICities;
using UnityEngine;

namespace M2WCity
{
    public partial class Host
    {
        GameObject modelRoot;
        Texture3D customLut;

        // ---------- automatic re-apply after every city load ----------
        public IEnumerator AutoApply()
        {
            yield return new WaitForSeconds(3f);
            try { ApplyLook(); } catch (Exception e) { L("auto look: " + e.Message); }
            try { BuildModels(); } catch (Exception e) { L("auto models: " + e.Message); }
            try
            {
                // the painted surface is stored in the saved city, so only redo it when asked to (data/surface.onload exists)
                if (File.Exists(Path.Combine(dataDir, "surface.onload"))) ApplySurfaceFile();
            }
            catch (Exception e) { L("auto surface: " + e.Message); }
        }

        void DestroyModels()
        {
            try { if (modelRoot != null) Destroy(modelRoot); } catch (Exception) { }
            modelRoot = null; glows.Clear(); ClearMovers();
        }

        string[] ReadData(string name)
        {
            var f = Path.Combine(dataDir, name);
            if (!File.Exists(f)) { L(name + ": not found"); return new string[0]; }
            return File.ReadAllLines(f);
        }

        // ---------- 1. surface painting ----------
        // pave type cx cz w l angleDeg : one rectangle.  surface : every U line of data/surface.txt
        IEnumerator CmdPave(string[] a)
        {
            try
            {
                if (a.Length < 7) { L("usage: pave type cx cz w l angleDeg"); yield break; }
                int n = PaintRect(a[1], F(a[2]), F(a[3]), F(a[4]), F(a[5]), F(a[6]));
                FlushSurface();
                L("pave " + a[1] + ": " + n + " cells");
            }
            catch (Exception e) { L("pave: " + e); }
            yield return null;
        }

        IEnumerator CmdSurface(string[] a)
        {
            try { ApplySurfaceFile(); } catch (Exception e) { L("surface: " + e); }
            yield return null;
        }

        void ApplySurfaceFile()
        {
            int rects = 0, cells = 0;
            foreach (var raw in ReadData("surface.txt"))
            {
                var l = raw.Trim();
                if (l.Length == 0 || l[0] == '#' || !l.StartsWith("U|")) continue;
                var f = l.Split('|');
                try { cells += PaintRect(f[1], F(f[2]), F(f[3]), F(f[4]), F(f[5]), f.Length > 6 ? F(f[6]) : 0f); rects++; }
                catch (Exception e) { L("surface line '" + l + "': " + e.Message); }
            }
            FlushSurface();   // ONE terrain update for the union of all rectangles
            L("surface: " + rects + " rectangles, " + cells + " cells");
        }

        // Union (in cell units) of everything PaintRect wrote since the last FlushSurface.
        bool surfDirty; int sdx0, sdz0, sdx1, sdz1;
        void MarkSurface(int x0, int z0, int x1, int z1)
        {
            if (!surfDirty) { sdx0 = x0; sdz0 = z0; sdx1 = x1; sdz1 = z1; surfDirty = true; return; }
            sdx0 = Mathf.Min(sdx0, x0); sdz0 = Mathf.Min(sdz0, z0); sdx1 = Mathf.Max(sdx1, x1); sdz1 = Mathf.Max(sdz1, z1);
        }

        public void MarkWholeSurface() { MarkSurface(0, 0, 1079, 1079); }

        // TerrainModify.UpdateArea has a float overload (world metres, converted with x/16+540 -/+2 and NOT clamped) and an int overload (cells).
        // Called outside Begin/EndUpdateArea it only queues the area and the next unrelated EndUpdateArea (a road being built, on the simulation
        // thread) flushes it, which is where "Array index is out of range ... UpdateAreaImplementation" came from. So: clamp to the 1080 grid,
        // use the int overload, tile big areas (the game's temp buffers hold about 128 cells), and do it on the simulation thread inside Begin/End.
        public void FlushSurface()
        {
            if (!surfDirty) return;
            surfDirty = false;
            int ax0 = Mathf.Clamp(sdx0 - 2, 0, 1079), az0 = Mathf.Clamp(sdz0 - 2, 0, 1079), ax1 = Mathf.Clamp(sdx1 + 2, 0, 1079), az1 = Mathf.Clamp(sdz1 + 2, 0, 1079);
            if (ax1 < ax0 || az1 < az0) return;
            Singleton<SimulationManager>.instance.AddAction(() =>
            {
                const int TILE = 96; int tiles = 0;
                try
                {
                    for (int z = az0; z <= az1; z += TILE)
                        for (int x = ax0; x <= ax1; x += TILE)
                        {
                            TerrainModify.BeginUpdateArea();
                            try { TerrainModify.UpdateArea(x, z, Mathf.Min(x + TILE - 1, ax1), Mathf.Min(z + TILE - 1, az1), false, true, false); tiles++; }
                            finally { TerrainModify.EndUpdateArea(); }
                        }
                    L("surface updated: cells " + ax0 + "," + az0 + " .. " + ax1 + "," + az1 + " in " + tiles + " tile(s)");
                }
                catch (Exception e) { L("surface update: " + e); }
            });
        }

        // Writes straight into TerrainManager.RawSurface (1080x1080 cells of 16 m, index = cellZ*1080+cellX, z grows north),
        // then asks the terrain to refresh that area. Rectangle edges are feathered over one cell.
        int PaintRect(string type, float cx, float cz, float w, float l, float angleDeg)
        {
            var tm = Singleton<TerrainManager>.instance;
            var surf = tm.RawSurface;
            const int N = 1080; const float CELL = 16f;
            float rad = angleDeg * Mathf.Deg2Rad, ca = Mathf.Cos(rad), sa = Mathf.Sin(rad);
            // local axes: u along the rectangle width, v along its length; the length looks along (sin a, cos a) like the props
            float ux = ca, uz = -sa, vx = sa, vz = ca;
            float r = 0.5f * (Mathf.Abs(w * ux) + Mathf.Abs(l * vx)) + CELL, rz = 0.5f * (Mathf.Abs(w * uz) + Mathf.Abs(l * vz)) + CELL;
            int x0 = Mathf.Max(0, (int)Mathf.Floor((cx - r + 8640f) / CELL)), x1 = Mathf.Min(N - 1, (int)Mathf.Floor((cx + r + 8640f) / CELL));
            int z0 = Mathf.Max(0, (int)Mathf.Floor((cz - rz + 8640f) / CELL)), z1 = Mathf.Min(N - 1, (int)Mathf.Floor((cz + rz + 8640f) / CELL));
            string t = type.ToLowerInvariant(); int count = 0;
            for (int j = z0; j <= z1; j++)
                for (int i = x0; i <= x1; i++)
                {
                    float px = -8640f + (i + 0.5f) * CELL - cx, pz = -8640f + (j + 0.5f) * CELL - cz;
                    float du = px * ux + pz * uz, dv = px * vx + pz * vz;
                    float cover = Mathf.Clamp01(Mathf.Min((w * 0.5f - Mathf.Abs(du)) / CELL + 0.5f, (l * 0.5f - Mathf.Abs(dv)) / CELL + 0.5f));
                    if (cover <= 0f) continue;
                    byte val = (byte)Mathf.RoundToInt(255f * cover);
                    int idx = j * N + i; var c = surf[idx];
                    switch (t)
                    {
                        case "pavementa": c.m_pavementA = (byte)Mathf.Max(c.m_pavementA, val); c.m_pavementB = (byte)(c.m_pavementB * (1f - cover)); break;
                        case "pavementb": c.m_pavementB = (byte)Mathf.Max(c.m_pavementB, val); c.m_pavementA = (byte)(c.m_pavementA * (1f - cover)); break;
                        case "gravel": c.m_gravel = (byte)Mathf.Max(c.m_gravel, val); break;
                        case "ruined": c.m_ruined = (byte)Mathf.Max(c.m_ruined, val); break;
                        case "field": c.m_field = (byte)Mathf.Max(c.m_field, val); break;
                        case "clip": c.m_clipped = (byte)Mathf.Max(c.m_clipped, val); break;
                        case "none": case "clear":
                            c.m_pavementA = (byte)(c.m_pavementA * (1f - cover)); c.m_pavementB = (byte)(c.m_pavementB * (1f - cover));
                            c.m_gravel = (byte)(c.m_gravel * (1f - cover)); c.m_ruined = (byte)(c.m_ruined * (1f - cover)); c.m_field = (byte)(c.m_field * (1f - cover)); break;
                        default: throw new Exception("unknown surface type " + type + " (PavementA, PavementB, Gravel, Ruined, Field, Clip, None)");
                    }
                    surf[idx] = c; count++;
                }
            if (x1 >= x0 && z1 >= z0) MarkSurface(x0, z0, x1, z1);
            return count;
        }

        // ---------- 2. look ----------
        static readonly string[] ColorProps = {
            "_Color", "_MainColor", "_BaseColor", "_Tint", "_TintColor", "_WaterColor", "_ShoreColor", "_DeepColor", "_ShallowColor", "_SeaColor",
            "_FoamColor", "_SpecColor", "_ReflectionColor", "_SkyColor", "_SandColor", "_GrassColor", "_GrassTint", "_TerrainColor", "_FogColor",
            "_ColorA", "_ColorB", "_Color1", "_Color2", "_WaterColor1", "_WaterColor2", "_DepthColor", "_SurfaceColor", "_TransparentColor", "_Emission", "_EmissionColor" };
        static readonly string[] FloatProps = {
            "_Glossiness", "_Shininess", "_Smoothness", "_Metallic", "_Cutoff", "_Saturation", "_Brightness", "_Contrast", "_Transparency", "_Alpha",
            "_Opacity", "_WaterTransparency", "_Depth", "_FoamAmount", "_Fresnel", "_Distortion", "_Gloss", "_Spec", "_SpecPower", "_Intensity", "_Exposure" };
        static readonly string[] TexProps = { "_MainTex", "_BumpMap", "_SurfaceTexA", "_SurfaceTexB", "_HeightMap", "_WaterMap", "_ShoreTex", "_FoamTex", "_NormalTex", "_ReflectionTex", "_RefractionTex", "_GrassDiffuseTex", "_RuinedDiffuseTex", "_PavementDiffuseTex", "_GravelDiffuseTex", "_CliffDiffuseTex", "_SandDiffuseTex" };

        Material MatByName(string n)
        {
            var tm = Singleton<TerrainManager>.instance;
            switch (n.ToLowerInvariant())
            {
                case "terrain": return tm.m_terrainMaterial;
                case "water": return tm.m_waterMaterial;
                case "watert": case "watertransparent": return tm.m_waterTransparentMaterial;
                case "topography": return tm.m_topographyMaterial;
                case "decoration": return tm.m_decorationMaterial;
            }
            return null;
        }

        void ProbeMaterials()
        {
            foreach (var n in new[] { "terrain", "water", "watert", "topography", "decoration" })
            {
                var m = MatByName(n);
                if (m == null) { L("probe " + n + ": (null)"); continue; }
                var sb = new StringBuilder();
                foreach (var p in ColorProps) if (m.HasProperty(p)) { string v = ""; try { v = m.GetColor(p).ToString(); } catch (Exception) { } sb.Append(p + "=" + v + "; "); }
                foreach (var p in FloatProps) if (m.HasProperty(p)) { string v = ""; try { v = m.GetFloat(p).ToString(CultureInfo.InvariantCulture); } catch (Exception) { } sb.Append(p + "=" + v + "; "); }
                foreach (var p in TexProps) if (m.HasProperty(p)) sb.Append(p + "(tex); ");
                L("probe " + n + ": shader " + (m.shader == null ? "?" : m.shader.name) + ", queue " + m.renderQueue + " :: " + sb);
            }
        }

        // tint [probe] : apply data/look.txt (key=value lines). Keys:
        //   grade=<LUT name | none | custom>
        //   lut.saturation / lut.contrast / lut.brightness / lut.gamma = number, lut.tint = r,g,b   (used by grade=custom)
        //   <terrain|water|watert|topography|decoration>.<_Property> = number | r,g,b[,a]
        IEnumerator CmdTint(string[] a)
        {
            try { if (a.Length > 1 && a[1] == "probe") ProbeMaterials(); else ApplyLook(); } catch (Exception e) { L("tint: " + e); }
            yield return null;
        }

        void ApplyLook()
        {
            var kv = new Dictionary<string, string>(); var order = new List<string>();
            foreach (var raw in ReadData("look.txt"))
            {
                var l = raw.Trim(); if (l.Length == 0 || l[0] == '#') continue;
                int eq = l.IndexOf('='); if (eq <= 0) continue;
                var k = l.Substring(0, eq).Trim(); if (!kv.ContainsKey(k)) order.Add(k);
                kv[k] = l.Substring(eq + 1).Trim();
            }
            string grade = null; kv.TryGetValue("grade", out grade);
            lutParams = kv;
            foreach (var k in order)
            {
                if (k == "grade" || k.StartsWith("lut.") || k.StartsWith("hour.") || k == "water.mipbias" || k == "water.aniso") continue;
                try
                {
                    int dot = k.IndexOf('.'); if (dot <= 0) { L("look: bad key " + k); continue; }
                    var m = MatByName(k.Substring(0, dot)); string prop = k.Substring(dot + 1);
                    if (m == null) { L("look: no material " + k); continue; }
                    if (!m.HasProperty(prop)) { L("look: " + k + " not a property of " + (m.shader == null ? "?" : m.shader.name)); continue; }
                    var parts = kv[k].Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length == 1) m.SetFloat(prop, F(parts[0]));
                    else if (parts.Length >= 3) m.SetColor(prop, new Color(F(parts[0]), F(parts[1]), F(parts[2]), parts.Length > 3 ? F(parts[3]) : 1f));
                    L("look: " + k + " = " + kv[k]);
                }
                catch (Exception e) { L("look " + k + ": " + e.Message); }
            }
            if (!string.IsNullOrEmpty(grade)) SetGrade(grade);
            if (kv.ContainsKey("water.mipbias") || kv.ContainsKey("water.aniso")) { try { WaterTex(false); L("look: water texture filtering applied"); } catch (Exception e) { L("look watertex: " + e.Message); } }
        }

        Dictionary<string, string> lutParams = new Dictionary<string, string>();

        float LutF(string key, float def) { string s; return lutParams.TryGetValue(key, out s) ? F(s) : def; }

        // grade list | grade <name> | grade none | grade custom (builds a LUT from lut.* keys of look.txt)
        IEnumerator CmdGrade(string[] a)
        {
            try
            {
                var mgr = UnityEngine.Object.FindObjectOfType<ColorCorrectionManager>();
                if (mgr == null) { L("grade: no ColorCorrectionManager"); yield break; }
                if (a.Length < 2 || a[1] == "list") { L("grade: LUTs: " + string.Join("; ", mgr.items) + "; (and 'custom')"); yield break; }
                if (a[1] == "custom") { ReadLookParamsOnly(); }
                SetGrade(string.Join(" ", a, 1, a.Length - 1));
            }
            catch (Exception e) { L("grade: " + e); }
            yield return null;
        }

        void ReadLookParamsOnly()
        {
            var kv = new Dictionary<string, string>();
            foreach (var raw in ReadData("look.txt")) { var l = raw.Trim(); int eq = l.IndexOf('='); if (l.Length == 0 || l[0] == '#' || eq <= 0) continue; kv[l.Substring(0, eq).Trim()] = l.Substring(eq + 1).Trim(); }
            lutParams = kv;
        }

        void SetGrade(string name)
        {
            var mgr = UnityEngine.Object.FindObjectOfType<ColorCorrectionManager>();
            if (mgr == null) { L("grade: no ColorCorrectionManager"); return; }
            if (name == "custom") { mgr.SetLUT(BuildCustomLut()); L("grade: custom LUT applied"); return; }
            var items = mgr.items;
            if (name == "none") { mgr.currentSelection = 0; L("grade: none"); return; }
            for (int i = 0; i < items.Length; i++)
                if (string.Equals(items[i], name, StringComparison.OrdinalIgnoreCase)) { mgr.currentSelection = i; L("grade: " + items[i]); return; }
            L("grade: no LUT '" + name + "'. Available: " + string.Join("; ", items));
        }

        Texture3D BuildCustomLut()
        {
            const int S = 32;
            float sat = LutF("lut.saturation", 1.2f), con = LutF("lut.contrast", 1f), bri = LutF("lut.brightness", 1f), gam = LutF("lut.gamma", 1f);
            float tr = 1f, tg = 1f, tb = 1f; string ts;
            if (lutParams.TryGetValue("lut.tint", out ts)) { var p = ts.Split(','); if (p.Length >= 3) { tr = F(p[0]); tg = F(p[1]); tb = F(p[2]); } }
            if (customLut != null) { try { Destroy(customLut); } catch (Exception) { } }
            var tex = new Texture3D(S, S, S, TextureFormat.RGB24, false);
            tex.wrapMode = TextureWrapMode.Clamp; tex.filterMode = FilterMode.Bilinear;
            var px = new Color[S * S * S];
            for (int b = 0; b < S; b++)
                for (int g = 0; g < S; g++)
                    for (int r = 0; r < S; r++)
                    {
                        float cr = r / (S - 1f), cg = g / (S - 1f), cb = b / (S - 1f);
                        float lum = cr * 0.299f + cg * 0.587f + cb * 0.114f;
                        cr = lum + (cr - lum) * sat; cg = lum + (cg - lum) * sat; cb = lum + (cb - lum) * sat;
                        cr = (cr - 0.5f) * con + 0.5f; cg = (cg - 0.5f) * con + 0.5f; cb = (cb - 0.5f) * con + 0.5f;
                        cr *= bri * tr; cg *= bri * tg; cb *= bri * tb;
                        if (gam != 1f) { cr = Mathf.Pow(Mathf.Max(0f, cr), 1f / gam); cg = Mathf.Pow(Mathf.Max(0f, cg), 1f / gam); cb = Mathf.Pow(Mathf.Max(0f, cb), 1f / gam); }
                        px[r + g * S + b * S * S] = new Color(Mathf.Clamp01(cr), Mathf.Clamp01(cg), Mathf.Clamp01(cb), 1f);
                    }
            tex.SetPixels(px); tex.Apply(false);
            customLut = tex;
            L("custom LUT: sat " + sat + " contrast " + con + " brightness " + bri + " gamma " + gam + " tint " + tr + "," + tg + "," + tb);
            return tex;
        }

        // ---------- 3. procedural props ----------
        // models : (re)build everything in data/models.txt: K|kind|x|z|angleDeg|scale  (kind: sealion, tower, statue)
        //          K|obj|name|x|z|angleDeg|scale|y[|move=..][|id=..]   and   K|objherd|name|cx|cz|radius|count|scale|seed   (OBJ files, see README)
        //          the model's front (head) looks along (sin a, cos a) in (x, z)
        IEnumerator CmdModels(string[] a)
        {
            try { BuildModels(); } catch (Exception e) { L("models: " + e); }
            yield return null;
        }

        Shader propShader; string propShaderName;

        Material MakeMat(Color c)
        {
            if (propShader == null)
            {
                foreach (var n in new[] { "Diffuse", "Legacy Shaders/Diffuse", "Standard", "Mobile/Diffuse", "Unlit/Color", "Sprites/Default" })
                {
                    Shader s = null; try { s = Shader.Find(n); } catch (Exception) { }
                    if (s != null) { propShader = s; propShaderName = n; break; }
                }
                L("prop shader: " + (propShaderName ?? "NONE"));
            }
            Material m = propShader != null ? new Material(propShader) : new Material(Shader.Find("Sprites/Default"));
            m.color = c; return m;
        }

        GameObject Part(Transform parent, PrimitiveType t, string name, Vector3 pos, Vector3 scale, Color col, Vector3 euler)
        {
            var g = GameObject.CreatePrimitive(t); g.name = name;
            var cl = g.GetComponent<Collider>(); if (cl != null) Destroy(cl);
            g.transform.SetParent(parent, false);
            g.transform.localPosition = pos; g.transform.localScale = scale; g.transform.localRotation = Quaternion.Euler(euler);
            var r = g.GetComponent<Renderer>(); r.material = MakeMat(col);
            r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On; r.receiveShadows = true;
            return g;
        }

        void BuildModels()
        {
            DestroyModels();
            modelRoot = new GameObject("M2WModels");
            LoadPaths();
            int n = 0;
            foreach (var raw in ReadData("models.txt"))
            {
                var l = raw.Trim();
                if (l.Length == 0 || l[0] == '#' || !l.StartsWith("K|")) continue;
                try
                {
                    var f = l.Split('|');
                    string kind = f[1].ToLowerInvariant();
                    if (kind == "glow") { BuildGlow(f); n++; continue; }
                    if (kind == "obj") { if (BuildObj(f)) n++; continue; }
                    if (kind == "objherd") { n += BuildObjHerd(f); continue; }
                    float x = F(f[2]), z = F(f[3]);
                    float ang = f.Length > 4 && f[4].Length > 0 ? F(f[4]) : 0f, sc = f.Length > 5 && f[5].Length > 0 ? F(f[5]) : 1f;
                    var tm = Singleton<TerrainManager>.instance;
                    float y = Ground(x, z);
                    if (kind == "sealion") { try { y = Mathf.Max(y, tm.WaterLevel(new Vector2(x, z))); } catch (Exception) { } }
                    var go = new GameObject("M2W_" + kind); go.transform.SetParent(modelRoot.transform, false);
                    go.transform.position = new Vector3(x, y, z); go.transform.rotation = Quaternion.Euler(0f, ang, 0f); go.transform.localScale = Vector3.one * sc;
                    if (kind == "sealion") MakeSeaLion(go.transform);
                    else if (kind == "tower") MakeTower(go.transform);
                    else if (kind == "statue") MakeStatue(go.transform);
                    else { L("models: unknown kind " + kind); Destroy(go); continue; }
                    n++;
                }
                catch (Exception e) { L("models line '" + l + "': " + e.Message); }
            }
            L("models: " + n + " built (shader " + (propShaderName ?? "none") + ")");
        }

        // K|obj|name|x|z|angleDeg|scale|y : data/models/<name>.obj (+ <name>.png, <name>.txt); y empty = max(ground, water surface), else absolute.
        // If the file is missing and name is sealion / tower / statue, the primitive model is built instead.
        bool BuildObj(string[] f)
        {
            if (f.Length < 5) { L("models: obj needs K|obj|name|x|z|angleDeg|scale|y"); return false; }
            string name = f[2]; float x = F(f[3]), z = F(f[4]);
            float ang = f.Length > 5 && f[5].Length > 0 ? F(f[5]) : 0f, sc = f.Length > 6 && f[6].Length > 0 ? F(f[6]) : 1f;
            float y = f.Length > 7 && f[7].Length > 0 ? F(f[7]) : SurfaceY(x, z);
            var a = GetObj(name);
            if (a == null) return BuildPrimitive(name.ToLowerInvariant(), x, z, ang, sc, y);
            var go = PlaceObj(a, modelRoot.transform, "obj_" + name, new Vector3(x, y, z), ang, sc);
            string mv, id; TrailFields(f, 5, out mv, out id);
            if (mv != null || id != null) RegisterMover(go, mv, id, x, y, z, ang, new System.Random((int)(x * 31f + z * 17f)), false);
            return true;
        }

        // K|objherd|name|cx|cz|radius|count|scale|seed : count copies in a disc, random yaw, scale jitter 0.8-1.25, resting on max(ground, water surface)
        int BuildObjHerd(string[] f)
        {
            if (f.Length < 7) { L("models: objherd needs K|objherd|name|cx|cz|radius|count|scale|seed"); return 0; }
            string name = f[2]; float cx = F(f[3]), cz = F(f[4]), rad = F(f[5]); int count = int.Parse(f[6]);
            float sc = f.Length > 7 && f[7].Length > 0 ? F(f[7]) : 1f; int seed = f.Length > 8 && f[8].Length > 0 ? int.Parse(f[8]) : 1;
            var a = GetObj(name); var rnd = new System.Random(seed); int n = 0;
            string mv, id; TrailFields(f, 7, out mv, out id);
            for (int i = 0; i < count; i++)
            {
                double rr = rad * Math.Sqrt(rnd.NextDouble()), th = rnd.NextDouble() * Math.PI * 2.0;
                float x = cx + (float)(rr * Math.Cos(th)), z = cz + (float)(rr * Math.Sin(th));
                float yaw = (float)(rnd.NextDouble() * 360.0), s = sc * (0.8f + (float)rnd.NextDouble() * 0.45f), y = SurfaceY(x, z);
                if (a != null)
                {
                    var go = PlaceObj(a, modelRoot.transform, "herd_" + name, new Vector3(x, y, z), yaw, s); n++;
                    if (mv != null || id != null) RegisterMover(go, mv, i == 0 ? id : null, x, y, z, yaw, rnd, true);
                }
                else if (BuildPrimitive(name.ToLowerInvariant(), x, z, yaw, s, y)) n++;
                else break;
            }
            L("models: herd " + name + " x" + n);
            return n;
        }

        float SurfaceY(float x, float z)
        {
            float y = Ground(x, z);
            try { y = Mathf.Max(y, Singleton<TerrainManager>.instance.WaterLevel(new Vector2(x, z))); } catch (Exception) { }
            return y;
        }

        bool BuildPrimitive(string kind, float x, float z, float ang, float sc, float y)
        {
            if (kind != "sealion" && kind != "tower" && kind != "statue") { L("models: unknown kind/model " + kind); return false; }
            var go = new GameObject("M2W_" + kind); go.transform.SetParent(modelRoot.transform, false);
            go.transform.position = new Vector3(x, y, z); go.transform.rotation = Quaternion.Euler(0f, ang, 0f); go.transform.localScale = Vector3.one * sc;
            if (kind == "sealion") MakeSeaLion(go.transform); else if (kind == "tower") MakeTower(go.transform); else MakeStatue(go.transform);
            return true;
        }

        // about 2.2 m long at scale 1; head toward +z
        void MakeSeaLion(Transform t)
        {
            var brown = new Color(0.36f, 0.25f, 0.16f); var dark = new Color(0.25f, 0.17f, 0.11f);
            Part(t, PrimitiveType.Sphere, "body", new Vector3(0, 0.45f, 0), new Vector3(0.9f, 0.8f, 2.0f), brown, Vector3.zero);
            Part(t, PrimitiveType.Sphere, "neck", new Vector3(0, 0.8f, 0.8f), new Vector3(0.5f, 0.7f, 0.6f), brown, new Vector3(-30, 0, 0));
            Part(t, PrimitiveType.Sphere, "head", new Vector3(0, 1.2f, 1.05f), new Vector3(0.38f, 0.34f, 0.46f), brown, Vector3.zero);
            Part(t, PrimitiveType.Sphere, "snout", new Vector3(0, 1.15f, 1.32f), new Vector3(0.2f, 0.17f, 0.24f), dark, Vector3.zero);
            Part(t, PrimitiveType.Sphere, "flipperL", new Vector3(-0.5f, 0.28f, 0.45f), new Vector3(0.7f, 0.08f, 0.3f), dark, new Vector3(0, -25, -15));
            Part(t, PrimitiveType.Sphere, "flipperR", new Vector3(0.5f, 0.28f, 0.45f), new Vector3(0.7f, 0.08f, 0.3f), dark, new Vector3(0, 25, 15));
            Part(t, PrimitiveType.Sphere, "tailL", new Vector3(-0.2f, 0.18f, -1.15f), new Vector3(0.4f, 0.07f, 0.5f), dark, new Vector3(0, 20, 0));
            Part(t, PrimitiveType.Sphere, "tailR", new Vector3(0.2f, 0.18f, -1.15f), new Vector3(0.4f, 0.07f, 0.5f), dark, new Vector3(0, -20, 0));
        }

        // about 60 m tall at scale 1: cream square tower with bands and a tiled blue/gold dome
        void MakeTower(Transform t)
        {
            var cream = new Color(0.93f, 0.88f, 0.76f); var band = new Color(0.82f, 0.74f, 0.58f);
            var blue = new Color(0.12f, 0.36f, 0.62f); var gold = new Color(0.86f, 0.68f, 0.18f);
            Part(t, PrimitiveType.Cube, "base", new Vector3(0, 4, 0), new Vector3(18, 8, 18), band, Vector3.zero);
            Part(t, PrimitiveType.Cube, "shaft", new Vector3(0, 23, 0), new Vector3(13, 30, 13), cream, Vector3.zero);
            for (int i = 0; i < 4; i++) Part(t, PrimitiveType.Cube, "band" + i, new Vector3(0, 12 + i * 8, 0), new Vector3(14, 1.0f, 14), band, Vector3.zero);
            Part(t, PrimitiveType.Cube, "belfry", new Vector3(0, 44, 0), new Vector3(11, 12, 11), cream, Vector3.zero);
            Part(t, PrimitiveType.Cube, "belfryBand", new Vector3(0, 38.5f, 0), new Vector3(12.5f, 1.2f, 12.5f), gold, Vector3.zero);
            for (int s = 0; s < 4; s++)   // dark window openings on each face
            {
                float ang = s * 90f * Mathf.Deg2Rad; var d = new Vector3(Mathf.Sin(ang), 0, Mathf.Cos(ang));
                Part(t, PrimitiveType.Cube, "arch" + s, new Vector3(d.x * 5.6f, 44, d.z * 5.6f), new Vector3(Mathf.Abs(d.x) > 0.5f ? 0.3f : 4f, 6.5f, Mathf.Abs(d.z) > 0.5f ? 0.3f : 4f), new Color(0.2f, 0.18f, 0.16f), Vector3.zero);
            }
            Part(t, PrimitiveType.Cube, "cornice", new Vector3(0, 50.4f, 0), new Vector3(13, 1.2f, 13), gold, Vector3.zero);
            Part(t, PrimitiveType.Sphere, "dome", new Vector3(0, 51f, 0), new Vector3(10.5f, 9f, 10.5f), blue, Vector3.zero);
            for (int i = 0; i < 4; i++)   // gold rings on the dome
            {
                float h = 52f + i * 2.1f; float r = 10.2f * Mathf.Sqrt(Mathf.Max(0.05f, 1f - Mathf.Pow((h - 51f) / 4.5f, 2f)));
                Part(t, PrimitiveType.Cylinder, "ring" + i, new Vector3(0, h, 0), new Vector3(r + 0.15f, 0.12f, r + 0.15f), gold, Vector3.zero);
            }
            Part(t, PrimitiveType.Cylinder, "lantern", new Vector3(0, 56.2f, 0), new Vector3(2.2f, 1.2f, 2.2f), cream, Vector3.zero);
            Part(t, PrimitiveType.Sphere, "lanternDome", new Vector3(0, 57.6f, 0), new Vector3(2.4f, 2.4f, 2.4f), gold, Vector3.zero);
            Part(t, PrimitiveType.Cylinder, "spire", new Vector3(0, 60f, 0), new Vector3(0.25f, 2.2f, 0.25f), gold, Vector3.zero);
        }

        // about 8 m tall at scale 1: a sailor and a nurse on a plinth
        void MakeStatue(Transform t)
        {
            var stone = new Color(0.35f, 0.34f, 0.33f); var white = new Color(0.92f, 0.92f, 0.9f); var navy = new Color(0.12f, 0.14f, 0.22f); var skin = new Color(0.85f, 0.78f, 0.7f);
            Part(t, PrimitiveType.Cube, "plinth", new Vector3(0, 0.6f, 0), new Vector3(4.5f, 1.2f, 4.5f), stone, Vector3.zero);
            Part(t, PrimitiveType.Capsule, "sailor", new Vector3(0, 4.2f, 0.1f), new Vector3(1.9f, 2.9f, 1.9f), navy, new Vector3(8, 0, 0));
            Part(t, PrimitiveType.Sphere, "sailorHead", new Vector3(0.1f, 7.3f, 0.45f), new Vector3(1.1f, 1.2f, 1.1f), skin, Vector3.zero);
            Part(t, PrimitiveType.Cylinder, "sailorCap", new Vector3(0.1f, 7.95f, 0.45f), new Vector3(1.15f, 0.12f, 1.15f), white, Vector3.zero);
            Part(t, PrimitiveType.Capsule, "nurse", new Vector3(0.5f, 3.9f, 0.9f), new Vector3(1.6f, 2.5f, 1.6f), white, new Vector3(-38, 0, 12));
            Part(t, PrimitiveType.Sphere, "nurseHead", new Vector3(0.45f, 6.4f, 1.55f), new Vector3(0.95f, 1.0f, 0.95f), skin, Vector3.zero);
            Part(t, PrimitiveType.Sphere, "nurseHair", new Vector3(0.45f, 6.6f, 1.7f), new Vector3(1.0f, 0.8f, 0.9f), navy, Vector3.zero);
            Part(t, PrimitiveType.Capsule, "armL", new Vector3(-0.7f, 4.8f, 0.4f), new Vector3(0.5f, 1.3f, 0.5f), navy, new Vector3(30, 0, -35));
            Part(t, PrimitiveType.Capsule, "armR", new Vector3(1.0f, 5.0f, 0.4f), new Vector3(0.5f, 1.3f, 0.5f), navy, new Vector3(30, 0, 40));
        }
    }
}
