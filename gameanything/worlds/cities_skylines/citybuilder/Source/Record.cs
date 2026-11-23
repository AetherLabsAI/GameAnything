// Video capture (record / tour), sun glow and water texture filtering. Generic: all content comes from data/*.txt.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using ColossalFramework;
using UnityEngine;

namespace M2WCity
{
    public partial class Host
    {
        // ---------- look.txt single values (read quietly; used for hour.sunset / hour.sunrise / water.*) ----------
        string LookStr(string key)
        {
            try
            {
                var f = Path.Combine(dataDir, "look.txt");
                if (!File.Exists(f)) return null;
                foreach (var raw in File.ReadAllLines(f))
                {
                    var l = raw.Trim(); int eq = l.IndexOf('=');
                    if (l.Length == 0 || l[0] == '#' || eq <= 0) continue;
                    if (l.Substring(0, eq).Trim() == key) return l.Substring(eq + 1).Trim();
                }
            }
            catch (Exception) { }
            return null;
        }
        float LookNum(string key, float def)
        {
            var s = LookStr(key); float v;
            return s != null && float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v) ? v : def;
        }
        public float SunsetHour { get { return LookNum("hour.sunset", 18.0f); } }
        public float SunriseHour { get { return LookNum("hour.sunrise", 6.4f); } }

        // ---------- recording: record <name> <seconds> [fps=12] [width=960]   record& (does not block the command queue) ----------
        class RecState
        {
            public string dir; public float fps; public int w, h, aa = 8; public float duration;   // duration <= 0: until stop
            public bool stop, finished; public int frames; public float start, elapsed;
            public List<float> times = new List<float>();
        }
        bool recording;

        IEnumerator CmdRecord(string[] a, bool background)
        {
            if (a.Length < 3) { L("usage: record <name> <seconds> [fps] [width]"); yield break; }
            if (recording) { L("record: already recording"); yield break; }
            float secs = F(a[2]), fps = a.Length > 3 ? F(a[3]) : 12f; int w = a.Length > 4 ? (int)F(a[4]) : 960;
            var st = NewRec(a[1], fps, w); st.duration = secs;
            StartRec(st);
            if (background) yield break;
            while (!st.finished) yield return null;
        }

        RecState NewRec(string name, float fps, int w, int aa = 8)
        {
            if (w > 2560) L("capture: width " + w + " limited to 2560");
            w = Mathf.Clamp(w, 160, 2560) & ~1; int h = (w * 9 / 16) & ~1;
            return new RecState { dir = Path.Combine(shotDir, "rec_" + name), fps = Mathf.Clamp(fps, 1f, 60f), w = w, h = h, aa = aa };
        }
        void StartRec(RecState st)
        {
            recording = true; st.start = Time.unscaledTime;
            StartCoroutine(RecLoop(st));
        }

