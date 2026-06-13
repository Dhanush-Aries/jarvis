"""Siri-style floating popup that reacts to Jarvis voice state.

Serves a minimal HTML page on a local port, then opens it in a Chrome --app
window (no address bar, no tabs) pinned to the bottom-centre of the screen.
The page polls /state every 150 ms and animates a coloured waveform + status.
"""
from __future__ import annotations

import http.server
import json
import re
import shutil
import socketserver
import subprocess
import sys
import threading

from ..core.state import get_state

POPUP_W = 560
POPUP_H = 130
PORT_DEFAULT = 8789

# ---------------------------------------------------------------------------
# Embedded HTML – no external assets, pure canvas + CSS
# ---------------------------------------------------------------------------
PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<title>JARVIS</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{
  width:560px;height:130px;
  background:#060c18;
  font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',system-ui,sans-serif;
  color:#c8d8ff;overflow:hidden;user-select:none;
}
#app{padding:11px 18px 10px;display:flex;flex-direction:column;gap:5px}
.hdr{display:flex;align-items:center;gap:8px}
#dot{
  width:9px;height:9px;border-radius:50%;flex-shrink:0;
  background:#1a4070;box-shadow:0 0 6px rgba(40,110,220,.4);
  transition:background .35s,box-shadow .35s;
}
.brand{
  font-size:10px;font-weight:700;letter-spacing:5px;
  text-transform:uppercase;color:rgba(185,210,255,.65);
}
#badge{
  margin-left:auto;font-size:10px;letter-spacing:2.5px;
  text-transform:uppercase;color:rgba(80,130,190,.45);
  transition:color .35s;min-width:64px;text-align:right;
}
#cwrap{
  display:flex;justify-content:center;
  filter:drop-shadow(0 0 7px rgba(40,110,220,.2));
  transition:filter .5s;
}
#text{
  font-size:11px;color:rgba(170,200,255,.5);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  height:16px;letter-spacing:.2px;
  transition:opacity .15s;
}
</style>
</head><body>
<div id="app">
  <div class="hdr">
    <div id="dot"></div>
    <span class="brand">JARVIS</span>
    <span id="badge">·</span>
  </div>
  <div id="cwrap">
    <canvas id="cv" width="524" height="54"></canvas>
  </div>
  <div id="text"></div>
</div>
<script>
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
const W=cv.width,H=cv.height,HALF=H/2;
const N=34,BW=7,BG=3,TW=N*(BW+BG)-BG,OX=(W-TW)/2;

/* per-state config: amplitude, baseline-H, speed, hue-range, saturation, lightness */
const S={
  idle:     {a:1.5,  b:3,  s:.45,  h1:215, h2:225, sat:50,  lit:18,  al:.5},
  listening:{a:23,   b:6,  s:3.0,  h1:182, h2:212, sat:100, lit:65,  al:1},
  thinking: {a:17,   b:7,  s:2.1,  h1:36,  h2:52,  sat:100, lit:60,  al:1},
  speaking: {a:27,   b:9,  s:4.8,  h1:0,   h2:360, sat:90,  lit:65,  al:1},
};
let st='idle',t=0;
const cur=Object.assign({},S.idle);
function lerp(a,b,k){return a+(b-a)*k}
function blend(){
  const T=S[st]||S.idle;
  for(const k of['a','b','s','h1','h2','sat','lit','al'])cur[k]=lerp(cur[k],T[k],.055);
}
function barColor(i){
  const hue=(st==='speaking')
    ? (cur.h1+(i/(N-1))*(cur.h2-cur.h1)+t*45)%360
    : cur.h1+(i/(N-1))*(cur.h2-cur.h1);
  return `hsla(${hue|0},${cur.sat|0}%,${cur.lit|0}%,${cur.al.toFixed(2)})`;
}
function draw(){
  t+=.016;blend();
  ctx.clearRect(0,0,W,H);
  for(let i=0;i<N;i++){
    const ph=i*.37;
    const wave=cur.a*(
      .55*Math.sin(t*cur.s+ph)+
      .35*Math.sin(t*cur.s*1.65+ph*.9)+
      .10*Math.sin(t*cur.s*.4+ph*1.25)
    );
    const h=Math.max(4,cur.b+Math.abs(wave));
    const x=OX+i*(BW+BG), y=HALF-h/2;
    ctx.fillStyle=barColor(i);
    ctx.beginPath();
    ctx.roundRect(x,y,BW,h,2);
    ctx.fill();
  }
  requestAnimationFrame(draw);
}

const dotEl=document.getElementById('dot');
const badgeEl=document.getElementById('badge');
const textEl=document.getElementById('text');
const cwrap=document.getElementById('cwrap');

