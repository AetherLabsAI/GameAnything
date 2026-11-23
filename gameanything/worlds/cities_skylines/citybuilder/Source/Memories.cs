using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using ColossalFramework;
using UnityEngine;

namespace M2WCity
{
    // In-city memory buttons (IMGUI: works with an OS font, so Chinese text shows), time buttons, and 3D text signs.
    public partial class Host
    {
        class Memory { public string id, title, titleEn, text; public Vector2 xz; public float dist, yaw, pitch; }
        List<Memory> memories = new List<Memory>(); string panelTitle = "GameAnything";
        string shownTitle, shownText; float shownSince; Coroutine tour;
        GUIStyle btn, box, titleStyle, textStyle, small; Font font; bool uiOpen = true;

        void LoadMemories()
        {
            memories.Clear();
            var f = Path.Combine(dataDir, "memories.txt");        // H|panel title   M|id|title|titleEn|x|z|dist|yaw|pitch|text (\n = newline)
            if (!File.Exists(f)) return;
            foreach (var line in File.ReadAllLines(f))
            {
                var p = line.Split('|');
                if (p.Length >= 2 && p[0] == "H") { panelTitle = p[1]; continue; }
                if (p.Length < 10 || p[0] != "M") continue;
                memories.Add(new Memory { id = p[1], title = p[2], titleEn = p[3], xz = new Vector2(F(p[4]), F(p[5])), dist = F(p[6]), yaw = F(p[7]), pitch = F(p[8]), text = p[9].Replace("\\n", "\n") });
            }
            L("memories loaded: " + memories.Count);
        }

        void MakeStyles()
        {
            if (btn != null) return;
            font = Font.CreateDynamicFontFromOSFont(new[] { "PingFang SC", "Heiti SC", "Hiragino Sans GB", "Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Zen Hei", "Arial Unicode MS", "Helvetica" }, 18);
            try { var osn = Font.GetOSInstalledFontNames(); var hit = new List<string>(); foreach (var n in osn) if (n.ToLower().Contains("noto") || n.ToLower().Contains("cjk") || n.ToLower().Contains("wenquan") || n.ToLower().Contains("han")) hit.Add(n); L("OS fonts: " + osn.Length + "; cjk-like: " + string.Join(", ", hit.ToArray()) + "; font.fontNames: " + (font.fontNames == null ? "null" : string.Join(", ", font.fontNames))); } catch (Exception e) { L("font probe failed: " + e.Message); }
            btn = new GUIStyle(GUI.skin.button); btn.font = font; btn.fontSize = 18; btn.alignment = TextAnchor.MiddleLeft; btn.padding = new RectOffset(12, 8, 6, 6);
            box = new GUIStyle(GUI.skin.box); box.font = font; box.fontSize = 16;
            titleStyle = new GUIStyle(GUI.skin.label); titleStyle.font = font; titleStyle.fontSize = 26; titleStyle.fontStyle = FontStyle.Bold; titleStyle.normal.textColor = Color.white; titleStyle.wordWrap = true;
            textStyle = new GUIStyle(GUI.skin.label); textStyle.font = font; textStyle.fontSize = 22; textStyle.normal.textColor = Color.white; textStyle.wordWrap = true;
            small = new GUIStyle(GUI.skin.label); small.font = font; small.fontSize = 14; small.normal.textColor = new Color(1, 1, 1, 0.85f);
        }


