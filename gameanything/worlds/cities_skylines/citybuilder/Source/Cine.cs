// Deterministic, frame-stepped cinematic recording: cine <name> [fps=24] [width=1280]. Camera = f(virtual time), independent of capture speed.
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
        class CineKey { public float t, x, z, y, dist, yaw, pitch; public bool hero, hasY, eye; public string ease = ""; public string follow; public float yawOff, height; }
        class CineChap { public string id, title, titleEn, text; public bool eyeMode, lift, chase; public float hour = -1f; public List<CineKey> keys = new List<CineKey>(); public float Length { get { return keys.Count == 0 ? 0f : keys[keys.Count - 1].t; } } }

        // data/cine.txt:  C|id|title|titleEn|text (\n)|hour[|lift 0/1]    K|sec|x|z|dist|yaw|pitch[|ease]    H|sec|x|z|y|dist|yaw|pitch   F|sec|tag|dist|yawOffset|pitch|height   E|sec|x|y|z|yaw|pitch   (# comments)
        List<CineChap> LoadCine()
        {
            var list = new List<CineChap>(); var f = Path.Combine(dataDir, "cine.txt");
            if (!File.Exists(f)) return list;
            CineChap cur = null; int n = 0;
            foreach (var raw in File.ReadAllLines(f))
            {
                n++; var l = raw.Trim(); if (l.Length == 0 || l[0] == '#') continue;
                var p = l.Split('|');
                try
                {
                    if (p[0] == "C" && p.Length >= 5)
                    {
                        cur = new CineChap { id = p[1], title = p[2], titleEn = p[3], text = p[4].Replace("\\n", "\n") };
                        if (p.Length > 5 && p[5].Trim().Length > 0) cur.hour = F(p[5].Trim());
                        if (p.Length > 6 && p[6].Trim().Length > 0) cur.lift = F(p[6].Trim()) >= 0.5f;
                        list.Add(cur);
                    }
                    else if (p[0] == "K" && p.Length >= 7 && cur != null)
                    {
                        var k = new CineKey { t = F(p[1]), x = F(p[2]), z = F(p[3]), dist = F(p[4]), yaw = F(p[5]), pitch = F(p[6]) };
                        if (p.Length > 7) k.ease = p[7].Trim().ToLowerInvariant();
                        cur.keys.Add(k);
                    }
                    else if (p[0] == "F" && p.Length >= 7 && cur != null)
                    {
                        if (FindMover(p[2].Trim()) == null) { L("cine.txt line " + n + ": follow tag '" + p[2].Trim() + "' not found (id= in models.txt); key skipped"); continue; }
                        cur.keys.Add(new CineKey { t = F(p[1]), follow = p[2].Trim(), dist = F(p[3]), yawOff = F(p[4]), pitch = F(p[5]), height = F(p[6]), hasY = true });
                    }
                    else if (p[0] == "E" && p.Length >= 7 && cur != null)
                    {
                        // absolute eye: camera AT (x, y, z) (y = metres above sea level 0), looking with yaw/pitch
                        cur.keys.Add(new CineKey { t = F(p[1]), x = F(p[2]), y = F(p[3]), z = F(p[4]), yaw = F(p[5]), pitch = F(p[6]), eye = true, hasY = true, dist = EyeLook });
                    }
                    else if (p[0] == "H" && p.Length >= 8 && cur != null)
                    {
                        var k = new CineKey { t = F(p[1]), x = F(p[2]), z = F(p[3]), dist = F(p[5]), yaw = F(p[6]), pitch = F(p[7]), hero = true };
                        if (p[4].Trim().Length > 0) { k.y = F(p[4]); k.hasY = true; }
                        cur.keys.Add(k);
                    }
                }
                catch (Exception e) { L("cine.txt line " + n + ": " + e.Message); }
            }
            foreach (var c in list) c.keys.Sort((a, b) => a.t.CompareTo(b.t));
            list.RemoveAll(c => c.keys.Count < 2);
            foreach (var c in list)
            {
                bool all = true, any = false;
                foreach (var k in c.keys) { if (k.eye) any = true; else all = false; }
                c.eyeMode = all;
                if (all) c.lift = true;                    // E-only chapters need the lifted camera (exact eye positions)
                foreach (var k in c.keys) if (k.follow != null) c.chase = true;
                if (any && !all)          // E mixed with K/H/F: E becomes the equivalent look-at key (target EyeLook m ahead of the eye)
                {
                    L("cine chapter " + c.id + ": E keys mixed with K/H/F keys, converted to look-at keys (dist " + EyeLook + "); use only E keys in a chapter for exact eye positions");
                    foreach (var k in c.keys)
                        if (k.eye)
                        {
                            var fw = Quaternion.AngleAxis(k.yaw, Vector3.up) * Quaternion.AngleAxis(k.pitch, Vector3.right) * Vector3.forward * EyeLook;
                            k.x += fw.x; k.y += fw.y; k.z += fw.z; k.eye = false; k.hasY = true; k.hero = false;
                        }
                }
            }
            return list;
        }

        const float EyeLook = 10f;      // look-at distance used for the fields / mixed chapters in eye mode

        static float CR(float p0, float p1, float p2, float p3, float u)
        {
            return 0.5f * ((2f * p1) + (-p0 + p2) * u + (2f * p0 - 5f * p1 + 4f * p2 - p3) * u * u + (-p0 + 3f * p1 - 3f * p2 + p3) * u * u * u);
        }
        static float Smoother(float u) { return u * u * u * (u * (u * 6f - 15f) + 10f); }

        // camera state at chapter-local time t (seconds)
        void CineEval(CineChap c, float t, out Vector3 pos, out float dist, out float yaw, out float pitch, out bool eye)
        {
            var k = c.keys; int n = k.Count;
            if (t <= k[0].t) t = k[0].t; if (t >= k[n - 1].t) t = k[n - 1].t;
            int i = 0; while (i < n - 2 && t > k[i + 1].t) i++;
            var a = k[i]; var b = k[i + 1];
            float span = Mathf.Max(1e-4f, b.t - a.t), u = Mathf.Clamp01((t - a.t) / span);
            eye = c.eyeMode;
            if (a.hero || b.hero || a.ease == "slow") u = Smoother(u);
            else if (a.ease == "smooth") u = Mathf.SmoothStep(0f, 1f, u);
            else if (a.ease == "lin") { }
            var k0 = k[Mathf.Max(0, i - 1)]; var k3 = k[Mathf.Min(n - 1, i + 2)];
            // unwrap yaw relative to a so the shortest way round is taken
            float y1 = a.yaw, y0 = y1 + Mathf.DeltaAngle(y1, k0.yaw), y2 = y1 + Mathf.DeltaAngle(y1, b.yaw), y3 = y2 + Mathf.DeltaAngle(y2, k3.yaw);
            yaw = CR(y0, y1, y2, y3, u);
            float x = CR(k0.x, a.x, b.x, k3.x, u), z = CR(k0.z, a.z, b.z, k3.z, u);
            if (eye)
            {
                dist = EyeLook; pitch = Mathf.Clamp(CR(k0.pitch, a.pitch, b.pitch, k3.pitch, u), -89f, 89f);
                pos = new Vector3(x, CR(k0.y, a.y, b.y, k3.y, u), z);
                return;
            }
            dist = Mathf.Max(1f, CR(k0.dist, a.dist, b.dist, k3.dist, u));
            pitch = Mathf.Clamp(CR(k0.pitch, a.pitch, b.pitch, k3.pitch, u), 1f, 89f);
            float g = Ground(x, z);
            float ya = a.hasY ? a.y : g, yb = b.hasY ? b.y : g;
            float y = (a.hasY || b.hasY) ? Mathf.Lerp(ya, yb, u) : g;
            pos = new Vector3(x, y, z);
        }

        class FState { public Vector3 p; public float yaw; public int stamp; }
        readonly Dictionary<string, FState> fstate = new Dictionary<string, FState>();
        int fstamp;

        // Moves the follow target of every F key of the chapter to the (smoothed) pose of its model at virtual time vt, and writes it into the keys.
        // The keys then act as ordinary keys (x, z, y, yaw) in CineEval, so K and F keys can be mixed and Catmull-Rom blends between them.
        void CineFollowUpdate(CineChap c, double vt, float dt, bool reset)
        {
            if (reset) fstate.Clear();
            fstamp++;
            float a = 1f - Mathf.Exp(-dt * 6f), ay = 1f - Mathf.Exp(-dt * 4f);   // virtual dt (1/fps): frame-rate independent; heading a little slower to hide road-polyline kinks
            for (int i = 0; i < c.keys.Count; i++)
            {
                var k = c.keys[i]; if (k.follow == null) continue;
                var m = FindMover(k.follow); if (m == null) continue;
                FState s;
                if (!fstate.TryGetValue(k.follow, out s)) { s = new FState(); fstate[k.follow] = s; }
                if (s.stamp != fstamp)
                {
                    bool first = s.stamp == 0;
                    if (m.mode != 0) { EvalMover(m, vt); Apply(m); }
                    var tp = new Vector3(m.px, m.py, m.pz);
                    if (first) { s.p = tp; s.yaw = m.yaw; } else { s.p = Vector3.Lerp(s.p, tp, a); s.yaw = Mathf.LerpAngle(s.yaw, m.yaw, ay); }
                    s.stamp = fstamp;
                }
                k.x = s.p.x; k.z = s.p.z; k.y = s.p.y + k.height; k.yaw = s.yaw + k.yawOff;
            }
        }

        // ---------- lifted camera limits ----------
        // CameraController (IL): LateUpdate = UpdateFreeCamera, UpdateTargetPosition, UpdateCurrentPosition, UpdateTransform.
        //  * m_targetSize = Clamp(.., m_minDistance, m_maxDistance) every frame        -> the "closer than 40 m behaves like 40" limit
        //  * target angle y is clamped to >= 0 and a tilt term pushes the pitch to 90 deg as size grows:
        //    effPitch = 90 - (90 - pitch) * (maxTilt/2) / (maxTilt/2 + size)            -> pitch 7-15 looks steeper; fixed by a huge m_maxTiltDistance
        //  * the eye is pushed up by CalculateCameraHeightOffset (terrain, and buildings/props/trees +5 m unless static m_disableCollision)
        //  * UpdateTransform: near = Max(origNear, size*0.005); D = size * Max(0, 1 - currentHeight/maxDistance) / tan(fov*Deg2Rad);
        //    rot = AngleAxis(yaw, up) * AngleAxis(pitch, right); eye = currentPosition + rot*(0,0,-D); eye.y += CalculateCameraHeightOffset(eye, D); clamp x/z to +-8640.
        //  * m_targetHeight = terrain height under the target point (not a user setting; it only feeds currentHeight / the D factor).
        // While a CamLift() scope is open (cine, tour, shot) the fields are relaxed AND Host.LateUpdate (order 32000, after the game) recomputes the final
        // transform from the last Cam()/CamEye() pose with the SAME formula but without any clamp, so any distance / pitch / eye position is exact.
        static int liftN; static float liftMin, liftTilt, liftNear, liftNearSet; static bool liftColl;
        static bool camPoseSet, camEye; static Vector3 camP, camEyePos; static float camDist, camYaw, camPitch;
        static float dPosMax, dSizeMax, dAngMax; static bool camChase; static float camChaseH;
        public static void CamLift()
        {
            if (liftN++ > 0) return;
            try
            {
                var cc = Singleton<CameraController>.instance; var cm = cc.GetComponent<Camera>();
                liftMin = cc.m_minDistance; liftTilt = cc.m_maxTiltDistance; liftColl = CameraController.m_disableCollision; liftNear = cm != null ? cm.nearClipPlane : 0f;
                cc.m_minDistance = 3f; cc.m_maxTiltDistance = 1000000f; CameraController.m_disableCollision = true; cc.m_unlimitedCamera = true;
                camPoseSet = false;
                L("camera limits lifted: m_minDistance " + liftMin + " -> 3, m_maxTiltDistance " + liftTilt + " -> 1e6, collision off (was " + (liftColl ? "off" : "on") + "), pitch/size/eye applied directly to the transform");
            }
            catch (Exception e) { L("CamLift: " + e.Message); }
        }
        public static void CamUnlift()
        {
            if (liftN <= 0) { liftN = 0; return; }
            if (--liftN > 0) return;
            camPoseSet = false;
            try
            {
                var cc = Singleton<CameraController>.instance; var cm = cc.GetComponent<Camera>();
                cc.m_minDistance = liftMin; cc.m_maxTiltDistance = liftTilt; CameraController.m_disableCollision = liftColl;
                if (cm != null && liftNear > 0f) cm.nearClipPlane = liftNear;
                L("camera limits restored (m_minDistance " + liftMin + ", m_maxTiltDistance " + liftTilt + ")");
            }
            catch (Exception e) { L("CamUnlift: " + e.Message); }
        }
        // camera AT eye, looking with yaw / pitch (pitch may be negative = looking up). The CameraController fields get an equivalent look-at point EyeLook m ahead.
        public static void CamEye(Vector3 eye, float yaw, float pitch)
        {
            var cc = Singleton<CameraController>.instance;
            var rot = Quaternion.AngleAxis(yaw, Vector3.up) * Quaternion.AngleAxis(pitch, Vector3.right);
            var look = eye + rot * new Vector3(0f, 0f, EyeLook);
            cc.m_targetPosition = look; cc.m_currentPosition = look;
            cc.m_targetSize = EyeLook; cc.m_currentSize = EyeLook;
            cc.m_targetAngle = new Vector2(yaw, pitch); cc.m_currentAngle = new Vector2(yaw, pitch);
            camEyePos = eye; camDist = EyeLook; camYaw = yaw; camPitch = pitch; camEye = true; camPoseSet = true;
        }
        void CineLateUpdate()
        {
            if (liftN <= 0 || !camPoseSet) return;
            try
            {
                var cc = Singleton<CameraController>.instance; var cm = cc.GetComponent<Camera>();
                if (cineActive)
                {
                    Vector3 lp = camEye ? camEyePos : camP;
                    dPosMax = Mathf.Max(dPosMax, (cc.m_currentPosition - (camEye ? camEyePos + Quaternion.AngleAxis(camYaw, Vector3.up) * Quaternion.AngleAxis(camPitch, Vector3.right) * new Vector3(0f, 0f, EyeLook) : lp)).magnitude);
                    dSizeMax = Mathf.Max(dSizeMax, Mathf.Abs(cc.m_currentSize - camDist));
                    dAngMax = Mathf.Max(dAngMax, Mathf.Abs(Mathf.DeltaAngle(cc.m_currentAngle.x, camYaw)), Mathf.Abs(cc.m_currentAngle.y - camPitch));
                }
                // no roll, pitch always inside the range, finite numbers only (the pose may have been written by Cam()/CamEye() with anything)
                float yawF = float.IsNaN(camYaw) || float.IsInfinity(camYaw) ? 0f : camYaw;
                float pitF = float.IsNaN(camPitch) || float.IsInfinity(camPitch) ? 10f : (camEye ? Mathf.Clamp(camPitch, -89f, 89f) : Mathf.Clamp(camPitch, 1f, 89f));
                Vector3 eye; float D;
                if (camEye) { eye = camEyePos; D = camDist; }
                else
                {
                    var rot0 = Quaternion.AngleAxis(yawF, Vector3.up) * Quaternion.AngleAxis(pitF, Vector3.right);
                    float k = Mathf.Clamp01(1f - cc.m_currentHeight / cc.m_maxDistance);
                    D = Mathf.Max(1.5f, camDist * k / Mathf.Tan(0.017453292f * cm.fieldOfView));
                    eye = camP + rot0 * new Vector3(0f, 0f, -D);
                    eye.x = Mathf.Clamp(eye.x, -8640f, 8640f); eye.z = Mathf.Clamp(eye.z, -8640f, 8640f);
                }
                // collision is off while lifted: never let the eye sink under the terrain, and in a chase never below the car/target
                float floor = Ground(eye.x, eye.z) + 1.5f;
                if (camChase && !camEye) floor = Mathf.Max(floor, camP.y - camChaseH + 2.5f);     // car height + 2.5 m (camP.y = car + the F key height)
                bool raised = false;
                if (eye.y < floor) { eye.y = floor; raised = true; }
                float pitUse = pitF;
                if (raised && !camEye)       // keep the target in view after raising the eye (still no roll, pitch inside 1..89)
                {
                    Vector3 dir = camP - eye; float hz = new Vector2(dir.x, dir.z).magnitude;
                    if (hz > 0.01f) pitUse = Mathf.Clamp(Mathf.Atan2(-dir.y, hz) * 57.29578f, 1f, 89f);
                }
                var fwd = Quaternion.AngleAxis(yawF, Vector3.up) * Quaternion.AngleAxis(pitUse, Vector3.right) * Vector3.forward;
                var rot = Quaternion.LookRotation(fwd, Vector3.up);
                cc.transform.rotation = rot; cc.transform.position = eye;
                if (D < 150f) cm.nearClipPlane = Mathf.Min(cm.nearClipPlane, 0.5f);      // game: Max(origNear, size*0.005); close views need a small near plane
            }
            catch (Exception) { }
        }

        IEnumerator CmdCine(string[] a)
        {
            if (a.Length < 2) { L("usage: cine <name> [fps=24] [width=1280] [aa=8]"); yield break; }
            if (recording) { L("cine: already recording"); yield break; }
            if (!inCity) { L("cine: not in a city"); yield break; }
            var chaps = LoadCine();
            if (chaps.Count == 0) { L("cine: no chapters in data/cine.txt"); yield break; }
            var st = NewRec(a[1], a.Length > 2 ? F(a[2]) : 24f, a.Length > 3 ? (int)F(a[3]) : 1280, a.Length > 4 ? (int)F(a[4]) : 8);
            var sm = Singleton<SimulationManager>.instance;
            bool wasPaused = sm.SimulationPaused || sm.ForcedSimulationPaused; int oldSpeed = sm.SelectedSimulationSpeed; float savedHold = holdHour;
            if (wasPaused) { sm.ForcedSimulationPaused = false; sm.SimulationPaused = false; sm.SelectedSimulationSpeed = 1; L("cine: sim was paused, running at speed 1"); }
            RenderTexture rt = null; Texture2D tex = null; Camera cam = null;
            recording = true;
            try
            {
                if (Directory.Exists(st.dir)) foreach (var f in Directory.GetFiles(st.dir, "*.jpg")) File.Delete(f);
                Directory.CreateDirectory(st.dir);
                cam = Singleton<CameraController>.instance.GetComponent<Camera>();
                rt = MakeCaptureRT(st.w, st.h, st.aa); tex = new Texture2D(st.w, st.h, TextureFormat.RGB24, false);
            }
            catch (Exception e) { L("cine setup: " + e.Message); recording = false; yield break; }
            var inv = CultureInfo.InvariantCulture; var ch = new StringBuilder(); var full = new StringBuilder();
            int frame = 0, fails = 0; float vstart = 0f; bool abort = false; float realStart = Time.realtimeSinceStartup;
            Vector3 lastPos = Vector3.zero; bool havePrev = false;
            float maxRot = 0f, maxFieldPos = 0f; int checks = 0;
            dPosMax = dSizeMax = dAngMax = 0f; camPoseSet = false;
            int oldCapture = Time.captureFramerate;
            bool chapLift = false;
            try
            {
            // deterministic time: every rendered frame advances Time.time / shader time by exactly 1/fps
            Time.captureFramerate = Mathf.Max(1, Mathf.RoundToInt(st.fps));
            cineActive = true; cineVT = 0.0;
            try
            {
                var cc0 = Singleton<CameraController>.instance; var sb = new StringBuilder();
                foreach (var fi in typeof(CameraController).GetFields(System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic))
                {
                    string ln = fi.Name.ToLowerInvariant();
                    if (ln.Contains("shake") || ln.Contains("collis") || ln.Contains("smooth") || ln.Contains("inert") || ln.Contains("damp"))
                    {
                        sb.Append(fi.Name).Append('=').Append(fi.GetValue(cc0)).Append(' ');
                        if (ln.Contains("shake") && fi.FieldType == typeof(float)) fi.SetValue(cc0, 0f);
                    }
                }
                cc0.m_unlimitedCamera = true;
                L("cine: captureFramerate " + Time.captureFramerate + "; camera fields: " + (sb.Length == 0 ? "(no shake/collision/smooth fields)" : sb.ToString()));
            }
            catch (Exception e) { L("cine camera fields: " + e.Message); }
            foreach (var c in chaps)
            {
                bool wantLift = c.lift || c.eyeMode; bool switched = false;
                if (wantLift && !chapLift) { CamLift(); chapLift = true; switched = true; }
                else if (!wantLift && chapLift) { CamUnlift(); chapLift = false; switched = true; }
                camChase = c.chase; camChaseH = 0f; if (c.chase) { camChaseH = 1e9f; foreach (var fk in c.keys) if (fk.follow != null) camChaseH = Mathf.Min(camChaseH, fk.height); camChaseH = Mathf.Max(0f, camChaseH); }
                camPoseSet = false;
                L("cine chapter " + c.id + ": " + (chapLift ? "LIFTED camera" : "NORMAL game camera limits"));
                if (switched) for (int w = 0; w < 4; w++) yield return null;     // let the game apply the restored / lifted limits before the first frame
                if (c.hour >= 0f)  { holdHour = c.hour; SetHour(c.hour); SetWeather(true); }
                int frames = Mathf.Max(1, Mathf.RoundToInt(c.Length * st.fps));
                for (int k = 0; k < frames && !abort; k++)
                {
                    Vector3 pos; float dist, yaw, pitch; bool eyeM;
                    cineVT = frame / (double)st.fps;
                    CineFollowUpdate(c, cineVT, 1f / st.fps, k == 0);
                    CineEval(c, k / st.fps, out pos, out dist, out yaw, out pitch, out eyeM);
                    if (eyeM) CamEye(pos, yaw, pitch); else Cam(pos, dist, yaw, pitch);
                    // let rendering / LOD / streaming settle: 1 frame normally, more after cuts and big jumps
                    int settle = 1;
                    if (k == 0) settle = switched ? 10 : 6; else if (havePrev && (pos - lastPos).magnitude > (eyeM ? 15f : dist * 0.25f)) settle = 3;
                    for (int s = 0; s < settle; s++) yield return null;
                    if (eyeM) CamEye(pos, yaw, pitch); else Cam(pos, dist, yaw, pitch);          // write the pose again after the settle waits, just before the capture
                    MoversTick();                        // movers near the final camera are at their pose for virtual time frame/fps
                    yield return new WaitForEndOfFrame();
                    try
                    {
                        var cc1 = Singleton<CameraController>.instance; checks++;
                        var cm = cc1.GetComponent<Camera>();
                        maxFieldPos = Mathf.Max(maxFieldPos, eyeM && cm != null ? (cm.transform.position - pos).magnitude : (cc1.m_currentPosition - pos).magnitude);
                        if (cm != null && chapLift) maxRot = Mathf.Max(maxRot, Quaternion.Angle(cm.transform.rotation, Quaternion.Euler(pitch, yaw, 0f)));
                    }
                    catch (Exception) { }
                    if (GrabJpg(cam, rt, tex, Path.Combine(st.dir, frame.ToString("00000") + ".jpg"), 92)) { frame++; fails = 0; }
                    else if (++fails >= 5) { L("cine: capture keeps failing, stopping"); abort = true; }
                    lastPos = pos; havePrev = true;
                }
                if (abort) break;
                float vend = frame / st.fps;
                ch.Append(vstart.ToString("0.00", inv)).Append('|').Append(c.id).Append('|').Append(c.title).Append("   ").Append(c.titleEn).Append('\n');
                full.Append(vstart.ToString("0.00", inv)).Append('|').Append(vend.ToString("0.00", inv)).Append('|').Append(c.id).Append('|').Append(c.title).Append('|').Append(c.titleEn).Append('|').Append(c.text.Replace("\n", "\\n")).Append('\n');
                vstart = vend;
            }
            }
            finally
            {
                cineActive = false; if (chapLift) { chapLift = false; CamUnlift(); } Time.captureFramerate = oldCapture;
            }
            holdHour = savedHold;
            if (wasPaused) { sm.SelectedSimulationSpeed = oldSpeed; sm.SimulationPaused = true; }
            try
            {
                File.WriteAllText(Path.Combine(st.dir, "chapters.txt"), ch.ToString(), new UTF8Encoding(false));
                File.WriteAllText(Path.Combine(st.dir, "chapters_full.txt"), full.ToString(), new UTF8Encoding(false));
            }
            catch (Exception e) { L("cine chapters: " + e.Message); }
            try { if (rt != null) Destroy(rt); if (tex != null) Destroy(tex); } catch (Exception) { }
            float real = Time.realtimeSinceStartup - realStart;
            L("cine: " + frame + " frames = " + (frame / st.fps).ToString("0.0", inv) + " s video at " + st.fps + " fps, " + st.w + "x" + st.h + ", captured in " + real.ToString("0.0", inv) + " s real (" + (frame / Mathf.Max(0.01f, real)).ToString("0.0", inv) + " fps capture) -> " + st.dir);
            L("cine: camera pose check: max |readback - written| over " + checks + " captures: position " + maxFieldPos.ToString("0.000", inv) + " m, camera rotation " + maxRot.ToString("0.000", inv)
              + " deg; drift the game applied between our writes (LateUpdate): position " + dPosMax.ToString("0.000", inv) + " m, size " + dSizeMax.ToString("0.000", inv) + " m, angle " + dAngMax.ToString("0.000", inv) + " deg");
            recording = false;
        }
    }
}
