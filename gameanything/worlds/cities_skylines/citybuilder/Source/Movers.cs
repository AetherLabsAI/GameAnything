// Movement of placed OBJ models (K|obj / K|objherd with a trailing move=... field), see README. Generic: everything comes from data/*.txt.
// Every mover is a PURE FUNCTION of time (Host.VirtualTime): no per-instance state is integrated, so cine captures are deterministic
// and a model that was out of range simply jumps to where it should be when the camera comes back.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using ColossalFramework;
using UnityEngine;

namespace M2WCity
{
    public class MPath { public string name; public float[] x, z, cum; public float total; }

    public class Mover
    {
        public Transform tr; public int mode;              // 1 walk, 2 bob, 3 fly, 4 path
        public string tag; public bool always;
        public float x0, y0, z0, baseOff;                  // start position, y offset above the ground at the start
        public float hd, dx, dz, lo, hi, speed, off;       // walk: heading (deg), unit direction, limits along the line, speed, start offset
        public float phase, amp, period, radius, phi0;     // bob / fly / sway phases
        public float yaw0;                                 // initial yaw of the placed model
        public MPath path; public bool pingpong; public float s0;
        public float px, py, pz, yaw;                      // last evaluated pose
        public Quaternion rot = Quaternion.identity;
    }

    public partial class Host
    {
        public static bool cineActive; public static double cineVT;
        // seconds of animation time: frame/fps while `cine` records (deterministic), Time.time otherwise
        public static double VirtualTime { get { return cineActive ? cineVT : (double)Time.time; } }

        readonly List<Mover> movers = new List<Mover>();
        readonly Dictionary<string, Mover> moverTags = new Dictionary<string, Mover>();
        readonly Dictionary<string, MPath> mpaths = new Dictionary<string, MPath>();
        const float MoverRange = 400f;
        CameraController ccCache; Camera ccCam;

        void ClearMovers() { movers.Clear(); moverTags.Clear(); ccCache = null; ccCam = null; }

        Mover FindMover(string tag) { Mover m; return tag != null && moverTags.TryGetValue(tag, out m) ? m : null; }

        // data/paths.txt : P|name|x,z x,z x,z ...
        void LoadPaths()
        {
            mpaths.Clear();
            var f = Path.Combine(dataDir, "paths.txt");
            if (!File.Exists(f)) return;
            int n = 0;
            foreach (var raw in File.ReadAllLines(f))
            {
                var l = raw.Trim(); if (l.Length == 0 || l[0] == '#' || !l.StartsWith("P|")) continue;
                try
                {
                    var p = l.Split('|'); var pts = p[2].Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                    if (pts.Length < 2) { L("paths: '" + p[1] + "' needs at least 2 points"); continue; }
                    var mp = new MPath { name = p[1].Trim(), x = new float[pts.Length], z = new float[pts.Length], cum = new float[pts.Length] };
                    for (int i = 0; i < pts.Length; i++)
                    {
                        var xz = pts[i].Split(','); mp.x[i] = F(xz[0]); mp.z[i] = F(xz[1]);
                        if (i > 0) { float ddx = mp.x[i] - mp.x[i - 1], ddz = mp.z[i] - mp.z[i - 1]; mp.cum[i] = mp.cum[i - 1] + Mathf.Sqrt(ddx * ddx + ddz * ddz); }
                    }
                    mp.total = mp.cum[pts.Length - 1];
                    if (mp.total < 1f) { L("paths: '" + mp.name + "' is shorter than 1 m"); continue; }
                    mpaths[mp.name] = mp; n++;
                }
                catch (Exception e) { L("paths line '" + l + "': " + e.Message); }
            }
            L("paths: " + n + " loaded");
        }

        // trailing optional fields of a K|obj / K|objherd line starting at index `from`: move=<spec>, id=<tag>
        static void TrailFields(string[] f, int from, out string move, out string id)
        {
            move = null; id = null;
            for (int i = from; i < f.Length; i++)
            {
                var s = f[i].Trim();
                if (s.StartsWith("move=")) move = s.Substring(5);
                else if (s.StartsWith("id=")) id = s.Substring(3);
            }
        }

        static float Pa(string[] p, int i, float def) { return p.Length > i && p[i].Trim().Length > 0 ? F(p[i].Trim()) : def; }

        bool MoverBlocked(float x, float z)
        {
            float g = Ground(x, z);
            if (keepWater && g < seaLevel + 0.2f) return true;
            try { if (Singleton<TerrainManager>.instance.WaterLevel(new Vector2(x, z)) - g > 0.2f) return true; } catch (Exception) { }
            return false;
        }

