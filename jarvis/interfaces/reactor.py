"""Arc-reactor visual UI — a spinning Iron-Man reactor that reacts to voice state.

Served by a dependency-free stdlib HTTP server (no FastAPI needed). The page polls
/state, which reflects what the voice service wrote via core.state. Open with
`jarvis reactor`.
"""
from __future__ import annotations

import http.server
import json
import shutil
import socketserver
import subprocess
import sys
import threading

from ..core.state import get_state

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS</title>
<style>
  html,body{margin:0;height:100%;background:#02060b;overflow:hidden;
    font-family:ui-monospace,Menlo,Consolas,monospace;color:#9fd8ff}
  #wrap{position:fixed;inset:0;display:flex;flex-direction:column;
    align-items:center;justify-content:center;gap:18px}
  canvas{filter:drop-shadow(0 0 24px rgba(40,200,255,.25))}
  #status{letter-spacing:6px;text-transform:uppercase;font-size:14px;opacity:.85;
    transition:color .4s}
  #detail{max-width:70vw;text-align:center;font-size:12px;opacity:.5;min-height:1.2em}
</style></head><body>
<div id="wrap">
  <canvas id="c" width="520" height="520"></canvas>
  <div id="status">idle</div>
  <div id="detail"></div>
</div>
<script>
const cv=document.getElementById('c'),x=cv.getContext('2d');
const W=cv.width,H=cv.height,CX=W/2,CY=H/2;
const THEME={
  idle:    {col:[60,150,220], glow:.5, spin:.25, pulse:.04, label:'idle'},
  listening:{col:[40,225,255], glow:1.0, spin:.7,  pulse:.10, label:'listening'},
  thinking:{col:[255,180,60], glow:.9,  spin:1.5, pulse:.06, label:'thinking'},
  speaking:{col:[210,245,255],glow:1.2, spin:1.0, pulse:.22, label:'speaking'}
};
let state='idle', t=0, ang=0, cur={col:[60,150,220],glow:.5,spin:.25,pulse:.04};
function lerp(a,b,k){return a+(b-a)*k}
function mix(){const T=THEME[state]||THEME.idle;
  cur.col=cur.col.map((v,i)=>lerp(v,T.col[i],.08));
  cur.glow=lerp(cur.glow,T.glow,.08);cur.spin=lerp(cur.spin,T.spin,.08);
  cur.pulse=lerp(cur.pulse,T.pulse,.08);}
function rgb(c,a){return 'rgba('+(c[0]|0)+','+(c[1]|0)+','+(c[2]|0)+','+a+')'}
function ring(r,ry,w,c,a){x.beginPath();x.ellipse(0,0,r,ry,0,0,7);x.lineWidth=w;
  x.strokeStyle=rgb(c,a);x.stroke();}
function draw(){
  t+=1; mix(); ang+=cur.spin*0.03;
  const tilt=0.34+0.05*Math.sin(t*0.012);           // 3D disc tilt wobble
  const audio = state==='speaking' ? (0.6+0.4*Math.abs(Math.sin(t*0.5)+0.5*Math.sin(t*0.93))) : 1;
  const pulse=1+cur.pulse*Math.sin(t*0.12)*audio;
  x.clearRect(0,0,W,H);
  // backdrop glow
  let bg=x.createRadialGradient(CX,CY,0,CX,CY,260);
  bg.addColorStop(0,rgb(cur.col,0.10*cur.glow));bg.addColorStop(1,'rgba(0,0,0,0)');
  x.fillStyle=bg;x.fillRect(0,0,W,H);
  x.save();x.translate(CX,CY);x.scale(1,1);
  x.shadowBlur=40*cur.glow;x.shadowColor=rgb(cur.col,0.9);
  // outer housing rings (tilted ellipses)
  ring(210,210*tilt+150*(1-tilt),6,cur.col,0.35);
  ring(186,186*tilt+140*(1-tilt),2,cur.col,0.25);
  // coil ring — N coils placed on a tilted ellipse, depth-scaled for 3D
  const N=9,R=150,RY=R*tilt+120*(1-tilt);
  for(let i=0;i<N;i++){
    const a=ang + i/N*Math.PI*2;
    const px=Math.cos(a)*R, py=Math.sin(a)*RY;
    const depth=(Math.sin(a)+1)/2;            // 0 back .. 1 front
    const s=0.55+0.75*depth, al=0.30+0.6*depth;
    x.save();x.translate(px,py);x.rotate(a+Math.PI/2);
    x.fillStyle=rgb(cur.col,al);
    x.fillRect(-9*s,-16*s,18*s,32*s);          // coil block
    x.fillStyle=rgb([255,255,255],0.15*depth);
    x.fillRect(-9*s,-16*s,18*s,5*s);
    x.restore();
  }
  // signature triangle (counter-rotating)
  x.save();x.rotate(-ang*0.6);x.beginPath();
  for(let i=0;i<3;i++){const a=i/3*Math.PI*2-Math.PI/2;
    const r=78*pulse;(i?x.lineTo:x.moveTo).call(x,Math.cos(a)*r,Math.sin(a)*r);}
  x.closePath();x.lineWidth=3;x.strokeStyle=rgb(cur.col,0.8);x.stroke();x.restore();
  // core
  let g=x.createRadialGradient(0,0,0,0,0,70*pulse);
  g.addColorStop(0,rgb([255,255,255],0.95*cur.glow));
  g.addColorStop(0.4,rgb(cur.col,0.9));
  g.addColorStop(1,rgb(cur.col,0));
  x.fillStyle=g;x.beginPath();x.arc(0,0,70*pulse,0,7);x.fill();
  x.restore();
  requestAnimationFrame(draw);
}
async function poll(){
  try{const r=await fetch('/state',{cache:'no-store'});const j=await r.json();
    if(j.state&&THEME[j.state])state=j.state;
    const s=document.getElementById('status');
    s.textContent=(THEME[state]||THEME.idle).label;
    s.style.color=rgb((THEME[state]||THEME.idle).col,0.95);
    document.getElementById('detail').textContent=j.detail||'';
  }catch(e){}
  setTimeout(poll,150);
}
draw();poll();
</script></body></html>"""


def _open_browser(url: str) -> None:
    for cmd in (["xdg-open", url], ["open", url]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    try:
        import webbrowser

        webbrowser.open(url)
    except Exception:
        pass


class _Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/state"):
            self._send(json.dumps(get_state()).encode(), "application/json")
        else:
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")

    def log_message(self, *a) -> None:  # silence access logs
        pass


def run_reactor(port: int = 8788, open_browser: bool = True) -> None:
    class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True

    srv = Server(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"[reactor] arc reactor at {url}  (Ctrl-C to close)")
    if open_browser:
        threading.Timer(0.6, _open_browser, args=[url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.shutdown()


if __name__ == "__main__":
    run_reactor(int(sys.argv[1]) if len(sys.argv) > 1 else 8788)
