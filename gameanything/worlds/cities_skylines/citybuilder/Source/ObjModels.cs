// Wavefront OBJ loader for the `obj` / `objherd` model kinds (see Props.cs). Generic: files come from data/models/.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace M2WCity
{
    // A parsed, normalised OBJ: one or more meshes (Unity's 65000 vertex limit) sharing one material. Parsed once, then cached.
    public class ObjAsset
    {
        public string name; public DateTime stamp;
        public List<Mesh> meshes = new List<Mesh>();
        public Material material; public Texture2D texture;
        public int tris; public Vector3 extent; public float sizeM;
    }

    public partial class Host
    {
        readonly Dictionary<string, ObjAsset> objCache = new Dictionary<string, ObjAsset>();

        string ModelsDir { get { return Path.Combine(dataDir, "models"); } }

        // Returns the cached asset (parsing it on first use or when the file changed); null if the file is missing or unreadable.
        ObjAsset GetObj(string name)
        {
            string path = Path.Combine(ModelsDir, name + ".obj");
            if (!File.Exists(path)) { L("obj: " + path + " not found"); return null; }
            DateTime stamp = File.GetLastWriteTimeUtc(path);
            ObjAsset a;
            if (objCache.TryGetValue(name, out a))
            {
                if (a != null && a.stamp == stamp) return a;
                DestroyObj(a); objCache.Remove(name);
            }
            try { a = LoadObj(name, path, stamp); }
            catch (Exception e) { L("obj " + name + ": " + e); a = null; }
            if (a != null) objCache[name] = a;
            return a;
        }

        void DestroyObj(ObjAsset a)
        {
            if (a == null) return;
            try { foreach (var m in a.meshes) Destroy(m); if (a.texture != null) Destroy(a.texture); if (a.material != null) Destroy(a.material); } catch (Exception) { }
        }

        void ClearObjCache() { foreach (var kv in objCache) DestroyObj(kv.Value); objCache.Clear(); }

        static float PF(string s) { return float.Parse(s, NumberStyles.Float, CultureInfo.InvariantCulture); }

        // index token of a face corner: 1-based, negative = relative to the count so far; returns -1 for "absent"
        static int ObjIdx(string s, int count)
        {
            if (s.Length == 0) return -1;
            int i = int.Parse(s, CultureInfo.InvariantCulture);
            i = i > 0 ? i - 1 : count + i;
            return i >= 0 && i < count ? i : -2;
        }

        ObjAsset LoadObj(string name, string path, DateTime stamp)
        {
            // optional <name>.txt : size=<m> scale=<k> yoffset=<m> up=y|z maxtris=<n>
            float size = 10f, extra = 1f, yoff = 0f; bool upZ = false; int maxTris = 0;
            string cfg = Path.Combine(ModelsDir, name + ".txt");
            if (File.Exists(cfg))
                foreach (var raw in File.ReadAllLines(cfg))
                {
                    var l = raw.Trim(); int eq = l.IndexOf('=');
                    if (l.Length == 0 || l[0] == '#' || eq <= 0) continue;
                    string k = l.Substring(0, eq).Trim().ToLowerInvariant(), v = l.Substring(eq + 1).Trim();
                    try
                    {
                        if (k == "size") size = PF(v); else if (k == "scale") extra = PF(v); else if (k == "yoffset") yoff = PF(v);
                        else if (k == "up") upZ = v.ToLowerInvariant() == "z"; else if (k == "maxtris") maxTris = int.Parse(v, CultureInfo.InvariantCulture);
                    }
                    catch (Exception e) { L("obj " + name + ".txt: bad line '" + l + "': " + e.Message); }
                }

            var pos = new List<Vector3>(); var uv = new List<Vector2>(); var nor = new List<Vector3>();
            var cp = new List<int>(); var ct = new List<int>(); var cn = new List<int>();   // one entry per triangle corner
            var seps = new[] { ' ', '\t' }; var slash = new[] { '/' };
            int badFaces = 0;
            using (var sr = new StreamReader(path))
            {
                string line;
                while ((line = sr.ReadLine()) != null)
                {
                    if (line.Length < 2 || line[0] == '#') continue;
                    if (line[0] == 'v')
                    {
                        var t = line.Split(seps, StringSplitOptions.RemoveEmptyEntries);
                        try
                        {
                            if (t[0] == "v" && t.Length >= 4) pos.Add(upZ ? new Vector3(PF(t[1]), PF(t[3]), PF(t[2])) : new Vector3(-PF(t[1]), PF(t[2]), PF(t[3])));
                            else if (t[0] == "vt" && t.Length >= 3) uv.Add(new Vector2(PF(t[1]), PF(t[2])));
                            else if (t[0] == "vn" && t.Length >= 4) nor.Add(upZ ? new Vector3(PF(t[1]), PF(t[3]), PF(t[2])) : new Vector3(-PF(t[1]), PF(t[2]), PF(t[3])));
                        }
                        catch (FormatException) { if (t[0] == "v") pos.Add(Vector3.zero); else if (t[0] == "vt") uv.Add(Vector2.zero); else if (t[0] == "vn") nor.Add(Vector3.up); }
                    }
                    else if (line[0] == 'f' && (line[1] == ' ' || line[1] == '\t'))
                    {
                        var t = line.Split(seps, StringSplitOptions.RemoveEmptyEntries);
                        int n = t.Length - 1; if (n < 3) { badFaces++; continue; }
                        var fp = new int[n]; var ft = new int[n]; var fn = new int[n]; bool ok = true;
                        for (int i = 0; i < n && ok; i++)
                        {
                            var q = t[i + 1].Split(slash);
                            try
                            {
                                fp[i] = ObjIdx(q[0], pos.Count);
                                ft[i] = q.Length > 1 ? ObjIdx(q[1], uv.Count) : -1;
                                fn[i] = q.Length > 2 ? ObjIdx(q[2], nor.Count) : -1;
                            }
                            catch (FormatException) { ok = false; }
                            if (fp[i] < 0 || ft[i] == -2 || fn[i] == -2) ok = false;
                        }
                        if (!ok) { badFaces++; continue; }
                        for (int i = 1; i + 1 < n; i++)   // fan triangulation; vertex order kept (the x mirror / axis swap already turns OBJ's CCW into Unity's CW)
                        {
                            cp.Add(fp[0]); ct.Add(ft[0]); cn.Add(fn[0]);
                            cp.Add(fp[i]); ct.Add(ft[i]); cn.Add(fn[i]);
                            cp.Add(fp[i + 1]); ct.Add(ft[i + 1]); cn.Add(fn[i + 1]);
                        }
                    }
                }
            }
            if (pos.Count == 0 || cp.Count == 0) throw new Exception("no geometry (" + pos.Count + " vertices, " + cp.Count / 3 + " triangles)");

            // decimate by stride if asked to
            int triCount = cp.Count / 3;
            if (maxTris > 0 && triCount > maxTris)
            {
                int stride = (triCount + maxTris - 1) / maxTris; var np = new List<int>(); var nt = new List<int>(); var nn = new List<int>();
                for (int tI = 0; tI < triCount; tI += stride)
                    for (int c = 0; c < 3; c++) { np.Add(cp[tI * 3 + c]); nt.Add(ct[tI * 3 + c]); nn.Add(cn[tI * 3 + c]); }
                cp = np; ct = nt; cn = nn; triCount = cp.Count / 3;
            }

            // bounds of the used vertices -> normalise: largest dimension = size, centred on x/z, min y = 0
            Vector3 mn = new Vector3(float.MaxValue, float.MaxValue, float.MaxValue), mx = new Vector3(float.MinValue, float.MinValue, float.MinValue);
            for (int i = 0; i < cp.Count; i++) { var p = pos[cp[i]]; mn = Vector3.Min(mn, p); mx = Vector3.Max(mx, p); }
            Vector3 ext = mx - mn; float big = Mathf.Max(ext.x, Mathf.Max(ext.y, ext.z));
            if (big <= 1e-9f) throw new Exception("degenerate model");
            float k2 = size / big * extra; Vector3 org = new Vector3((mn.x + mx.x) * 0.5f, mn.y, (mn.z + mx.z) * 0.5f);
            var P = new Vector3[pos.Count];
            for (int i = 0; i < P.Length; i++) P[i] = (pos[i] - org) * k2 + new Vector3(0f, yoff, 0f);

            // smooth normals per position for corners that have no vn
            Vector3[] acc = null;
            for (int i = 0; i < cn.Count; i++) if (cn[i] < 0) { acc = new Vector3[pos.Count]; break; }
            if (acc != null)
                for (int tI = 0; tI < triCount; tI++)
                {
                    int a0 = cp[tI * 3], a1 = cp[tI * 3 + 1], a2 = cp[tI * 3 + 2];
                    var fnrm = Vector3.Cross(P[a1] - P[a0], P[a2] - P[a0]);   // Unity's own convention for clockwise front faces
                    acc[a0] += fnrm; acc[a1] += fnrm; acc[a2] += fnrm;
                }

            var asset = new ObjAsset { name = name, stamp = stamp, tris = triCount, extent = ext * k2, sizeM = size };
            const int MAXV = 64998;   // multiple of 3, below Unity's 65000
            for (int s0 = 0; s0 < cp.Count; s0 += MAXV)
            {
                int cnt = Mathf.Min(MAXV, cp.Count - s0);
                var V = new Vector3[cnt]; var N = new Vector3[cnt]; var U = new Vector2[cnt]; var T = new int[cnt];
                for (int i = 0; i < cnt; i++)
                {
                    int g = s0 + i; V[i] = P[cp[g]]; T[i] = i;
                    U[i] = ct[g] >= 0 ? uv[ct[g]] : Vector2.zero;
                    if (cn[g] >= 0) N[i] = nor[cn[g]].normalized;
                    else { var a = acc[cp[g]]; N[i] = a.sqrMagnitude > 1e-20f ? a.normalized : Vector3.up; }
                }
                var m = new Mesh(); m.name = name + (s0 == 0 ? "" : "_" + (s0 / MAXV));
                m.vertices = V; m.normals = N; m.uv = U; m.triangles = T; m.RecalculateBounds();
                asset.meshes.Add(m);
            }

            // texture: <name>.png / .jpg, then _base_color, _albedo, _basecolor, _diffuse
            Texture2D tex = null;
            foreach (var suffix in new[] { "", "_base_color", "_albedo", "_basecolor", "_diffuse", "_texture" })
                foreach (var ext2 in new[] { ".png", ".jpg", ".jpeg" })
                {
                    var tp = Path.Combine(ModelsDir, name + suffix + ext2);
                    if (tex != null || !File.Exists(tp)) continue;
                    var t2 = new Texture2D(2, 2, TextureFormat.RGBA32, true);
                    if (t2.LoadImage(File.ReadAllBytes(tp))) { tex = t2; t2.wrapMode = TextureWrapMode.Repeat; t2.filterMode = FilterMode.Trilinear; t2.anisoLevel = 4; L("obj " + name + ": texture " + Path.GetFileName(tp) + " " + t2.width + "x" + t2.height); }
                    else { Destroy(t2); L("obj " + name + ": cannot decode " + tp); }
                }
            asset.texture = tex;
            asset.material = MakeMat(tex != null ? Color.white : new Color(0.75f, 0.75f, 0.72f));
            if (tex != null) asset.material.mainTexture = tex;
            L("obj " + name + ": " + pos.Count + " v, " + triCount + " tris, " + asset.meshes.Count + " mesh(es), " + (acc != null ? "computed" : "file") + " normals, extent "
              + asset.extent.x.ToString("F1", CultureInfo.InvariantCulture) + "x" + asset.extent.y.ToString("F1", CultureInfo.InvariantCulture) + "x" + asset.extent.z.ToString("F1", CultureInfo.InvariantCulture)
              + " m" + (badFaces > 0 ? ", skipped " + badFaces + " bad faces" : ""));
            return asset;
        }

        // one placed instance: shares the asset's Mesh / Material
        GameObject PlaceObj(ObjAsset a, Transform parent, string label, Vector3 pos, float yaw, float scale)
        {
            var go = new GameObject("M2W_" + label); go.transform.SetParent(parent, false);
            go.transform.position = pos; go.transform.rotation = Quaternion.Euler(0f, yaw, 0f); go.transform.localScale = Vector3.one * scale;
            for (int i = 0; i < a.meshes.Count; i++)
            {
                var part = new GameObject("part" + i); part.transform.SetParent(go.transform, false);
                part.AddComponent<MeshFilter>().sharedMesh = a.meshes[i];
                var r = part.AddComponent<MeshRenderer>(); r.sharedMaterial = a.material;
                r.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.On; r.receiveShadows = true;
            }
            return go;
        }
    }
}
