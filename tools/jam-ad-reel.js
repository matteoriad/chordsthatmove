/* chords that move – Jam tool ad reel flow (v2.1)
 * Runs entirely in Chrome on https://chordsthatmove.com/jam via the Claude in Chrome javascript tool.
 *
 * Steps:
 *   1. Open the jam URL (JAM_URL below), start a session (email gate), press Play/Stop once with a REAL click
 *      so the AudioContext is unlocked.
 *   2. Paste this whole file → it defines helpers, resets state and adds a "● Start recording" button.
 *   3. Real-click that button → user clicks "Share" in Chrome's tab-share prompt (tab audio on).
 *      The schedule plays itself (~38 s). Status in __reel.status ('recorded' when done).
 *   4. await __render()  → real-time render (1080x1920 MP4) into __reel.final
 *      __render({still: 12.3}) returns a canvas for previewing single frames.
 *   5. __download()     → saves chords-that-move-jam-ad.mp4 to Downloads.
 *
 * v1 (11 Nov 2026) worked: Am F C G Am F G E, 100 bpm, Pad, drums Groove, texture sound Between.
 * v2 changes (Matteo's feedback):
 *   - First texture drop uses Texture sound "Clean pluck" (softer) + Arpeggio.
 *   - "Harder" section: drums Funky + Drum length Legato, texture sound Between + Climb.
 *   - Real logo taken from the page header SVG instead of a hand-drawn one.
 *   - Smoother camera: slow zoom-outs (~1.4 s), no instant out→in, cursor heads to the next target while the
 *     camera eases out, and camera/zoom are spring-smoothed frame to frame.
 * v2.1 (20 Nov 2026):
 *   - Export: the beta export records in the browser. "Export reel" opens a sheet, "Record reel" draws the reel
 *     live in a small preview; we film a few seconds of that and press Cancel, so no export is counted.
 *   - Texture sound "classic" no longer exists: reset uses "between". Texture is an on/off toggle button
 *     (the pattern menu has no "off"): the first texture drop presses it.
 */
const JAM_URL = 'https://chordsthatmove.com/jam?k=C-major&bpm=100&s=pad&c=Am%3A1_F%3A1_C%3A1_G%3A1_Am%3A1_F%3A1_G%3A1_E%3A1';

/* ---------- helpers ---------- */
const W_ = ms => new Promise(r => setTimeout(r, ms));
const B_ = () => [...document.querySelectorAll('button')];
const L_ = b => (b.getAttribute('aria-label') || b.textContent).trim();
const R = {
  play: () => B_().find(b => ['Play', 'Stop', 'Pause'].includes(L_(b))),
  drums: () => B_().find(b => L_(b) === 'Drums'),
  tex: () => B_().find(b => L_(b) === 'Texture'),
  metro: () => B_().find(b => L_(b) === 'Metronome'),
  export: () => B_().find(b => L_(b).startsWith('Export reel')),
  record: () => B_().find(b => L_(b).startsWith('Record reel')),
  cancel: () => B_().find(b => L_(b) === 'Cancel'),
  // selects are native <select> inside a <label>; the label text contains the hidden name, e.g. "Drum style"
  sel: name => [...document.querySelectorAll('select')].find(s => s.parentElement.textContent.includes(name)),
  label: name => () => R.sel(name).parentElement,
};
window.__R = R;
const setSel = (name, v) => {
  const s = R.sel(name);
  const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
  try { set.call(s, v); } catch (e) { s.value = v; }
  s.dispatchEvent(new Event('change', { bubbles: true }));
};
window.__setSel = setSel;
const pressed = b => b.getAttribute('aria-pressed') === 'true';
const rectOf = e => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; };

