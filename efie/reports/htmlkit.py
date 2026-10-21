"""Shared page styling and chart code for the dashboard and the Pine preview.

Single-series charts only (no dual axes); colour tokens follow the reference palette,
with dark-mode steps selected separately rather than inverted.
"""

BASE_CSS = r"""
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--s1:#2a78d6;--neg:#2a78d6;--pos:#e34948;--good:#0ca30c;--critical:#d03b3b;--ring:rgba(11,11,11,.10)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;
--grid:#2c2c2a;--axis:#383835;--s1:#3987e5;--neg:#3987e5;--pos:#e66767;--ring:rgba(255,255,255,.10)}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--s1:#3987e5;--neg:#3987e5;--pos:#e66767;--ring:rgba(255,255,255,.10)}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1200px;margin:0 auto;padding:16px}header{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;justify-content:space-between;margin-bottom:12px}
h1{font-size:20px;margin:0}h2{font-size:16px;margin:24px 0 8px}h3{font-size:14px;margin:0 0 4px}
.hero{font-size:48px;font-weight:600;line-height:1}.sub{color:var(--ink2);font-size:12px}.muted{color:var(--muted)}
.note{border-left:3px solid var(--axis);padding:8px 12px;background:var(--surface);color:var(--ink2);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--ring);border-radius:8px;padding:12px;min-width:0}
.card ul{margin:6px 0 0;padding-left:18px}.tag{font-weight:400;font-size:12px;color:var(--ink2);border:1px solid var(--ring);border-radius:10px;padding:1px 8px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
td.num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}.scroll{overflow-x:auto}
.chip{display:inline-block;border-radius:10px;padding:1px 8px;font-size:12px;border:1px solid currentColor;white-space:nowrap}
.chip.good{color:var(--good)}.chip.critical{color:var(--critical)}
svg{display:block;width:100%;height:auto}.tt{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--ring);
border-radius:6px;padding:4px 8px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,.12);display:none;z-index:10}
.key{display:inline-flex;align-items:center;gap:6px;margin-right:12px;font-size:12px;color:var(--ink2)}.key i{width:10px;height:10px;border-radius:2px;display:inline-block}
"""