        // ---- CJK fallback: Unity on Linux only sees the system fonts (DejaVu), so Chinese would be blank. Text the font cannot draw is shown from a
        // picture pre-rendered by 5_build/m7/make_ui_tex.py: data/ui/<md5(text)>_<tag>.png (tag b = button 18 px, s = small 14 px, T = title 26 px bold, t = wrapped text 22 px).
        Dictionary<string, Texture2D> uiTex = new Dictionary<string, Texture2D>();
        static string Md5(string s) { using (var m = System.Security.Cryptography.MD5.Create()) { var b = m.ComputeHash(System.Text.Encoding.UTF8.GetBytes(s)); var sb = new System.Text.StringBuilder(); foreach (var x in b) sb.Append(x.ToString("x2")); return sb.ToString(); } }
        bool? hasCjk;
        bool CanDraw(string s)
        {
            if (hasCjk == null)
            {
                bool f = false; try { foreach (var n in Font.GetOSInstalledFontNames()) { var l = n.ToLower(); if (l.Contains("pingfang") || l.Contains("heiti") || l.Contains("hiragino") || l.Contains("noto") || l.Contains("cjk") || l.Contains("wenquan") || l.Contains("han sans") || l.Contains("arial unicode") || l.Contains("yahei") || l.Contains("simsun")) f = true; } } catch { }
                hasCjk = f; L("CJK font installed: " + f + " (false = Chinese text is shown from data/ui pictures)");
            }
            if (hasCjk == true) return true;
            foreach (var c in s) if ((c >= 0x2E80 && c <= 0x9FFF) || (c >= 0x3000 && c <= 0x303F) || (c >= 0xFF00 && c <= 0xFFEF) || (c >= 0xD800 && c <= 0xDFFF) || (c >= 0x2600 && c <= 0x27BF) || c == 0x23F1) return false;
            return true;
        }
        Texture2D UiTex(string key)
        {
            Texture2D t; if (uiTex.TryGetValue(key, out t)) return t;
            var p = Path.Combine(Path.Combine(dataDir, "ui"), key + ".png"); t = null;
            if (File.Exists(p)) { t = new Texture2D(2, 2, TextureFormat.ARGB32, false); t.LoadImage(File.ReadAllBytes(p)); t.filterMode = FilterMode.Bilinear; }
            uiTex[key] = t; return t;
        }
        // draws s as text, or as its picture (left/top aligned, shrunk to fit the rect) when the font lacks glyphs; returns true if a picture was used
        bool LblTex(Rect r, string s, string tag, GUIStyle st)
        {
            if (!CanDraw(s)) { var t = UiTex(Md5(s) + "_" + tag); if (t != null) { float k = Mathf.Min(1f, Mathf.Min(r.width / t.width, r.height / t.height)); GUI.DrawTexture(new Rect(r.x, r.y, t.width * k, t.height * k), t, ScaleMode.ScaleToFit); return true; } }
            GUI.Label(r, s, st); return false;
        }
        bool BtnTex(Rect r, string s, GUIStyle st)
        {
            if (CanDraw(s)) return GUI.Button(r, s, st);
            bool c = GUI.Button(r, "", st); LblTex(new Rect(r.x + 12, r.y + 4, r.width - 20, r.height - 8), s, "b", st); return c;
        }

        void OnGUI()
        {
            if (!inCity || hideGui || memories.Count == 0 && !Directory.Exists(dataDir)) return;
            MakeStyles();
            float w = 270f, x = 14f, y = 120f;
            if (GUI.Button(new Rect(x, y - 34f, w, 28f), (uiOpen ? "▾ " : "▸ ") + panelTitle, btn)) uiOpen = !uiOpen;
            if (uiOpen)
            {
                float h = 12f + memories.Count * 40f + 14f + 4 * 38f + 10f;
                GUI.Box(new Rect(x, y, w, h), "", box);
                float yy = y + 8f;
                LblTex(new Rect(x + 10, yy, w - 20, 22), "回忆镜头 Memories", "s", small); yy += 24f;
                foreach (var m in memories)
                {
                    if (BtnTex(new Rect(x + 8, yy, w - 16, 34f), m.title, btn)) Fly(m);
                    yy += 38f;
                }
                yy += 8f;
                GUI.Label(new Rect(x + 10, yy, w - 20, 22), "天气 / 时间 Sky", small); yy += 24f;
                if (BtnTex(new Rect(x + 8, yy, w - 16, 34f), "🌇 日落 Sunset", btn)) { holdHour = -1f; SetHour(SunsetHour); SetWeather(true); } yy += 38f;
                if (BtnTex(new Rect(x + 8, yy, w - 16, 34f), "🌅 日出 Sunrise", btn)) { holdHour = -1f; SetHour(SunriseHour); SetWeather(true); } yy += 38f;
                if (BtnTex(new Rect(x + 8, yy, w - 16, 34f), "☀ 晴天 Clear day", btn)) { holdHour = -1f; SetHour(12.5f); SetWeather(true); } yy += 38f;
                if (BtnTex(new Rect(x + 8, yy, w - 16, 34f), "⏱ 昼夜流动 Natural cycle", btn)) { holdHour = -1f; SetWeather(false); }
            }
            if (!string.IsNullOrEmpty(shownText))
            {
                float a = Mathf.Clamp01((Time.realtimeSinceStartup - shownSince) / 1.2f);
                var old = GUI.color; GUI.color = new Color(1, 1, 1, a);
                float bw = Mathf.Min(Screen.width - 80f, 900f), bh = 190f;
                var r = new Rect((Screen.width - bw) / 2f, Screen.height - bh - 40f, bw, bh);
                GUI.Box(r, "", box); GUI.Box(r, "", box);
                LblTex(new Rect(r.x + 22, r.y + 14, bw - 44, 40), shownTitle, "T", titleStyle);
                LblTex(new Rect(r.x + 22, r.y + 62, bw - 44, bh - 70), shownText, "t", textStyle);
                GUI.color = old;
            }
        }