/* ---------- reset to start state ---------- */
async function resetState() {
  window.scrollTo(0, 0);
  if (L_(R.play()) !== 'Play') { R.play().click(); await W_(300); }
  setSel('Texture:', 'arpeggio'); await W_(150);      // 'Texture:' (with colon) so it doesn't match 'Texture sound'
  setSel('Texture sound', 'between'); await W_(150);
  setSel('Drum style', 'groove'); await W_(150);
  setSel('Drum length', 'smooth'); await W_(150);
  if (pressed(R.drums())) { R.drums().click(); await W_(200); }   // selecting a drum style turns drums ON
  if (pressed(R.metro())) { R.metro().click(); await W_(200); }
  if (pressed(R.tex())) { R.tex().click(); await W_(200); }      // texture is an on/off toggle since 17 Nov
}

/* ---------- schedule (seconds from recording start; 1 bar = 2.4 s at 100 bpm, Play at 1.0) ---------- */
const SCHEDULE = [
  // [t, name, target element getter, action, callout label, callout end]
  [1.0,  'play',       R.play,                  e => e.click(),                          '▶  PLAY',               2.8],
  [5.6,  'drums_on',   R.drums,                 e => e.click(),                          'DRUMS  ·  ON',          7.6],
  [10.0, 'tex_sound',  R.label('Texture sound'), () => setSel('Texture sound','clean-pluck'), 'TEXTURE  ·  CLEAN PLUCK', 10.5],
  [10.6, 'texture',    R.tex,                   e => { if (!pressed(e)) e.click(); },     'TEXTURE  ·  ARPEGGIO',  12.6],
  [15.4, 'drums_off',  R.drums,                 e => e.click(),                          'DRUMS  ·  OFF',         17.4],
  [19.4, 'style',      R.label('Drum style'),   () => setSel('Drum style','funky'),       'DRUMS  ·  FUNKY',       19.85],
  [19.9, 'length',     R.label('Drum length'),  () => setSel('Drum length','legato'),     'DRUMS  ·  LEGATO',      20.45],
  [20.5, 'tex_sound2', R.label('Texture sound'), () => setSel('Texture sound','between'), 'TEXTURE  ·  BETWEEN',   20.95],
  [21.0, 'texture2',   R.label('Texture:'),     () => setSel('Texture:','climb'),          'TEXTURE  ·  CLIMB',     22.6],
  [28.6, 'export',     R.export,                e => e.click(),                          'EXPORT  ·  REEL',       30.0],
  [30.2, 'record',     R.record,                e => e.click(),                          'RECORDING  ·  LIVE',    35.6],
];
const STOP_AT = 36.4;      // press Cancel in the export sheet: the preview stops and no export is counted
const REC_LEN = 38.2;      // recording length

/* ---------- recorder ---------- */
window.__reel = { log: [], status: 'idle' };
(async () => {
  await resetState();
  document.getElementById('__recbtn')?.remove();
  const btn = document.createElement('button');
  btn.id = '__recbtn'; btn.textContent = '● Start recording';
  Object.assign(btn.style, { position: 'fixed', right: '24px', bottom: '24px', zIndex: 99999, padding: '14px 22px', background: '#ff5c8a', color: '#fff', border: '0', borderRadius: '999px', font: '600 16px Inter, sans-serif', cursor: 'pointer' });
  btn.onclick = async () => {
    const S = window.__reel;
    try {
      S.status = 'asking';
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { width: { ideal: 3840 }, height: { ideal: 2160 }, frameRate: { ideal: 30 } },
        audio: { suppressLocalAudioPlayback: false, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        preferCurrentTab: true, selfBrowserSurface: 'include', surfaceSwitching: 'exclude', systemAudio: 'include' });
      btn.remove();
      S.hasAudio = stream.getAudioTracks().length > 0;
      await W_(800);
      S.iw = innerWidth; S.ih = innerHeight;
      // grab the real logo from the header for the editor
      const svg = document.querySelector('a[href="/"] svg');
      if (svg) S.logoSvg = new XMLSerializer().serializeToString(svg);
      const chunks = [];
      const mr = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp9,opus', videoBitsPerSecond: 16e6, audioBitsPerSecond: 256000 });
      mr.ondataavailable = e => e.data.size && chunks.push(e.data);
      const done = new Promise(r => mr.onstop = r);
      mr.start(500); const t0 = performance.now(); S.status = 'recording';
      for (const [t, name, el, fn, label, end] of SCHEDULE) setTimeout(() => {
        const e = el(); S.log.push({ t: (performance.now() - t0) / 1000, name, label, end, rect: rectOf(e), drumsOn: pressed(R.drums()) }); fn(e);
      }, t * 1000);
      setTimeout(() => { const c = R.cancel(); if (c) c.click(); else if (L_(R.play()) !== 'Play') R.play().click(); }, STOP_AT * 1000);
      await W_(REC_LEN * 1000);
      mr.stop(); await done; stream.getTracks().forEach(t => t.stop());
      S.raw = new Blob(chunks, { type: 'video/webm' }); S.status = 'recorded';
    } catch (err) { S.status = 'error: ' + err.message; }
  };
  document.body.appendChild(btn);
})();