        IEnumerator RecLoop(RecState st)
        {
            RenderTexture rt = null; Texture2D tex = null; Camera cam = null;
            try
            {
                if (Directory.Exists(st.dir)) foreach (var f in Directory.GetFiles(st.dir, "*.jpg")) File.Delete(f);
                Directory.CreateDirectory(st.dir);
                cam = Singleton<CameraController>.instance.GetComponent<Camera>();
                rt = MakeCaptureRT(st.w, st.h, st.aa); tex = new Texture2D(st.w, st.h, TextureFormat.RGB24, false);
            }
            catch (Exception e) { L("record setup: " + e.Message); st.finished = true; recording = false; yield break; }
            float interval = 1f / st.fps, next = st.start; int fails = 0;
            while (true)
            {
                yield return new WaitForEndOfFrame();
                float now = Time.unscaledTime;
                if (st.stop || (st.duration > 0f && now - st.start >= st.duration)) break;
                if (now < next || !inCity) continue;
                if (GrabJpg(cam, rt, tex, Path.Combine(st.dir, st.frames.ToString("00000") + ".jpg"))) { st.times.Add(now - st.start); st.frames++; fails = 0; }
                else if (++fails >= 5) { L("record: capture keeps failing, stopping"); break; }
                next += interval; if (next < now - interval) next = now;       // never try to catch up with a burst
            }
            st.elapsed = Time.unscaledTime - st.start;
            try
            {
                var sb = new StringBuilder(); for (int i = 0; i < st.times.Count; i++) sb.Append(i.ToString("00000")).Append(' ').Append(st.times[i].ToString("0.000", CultureInfo.InvariantCulture)).Append('\n');
                File.WriteAllText(Path.Combine(st.dir, "times.txt"), sb.ToString());
            }
            catch (Exception) { }
            try { if (rt != null) Destroy(rt); if (tex != null) Destroy(tex); } catch (Exception) { }
            L("record: " + st.frames + " frames in " + st.elapsed.ToString("0.0", CultureInfo.InvariantCulture) + " s (" + (st.frames / Mathf.Max(0.01f, st.elapsed)).ToString("0.0", CultureInfo.InvariantCulture) + " fps achieved, target " + st.fps + ", " + st.w + "x" + st.h + ") -> " + st.dir);
            st.finished = true; recording = false;
        }

        // Capture target with MSAA: tries aa (8 default), falls back 4, 2, 1 if Create() fails; logs what the render texture really reports.
        static RenderTexture MakeCaptureRT(int w, int h, int aa)
        {
            RenderTexture rt = null; int req = aa;
            foreach (int level in new[] { 8, 4, 2, 1 })
            {
                if (level > aa) continue;
                var t = new RenderTexture(w, h, 24, RenderTextureFormat.ARGB32);
                t.antiAliasing = level; t.wrapMode = TextureWrapMode.Clamp;
                bool ok = false; try { ok = t.Create(); } catch (Exception) { }
                if (ok) { rt = t; break; }
                Destroy(t);
            }
            if (rt == null) { rt = new RenderTexture(w, h, 24); }
            L("capture RT " + w + "x" + h + ": requested antiAliasing " + req + ", render texture reports " + rt.antiAliasing + " (QualitySettings.antiAliasing " + QualitySettings.antiAliasing + ")");
            return rt;
        }

        static bool GrabJpg(Camera cam, RenderTexture rt, Texture2D tex, string path, int quality = 85)
        {
            var old = cam.targetTexture; var oldActive = RenderTexture.active;
            try
            {
                cam.targetTexture = rt; cam.Render(); cam.targetTexture = old;
                RenderTexture.active = rt;
                tex.ReadPixels(new Rect(0, 0, rt.width, rt.height), 0, 0, false);
                RenderTexture.active = oldActive;
                File.WriteAllBytes(path, tex.EncodeToJPG(quality));
                return true;
            }
            catch (Exception e) { try { cam.targetTexture = old; RenderTexture.active = oldActive; } catch (Exception) { } L("grab: " + e.Message); return false; }
        }

        // ---------- tour <name> [fps] [width]: records while flying through every memory ----------
        // Chapter files in the rec folder: chapters.txt (start seconds|memory id|title), chapters_full.txt (start|end|id|title|titleEn|text).
        // data/tour.txt (optional): <memory id>|<hour>  holds that hour of day while flying to / orbiting that memory.
        const float TourOrbit = 8f;