        // Called after PlaceObj. rnd supplies the per-copy randomness (heading, phase); herd = true gives each copy a random phase.
        void RegisterMover(GameObject go, string move, string tag, float x, float y, float z, float yaw, System.Random rnd, bool herd)
        {
            if (go == null || (move == null && tag == null)) return;
            Mover m = null;
            if (move != null)
            {
                try
                {
                    var p = move.Split(':'); string mode = p[0].Trim().ToLowerInvariant();
                    m = new Mover { tr = go.transform, x0 = x, y0 = y, z0 = z, yaw0 = yaw, yaw = yaw, px = x, py = y, pz = z };
                    m.baseOff = y - Ground(x, z); m.phase = (float)(rnd.NextDouble() * Math.PI * 2.0);
                    if (mode == "walk")
                    {
                        m.mode = 1; m.speed = Pa(p, 1, 1.3f); float range = Mathf.Max(0f, Pa(p, 2, 12f));
                        m.hd = (float)(rnd.NextDouble() * 360.0); float hr = m.hd * Mathf.Deg2Rad; m.dx = Mathf.Sin(hr); m.dz = Mathf.Cos(hr);
                        bool startBad = MoverBlocked(x, z);
                        for (float s = 1f; !startBad && s <= range; s += 1f) { if (MoverBlocked(x + m.dx * s, z + m.dz * s)) break; m.hi = s; }
                        for (float s = 1f; !startBad && s <= range; s += 1f) { if (MoverBlocked(x - m.dx * s, z - m.dz * s)) break; m.lo = -s; }
                        float L2 = 2f * (m.hi - m.lo);
                        m.off = -m.lo + (herd && L2 > 0f ? (float)rnd.NextDouble() * L2 : 0f);
                    }
                    else if (mode == "bob") { m.mode = 2; m.amp = Pa(p, 1, 0.3f); m.period = Mathf.Max(0.1f, Pa(p, 2, 4f)); }
                    else if (mode == "fly")
                    {
                        m.mode = 3; m.radius = Mathf.Max(1f, Pa(p, 1, 30f)); m.speed = Pa(p, 2, 8f);
                        if (herd) m.radius *= 0.7f + 0.6f * (float)rnd.NextDouble();
                        m.y0 = y + Pa(p, 3, 25f); m.phi0 = herd ? m.phase : 0f;
                    }
                    else if (mode == "path")
                    {
                        m.mode = 4; MPath mp; string pn = p.Length > 1 ? p[1].Trim() : "";
                        if (!mpaths.TryGetValue(pn, out mp)) { L("models: move path '" + pn + "' not found in paths.txt"); m = null; }
                        else
                        {
                            m.path = mp; m.speed = Pa(p, 2, 10f); m.pingpong = p.Length > 3 && p[3].Trim().ToLowerInvariant() == "pingpong";
                            m.s0 = herd ? (float)rnd.NextDouble() * mp.total : 0f;
                        }
                    }
                    else { L("models: unknown move mode '" + mode + "'"); m = null; }
                }
                catch (Exception e) { L("models: bad move '" + move + "': " + e.Message); m = null; }
            }
            if (m == null)
            {
                if (tag == null) return;
                m = new Mover { tr = go.transform, mode = 0, x0 = x, y0 = y, z0 = z, px = x, py = y, pz = z, yaw = yaw, yaw0 = yaw };   // tag only, static
            }
            if (tag != null) { m.tag = tag; m.always = true; if (!moverTags.ContainsKey(tag)) moverTags[tag] = m; else L("models: duplicate id=" + tag); }
            if (m.mode != 0) { EvalMover(m, VirtualTime); Apply(m); }
            movers.Add(m);
        }

        static void PathPt(MPath p, float s, out float x, out float z)
        {
            if (s <= 0f) { x = p.x[0]; z = p.z[0]; return; }
            int n = p.x.Length;
            if (s >= p.total) { x = p.x[n - 1]; z = p.z[n - 1]; return; }
            int lo = 0, hi = n - 2;
            while (lo < hi) { int mid = (lo + hi + 1) >> 1; if (p.cum[mid] <= s) lo = mid; else hi = mid - 1; }
            float seg = p.cum[lo + 1] - p.cum[lo], u = seg > 1e-6f ? (s - p.cum[lo]) / seg : 0f;
            x = p.x[lo] + (p.x[lo + 1] - p.x[lo]) * u; z = p.z[lo] + (p.z[lo + 1] - p.z[lo]) * u;
        }

        // distance along the path (0..total) and whether we are on the way back, at time t
        static float PathS(Mover m, double t, out bool rev)
        {
            double T = m.path.total, d = m.speed * t + m.s0; rev = false;
            if (m.pingpong) { d %= 2.0 * T; if (d < 0) d += 2.0 * T; if (d > T) { d = 2.0 * T - d; rev = true; } }
            else { d %= T; if (d < 0) d += T; }
            return (float)d;
        }