/* ---------- editor / renderer ---------- */
window.__render = async function (opts = {}) {
  const S = window.__reel; S.renderStatus = 'starting';
  const W = 1080, H = 1920, FPS = 30;
  const END = opts.end || (REC_LEN - 0.2);   // end card at ~33.7 s: 3.5 s of the live export preview first
  const EC = END - 4.3;                       // end card start
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');
  const v = document.createElement('video'); v.src = URL.createObjectURL(S.raw); v.playsInline = true; v.preload = 'auto';
  await new Promise(r => v.onloadeddata = r);
  const sc = v.videoWidth / S.iw, VW = v.videoWidth / sc, VH = v.videoHeight / sc;
  const C = { bg: '#0b0b10', fg: '#f2f2f5', muted: '#8a8a99', pink: '#ff6b9a' };
  let logoImg = null;
  if (S.logoSvg) {
    let s = S.logoSvg; if (!s.includes('xmlns=')) s = s.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
    logoImg = new Image(); logoImg.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(s);
    await new Promise(r => { logoImg.onload = r; logoImg.onerror = () => { logoImg = null; r(); }; });
  }
  const drawLogo = (x, y, h, alpha = 1) => { if (!logoImg) return; const w = h * (logoImg.width / logoImg.height || 1); ctx.globalAlpha *= alpha; ctx.drawImage(logoImg, x, y, w, h); ctx.globalAlpha = 1; return w; };
  const log = Object.fromEntries(S.log.map(l => [l.name, l]));
  const ctr = n => { const r = log[n].rect; return [r.x + r.w / 2, r.y + r.h / 2]; };
  const OW = 1180, OX = 370, OH = Math.min(882, VH);
  const OC = [OX + OW / 2, OH / 2];
  const winW = 1000, winH = Math.round(winW * OH / OW), winX = 40, winY = 560;

  // Zoom keyframes: zoom-outs take ~1.4 s, and back-to-back actions stay zoomed (camera glides instead).
  const ZK = opts.zk || [
    [0, 1], [0.3, 1], [1.0, 2.3], [1.9, 2.3], [3.3, 1],
    [4.6, 1], [5.5, 2.3], [6.6, 2.3], [8.0, 1],
    [9.2, 1], [9.9, 2.3], [11.4, 2.3], [12.8, 1],          // clean pluck → arpeggio: glide while zoomed
    [14.4, 1], [15.2, 2.2], [16.2, 2.2], [17.6, 1],
    [18.4, 1], [19.3, 2.0], [21.6, 2.0],                   // funky → legato → between → climb: one long zoomed glide
    [23.2, 1.6], [24.2, 1.9], [27.4, 1.9],                 // ease straight into the voice-lines pan, no full zoom-out
    [28.0, 1.6], [28.6, 2.2], [29.6, 2.2], [30.6, 1.4], [40, 1.4]];   // export button, then the sheet's live preview
  const ease = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const kf = (K, t) => { for (let i = 0; i < K.length - 1; i++) { const [a, va] = K[i], [b, vb] = K[i + 1]; if (t <= b) { const p = clamp((t - a) / (b - a), 0, 1); return va + (vb - va) * ease(p); } } return K[K.length - 1][1]; };

  // Cursor: from each click it heads (slowly) toward the next target, arriving exactly at that click.
  const lane = [540, 410], laneR = [1380, 410];
  const order = SCHEDULE.map(s => s[1]).filter(n => log[n]);
  const CW = [[0, 0, 960, 520]];
  order.forEach((n, i) => {
    const t = log[n].t, prev = i ? log[order[i - 1]].t : 0;
    if (n === 'export') { CW.push([23.6, 24.4, ...lane, 1], [24.8, 27.0, ...laneR, 1]); CW.push([27.2, t, ...ctr(n)]); return; }
    CW.push([Math.max(prev + 0.35, t - 2.4), t, ...ctr(n)]);
  });
  const cursorAt = t => { let x = CW[0][2], y = CW[0][3], hid = 0; for (let i = 1; i < CW.length; i++) { const [d, a, tx, ty, h] = CW[i]; if (t < d) break; const p = ease(clamp((t - d) / (a - d), 0, 1)); x = x + (tx - x) * p; y = y + (ty - y) * p; hid = h ? 1 : 0; } return [x, y, hid]; };
  const clicks = S.log.filter(l => l.label).map(l => ({ n: l.name, l: l.label, t: l.t, r: l.rect, e: l.end }));

  const HL = [[0, 4.6, ['Build chords', 'that move.']], [4.6, 9.4, ['Drop the', 'drums in.']], [9.4, 14.4, ['Layer a', 'soft texture.']],
    [14.4, 18.2, ['Cut the drums.', 'Feel the tension.']], [18.2, 24.0, ['Bring it back.', 'Funkier.']],
    [24.0, 28.4, ['Watch every', 'voice move.']], [28.4, EC, ['Export it', 'as a reel.']]];
  const MONO = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace';
  const cursorPath = (x, y, s) => { ctx.save(); ctx.translate(x, y); ctx.scale(s / 22, s / 22); ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, 17); ctx.lineTo(4.2, 13.2); ctx.lineTo(7, 19.5); ctx.lineTo(9.6, 18.4); ctx.lineTo(6.9, 12.3); ctx.lineTo(12.2, 12.3); ctx.closePath(); ctx.shadowColor = 'rgba(0,0,0,.5)'; ctx.shadowBlur = 6; ctx.shadowOffsetY = 2; ctx.fillStyle = '#fff'; ctx.fill(); ctx.shadowColor = 'transparent'; ctx.lineWidth = 1.4; ctx.strokeStyle = '#111'; ctx.stroke(); ctx.restore(); };

  // spring-smoothed camera (only in live render; stills use the raw target)
  const cam = { z: 1, x: OC[0], y: OC[1], t: null };
  function frame(t, smooth) {
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
    const g = ctx.createRadialGradient(540, 960, 50, 540, 960, 900); g.addColorStop(0, 'rgba(255,107,154,0.10)'); g.addColorStop(0.5, 'rgba(91,184,224,0.05)'); g.addColorStop(1, 'rgba(0,0,0,0)'); ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
    // brand: real logo + wordmark
    ctx.font = '600 34px Inter'; const tw = ctx.measureText('chords that move').width; const lw = logoImg ? 44 * (logoImg.width / logoImg.height || 1) : 0;
    const bx = 540 - (lw + 16 + tw) / 2; drawLogo(bx, 102, 44); ctx.fillStyle = C.fg; ctx.textBaseline = 'middle'; ctx.textAlign = 'left'; ctx.fillText('chords that move', bx + lw + 16, 124);
    for (const [a, b, lines] of HL) { if (t < a - 0.05 || t > b + 0.05) continue; const fi = clamp((t - a) / 0.35, 0, 1), fo = clamp((b - t) / 0.3, 0, 1); ctx.globalAlpha = ease(Math.min(fi, fo)); ctx.fillStyle = C.fg; ctx.font = '700 84px Inter'; ctx.textAlign = 'center'; lines.forEach((ln, i) => ctx.fillText(ln, 540, 300 + i * 98 + (1 - ease(fi)) * 24)); ctx.globalAlpha = 1; }
    // camera
    const [cx, cy, hid] = cursorAt(t);
    let z = kf(ZK, t); const k = clamp((z - 1) / 0.8, 0, 1);
    let fx = OC[0] + (cx - OC[0]) * k, fy = OC[1] + (cy - OC[1]) * k;
    if (smooth) { const dt = cam.t == null ? 1 : clamp(t - cam.t, 0, 0.2); const a = 1 - Math.exp(-dt * 7); if (cam.t == null) { cam.z = z; cam.x = fx; cam.y = fy; } else { cam.z += (z - cam.z) * a; cam.x += (fx - cam.x) * a; cam.y += (fy - cam.y) * a; } cam.t = t; z = cam.z; fx = cam.x; fy = cam.y; }
    const rw = OW / z, rh = OH / z; fx = clamp(fx, rw / 2, VW - rw / 2); fy = clamp(fy, rh / 2, VH - rh / 2);
    const rx = fx - rw / 2, ry = fy - rh / 2, m = winW / rw;
    const P = (x, y) => [winX + (x - rx) * m, winY + (y - ry) * m];
    ctx.save(); ctx.shadowColor = 'rgba(0,0,0,.6)'; ctx.shadowBlur = 60; ctx.shadowOffsetY = 20; ctx.fillStyle = C.bg; ctx.beginPath(); ctx.roundRect(winX, winY, winW, winH, 32); ctx.fill(); ctx.restore();
    ctx.save(); ctx.beginPath(); ctx.roundRect(winX, winY, winW, winH, 32); ctx.clip();
    ctx.drawImage(v, rx * sc, ry * sc, rw * sc, rh * sc, winX, winY, winW, winH);
    for (const c of clicks) { const d = t - c.t; if (d > -0.15 && d < 1.1) { const a = d < 0 ? (d + 0.15) / 0.15 : clamp(1 - (d - 0.7) / 0.4, 0, 1); const [x0, y0] = P(c.r.x - 6, c.r.y - 4); ctx.globalAlpha = a; ctx.strokeStyle = C.pink; ctx.lineWidth = 3; ctx.beginPath(); ctx.roundRect(x0, y0, (c.r.w + 12) * m, (c.r.h + 8) * m, 5 * m); ctx.stroke(); ctx.globalAlpha = 1; }
      if (d >= 0 && d < 0.6) { const [px, py] = P(c.r.x + c.r.w / 2, c.r.y + c.r.h / 2); ctx.globalAlpha = 1 - d / 0.6; ctx.strokeStyle = C.pink; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(px, py, (10 + d * 70) * m / 2, 0, 7); ctx.stroke(); ctx.globalAlpha = 1; } }
    if (!hid) { let s = 22 * m; if (clicks.some(c => t >= c.t - 0.06 && t < c.t + 0.12)) s *= 0.85; const [px, py] = P(cx, cy); cursorPath(px - 2, py - 2, s); }
    ctx.restore();
    ctx.strokeStyle = 'rgba(255,255,255,0.09)'; ctx.lineWidth = 2; ctx.beginPath(); ctx.roundRect(winX, winY, winW, winH, 32); ctx.stroke();
    // callout pill (latest active one wins)
    const act = clicks.filter(c => t >= c.t && t <= c.e).pop();
    if (act) { const fi = clamp((t - act.t) / 0.2, 0, 1), fo = clamp((act.e - t) / 0.25, 0, 1); ctx.font = '600 34px ' + MONO; const pw = ctx.measureText(act.l).width + 72, ph = 78, px = 540 - pw / 2, py = winY + winH + 70 + (1 - ease(fi)) * 20; ctx.globalAlpha = Math.min(fi, fo); ctx.fillStyle = C.pink; ctx.beginPath(); ctx.roundRect(px, py, pw, ph, 39); ctx.fill(); ctx.fillStyle = C.bg; ctx.textAlign = 'center'; ctx.fillText(act.l, 540, py + ph / 2 + 2); ctx.globalAlpha = 1; }
    ctx.font = '500 30px ' + MONO; ctx.fillStyle = C.muted; ctx.textAlign = 'center'; ctx.fillText('chordsthatmove.com', 540, 1830);
    // end card
    if (t > EC) { const a = ease(clamp((t - EC) / 0.5, 0, 1)); ctx.globalAlpha = a; ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
      const g2 = ctx.createRadialGradient(540, 900, 50, 540, 900, 800); g2.addColorStop(0, 'rgba(255,107,154,0.16)'); g2.addColorStop(1, 'rgba(0,0,0,0)'); ctx.fillStyle = g2; ctx.fillRect(0, 0, W, H);
      const tA = s => ease(clamp((t - EC - s) / 0.45, 0, 1));
      if (logoImg) { const lh = 170, lw2 = lh * (logoImg.width / logoImg.height || 1); ctx.globalAlpha = a * tA(0.15); ctx.drawImage(logoImg, 540 - lw2 / 2, 560 + (1 - tA(0.15)) * 20, lw2, lh); }
      ctx.textAlign = 'center'; ctx.fillStyle = C.fg;
      ctx.globalAlpha = a * tA(0.5); ctx.font = '700 92px Inter'; ctx.fillText('Chords that', 540, 960 + (1 - tA(0.5)) * 20); ctx.fillText('move you.', 540, 1066 + (1 - tA(0.5)) * 20);
      ctx.globalAlpha = a * tA(1.0); ctx.font = '500 46px Inter'; ctx.fillStyle = C.muted; ctx.fillText('Build it. Jam it. Export it.', 540, 1200);
      ctx.globalAlpha = a * tA(1.5); ctx.font = '600 40px ' + MONO; ctx.fillStyle = C.pink; ctx.fillText('chordsthatmove.com', 540, 1340);
      ctx.globalAlpha = 1; }
  }
  if (opts.still !== undefined) { v.currentTime = opts.still; await new Promise(r => v.onseeked = r); frame(opts.still, false); return cv; }
  const ac = new AudioContext(); const src = ac.createMediaElementSource(v); const gain = ac.createGain(); const dst = ac.createMediaStreamDestination(); src.connect(gain).connect(dst);
  const stream = new MediaStream([...cv.captureStream(FPS).getVideoTracks(), ...dst.stream.getAudioTracks()]);
  const mime = MediaRecorder.isTypeSupported('video/mp4;codecs=avc1,mp4a.40.2') ? 'video/mp4;codecs=avc1,mp4a.40.2' : 'video/webm;codecs=vp9,opus';
  const mr = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 12e6, audioBitsPerSecond: 256000 }); const chunks = []; mr.ondataavailable = e => e.data.size && chunks.push(e.data); const done = new Promise(r => mr.onstop = r);
  v.currentTime = 0; await new Promise(r => v.onseeked = r); frame(0, true);
  await ac.resume(); mr.start(500); await v.play(); S.renderStatus = 'rendering';
  let faded = false;
  await new Promise(res => { const loop = () => { const t = v.currentTime; frame(t, true); if (!faded && t > END - 1.4) { faded = true; gain.gain.setValueAtTime(1, ac.currentTime); gain.gain.linearRampToValueAtTime(0, ac.currentTime + 1.3); } if (t >= END || v.ended) { res(); return; } requestAnimationFrame(loop); }; requestAnimationFrame(loop); });
  v.pause(); mr.stop(); await done;
  S.final = new Blob(chunks, { type: mime.split(';')[0] }); S.renderStatus = 'done';
  return S.final.size;
};

window.__download = (name = 'chords-that-move-jam-ad.mp4') => { const a = document.createElement('a'); a.href = URL.createObjectURL(window.__reel.final); a.download = name; document.body.appendChild(a); a.click(); a.remove(); };