        IEnumerator CmdTour(string[] a)
        {
            if (a.Length < 2) { L("usage: tour <name> [fps] [width]"); yield break; }
            if (recording) { L("tour: already recording"); yield break; }
            if (memories.Count == 0) { L("tour: no memories"); yield break; }
            var hours = new Dictionary<string, float>();
            var tf = Path.Combine(dataDir, "tour.txt");
            if (File.Exists(tf)) foreach (var raw in File.ReadAllLines(tf))
            {
                var l = raw.Trim(); if (l.Length == 0 || l[0] == '#') continue;
                var p = l.Split('|'); float hv;
                if (p.Length >= 2 && float.TryParse(p[1].Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out hv)) hours[p[0].Trim()] = hv;
            }
            var st = NewRec(a[1], a.Length > 2 ? F(a[2]) : 12f, a.Length > 3 ? (int)F(a[3]) : 960);
            float savedHold = holdHour;
            var ch = new StringBuilder(); var full = new StringBuilder();
            CamLift();
            try { StartRec(st);
            if (tour != null) { StopCoroutine(tour); tour = null; }
            for (int i = 0; i < memories.Count; i++)
            {
                var m = memories[i];
                float hv;
                if (hours.TryGetValue(m.id, out hv)) { holdHour = hv; SetHour(hv); SetWeather(true); }
                float capStart = -1f;
                var it = FlyRoutine(m, TourOrbit);
                while (true)
                {
                    bool more;
                    try { more = it.MoveNext(); } catch (Exception e) { L("tour fly " + m.id + ": " + e.Message); break; }
                    if (!more) break;
                    if (capStart < 0f && !string.IsNullOrEmpty(shownText)) capStart = Time.unscaledTime - st.start;
                    yield return it.Current;
                }
                float end = Time.unscaledTime - st.start; if (capStart < 0f) capStart = end;
                var inv = CultureInfo.InvariantCulture;
                ch.Append(capStart.ToString("0.00", inv)).Append('|').Append(m.id).Append('|').Append(m.title).Append("   ").Append(m.titleEn).Append('\n');
                full.Append(capStart.ToString("0.00", inv)).Append('|').Append(end.ToString("0.00", inv)).Append('|').Append(m.id).Append('|').Append(m.title).Append('|').Append(m.titleEn).Append('|').Append(m.text.Replace("\n", "\\n")).Append('\n');
            }
            st.stop = true;
            while (!st.finished) yield return null;
            }
            finally { CamUnlift(); }
            holdHour = savedHold;
            try
            {
                File.WriteAllText(Path.Combine(st.dir, "chapters.txt"), ch.ToString(), new UTF8Encoding(false));
                File.WriteAllText(Path.Combine(st.dir, "chapters_full.txt"), full.ToString(), new UTF8Encoding(false));
                L("tour: chapters written to " + st.dir);
            }
            catch (Exception e) { L("tour chapters: " + e.Message); }
        }

        // ---------- sun glow:  K|glow|x|z|y|size  (x,z = fallback sun direction if no sun light is found, default -1,0.3; y = extra height in m; size in m at 6000 m) ----------
        class Glow { public GameObject go; public Material mat; public float size, yoff; public Vector2 fb; public bool additive; }
        List<Glow> glows = new List<Glow>();
        Texture2D glowTex; Shader glowShader; string glowShaderName; bool glowProbed;

        void ProbeGlowShaders()
        {
            if (glowProbed) return; glowProbed = true;
            var sb = new StringBuilder();
            foreach (var n in new[] { "Particles/Additive", "Legacy Shaders/Particles/Additive", "Sprites/Default", "Particles/Alpha Blended", "Legacy Shaders/Particles/Alpha Blended", "Unlit/Transparent" })
            {
                Shader s = null; try { s = Shader.Find(n); } catch (Exception) { }
                sb.Append(n).Append(s != null ? "=FOUND; " : "=missing; ");
                if (s != null && glowShader == null) { glowShader = s; glowShaderName = n; }
            }
            L("glow shaders: " + sb + "using " + (glowShaderName ?? "NONE"));
        }

