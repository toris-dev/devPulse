"""devPulse 웹 대시보드 — 사이버틱 NOC 모니터."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from pipeline.lib.env import load_env
from pipeline.web.status import build_dashboard_payload
from pipeline.web.stream import sse_stream

_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT = _ROOT / "output"

_CLIENT_DISCONNECT_ERRORS = (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)


def _is_client_disconnect(exc: BaseException) -> bool:
    if isinstance(exc, _CLIENT_DISCONNECT_ERRORS):
        return True
    if isinstance(exc, OSError):
        return getattr(exc, "errno", None) in (32, 54, 104)  # EPIPE, ECONNRESET
    return False


def _html_page() -> str:
    return """<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>devPulse // SYS.MONITOR</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Orbitron:wght@500;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg:#030508; --grid:#0a1218; --panel:rgba(4,14,22,.92);
      --text:#c8f4ff; --muted:#5a7a8a; --cyan:#00e5ff; --magenta:#ff2a7a;
      --ok:#00ff9d; --warn:#ffb020; --err:#ff4466; --border:rgba(0,229,255,.22);
      --glow:0 0 12px rgba(0,229,255,.35);
    }
    * { box-sizing:border-box; }
    html, body { height:100%; margin:0; overflow:hidden; }
    body {
      font-family:'JetBrains Mono',ui-monospace,monospace;
      background:var(--bg); color:var(--text);
      background-image:
        linear-gradient(rgba(0,229,255,.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,229,255,.03) 1px, transparent 1px);
      background-size:24px 24px;
    }
    .scanlines {
      pointer-events:none; position:fixed; inset:0; z-index:9999; opacity:.04;
      background:repeating-linear-gradient(0deg, transparent, transparent 2px, #000 2px, #000 4px);
    }
    .hud { display:flex; flex-direction:column; height:100vh; }

    .hud-header {
      display:flex; justify-content:space-between; align-items:center; gap:16px;
      padding:10px 16px; border-bottom:1px solid var(--border);
      background:linear-gradient(180deg, rgba(0,229,255,.08), transparent);
      flex-shrink:0;
    }
    .brand { display:flex; align-items:baseline; gap:12px; }
    .logo {
      font-family:'Orbitron',sans-serif; font-weight:700; font-size:1.1rem;
      color:var(--cyan); text-shadow:var(--glow); letter-spacing:.12em;
    }
    .sys-id { font-size:.65rem; color:var(--muted); letter-spacing:.2em; }
    .header-right { display:flex; align-items:center; gap:16px; font-size:.72rem; color:var(--muted); }
    .live { display:flex; align-items:center; gap:6px; color:var(--ok); font-weight:600; letter-spacing:.15em; }
    .live-dot {
      width:8px; height:8px; border-radius:50%; background:var(--ok);
      box-shadow:0 0 8px var(--ok); animation:pulse 1.4s ease infinite;
    }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.35} }
    #subtitle { max-width:52vw; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

    .command-grid {
      flex:1; min-height:0; display:grid; gap:8px; padding:8px;
      grid-template-columns:minmax(220px,260px) 1fr minmax(240px,300px);
      grid-template-rows:auto 1fr minmax(140px,22vh);
    }
    .span-full { grid-column:1 / -1; }

    .panel {
      position:relative; background:var(--panel); border:1px solid var(--border);
      min-height:0; display:flex; flex-direction:column;
      clip-path:polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 12px 100%, 0 calc(100% - 12px));
    }
    .panel::before {
      content:''; position:absolute; top:0; left:0; width:28px; height:2px; background:var(--cyan);
      box-shadow:var(--glow);
    }
    .panel-title {
      flex-shrink:0; padding:8px 12px 6px; font-size:.62rem; font-weight:600;
      letter-spacing:.18em; color:var(--cyan); border-bottom:1px solid rgba(0,229,255,.12);
      display:flex; justify-content:space-between; align-items:center;
    }
    .panel-title .count { color:var(--magenta); }
    .panel-body { flex:1; min-height:0; overflow:auto; padding:8px; }
    .panel-body::-webkit-scrollbar { width:5px; height:5px; }
    .panel-body::-webkit-scrollbar-thumb { background:rgba(0,229,255,.3); border-radius:3px; }

    .telemetry { display:flex; flex-wrap:wrap; gap:8px; padding:8px 12px; align-items:stretch; }
    .tel {
      flex:1; min-width:100px; padding:8px 10px; border:1px solid var(--border);
      background:rgba(0,0,0,.35);
    }
    .tel-label { font-size:.58rem; letter-spacing:.14em; color:var(--muted); margin-bottom:4px; }
    .tel-value { font-size:1.05rem; font-weight:700; color:var(--text); font-family:'Orbitron',sans-serif; }
    .tel.ok .tel-value { color:var(--ok); }
    .tel.warn .tel-value { color:var(--warn); }
    .tel.err .tel-value { color:var(--err); }

    .queue-meta { font-size:.68rem; color:var(--muted); margin-bottom:6px; line-height:1.5; }
    .bar {
      height:6px; background:#000; border:1px solid var(--border); margin:6px 0 10px;
      position:relative; overflow:hidden;
    }
    .bar > i {
      display:block; height:100%; width:0%;
      background:linear-gradient(90deg, var(--magenta), var(--cyan));
      box-shadow:0 0 10px var(--cyan); transition:width .4s ease;
    }
    .slot-grid {
      display:grid; grid-template-columns:repeat(3,1fr); gap:6px;
    }
    .slot {
      border:1px dashed rgba(0,229,255,.2); padding:4px; background:rgba(0,0,0,.4);
      min-height:90px; display:flex; flex-direction:column; gap:3px;
    }
    .slot.filled { border-style:solid; border-color:rgba(0,255,157,.4); }
    .slot.ready { border-color:var(--ok); box-shadow:inset 0 0 12px rgba(0,255,157,.15); }
    .slot-num { font-size:.55rem; color:var(--cyan); }
    .slot img { width:100%; border-radius:2px; aspect-ratio:9/16; object-fit:cover; background:#000; }
    .slot-empty {
      flex:1; display:flex; align-items:center; justify-content:center;
      font-size:.6rem; color:var(--muted); border:1px dashed rgba(255,255,255,.08);
    }
    .slot-title {
      font-size:.58rem; line-height:1.3; color:var(--text);
      display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
    }

    .dup-note {
      font-size:.62rem; color:var(--warn); margin:0 0 8px; padding:4px 8px;
      border-left:2px solid var(--warn); background:rgba(255,176,32,.08);
    }
    .bundle-list {
      display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:8px;
    }
    .artifact-item {
      border:1px solid var(--border); background:rgba(0,0,0,.45); padding:8px;
      transition:border-color .2s;
    }
    .artifact-item:hover { border-color:var(--cyan); }
    .bundle-headline {
      font-size:.65rem; margin-bottom:6px; line-height:1.5; word-break:break-all;
    }
    .bundle-headline strong { color:var(--cyan); font-size:.7rem; }
    video {
      width:100%; max-height:200px; border-radius:2px; background:#000;
      border:1px solid rgba(0,229,255,.15);
    }
    .caption-box {
      margin-top:6px; max-height:72px; overflow:auto; font-size:.62rem; line-height:1.45;
      color:var(--muted); background:rgba(0,0,0,.5); padding:6px; border-left:2px solid var(--magenta);
    }
    .link-row { display:flex; flex-wrap:wrap; gap:8px; margin-top:6px; font-size:.6rem; }
    a { color:var(--cyan); text-decoration:none; }
    a:hover { color:var(--magenta); text-shadow:0 0 6px var(--magenta); }

    .badge {
      display:inline-block; padding:1px 6px; font-size:.55rem; letter-spacing:.08em;
      border:1px solid; margin-right:4px; vertical-align:middle;
    }
    .badge.ok { color:var(--ok); border-color:var(--ok); background:rgba(0,255,157,.1); }
    .badge.warn { color:var(--warn); border-color:var(--warn); background:rgba(255,176,32,.1); }

    .card-strip {
      display:flex; gap:8px; overflow-x:auto; padding-bottom:4px;
    }
    .card-strip .artifact-item {
      flex:0 0 110px; padding:6px;
    }
    .card-strip img {
      width:100%; aspect-ratio:9/16; object-fit:cover; border:1px solid var(--border);
      background:#000;
    }
    .card-strip .title {
      font-size:.58rem; margin-top:4px; line-height:1.3;
      display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
    }
    .card-strip .meta { font-size:.52rem; color:var(--muted); margin-top:2px; }

    #logs-top {
      margin:0; height:100%; overflow:auto; font-size:.62rem; line-height:1.45;
      white-space:pre-wrap; word-break:break-word; color:#7ec8e3;
      background:transparent; border:none; padding:4px;
    }
    .empty {
      color:var(--muted); padding:20px; text-align:center; font-size:.7rem;
      letter-spacing:.1em;
    }

    @media (max-width:1100px) {
      .command-grid {
        grid-template-columns:1fr 1fr;
        grid-template-rows:auto auto 1fr minmax(120px,20vh);
      }
      .panel-queue { grid-column:1; grid-row:2; }
      .panel-bundles { grid-column:1 / -1; grid-row:3; }
      .panel-logs { grid-column:2; grid-row:2; }
    }
    @media (max-width:720px) {
      .command-grid { grid-template-columns:1fr; grid-template-rows:auto repeat(4, minmax(0,1fr)); }
      .panel-queue, .panel-bundles, .panel-logs, .panel-cards { grid-column:1; }
      html, body { overflow:auto; height:auto; }
      .hud { height:auto; min-height:100vh; }
    }
  </style>