        void Fly(Memory m)
        {
            if (tour != null) StopCoroutine(tour);
            tour = StartCoroutine(FlyRoutine(m));
        }

        IEnumerator FlyRoutine(Memory m, float orbit = 22f)
        {
            var cc = Singleton<CameraController>.instance;
            shownTitle = null; shownText = null;
            Vector3 p0 = cc.m_currentPosition; float d0 = cc.m_currentSize; Vector2 a0 = cc.m_currentAngle;
            Vector3 p1 = new Vector3(m.xz.x, Ground(m.xz.x, m.xz.y), m.xz.y);
            float yaw0 = a0.x, yawT = m.yaw;
            float dy = Mathf.DeltaAngle(yaw0, yawT);
            float t = 0f, dur = 2.6f;
            while (t < dur)
            {
                t += Time.deltaTime; float k = Mathf.SmoothStep(0f, 1f, Mathf.Clamp01(t / dur));
                Cam(Vector3.Lerp(p0, p1, k), Mathf.Lerp(d0, m.dist, k), yaw0 + dy * k, Mathf.Lerp(a0.y, m.pitch, k));
                yield return null;
            }
            shownTitle = m.title + "   " + m.titleEn; shownText = m.text; shownSince = Time.realtimeSinceStartup;
            t = 0f; dur = orbit;
            while (t < dur)                                  // one slow turn around the place
            {
                t += Time.deltaTime;
                Cam(p1, m.dist, yawT + 360f * (t / dur), m.pitch);
                yield return null;
            }
            // the words stay until another button is pressed
            tour = null;
        }

        // ---------- 3D text signs: S|text|x|z|y|size ----------
        class Sign { public GameObject go; public Vector3 pos; }
        List<Sign> signs = new List<Sign>();

        IEnumerator CmdSigns(string[] a)
        {
            foreach (var s in signs) if (s.go != null) Destroy(s.go);
            signs.Clear();
            var file = Path.Combine(dataDir, a.Length > 1 ? a[1] : "signs.txt");
            if (!File.Exists(file)) yield break;
            var sfont = Font.CreateDynamicFontFromOSFont(new[] { "PingFang SC", "Noto Sans SC", "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Zen Hei", "Helvetica" }, 64);
            foreach (var line in File.ReadAllLines(file))
            {
                var p = line.Split('|');
                if (p.Length < 5 || p[0] != "S") continue;
                float x = F(p[2]), z = F(p[3]), y = F(p[4]); float size = p.Length > 5 ? F(p[5]) : 1f;
                var go = new GameObject("M2WSign");
                var tm = go.AddComponent<TextMesh>();
                tm.text = p[1]; tm.font = sfont; tm.fontSize = 64; tm.characterSize = 0.12f * size; tm.anchor = TextAnchor.MiddleCenter; tm.alignment = TextAlignment.Center; tm.color = Color.white;
                go.GetComponent<MeshRenderer>().material = sfont.material;
                go.transform.position = new Vector3(x, y, z);
                var shadow = new GameObject("shadow"); shadow.transform.parent = go.transform; shadow.transform.localPosition = new Vector3(0.12f, -0.12f, 0.02f) * size; shadow.transform.localRotation = Quaternion.identity; shadow.transform.localScale = Vector3.one;
                var tm2 = shadow.AddComponent<TextMesh>(); tm2.text = p[1]; tm2.font = sfont; tm2.fontSize = 64; tm2.characterSize = 0.12f * size; tm2.anchor = TextAnchor.MiddleCenter; tm2.alignment = TextAlignment.Center; tm2.color = new Color(0, 0, 0, 0.9f);
                shadow.GetComponent<MeshRenderer>().material = sfont.material;
                signs.Add(new Sign { go = go, pos = go.transform.position });
            }
            L("signs: " + signs.Count);
            yield return null;
        }

        void LateUpdate()
        {
            CineLateUpdate();
            UpdateGlows();
            if (signs.Count == 0 || !inCity) return;
            var cam = Camera.main; if (cam == null) return;
            foreach (var s in signs)
            {
                if (s.go == null) continue;
                float d = Vector3.Distance(cam.transform.position, s.pos);
                s.go.SetActive(d < 650f);
                s.go.transform.rotation = cam.transform.rotation;
                float k = Mathf.Max(1f, d / 120f);          // stay readable from further away
                s.go.transform.localScale = Vector3.one * k;
            }
        }
    }
}