        Texture2D MakeGlowTex()
        {
            if (glowTex != null) return glowTex;
            const int S = 128;
            var t = new Texture2D(S, S, TextureFormat.RGBA32, false); t.wrapMode = TextureWrapMode.Clamp; t.filterMode = FilterMode.Bilinear;
            var px = new Color[S * S];
            for (int y = 0; y < S; y++)
                for (int x = 0; x < S; x++)
                {
                    float dx = (x + 0.5f) / S * 2f - 1f, dy = (y + 0.5f) / S * 2f - 1f;
                    float r = Mathf.Sqrt(dx * dx + dy * dy);
                    float v = Mathf.Clamp01(1f - r); v = v * v * (3f - 2f * v); v = Mathf.Pow(v, 1.6f);     // soft radial falloff, exactly 0 at the edge
                    float core = Mathf.Pow(Mathf.Clamp01(1f - r * 3f), 2f);                                   // small hotter core
                    px[y * S + x] = new Color(1f, Mathf.Lerp(0.52f, 0.85f, core), Mathf.Lerp(0.18f, 0.55f, core), Mathf.Clamp01(v + core * 0.4f));
                }
            t.SetPixels(px); t.Apply(false);
            glowTex = t; return t;
        }

        void BuildGlow(string[] f)
        {
            ProbeGlowShaders();
            if (glowShader == null) { L("glow: no usable shader, skipped"); return; }
            var g = new Glow();
            g.fb = new Vector2(f.Length > 2 && f[2].Length > 0 ? F(f[2]) : -1f, f.Length > 3 && f[3].Length > 0 ? F(f[3]) : 0.3f);
            g.yoff = f.Length > 4 && f[4].Length > 0 ? F(f[4]) : 0f; g.size = f.Length > 5 && f[5].Length > 0 ? F(f[5]) : 2500f;
            g.additive = glowShaderName.IndexOf("Additive", StringComparison.Ordinal) >= 0;
            var go = GameObject.CreatePrimitive(PrimitiveType.Quad); go.name = "M2W_glow";
            var cl = go.GetComponent<Collider>(); if (cl != null) Destroy(cl);
            go.transform.SetParent(modelRoot.transform, false);
            var mat = new Material(glowShader); mat.mainTexture = MakeGlowTex(); mat.renderQueue = 3500;
            if (mat.HasProperty("_TintColor")) mat.SetColor("_TintColor", new Color(0.5f, 0.5f, 0.5f, 0f));
            var r = go.GetComponent<Renderer>(); r.material = mat; r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off; r.receiveShadows = false;
            go.SetActive(false);
            g.go = go; g.mat = mat; glows.Add(g);
        }

        Vector3 SunDirection(Vector2 fb)
        {
            Light sun = null;
            try { sun = RenderSettings.sun; } catch (Exception) { }
            if (sun == null)
                foreach (var l in UnityEngine.Object.FindObjectsOfType<Light>()) if (l.type == LightType.Directional && l.enabled) { sun = l; break; }
            Vector3 d = sun != null ? -sun.transform.forward : new Vector3(fb.x, 0f, fb.y);
            d.y = Mathf.Max(d.y, 0.0f);
            return d.sqrMagnitude < 1e-6f ? new Vector3(-1f, 0f, 0.3f).normalized : d.normalized;
        }

        float lastGlowLog;
        void UpdateGlows()
        {
            if (glows.Count == 0 || !inCity) return;
            var cam = Camera.main; if (cam == null) { try { cam = Singleton<CameraController>.instance.GetComponent<Camera>(); } catch (Exception) { } }
            if (cam == null) return;
            float h = Singleton<SimulationManager>.instance.m_currentDayTimeHour;
            float a = Mathf.Clamp01((h - 17f) / 1.0f) * Mathf.Clamp01((19.5f - h) / 0.75f);
            float dist = Mathf.Min(6000f, cam.farClipPlane * 0.9f);
            foreach (var g in glows)
            {
                if (g.go == null) continue;
                bool on = a > 0.01f; if (g.go.activeSelf != on) g.go.SetActive(on);
                if (!on) continue;
                Vector3 pos = cam.transform.position + SunDirection(g.fb) * dist + Vector3.up * g.yoff;
                g.go.transform.position = pos;
                g.go.transform.rotation = Quaternion.LookRotation(pos - cam.transform.position);
                g.go.transform.localScale = Vector3.one * g.size * (dist / 6000f);
                if (g.additive) { if (g.mat.HasProperty("_TintColor")) g.mat.SetColor("_TintColor", new Color(0.5f * a, 0.5f * a, 0.5f * a, a)); }
                else g.mat.color = new Color(1f, 1f, 1f, a * 0.85f);
            }
            if (Time.unscaledTime - lastGlowLog > 60f) { lastGlowLog = Time.unscaledTime; L("glow: hour " + h.ToString("0.0", CultureInfo.InvariantCulture) + " alpha " + a.ToString("0.00", CultureInfo.InvariantCulture) + " dist " + dist + " far " + cam.farClipPlane); }
        }