const DOT={
  idle:     ['#1a3f72','rgba(30,90,200,.35)'],
  listening:['#00d4ff','rgba(0,210,255,.75)'],
  thinking: ['#ffbe0b','rgba(255,185,11,.75)'],
  speaking: ['#5dfc60','rgba(80,255,80,.7)'],
};
const BADGE_COL={
  idle:'rgba(70,110,170,.4)',
  listening:'rgba(0,210,255,.75)',
  thinking:'rgba(255,190,11,.75)',
  speaking:'rgba(80,255,80,.7)',
};
const GLOW={
  idle:'rgba(30,100,220,.12)',
  listening:'rgba(0,200,255,.32)',
  thinking:'rgba(255,185,11,.28)',
  speaking:'rgba(60,255,60,.28)',
};

function setText(txt){
  if(textEl.textContent===txt)return;
  textEl.style.opacity='0';
  setTimeout(()=>{textEl.textContent=txt;textEl.style.opacity='1';},130);
}

async function poll(){
  try{
    const j=await(await fetch('/state',{cache:'no-store'})).json();
    if(j.state&&S[j.state])st=j.state;
    // dot
    const[dc,ds]=DOT[st]||DOT.idle;
    dotEl.style.background=dc;dotEl.style.boxShadow=`0 0 10px ${ds}`;
    // badge
    badgeEl.textContent=st==='idle'?'·':st;
    badgeEl.style.color=BADGE_COL[st];
    // glow
    cwrap.style.filter=`drop-shadow(0 0 10px ${GLOW[st]})`;
    // text
    let txt='';
    if(st==='listening')txt='Listening…';
    else if(st==='thinking'&&j.detail)txt=`You: ${j.detail}`;
    else if(st==='speaking'){
      if(j.transcript&&j.detail)txt=`You: ${j.transcript}  ·  J: ${j.detail}`;
      else if(j.detail)txt=`J: ${j.detail}`;
    }
    setText(txt);
  }catch(_){}
  setTimeout(poll,150);
}
draw();poll();
</script>
</body></html>"""


# ---------------------------------------------------------------------------
# Screen-size detection (Hyprland/Wayland first, then xrandr fallback)
# ---------------------------------------------------------------------------
def _screen_size() -> tuple[int, int]:
    if shutil.which("hyprctl"):
        try:
            raw = subprocess.check_output(
                ["hyprctl", "monitors", "-j"],
                stderr=subprocess.DEVNULL, text=True, timeout=2,
            )
            monitors = json.loads(raw)
            if monitors:
                m = monitors[0]
                return m["width"], m["height"]
        except Exception:
            pass
    if shutil.which("xrandr"):
        try:
            raw = subprocess.check_output(
                ["xrandr", "--current"],
                stderr=subprocess.DEVNULL, text=True, timeout=2,
            )
            match = re.search(r"current\s+(\d+)\s*x\s*(\d+)", raw)
            if match:
                return int(match.group(1)), int(match.group(2))
        except Exception:
            pass
    return 1920, 1080


# ---------------------------------------------------------------------------
# Chrome launcher
# ---------------------------------------------------------------------------
def _launch_chrome(port: int, w: int, h: int) -> None:
    exe = (
        shutil.which("google-chrome-stable")
        or shutil.which("google-chrome")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    if not exe:
        print(f"[popup] Chrome not found — open manually: http://127.0.0.1:{port}/")
        return

    sw, sh = _screen_size()
    x = (sw - w) // 2
    y = sh - h - 44   # 44 px above the bottom edge / dock

    cmd = [
        exe,
        f"--app=http://127.0.0.1:{port}/",
        f"--window-size={w},{h}",
        f"--window-position={x},{y}",
        "--disable-infobars",
        "--no-first-run",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--no-default-browser-check",
        "--disable-features=TranslateUI",
        "--class=jarvis-popup",     # X11 WM_CLASS (useful for window rules)
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------
class _Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/state"):
            self._send(json.dumps(get_state()).encode(), "application/json")
        else:
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, *_) -> None:
        pass


def run_popup(port: int = PORT_DEFAULT, open_browser: bool = True) -> None:
    class _Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    srv = _Srv(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"[popup] Jarvis popup server at {url}")
    print("[popup] Tip — add to hyprland.conf for a borderless pin:")
    print("  windowrulev2 = float,       title:^(JARVIS)$")
    print("  windowrulev2 = noborder,    title:^(JARVIS)$")
    print("  windowrulev2 = noshadow,    title:^(JARVIS)$")
    print("  windowrulev2 = pin,         title:^(JARVIS)$")

    if open_browser:
        threading.Timer(0.5, _launch_chrome, args=[port, POPUP_W, POPUP_H]).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()


if __name__ == "__main__":
    run_popup(int(sys.argv[1]) if len(sys.argv) > 1 else PORT_DEFAULT)