</head>
<body>
  <div class="scanlines"></div>
  <div class="hud">
    <header class="hud-header">
      <div class="brand">
        <span class="logo">◈ DEVPULSE</span>
        <span class="sys-id">SYS.MONITOR</span>
      </div>
      <div class="header-right">
        <span class="live"><span class="live-dot"></span>SSE LIVE</span>
        <span id="subtitle">INITIALIZING...</span>
        <a href="/api/status" target="_blank">RAW.JSON</a>
      </div>
    </header>

    <div class="command-grid">
      <section class="panel span-full">
        <div class="telemetry" id="stats"></div>
      </section>

      <section class="panel panel-queue">
        <div class="panel-title">// PIPELINE.QUEUE</div>
        <div class="panel-body">
          <div class="queue-meta" id="bundle-text">0/6</div>
          <div class="bar"><i id="bundle-bar"></i></div>
          <div class="queue-meta" id="bundle-status">—</div>
          <div class="slot-grid" id="bundle-slot-grid"></div>
        </div>
      </section>

      <section class="panel panel-bundles">
        <div class="panel-title">// OUTPUT.BUNDLES <span class="count" id="tab-count-bundles"></span></div>
        <div class="panel-body" id="panel-bundles"></div>
      </section>

      <section class="panel panel-logs">
        <div class="panel-title">// SIGNAL.LOG <span class="count" id="log-meta">—</span></div>
        <div class="panel-body"><pre id="logs-top"></pre></div>
      </section>

      <section class="panel panel-cards span-full">
        <div class="panel-title">// CARD.FEED <span class="count" id="tab-count-cards"></span></div>
        <div class="panel-body" id="panel-cards"></div>
      </section>
    </div>
  </div>
  <script>
    function esc(s){const d=document.createElement('div');d.textContent=s??'';return d.innerHTML;}

    function renderCards(items){
      const el = document.getElementById('panel-cards');
      if (!items.length) {
        if (!el.querySelector('.card-list')) {
          el.innerHTML = '<p class="empty">NO CARDS — AWAITING PIPELINE</p>';
        }
        return;
      }
      el.querySelector('.empty')?.remove();
      let list = el.querySelector('.card-list');
      if (!list) {
        el.innerHTML = '';
        list = document.createElement('div');
        list.className = 'card-strip card-list';
        el.appendChild(list);
      }
      const known = new Set([...list.querySelectorAll('[data-post-id]')].map(n => n.dataset.postId));
      const incoming = new Set(items.map(c => c.post_id));
      for (const node of [...list.querySelectorAll('[data-post-id]')]) {
        if (!incoming.has(node.dataset.postId)) node.remove();
      }
      const frag = document.createDocumentFragment();
      for (const c of items) {
        if (known.has(c.post_id)) continue;
        const item = document.createElement('div');
        item.className = 'artifact-item';
        item.dataset.postId = c.post_id;
        item.innerHTML = `
          <a href="${c.url}" target="_blank"><img src="${c.url}" alt="${esc(c.post_id)}" loading="lazy"/></a>
          <div class="title">${esc(c.title || c.post_id)}</div>
          <div class="meta">${esc(c.post_id)}<br>${esc(c.created_at)} · ${c.size_kb}KB</div>`;
        frag.appendChild(item);
      }
      list.prepend(frag);
    }

    function bundleItemInner(b){
      return `
          <div class="bundle-headline">
            <strong>${esc(b.bundle_id)}</strong>
            <span class="badge ok">${b.post_count || b.card_count}건</span>
            ${b.duplicate_count ? `<span class="badge warn">동일 ${b.duplicate_count + 1}개</span>` : ''}
            <span class="muted">${esc(b.created_at)} · ${b.card_count}장 · ${b.size_kb}KB</span>
          </div>
          ${b.video_url ? `<video controls preload="metadata" src="${b.video_url}"></video>` : ''}
          <div class="caption-box">${esc(b.caption || '(NO CAPTION)')}</div>
          <div class="link-row">
            ${b.video_url ? `<a href="${b.video_url}" download>DL.MP4</a>` : ''}
            ${b.caption_url ? `<a href="${b.caption_url}" target="_blank">TXT</a>` : ''}
            ${b.json_url ? `<a href="${b.json_url}" target="_blank">JSON</a>` : ''}
          </div>`;
    }

    function renderBundles(items, counts){
      const el = document.getElementById('panel-bundles');
      if (!items.length) {
        if (!el.querySelector('.bundle-list')) {
          el.innerHTML = '<p class="empty">NO BUNDLES — NEED 6 CARDS</p>';
        }
        return;
      }
      el.querySelector('.empty')?.remove();

      const dupText = (counts.bundles_raw ?? 0) > (counts.bundles ?? 0)
        ? `DEDUP: ${counts.bundles_raw - counts.bundles} duplicate bundles hidden (post_ids)`
        : '';
      let dupNote = el.querySelector('.dup-note');
      if (dupText) {
        if (!dupNote) {
          dupNote = document.createElement('p');
          dupNote.className = 'dup-note';
          el.prepend(dupNote);
        }
        dupNote.textContent = dupText;
      } else {
        dupNote?.remove();
      }

      let list = el.querySelector('.bundle-list');
      if (!list) {
        el.querySelectorAll('.artifact-item, .bundle-list').forEach(n => n.remove());
        list = document.createElement('div');
        list.className = 'bundle-list';
        el.appendChild(list);
      }

      const known = new Set([...list.querySelectorAll('[data-bundle-id]')].map(n => n.dataset.bundleId));
      const incoming = new Set(items.map(b => b.bundle_id));

      for (const node of [...list.querySelectorAll('[data-bundle-id]')]) {
        if (incoming.has(node.dataset.bundleId)) continue;
        const video = node.querySelector('video');
        if (video && !video.paused && !video.ended) continue;
        node.remove();
      }

      const frag = document.createDocumentFragment();
      for (const b of items) {
        if (known.has(b.bundle_id)) continue;
        const item = document.createElement('div');
        item.className = 'artifact-item';
        item.dataset.bundleId = b.bundle_id;
        item.innerHTML = bundleItemInner(b);
        frag.appendChild(item);
      }
      list.prepend(frag);

      for (const b of items) {
        const node = list.querySelector(`[data-bundle-id="${CSS.escape(b.bundle_id)}"]`);
        if (!node) continue;
        const headline = node.querySelector('.bundle-headline');
        if (headline) {
          headline.innerHTML = `
            <strong>${esc(b.bundle_id)}</strong>
            <span class="badge ok">${b.post_count || b.card_count}건</span>
            ${b.duplicate_count ? `<span class="badge warn">동일 ${b.duplicate_count + 1}개</span>` : ''}
            <span class="muted">${esc(b.created_at)} · ${b.card_count}장 · ${b.size_kb}KB</span>`;
        }
        const cap = node.querySelector('.caption-box');
        if (cap) cap.textContent = b.caption || '(NO CAPTION)';
      }
    }

    function renderBundle(bundle, progress, db){
      const slots = bundle.slots || [];
      const target = bundle.target ?? 6;
      const ready = !!bundle.ready;
      document.getElementById('bundle-text').textContent =
        `QUEUE ${bundle.current ?? 0}/${target} · ${bundle.percent ?? 0}%`;
      document.getElementById('bundle-bar').style.width = `${bundle.percent ?? 0}%`;
      document.getElementById('bundle-status').innerHTML =
        `${ready ? '<span class="badge ok">READY</span>' : '<span class="badge warn">COLLECTING</span>'}` +
        ` ${esc(progress.phase || '-')} / ${esc(progress.step || '-')}` +
        `<br>TOTAL BUNDLES: ${esc(String(db.bundle_total ?? 0))}`;
      const grid = document.getElementById('bundle-slot-grid');
      if (!slots.length) {
        if (!grid.querySelector('[data-slot-index]')) {
          grid.innerHTML = `<p class="empty">QUEUE EMPTY</p>`;
        }
        return;
      }
      grid.querySelector('.empty')?.remove();
      const known = new Set([...grid.querySelectorAll('[data-slot-index]')].map(n => n.dataset.slotIndex));
      for (const s of slots) {
        const key = String(s.index);
        let slot = grid.querySelector(`[data-slot-index="${key}"]`);
        if (!slot) {
          slot = document.createElement('div');
          slot.dataset.slotIndex = key;
          grid.appendChild(slot);
        }
        if (s.filled && s.url) {
          const img = slot.querySelector('img');
          const same = img && img.getAttribute('src') === s.url;
          if (!same) {
            slot.className = `slot filled${ready ? ' ready' : ''}`;
            slot.innerHTML = `
              <div class="slot-num">#${s.index}</div>
              <a href="${s.url}" target="_blank"><img src="${s.url}" alt="${esc(s.post_id)}" loading="lazy"/></a>
              <div class="slot-title" title="${esc(s.title || s.post_id)}">${esc(s.title || s.post_id)}</div>`;
          } else {
            slot.className = `slot filled${ready ? ' ready' : ''}`;
            const title = slot.querySelector('.slot-title');
            if (title) {
              title.textContent = s.title || s.post_id;
              title.title = s.title || s.post_id;
            }
          }
        } else if (!known.has(key) || !slot.querySelector('.slot-empty')) {
          slot.className = 'slot';
          slot.innerHTML = `
            <div class="slot-num">#${s.index}</div>
            <div class="slot-empty">대기</div>`;
        }
        known.delete(key);
      }
      for (const idx of known) {
        grid.querySelector(`[data-slot-index="${idx}"]`)?.remove();
      }
    }

    function renderLogs(data){
      const el = document.getElementById('logs-top');
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      const logs = (data.logs?.tail || []).concat(data.progress?.recent_logs || []);
      const uniq = [...new Set(logs)];
      const lines = uniq.slice(-80);
      el.textContent = lines.join('\\n');
      document.getElementById('log-meta').textContent =
        `${lines.length}L · ${data.logs?.log_file || 'daemon.log'}`;
      if (atBottom) el.scrollTop = el.scrollHeight;
    }

    function renderAll(data){
      const p = data.progress || {};
      const db = data.db || {};
      const counts = db.counts || {};
      const art = data.artifacts || {};
      const ac = art.counts || {};

      document.getElementById('subtitle').textContent =
        `${(p.daemon_status || 'OFFLINE').toUpperCase()} · CYCLE ${p.run_number||0} · ${p.phase||'-'} / ${p.step||'-'} · ${data.generated_at||''}`;

      const bundle = data.bundle || {};
      const bundleStat = (ac.bundles_raw ?? ac.bundles ?? 0) > (ac.bundles ?? 0)
        ? `${ac.bundles ?? 0}/${ac.bundles_raw}`
        : String(ac.bundles ?? 0);
      const failed = counts.failed ?? 0;
      const stats = [
        ['QUEUE', db.bundle_pending || '-', ''],
        ['PROGRESS', `${bundle.percent ?? 0}%`, bundle.ready ? 'ok' : 'warn'],
        ['CARDS', ac.cards ?? '-', ''],
        ['BUNDLES', bundleStat, 'ok'],
        ['PUBLISHED', counts.published ?? '-', 'ok'],
        ['FAILED', failed, failed > 0 ? 'err' : ''],
      ];
      document.getElementById('stats').innerHTML = stats.map(([k,v,cls]) =>
        `<div class="tel${cls ? ' ' + cls : ''}"><div class="tel-label">${esc(k)}</div><div class="tel-value">${esc(String(v))}</div></div>`
      ).join('');

      renderBundle(bundle, p, db);

      document.getElementById('tab-count-cards').textContent = `[${ac.cards ?? 0}]`;
      document.getElementById('tab-count-bundles').textContent = `[${ac.bundles ?? 0}]`;

      renderCards(art.cards || []);
      renderBundles(art.bundles || [], ac);
      renderLogs(data);
    }

    async function refreshOnce(){
      try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderAll(data);
      } catch (err) {
        document.getElementById('subtitle').textContent =
          `연결 실패 — ${err?.message || err} (서버 확인: ./scripts/start.sh)`;
      }
    }

    let streamBackoffMs = 1000;
    let stream = null;

    function connectStream(){
      if (stream) {
        stream.close();
        stream = null;
      }
      stream = new EventSource('/api/stream');
      stream.onopen = () => {
        streamBackoffMs = 1000;
      };
      stream.onmessage = (ev) => {
        if (!ev.data || ev.data.startsWith(':')) return;
        try {
          const data = JSON.parse(ev.data);
          renderAll(data);
        } catch (e) {}
      };
      stream.onerror = () => {
        stream?.close();
        stream = null;
        setTimeout(connectStream, streamBackoffMs);
        streamBackoffMs = Math.min(streamBackoffMs * 2, 15000);
      };
    }

    refreshOnce();
    connectStream();
  </script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def handle(self) -> None:
        try:
            super().handle()
        except Exception as exc:
            if _is_client_disconnect(exc):
                return
            raise

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except Exception as exc:
            if _is_client_disconnect(exc):
                return
            raise

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(self.path.split("?", 1)[0])
        if path in ("/", "/index.html"):
            self._respond(200, _html_page().encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/status":
            payload = json.dumps(build_dashboard_payload(), ensure_ascii=False, default=str)
            self._respond(200, payload.encode("utf-8"), "application/json; charset=utf-8")
            return
        if path == "/api/stream":
            self._respond_sse()
            return
        if path.startswith("/output/"):
            rel = path[len("/output/") :]
            file_path = (_OUTPUT / rel).resolve()
            if not str(file_path).startswith(str(_OUTPUT.resolve())):
                self._respond(403, b"forbidden", "text/plain")
                return
            if not file_path.is_file():
                self._respond(404, b"not found", "text/plain")
                return
            ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
            self._respond(200, file_path.read_bytes(), ctype)
            return
        self._respond(404, b"not found", "text/plain")


    def _respond_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            for chunk in sse_stream(root=_ROOT):
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except Exception as exc:
            if not _is_client_disconnect(exc):
                raise

    def _respond(self, code: int, body: bytes, content_type: str) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            if not _is_client_disconnect(exc):
                raise


class DashboardHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        exc = sys.exc_info()[1]
        if exc is not None and _is_client_disconnect(exc):
            return
        super().handle_error(request, client_address)

    def process_request_thread(self, request, client_address) -> None:  # noqa: ANN001
        try:
            self.finish_request(request, client_address)
        except Exception as exc:
            if _is_client_disconnect(exc):
                self.close_request(request)
                return
            self.handle_error(request, client_address)
            self.close_request(request)


_dashboard_server: DashboardHTTPServer | None = None
_dashboard_thread: threading.Thread | None = None


def start_dashboard_background(*, host: str | None = None, port: int | None = None) -> str:
    """백그라운드에서 대시보드 HTTP 서버 시작. 접속 URL 반환."""
    global _dashboard_server, _dashboard_thread
    load_env()
    h = host or os.getenv("DASHBOARD_HOST", "127.0.0.1")
    p = port or int(os.getenv("DASHBOARD_PORT", "8787"))
    if _dashboard_server is not None:
        return f"http://{h}:{p}"
    _dashboard_server = DashboardHTTPServer((h, p), DashboardHandler)
    _dashboard_thread = threading.Thread(
        target=_dashboard_server.serve_forever,
        daemon=True,
        name="devpulse-dashboard",
    )
    _dashboard_thread.start()
    return f"http://{h}:{p}"


def stop_dashboard() -> None:
    global _dashboard_server, _dashboard_thread
    if _dashboard_server is not None:
        _dashboard_server.shutdown()
        _dashboard_server.server_close()
        _dashboard_server = None
    if _dashboard_thread is not None:
        _dashboard_thread.join(timeout=2)
        _dashboard_thread = None


def run_dashboard(*, host: str | None = None, port: int | None = None) -> None:
    start_dashboard_background(host=host, port=port)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        stop_dashboard()


if __name__ == "__main__":
    run_dashboard()