        IEnumerator CmdGlow()
        {
            glowProbed = false; glowShader = null; ProbeGlowShaders();
            L("glow: " + glows.Count + " in scene; sun light " + (RenderSettings.sun != null ? RenderSettings.sun.name : "(RenderSettings.sun null)"));
            yield return null;
        }

        // ---------- watertex: log the water materials' textures and make them trilinear + anisotropic (+ mip bias) ----------
        static readonly string[] WaterTexNames = { "_MainTex", "_BumpMap", "_NormalTex", "_NormalMap", "_WaterNormal", "_WaterBump", "_WaterFoam", "_Foam", "_FoamTex", "_Noise", "_NoiseTex", "_DetailTex", "_RippleTex", "_ShoreTex", "_HeightMap", "_WaterMap", "_SurfaceTexA", "_SurfaceTexB", "_ReflectionTex", "_RefractionTex", "_Cube", "_CubeTex", "_Reflection" };

        IEnumerator CmdWaterTex(string[] a)
        {
            try { WaterTex(true); } catch (Exception e) { L("watertex: " + e); }
            yield return null;
        }

        // log=true : log every texture. Called with log=false from `tint` when look.txt has water.mipbias / water.aniso.
        void WaterTex(bool log)
        {
            string sb = LookStr("water.mipbias"), sa = LookStr("water.aniso");
            float bias = 0f; bool hasBias = sb != null && float.TryParse(sb, NumberStyles.Float, CultureInfo.InvariantCulture, out bias);
            int aniso = Mathf.Clamp(sa != null ? (int)LookNum("water.aniso", 8f) : 8, 1, 16);
            if (log) L("watertex: QualitySettings.anisotropicFiltering " + QualitySettings.anisotropicFiltering + ", setting aniso " + aniso + (hasBias ? ", mipMapBias " + bias.ToString(CultureInfo.InvariantCulture) : ", mipMapBias untouched"));
            var seen = new HashSet<int>();
            foreach (var mn in new[] { "water", "watert" })
            {
                var m = MatByName(mn);
                if (m == null) { if (log) L("watertex " + mn + ": (null)"); continue; }
                foreach (var p in WaterTexNames)
                {
                    try
                    {
                        if (!m.HasProperty(p)) continue;
                        var t = m.GetTexture(p);
                        if (t == null) { if (log) L("watertex " + mn + "." + p + ": (empty)"); continue; }
                        bool rtex = t is RenderTexture, first = seen.Add(t.GetInstanceID());
                        if (log)
                        {
                            string extra = ""; var t2 = t as Texture2D; if (t2 != null) extra = ", format " + t2.format + ", mips " + t2.mipmapCount;
                            L("watertex " + mn + "." + p + ": '" + t.name + "' " + t.GetType().Name + " " + t.width + "x" + t.height + ", wrap " + t.wrapMode + ", filter " + t.filterMode + ", aniso " + t.anisoLevel + ", mipBias " + t.mipMapBias + extra + (rtex ? " (render texture, not modified)" : ""));
                        }
                        if (rtex || !first) continue;
                        t.filterMode = FilterMode.Trilinear; t.anisoLevel = aniso;
                        if (hasBias) t.mipMapBias = bias;
                    }
                    catch (Exception e) { L("watertex " + mn + "." + p + ": " + e.Message); }
                }
            }
            if (log) L("watertex: done");
        }
    }
}