CHART_JS = r"""const tt=document.getElementById('tt');
function show(e,t){tt.style.display='block';tt.textContent=t;tt.style.left=(e.clientX+12)+'px';tt.style.top=(e.clientY+12)+'px'}
function hide(){tt.style.display='none'}
function nice(v){return Math.abs(v)>=100?v.toFixed(0):Math.abs(v)>=10?v.toFixed(1):v.toFixed(2)}
function line(el,c){const W=520,H=200,L=44,R=12,T=10,B=24;const d=c.data;if(!d.length){el.innerHTML='<h3>'+c.title+'</h3><p class="sub">No data in this feed.</p>';return}
 const ys=d.map(p=>p[1]);let lo=Math.min(...ys),hi=Math.max(...ys);if(c.zero){lo=Math.min(lo,0);hi=Math.max(hi,0)}const pad=(hi-lo)*.06||1;const pos=lo>=0;lo-=pad;hi+=pad;if(pos&&lo<0)lo=0;
 const x=i=>L+(W-L-R)*i/(d.length-1||1),y=v=>T+(H-T-B)*(hi-v)/(hi-lo);let g='';
 for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;g+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)" stroke-width="1"/><text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--muted)">${nice(v)}</text>`}
 if(c.zero)g+=`<line x1="${L}" x2="${W-R}" y1="${y(0)}" y2="${y(0)}" stroke="var(--axis)" stroke-width="1"/>`;
 [0,Math.floor(d.length/2),d.length-1].forEach(i=>g+=`<text x="${x(i)}" y="${H-6}" text-anchor="${i==0?'start':i==d.length-1?'end':'middle'}" font-size="11" fill="var(--muted)">${d[i][0]}</text>`);
 const pts=d.map((p,i)=>x(i).toFixed(1)+','+y(p[1]).toFixed(1)).join(' ');const last=d[d.length-1];
 el.innerHTML=`<h3>${c.title}</h3><div class="sub">${c.unit} · last ${nice(last[1])} (${last[0]})</div><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${c.title}">${g}<polyline fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="${pts}"/><line class="xh" y1="${T}" y2="${H-B}" stroke="var(--axis)" stroke-width="1" visibility="hidden"/><circle class="dot" r="4" fill="var(--s1)" stroke="var(--surface)" stroke-width="2" visibility="hidden"/><circle cx="${x(d.length-1)}" cy="${y(last[1])}" r="4" fill="var(--s1)" stroke="var(--surface)" stroke-width="2"/><rect x="${L}" y="${T}" width="${W-L-R}" height="${H-T-B}" fill="transparent"/></svg>`;
 const svg=el.querySelector('svg'),xh=svg.querySelector('.xh'),dot=svg.querySelector('.dot');
 svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect();const px=(e.clientX-r.left)*W/r.width;const i=Math.max(0,Math.min(d.length-1,Math.round((px-L)/(W-L-R)*(d.length-1))));
  xh.setAttribute('x1',x(i));xh.setAttribute('x2',x(i));xh.setAttribute('visibility','visible');dot.setAttribute('cx',x(i));dot.setAttribute('cy',y(d[i][1]));dot.setAttribute('visibility','visible');show(e,d[i][0]+': '+nice(d[i][1])+' '+c.unit)});
 svg.addEventListener('mouseleave',()=>{xh.setAttribute('visibility','hidden');dot.setAttribute('visibility','hidden');hide()})}
function bars(el,c){const W=520,H=220,L=44,R=12,T=10,B=24;const d=c.bars;if(!d.length){el.innerHTML='<h3>'+c.title+'</h3>';return}
 const ys=d.map(p=>p[1]);const m=Math.max(...ys.map(Math.abs))*1.1||1;const y=v=>T+(H-T-B)*(m-v)/(2*m);const bw=Math.min(24,(W-L-R)/d.length-2);
 let g='';[-m,-m/2,0,m/2,m].forEach(v=>g+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="${v==0?'var(--axis)':'var(--grid)'}" stroke-width="1"/><text x="${L-6}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--muted)">${nice(v)}</text>`);
 d.forEach((p,i)=>{const cx=L+(W-L-R)*(i+.5)/d.length,v=p[1],y0=y(0),y1=y(v),h=Math.abs(y1-y0),top=Math.min(y0,y1),r=Math.min(4,h/2);
  const col=v<0?'var(--neg)':'var(--pos)';const x0=cx-bw/2;
  const path=v>=0?`M${x0},${y0}V${top+r}Q${x0},${top} ${x0+r},${top}H${x0+bw-r}Q${x0+bw},${top} ${x0+bw},${top+r}V${y0}Z`:`M${x0},${y0}V${top+h-r}Q${x0},${top+h} ${x0+r},${top+h}H${x0+bw-r}Q${x0+bw},${top+h} ${x0+bw},${top+h-r}V${y0}Z`;
  g+=`<path d="${path}" fill="${col}"/><rect x="${cx-(W-L-R)/d.length/2}" y="${T}" width="${(W-L-R)/d.length}" height="${H-T-B}" fill="transparent" data-t="${p[0]}: ${v>0?'+':''}${v.toFixed(2)} M bbl (${v<0?'draw vs consensus':'build vs consensus'})"/>`});
 g+=`<text x="${L}" y="${H-6}" font-size="11" fill="var(--muted)">${d[0][0]}</text><text x="${W-R}" y="${H-6}" text-anchor="end" font-size="11" fill="var(--muted)">${d[d.length-1][0]}</text>`;
 el.innerHTML=`<h3>${c.title}</h3><div class="sub"><span class="key"><i style="background:var(--neg)"></i>below consensus (bullish)</span><span class="key"><i style="background:var(--pos)"></i>above consensus (bearish)</span></div><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${c.title}">${g}</svg>`;
 el.querySelectorAll('rect[data-t]').forEach(r=>{r.addEventListener('mousemove',e=>show(e,r.dataset.t));r.addEventListener('mouseleave',hide)})}
"""