        // pure function of t; fills px/py/pz/yaw/rot
        void EvalMover(Mover m, double t)
        {
            const float TwoPi = 6.2831853f;
            switch (m.mode)
            {
                case 1:
                    {
                        float L = m.hi - m.lo, x = m.x0, z = m.z0, yaw = m.hd, roll = 0f, bob = 0f;
                        if (L > 0.5f)
                        {
                            double d = (m.speed * t + m.off) % (2.0 * L); if (d < 0) d += 2.0 * L;
                            float s; bool fwd;
                            if (d < L) { s = m.lo + (float)d; fwd = true; } else { s = m.hi - (float)(d - L); fwd = false; }
                            float tau = (float)(t % 1.0) * TwoPi, sw = Mathf.Sin(tau + m.phase);
                            x = m.x0 + m.dx * s + m.dz * 0.05f * sw; z = m.z0 + m.dz * s - m.dx * 0.05f * sw;   // side sway 5 cm
                            yaw = fwd ? m.hd : m.hd + 180f; roll = 2f * sw;
                            bob = 0.08f * Mathf.Abs(Mathf.Sin(tau + m.phase));                                    // 2 steps per second
                        }
                        m.px = x; m.pz = z; m.py = Ground(x, z) + m.baseOff + bob; m.yaw = yaw;
                        m.rot = Quaternion.Euler(0f, yaw, roll); break;
                    }
                case 2:
                    {
                        float a = (float)(t % m.period) / m.period * TwoPi + m.phase;
                        m.px = m.x0; m.pz = m.z0; m.py = m.y0 + m.amp * Mathf.Sin(a); m.yaw = m.yaw0;
                        m.rot = Quaternion.Euler(2f * Mathf.Cos(a), m.yaw0, 3f * Mathf.Cos(a)); break;
                    }
                case 3:
                    {
                        float sign = m.speed >= 0f ? 1f : -1f; double w = m.speed / m.radius;
                        float phi = m.phi0 + (float)((t * w) % (double)TwoPi);
                        m.px = m.x0 + m.radius * Mathf.Sin(phi); m.pz = m.z0 + m.radius * Mathf.Cos(phi); m.py = m.y0;
                        m.yaw = phi * Mathf.Rad2Deg + 90f * sign;
                        m.rot = Quaternion.Euler(0f, m.yaw, -sign * 20f); break;   // yaw increases = turning right = bank right (negative z roll)
                    }
                case 4:
                    {
                        bool rev; float s = PathS(m, t, out rev), xa, za, xb, zb, x, z;
                        PathPt(m.path, s, out x, out z);
                        PathPt(m.path, Mathf.Max(0f, s - 1.5f), out xa, out za); PathPt(m.path, Mathf.Min(m.path.total, s + 1.5f), out xb, out zb);
                        float fx = xb - xa, fz = zb - za, len = Mathf.Sqrt(fx * fx + fz * fz);
                        float gA = Ground(xa, za), gB = Ground(xb, zb), pitch = 0f;
                        if (len > 1e-3f)
                        {
                            m.yaw = Mathf.Atan2(rev ? -fx : fx, rev ? -fz : fz) * Mathf.Rad2Deg;
                            float gFront = rev ? gA : gB, gBack = rev ? gB : gA;
                            pitch = Mathf.Atan2(gBack - gFront, len) * Mathf.Rad2Deg;   // positive x rotation = nose down
                        }
                        m.px = x; m.pz = z; m.py = (gA + gB) * 0.5f + m.baseOff;
                        m.rot = Quaternion.Euler(pitch, m.yaw, 0f); break;
                    }
            }
        }

        static void Apply(Mover m) { m.tr.position = new Vector3(m.px, m.py, m.pz); m.tr.rotation = m.rot; }

        // Updates the movers near the camera (target point or camera position within MoverRange; tagged ones always). No allocations.
        void MoversTick()
        {
            int n = movers.Count; if (n == 0) return;
            if (ccCache == null)
            {
                try { ccCache = Singleton<CameraController>.instance; ccCam = ccCache != null ? ccCache.GetComponent<Camera>() : null; } catch (Exception) { return; }
                if (ccCache == null) return;
            }
            Vector3 tp = ccCache.m_currentPosition, cp = ccCam != null ? ccCam.transform.position : tp;
            float r2 = MoverRange * MoverRange; double t = VirtualTime;
            for (int i = 0; i < n; i++)
            {
                var m = movers[i];
                if (m.mode == 0 || m.tr == null) continue;
                if (!m.always)
                {
                    float x, z;
                    if (m.mode == 4) { bool rev; PathPt(m.path, PathS(m, t, out rev), out x, out z); } else { x = m.x0; z = m.z0; }
                    float a = x - tp.x, b = z - tp.z, c = x - cp.x, d = z - cp.z;
                    if (a * a + b * b > r2 && c * c + d * d > r2) continue;
                }
                EvalMover(m, t); Apply(m);
            }
        }
    }
}
