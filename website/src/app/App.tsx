import { useState, useEffect, useRef, memo, useCallback } from "react";
import {
  type CF, type Level, type VHMeta, LVL_INK, FALLBACK_FILES, levelFromScore,
  VHProvider, useVH, API_BASE,
} from "./data";

/* ─── PALETTE ────────────────────────────────────────────────────────────────
   paper: #F4F2EA   warm:   #E9E5DA   gray:   #D8D4C9
   ink:   #101010   soft:   #2A2926   muted:  #6B6660
   red:   #8D2F2F   amber:  #A08A54   teal:   #2F5F5F

   Country data, palette, levels and the live API client live in ./data.tsx.
   Components read live data via the useVH() hook; FALLBACK_FILES is the static
   archive snapshot used until (or unless) the API responds.
─────────────────────────────────────────────────────────────────────────── */
const STREAM_Q=["BRA","EGY","PAK","RUS","USA","TUR","NGA","UKR","ARG","CHN","IND","VEN","ZAF","MEX","GHA","IRN","COL","PER","ZWE","KEN"];
const m="font-['JetBrains_Mono',monospace]";
function bar(s:number,w=10){const n=Math.round(s/100*w);return"▓".repeat(n)+"░".repeat(w-n);}

/* ═══════════════════════════════════════════════════════════════════════════
   ASCII ART TITLE  ·  box-drawing chars, per-character spring physics
═══════════════════════════════════════════════════════════════════════════ */
const VH_ASCII = [
  "██╗   ██╗██╗███████╗██╗██████╗ ██╗     ███████╗    ██╗  ██╗ █████╗ ███╗   ██╗██████╗ ",
  "██║   ██║██║██╔════╝██║██╔══██╗██║     ██╔════╝    ██║  ██║██╔══██╗████╗  ██║██╔══██╗",
  "██║   ██║██║███████╗██║██████╔╝██║     █████╗      ███████║███████║██╔██╗ ██║██║  ██║",
  "╚██╗ ██╔╝██║╚════██║██║██╔══██╗██║     ██╔══╝      ██╔══██║██╔══██║██║╚██╗██║██║  ██║",
  " ╚████╔╝ ██║███████║██║██████╔╝███████╗███████╗    ██║  ██║██║  ██║██║ ╚████║██████╔╝",
  "  ╚═══╝  ╚═╝╚══════╝╚═╝╚═════╝ ╚══════╝╚══════╝    ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═════╝",
];

/* ASCII title drawn to ONE <canvas> — a single GPU layer with ~330 fillText
   calls per frame, instead of ~330 individually-transformed DOM spans (each its
   own compositor layer). Same per-character spring physics; lightning-fast and
   it never touches layout, so it can't lag the page or flicker a scrollbar. */
const AsciiTitle = memo(function AsciiTitle(){
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(()=>{
    const canvas = ref.current; if(!canvas) return;
    const ctx = canvas.getContext("2d"); if(!ctx) return;
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const COLS = Math.max(...VH_ASCII.map(l=>l.length));
    const ROWS = VH_ASCII.length;
    const glyphs:{ch:string;col:number;row:number;x:number;y:number;vx:number;vy:number}[] = [];
    for(let row=0;row<ROWS;row++){
      const line = VH_ASCII[row]!;
      for(let col=0;col<line.length;col++){
        if(line[col] !== " ") glyphs.push({ch:line[col]!,col,row,x:0,y:0,vx:0,vy:0});
      }
    }

    let fs=0, charW=0, lineH=0, W=0, H=0, mx=-9999, my=-9999;
    const layout = ()=>{
      const dpr = window.devicePixelRatio || 1;
      const availW = canvas.parentElement?.clientWidth || window.innerWidth;
      fs = Math.max(6, Math.min(21, availW/(COLS*0.6)));   // matches the old clamp(6,1.45vw,21)
      charW = fs*0.6; lineH = fs*1.25;
      W = COLS*charW; H = ROWS*lineH;
      canvas.style.width = W+"px"; canvas.style.height = H+"px";
      canvas.width = Math.round(W*dpr); canvas.height = Math.round(H*dpr);
      ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.font = `${fs}px 'JetBrains Mono', ui-monospace, monospace`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillStyle = "#101010";
    };
    const drawStatic = ()=>{ ctx.clearRect(0,0,W,H); for(const g of glyphs) ctx.fillText(g.ch, g.col*charW+charW/2, g.row*lineH+lineH/2); };
    layout(); drawStatic();

    const onMove = (e:MouseEvent)=>{ const r=canvas.getBoundingClientRect(); mx=e.clientX-r.left; my=e.clientY-r.top; };
    window.addEventListener("mousemove", onMove, {passive:true});
    window.addEventListener("resize", layout);

    const SPRING=0.055, DAMPING=0.72, RADIUS=160, FORCE=28, DEG=Math.PI/180;
    let running=false, visible=true, raf=0;
    const frame = (time:number)=>{
      ctx.clearRect(0,0,W,H);
      const t = time*0.001;
      for(let i=0;i<glyphs.length;i++){
        const g = glyphs[i]!;
        const cx = g.col*charW+charW/2, cy = g.row*lineH+lineH/2;
        const ambFx = Math.sin(t*0.38+i*0.31)*0.04, ambFy = Math.cos(t*0.27+i*0.47)*0.025;
        const dx = mx-cx, dy = my-cy, dist = Math.sqrt(dx*dx+dy*dy);
        let fx=0, fy=0;
        if(dist<RADIUS && dist>0.5){ const s=(1-dist/RADIUS)**2*FORCE; fx=-(dx/dist)*s; fy=-(dy/dist)*s; }
        g.vx = (g.vx - g.x*SPRING + fx + ambFx)*DAMPING;
        g.vy = (g.vy - g.y*SPRING + fy + ambFy)*DAMPING;
        g.x += g.vx; g.y += g.vy;
        const rot = g.vx*0.6*DEG;
        if(rot>0.0008 || rot<-0.0008){
          ctx.save(); ctx.translate(cx+g.x, cy+g.y); ctx.rotate(rot); ctx.fillText(g.ch,0,0); ctx.restore();
        } else {
          ctx.fillText(g.ch, cx+g.x, cy+g.y);
        }
      }
      if(running) raf = requestAnimationFrame(frame);
    };
    const start = ()=>{ if(!running && !reduce){ running=true; raf=requestAnimationFrame(frame); } };
    const stop  = ()=>{ running=false; cancelAnimationFrame(raf); };

    const hero = document.getElementById("top");
    const io = new IntersectionObserver(([e])=>{ visible=e.isIntersecting; (visible && !document.hidden) ? start() : stop(); }, {threshold:0});
    if(!reduce){ if(hero) io.observe(hero); else start(); }
    const onVis = ()=>{ document.hidden ? stop() : (visible && start()); };
    document.addEventListener("visibilitychange", onVis);
    // Re-measure once the web font loads (first paint may use the fallback metrics).
    if(document.fonts && document.fonts.ready) document.fonts.ready.then(()=>{ layout(); if(!running) drawStatic(); });

    return ()=>{ stop(); io.disconnect(); document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("mousemove", onMove); window.removeEventListener("resize", layout); };
  },[]);
  return <canvas ref={ref} aria-label="VisibleHand" role="img" className="select-none block max-w-full" style={{display:"block"}}/>;
});

/* ═══════════════════════════════════════════════════════════════════════════
   TERRAIN CANVAS  ·  black ink on paper
═══════════════════════════════════════════════════════════════════════════ */
const TerrainCanvas=memo(function TerrainCanvas({opacity=1}:{opacity?:number}){
  const ref=useRef<HTMLCanvasElement>(null);
  const raf=useRef(0);const t=useRef(0);
  useEffect(()=>{
    const canvas=ref.current; if(!canvas)return;
    const ctx=canvas.getContext("2d"); if(!ctx)return;
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let W=0,H=0, running=false, visible=true, io:IntersectionObserver|null=null;
    const resize=()=>{
      const r=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
      canvas.width=(W=r.width)*dpr; canvas.height=(H=r.height)*dpr; ctx.scale(dpr,dpr);
    };
    resize();
    const ro=new ResizeObserver(resize); ro.observe(canvas);
    const ROWS=44,COLS=62;
    const getH=(wx:number,wz:number,tt:number)=>(
      Math.sin(wx*1.1+tt*1.0)*0.38+Math.sin(wx*2.3-tt*0.7+wz*0.25)*0.22+
      Math.cos(wx*0.55+wz*0.18-tt*0.55)*0.28+Math.sin((wx+wz)*0.75+tt*0.85)*0.14
    );
    const draw=()=>{
      ctx.clearRect(0,0,W,H); ctx.fillStyle="#F4F2EA"; ctx.fillRect(0,0,W,H);
      const tt=t.current; t.current+=0.0045;
      const HOR=H*0.38;
      for(let yi=0;yi<ROWS;yi++){
        const yp=yi/(ROWS-1);
        const sy=HOR+Math.pow(yp,1.6)*(H-HOR);
        const wz=(1-yp)*12+0.2;
        const alpha=(0.035+yp*0.50)*opacity;
        ctx.beginPath();
        for(let xi=0;xi<=COLS;xi++){
          const xp=xi/COLS,wx=(xp-0.5)*10;
          const hv=getH(wx,wz,tt)*(0.25+yp*0.75);
          const sx=W*0.5+(wx/wz)*W*0.52;
          const syi=sy-hv*H*0.28;
          xi===0?ctx.moveTo(sx,syi):ctx.lineTo(sx,syi);
        }
        ctx.strokeStyle=`rgba(16,14,12,${alpha})`; ctx.lineWidth=0.3+yp*1.0; ctx.stroke();
      }
      for(let xi=0;xi<=22;xi++){
        const xp=xi/22,wx=(xp-0.5)*10;
        const alpha=(0.02+Math.abs(xp-0.5)*0.04)*opacity;
        ctx.beginPath();
        for(let yi=0;yi<ROWS;yi++){
          const yp=yi/(ROWS-1);
          const sy=HOR+Math.pow(yp,1.6)*(H-HOR);
          const wz=(1-yp)*12+0.2;
          const hv=getH(wx,wz,tt)*(0.25+yp*0.75);
          const sx=W*0.5+(wx/wz)*W*0.52;
          const syi=sy-hv*H*0.28;
          yi===0?ctx.moveTo(sx,syi):ctx.lineTo(sx,syi);
        }
        ctx.strokeStyle=`rgba(16,14,12,${alpha})`; ctx.lineWidth=0.25; ctx.stroke();
      }
      ctx.beginPath(); ctx.moveTo(0,HOR); ctx.lineTo(W,HOR);
      ctx.strokeStyle=`rgba(16,14,12,${0.05*opacity})`; ctx.lineWidth=0.5; ctx.stroke();
      if(running) raf.current=requestAnimationFrame(draw);
    };
    const start=()=>{ if(!running && !reduce){ running=true; raf.current=requestAnimationFrame(draw); } };
    const stop =()=>{ running=false; cancelAnimationFrame(raf.current); };
    if(reduce){ draw(); }   // single static frame for reduced-motion
    else {
      io=new IntersectionObserver(([e])=>{ visible=e.isIntersecting; (visible && !document.hidden)?start():stop(); },{threshold:0});
      io.observe(canvas);
    }
    const onVis=()=>{ document.hidden?stop():(visible&&start()); };
    document.addEventListener("visibilitychange",onVis);
    return()=>{ stop(); ro.disconnect(); io&&io.disconnect(); document.removeEventListener("visibilitychange",onVis); };
  },[opacity]);
  return <canvas ref={ref} className="absolute inset-0 w-full h-full" aria-hidden/>;
});

/* ═══════════════════════════════════════════════════════════════════════════
   COUNT-UP
═══════════════════════════════════════════════════════════════════════════ */
function useCountUp(target:number,dec=2):[React.RefObject<HTMLSpanElement>,number]{
  const ref=useRef<HTMLSpanElement>(null!); const [val,setVal]=useState(0); const fired=useRef(false);
  useEffect(()=>{
    const obs=new IntersectionObserver(([e])=>{
      if(e.isIntersecting&&!fired.current){fired.current=true;
        const start=performance.now(),dur=1500;
        const step=(now:number)=>{const t=Math.min((now-start)/dur,1);const ease=1-Math.pow(1-t,3);setVal(parseFloat((target*ease).toFixed(dec)));if(t<1)requestAnimationFrame(step);else setVal(target);};
        requestAnimationFrame(step);}
    },{threshold:0.4});
    if(ref.current)obs.observe(ref.current); return()=>obs.disconnect();
  },[target,dec]);
  return[ref,val];
}

/* ═══════════════════════════════════════════════════════════════════════════
   SIGNAL FEED
═══════════════════════════════════════════════════════════════════════════ */
const SignalFeed=memo(function SignalFeed(){
  const {files:FILES}=useVH();
  const [boot,setBoot]=useState(0);const[booted,setBooted]=useState(false);
  const [lines,setLines]=useState<{code:string;ts:string}[]>([]);
  const [cur,setCur]=useState(true);const idx=useRef(0);
  const BOOT=["> CONNECT VH-ARCHIVE ............ OK","> AUTH    PUBLIC ACCESS ........... OK","> INDEX   PUBLIC RECORD ......... OK","> STREAM  OPEN  ● LIVE","────────────────────────────────────"];
  useEffect(()=>{if(boot<BOOT.length){const t=setTimeout(()=>setBoot(s=>s+1),340);return()=>clearTimeout(t);}setBooted(true);},[boot]);
  useEffect(()=>{if(!booted)return;const t=setInterval(()=>{const code=STREAM_Q[idx.current%STREAM_Q.length]!;idx.current++;const d=new Date();const ts=`${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}`;setLines(p=>[...p.slice(-9),{code,ts}]);},950);return()=>clearInterval(t);},[booted]);
  useEffect(()=>{const t=setInterval(()=>setCur(c=>!c),520);return()=>clearInterval(t);},[]);
  return(
    <div className={`${m} text-[11px] flex flex-col bg-[#F4F2EA] border-2 border-[#101010] h-full`}
      style={{minHeight:320,boxShadow:"3px 3px 0 #101010"}}>
      <div className="flex items-center justify-between px-3 py-[5px] border-b-2 border-[#101010] shrink-0"
        style={{background:"repeating-linear-gradient(90deg,#E0DDD4 0,#E0DDD4 1px,#D4D1C8 1px,#D4D1C8 2px)"}}>
        <div className="flex items-center gap-[5px]">
          <div className="w-[11px] h-[11px] border border-[#101010] bg-[#F4F2EA] flex items-center justify-center">
            <div className="w-[5px] h-[5px] bg-[#101010]"/></div>
          <span className="text-[10px] font-bold tracking-[0.06em] text-[#101010]">VH-STREAM</span>
        </div>
        <span className={`text-[9px] tracking-[0.1em] ${booted?"text-[#4A6840]":"text-[#A08A54]"}`}>{booted?"● LIVE":"○ INIT"}</span>
      </div>
      <div className="p-3 flex-1 overflow-hidden leading-[1.9]">
        {BOOT.slice(0,boot).map((l,i)=><div key={i} className="text-[#6B6660]">{l}</div>)}
        {lines.map((ln,i)=>{const f=FILES[ln.code];if(!f)return null;return(
          <div key={i} className="flex gap-2 items-baseline">
            <span className="text-[#A8A49A] text-[9px] w-[52px] shrink-0">{ln.ts}</span>
            <span className="font-semibold w-7 shrink-0 text-[#101010]">{ln.code}</span>
            <span style={{color:LVL_INK[f.level]}}>{bar(f.score,7)}</span>
            <span className="tabular-nums text-[#101010]">{f.score.toFixed(1)}</span>
            <span className="text-[9px] shrink-0" style={{color:LVL_INK[f.level]}}>{f.level}</span>
          </div>
        );})}
        {booted&&<div className="text-[#6B6660]">{"> "}{STREAM_Q[idx.current%STREAM_Q.length]}{"..."}<span className={cur?"opacity-100":"opacity-0"}>▌</span></div>}
      </div>
    </div>
  );
});

/* ═══════════════════════════════════════════════════════════════════════════
   VU METER  ·  hardware channel strip
═══════════════════════════════════════════════════════════════════════════ */
function VUMeter({code}:{code:string}){
  const {files:FILES}=useVH();
  const f=FILES[code];if(!f)return null;
  const [h,setH]=useState(0);const ref=useRef<HTMLDivElement>(null);const fired=useRef(false);
  useEffect(()=>{
    const obs=new IntersectionObserver(([e])=>{if(e.isIntersecting&&!fired.current){fired.current=true;let cur=0;const step=()=>{cur=Math.min(cur+1.6,f.score);setH(cur);if(cur<f.score)requestAnimationFrame(step);};requestAnimationFrame(step);}},{threshold:0.3});
    if(ref.current)obs.observe(ref.current);return()=>obs.disconnect();
  },[f.score]);
  const pct=h/100,col=LVL_INK[f.level];
  return(
    <div ref={ref} className="flex flex-col items-center gap-[5px]" style={{width:42}}>
      <div className="w-full border border-[#101010] relative overflow-hidden bg-[#F4F2EA]" style={{height:84}}>
        {[2,4,6,8,10].map(i=><div key={i} className="absolute left-0 right-0 border-t border-[#D8D4C9]" style={{bottom:`${i*10}%`}}/>)}
        <div className="absolute bottom-0 left-0 right-0 transition-all duration-[600ms] ease-out" style={{height:`${pct*100}%`,background:col,opacity:0.85}}/>
        <div className="absolute left-0 right-0 h-[1px] transition-all duration-[600ms]" style={{bottom:`${pct*100}%`,background:col}}/>
        {[25,50,75].map(v=><div key={v} className="absolute left-0 w-[4px] border-t border-[#C5C1B8]" style={{bottom:`${v}%`}}/>)}
      </div>
      <span className={`${m} text-[8px] tracking-[0.04em] text-[#6B6660]`}>{code}</span>
      <span className={`${m} text-[10px] font-bold tabular-nums`} style={{color:col}}>{f.score.toFixed(0)}</span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   ANIMATED BAR
═══════════════════════════════════════════════════════════════════════════ */
function AnimBar({score,label,color}:{score:number;label:string;color:string}){
  const [v,setV]=useState(0);const ref=useRef<HTMLDivElement>(null);const fired=useRef(false);
  useEffect(()=>{
    const obs=new IntersectionObserver(([e])=>{if(e.isIntersecting&&!fired.current){fired.current=true;let cur=0;const step=()=>{cur=Math.min(cur+1.5,score);setV(cur);if(cur<score)requestAnimationFrame(step);};requestAnimationFrame(step);}},{threshold:0.3});
    if(ref.current)obs.observe(ref.current);return()=>obs.disconnect();
  },[score]);
  return(
    <div ref={ref} className={`${m} flex items-baseline gap-3 text-[12px] py-[2px]`}>
      <span className="w-7 shrink-0 text-[#6B6660]">{label}</span>
      <span style={{color}}>{bar(v)}</span>
      <span className="tabular-nums text-[#101010] w-9">{v.toFixed(1)}</span>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAGNETIC BUTTON
═══════════════════════════════════════════════════════════════════════════ */
function MagBtn({href,children,dark,ext}:{href:string;children:React.ReactNode;dark?:boolean;ext?:boolean}){
  const ref=useRef<HTMLAnchorElement>(null);
  const [off,setOff]=useState({x:0,y:0});
  const mv=(e:React.MouseEvent)=>{if(!ref.current)return;const r=ref.current.getBoundingClientRect();setOff({x:(e.clientX-(r.left+r.width/2))*0.2,y:(e.clientY-(r.top+r.height/2))*0.2});};
  return(
    <a ref={ref} href={href} target={ext?"_blank":undefined} rel={ext?"noopener noreferrer":undefined}
      onMouseMove={mv} onMouseLeave={()=>setOff({x:0,y:0})}
      className={`${m} inline-flex items-center gap-2 px-5 py-3 text-[11px] tracking-[0.16em] uppercase border-2 border-[#101010] transition-colors duration-[120ms]`}
      style={{transform:`translate(${off.x}px,${off.y}px)`,transition:"transform 180ms cubic-bezier(0.2,0,0,1), background-color 120ms",
        background:dark?"#101010":"transparent",color:dark?"#F4F2EA":"#101010"}}>
      {children}
    </a>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAC WINDOW  ·  pinstripe chrome
═══════════════════════════════════════════════════════════════════════════ */
function MacWin({title,children}:{title:string;children:React.ReactNode}){
  return(
    <div className="border-2 border-[#101010] bg-[#F4F2EA]" style={{boxShadow:"3px 3px 0 #101010"}}>
      <div className="flex items-center gap-[5px] px-2 h-[20px] border-b-2 border-[#101010]"
        style={{background:"repeating-linear-gradient(90deg,#E0DDD4 0,#E0DDD4 1px,#D4D1C8 1px,#D4D1C8 2px)"}}>
        <div className="w-[11px] h-[11px] border border-[#101010] bg-[#F4F2EA] flex items-center justify-center shrink-0">
          <div className="w-[5px] h-[5px] bg-[#101010]"/></div>
        <span className={`${m} flex-1 text-center text-[10px] font-bold tracking-[0.04em] truncate text-[#101010]`}>{title}</span>
        <div className="w-[11px] h-[11px] border border-[#101010] bg-[#F4F2EA] shrink-0"/>
      </div>
      {children}
      <div className="h-[14px] border-t-2 border-[#101010] bg-[#E9E5DA] flex">
        <div className="w-[14px] border-r border-[#101010] flex items-center justify-center shrink-0"><span className={`${m} text-[7px] text-[#6B6660]`}>◂</span></div>
        <div className="flex-1 relative"><div className="absolute left-1/4 top-0 bottom-0 w-1/3 bg-[#D8D4C9] border-x border-[#C5C1B8]"/></div>
        <div className="w-[14px] border-l border-[#101010] flex items-center justify-center shrink-0"><span className={`${m} text-[7px] text-[#6B6660]`}>▸</span></div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DRAGGABLE WINDOW
═══════════════════════════════════════════════════════════════════════════ */
function DragWin({title,children,dp,zIdx,onFocus,w=260}:{title:string;children:React.ReactNode;dp:{x:number;y:number};zIdx:number;onFocus:()=>void;w?:number}){
  const [pos,setPos]=useState(dp);
  const drag=useRef({on:false,ox:0,oy:0,px:0,py:0});
  useEffect(()=>{
    const mv=(e:MouseEvent)=>{if(!drag.current.on)return;setPos({x:drag.current.px+e.clientX-drag.current.ox,y:drag.current.py+e.clientY-drag.current.oy});};
    const up=()=>{drag.current.on=false;};
    window.addEventListener("mousemove",mv); window.addEventListener("mouseup",up);
    return()=>{window.removeEventListener("mousemove",mv);window.removeEventListener("mouseup",up);};
  },[]);
  return(
    <div className="absolute select-none" style={{left:pos.x,top:pos.y,zIndex:zIdx,width:w}} onClick={onFocus}>
      <div className="border-2 border-[#101010] bg-[#F4F2EA]" style={{boxShadow:"3px 3px 0 #101010"}}>
        <div className="flex items-center gap-[5px] px-2 h-[20px] border-b-2 border-[#101010] cursor-grab active:cursor-grabbing"
          style={{background:"repeating-linear-gradient(90deg,#E0DDD4 0,#E0DDD4 1px,#D4D1C8 1px,#D4D1C8 2px)"}}
          onMouseDown={e=>{e.preventDefault();drag.current={on:true,ox:e.clientX,oy:e.clientY,px:pos.x,py:pos.y};onFocus();}}>
          <div className="w-[11px] h-[11px] border border-[#101010] bg-[#F4F2EA] flex items-center justify-center shrink-0">
            <div className="w-[5px] h-[5px] bg-[#101010]"/></div>
          <span className={`${m} flex-1 text-center text-[10px] font-bold truncate text-[#101010]`}>{title}</span>
          <div className="w-[11px] h-[11px] border border-[#101010] bg-[#F4F2EA] shrink-0"/>
        </div>
        {children}
        <div className="h-[14px] border-t-2 border-[#101010] bg-[#E9E5DA]"/>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   STAMP  ·  slams into view on scroll
═══════════════════════════════════════════════════════════════════════════ */
function Stamp({text,color="#8D2F2F",angle=-4}:{text:string;color?:string;angle?:number}){
  const [on,setOn]=useState(false);const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{const obs=new IntersectionObserver(([e])=>{if(e.isIntersecting){setOn(true);obs.disconnect();}},{threshold:0.5});if(ref.current)obs.observe(ref.current);return()=>obs.disconnect();},[]);
  return(
    <div ref={ref} className={`${m} inline-block border-2 px-3 py-[4px] text-[10px] tracking-[0.22em] uppercase pointer-events-none`}
      style={{borderColor:color,color,transform:on?`rotate(${angle}deg) scale(1)`:`rotate(${angle}deg) scale(2.4)`,opacity:on?1:0,transition:"transform 260ms cubic-bezier(0.2,0,0,1), opacity 80ms"}}>
      {text}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   CUSTOM CURSOR
═══════════════════════════════════════════════════════════════════════════ */
function CustomCursor(){
  const [over,setOver]=useState(false);
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    let x=-200,y=-200,raf=0,pending=false;
    const apply=()=>{ pending=false; const el=ref.current; if(el) el.style.transform=`translate(${x-1}px,${y-1}px)`; };
    const mv=(e:MouseEvent)=>{ x=e.clientX; y=e.clientY; if(!pending){ pending=true; raf=requestAnimationFrame(apply); } };
    const en=(e:Event)=>{if((e.target as Element).closest("a,button"))setOver(true);};
    const lv=(e:Event)=>{if((e.target as Element).closest("a,button"))setOver(false);};
    document.addEventListener("mousemove",mv,{passive:true});document.addEventListener("mouseover",en,{passive:true});document.addEventListener("mouseout",lv,{passive:true});
    return()=>{cancelAnimationFrame(raf);document.removeEventListener("mousemove",mv);document.removeEventListener("mouseover",en);document.removeEventListener("mouseout",lv);};
  },[]);
  return(
    <div ref={ref} className="hidden lg:block fixed top-0 left-0 pointer-events-none z-[9999]" style={{transform:"translate(-200px,-200px)"}}>
      <svg width="22" height="26" viewBox="0 0 22 26" fill="none" aria-hidden>
        {over?<><rect x="4" y="1" width="14" height="24" fill="#F4F2EA" stroke="#101010" strokeWidth="1.5"/><rect x="8" y="9" width="6" height="4" fill="#101010"/></>
          :<><path d="M2 0 L2 20 L6 15 L9 22 L12 21 L9 14 L16 14 Z" fill="#F4F2EA"/><path d="M2 0 L2 20 L6 15 L9 22 L12 21 L9 14 L16 14 Z" fill="none" stroke="#101010" strokeWidth="1.5"/></>}
      </svg>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   HARDWARE PANEL WRAPPER  ·  image-4 aesthetic
═══════════════════════════════════════════════════════════════════════════ */
function HwPanel({title,code="",accent="#101010",children}:{title:string;code?:string;accent?:string;children:React.ReactNode}){
  return(
    <div className="border-2 border-[#101010] bg-[#F4F2EA]" style={{boxShadow:"4px 4px 0 #101010"}}>
      <div className="flex items-center justify-between border-b-2 border-[#101010] px-3 py-[5px] bg-[#E9E5DA]">
        <div className="flex items-center gap-2">
          <div className="w-[7px] h-[7px] border border-[#101010]" style={{background:accent}}/>
          <span className={`${m} text-[10px] tracking-[0.18em] font-bold text-[#101010]`}>{title}</span>
        </div>
        {code&&<span className={`${m} text-[9px] text-[#6B6660]`}>{code}</span>}
      </div>
      {children}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   NAV
═══════════════════════════════════════════════════════════════════════════ */
function Nav(){
  const [open,setOpen]=useState(false);
  const {meta}=useVH();
  const links=[["001","#signal"],["002","#cabinet"],["003","#desktop"],["004","#terminal"],["999","https://github.com/nenticul/VisibleHand"]];
  return(
    <nav className="fixed top-0 left-0 right-0 z-50 bg-[#F4F2EA] border-b-2 border-[#101010]" style={{height:44}}>
      <div className="max-w-[1440px] mx-auto px-6 md:px-12 h-full flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className={`${m} text-[12px] font-bold tracking-[0.2em] text-[#101010]`}>VISIBLEHAND</span>
          <span className={`${m} hidden sm:flex items-center gap-[5px] text-[8px] tracking-[0.14em] border border-[#101010] px-[6px] py-[2px] text-[#101010]`} title={`data source: ${API_BASE}`}>
            <span style={{width:6,height:6,borderRadius:9,background:meta.live?"#4A6840":"#A08A54",boxShadow:meta.live?"0 0 5px #4A6840":"none",display:"inline-block"}}/>
            {meta.live?`LIVE${meta.asOf?` · ${meta.asOf}`:""}`:"SNAPSHOT"}
          </span>
        </div>
        <div className={`${m} hidden md:flex border-l-2 border-[#101010]`}>
          {links.map(([n,h])=>(
            <a key={n} href={h} target={h.startsWith("http")?"_blank":undefined} rel={h.startsWith("http")?"noopener noreferrer":undefined}
              className="flex items-center px-5 h-[44px] border-r-2 border-[#101010] text-[10px] tracking-[0.14em] text-[#101010] hover:bg-[#101010] hover:text-[#F4F2EA] transition-colors duration-[100ms]">
              {n}
            </a>
          ))}
        </div>
        <button className={`${m} md:hidden text-[10px] tracking-[0.1em] px-3 py-1 border-2 border-[#101010]`}
          onClick={()=>setOpen(o=>!o)} aria-label="menu">{open?"CLOSE":"INDEX"}</button>
      </div>
      {open&&(
        <div className={`${m} md:hidden bg-[#F4F2EA] border-t-2 border-[#101010] px-6 py-4`}>
          {links.map(([n,h])=>(
            <a key={n} href={h} className="flex items-center gap-4 py-3 border-b border-[#D8D4C9] last:border-0 text-[11px] tracking-[0.12em] text-[#101010]" onClick={()=>setOpen(false)}>
              <span className="text-[#6B6660]">{n}</span>
            </a>
          ))}
        </div>
      )}
    </nav>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   HERO  ·  physics title floating above terrain
═══════════════════════════════════════════════════════════════════════════ */
function Hero(){
  const {meta}=useVH();
  return(
    <section id="top" className="relative min-h-screen overflow-hidden bg-[#F4F2EA]"
      style={{backgroundImage:"linear-gradient(#D8D4C925 1px,transparent 1px),linear-gradient(90deg,#D8D4C925 1px,transparent 1px)",backgroundSize:"40px 40px"}}>
      <TerrainCanvas opacity={0.5}/>
      <div className="absolute inset-0 pointer-events-none" style={{background:"linear-gradient(to bottom,#F4F2EA 0%,transparent 14%,transparent 78%,#F4F2EA 100%)"}}/>
      <div className="relative max-w-[1440px] mx-auto px-6 md:px-12 pt-[60px] pb-16 min-h-screen flex flex-col">
        {/* ASCII art title */}
        <div className="mb-6 md:mb-8">
          <AsciiTitle/>
        </div>
        {/* Content */}
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-8 lg:gap-12 mt-auto">
          <div>
            <div className={`${m} grid grid-cols-3 border-2 border-[#101010] mb-6`} style={{boxShadow:"4px 4px 0 #101010"}}>
              {[[`${meta.scored ?? 44}`,"COUNTRIES"],["25+","YEARS"],["DAILY","UPDATES"]].map(([n,l])=>(
                <div key={l} className="px-4 py-4 border-r-2 border-[#101010] last:border-0">
                  <div className="text-[28px] md:text-[36px] font-black leading-none text-[#101010]">{n}</div>
                  <div className="text-[9px] tracking-[0.14em] text-[#6B6660] mt-1">{l}</div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap gap-3">
              <MagBtn href="https://github.com/nenticul/VisibleHand" dark ext>OPEN REPOSITORY →</MagBtn>
              <MagBtn href="#terminal">VIEW API SPECIMEN</MagBtn>
            </div>
          </div>
          <div className="lg:sticky lg:top-[64px]"><SignalFeed/></div>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   TICKER
═══════════════════════════════════════════════════════════════════════════ */
function Ticker(){
  const {files:FILES}=useVH();
  const TICK=Object.entries(FILES).map(([c,f])=>`${c}  ${f.score.toFixed(1)}  ${f.level}`).join("  ·  ")+"  ·  ";
  return(
    <div className="border-t-2 border-b-2 border-[#101010] bg-[#101010] overflow-hidden">
      <div className="flex" style={{animation:"vhTick 44s linear infinite"}}>
        <div className={`${m} text-[10px] tracking-[0.1em] uppercase py-[7px] whitespace-nowrap px-4`}>
          {(TICK+TICK).split("  ·  ").map((seg,i)=>{const code=seg.trim().split(/\s+/)[0]??"";const f=FILES[code];
            return <span key={i} style={{color:f?LVL_INK[f.level]:"#D8D4C9"}} className="mr-6">{seg}</span>;
          })}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SIGNAL MODULE  ·  hardware panel + VU meters (image-4 aesthetic)
═══════════════════════════════════════════════════════════════════════════ */
/* Approx. lat/long (deg) for the countries the API scores — used to place live
   risk markers on the rotating globe. */
const GEO:Record<string,[number,number]>={
  ARG:[-34,-64], BRA:[-10,-52], CHN:[35,103], COL:[4,-73], EGY:[27,30],
  GHA:[8,-1], IND:[22,79], IDN:[-2,118], IRN:[32,53], KEN:[0,38],
  MEX:[23,-102], NGA:[10,8], PAK:[30,70], PER:[-10,-76], PHL:[13,122],
  RUS:[61,100], TUR:[39,35], UKR:[49,32], USA:[40,-100], VEN:[7,-66],
  ZAF:[-29,24], ZWE:[-19,29],
};
/* risk band → ASCII glyph (denser = higher risk); pure black on white. */
const GLYPH:Record<Level,string>={LOW:"·",WATCH:"+",ELEVATED:"o",HIGH:"O",SEVERE:"#"};

/* Rotating ASCII world drawn to ONE <canvas>: a faint graticule sphere (single
   GPU layer, ~1k fillText/frame) with live country markers projected from real
   lat/long onto the front hemisphere and glyphed by risk band. White terminal,
   black ASCII. Gated by IntersectionObserver + visibility + reduced-motion so it
   never spins off-screen. */
const AsciiGlobe=memo(function AsciiGlobe(){
  const {files:FILES}=useVH();
  const ref=useRef<HTMLCanvasElement>(null);
  const filesRef=useRef(FILES); filesRef.current=FILES;
  useEffect(()=>{
    const canvas=ref.current; if(!canvas) return;
    const ctx=canvas.getContext("2d"); if(!ctx) return;
    const reduce=window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const LAT_STEP=20, LON_STEP=20, DEG=Math.PI/180;

    let W=0,H=0,Rp=0,fs=0,cw=0,chh=0;
    type Cell={px:number;py:number;nx:number;ny:number;nz:number;limb:boolean};
    let cells:Cell[]=[];
    const layout=()=>{
      const dpr=window.devicePixelRatio||1;
      const availW=canvas.parentElement?.clientWidth||360;
      W=availW; H=Math.max(300,Math.min(440,Math.round(availW*0.86)));
      fs=Math.max(9,Math.min(14,W/40));
      cw=fs*0.6; chh=fs*1.06;
      Rp=Math.min(W,H)*0.43;
      canvas.style.width=W+"px"; canvas.style.height=H+"px";
      canvas.width=Math.round(W*dpr); canvas.height=Math.round(H*dpr);
      ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.textAlign="center"; ctx.textBaseline="middle";
      // Precompute every cell that lands inside the projected disc (rotation-invariant).
      cells=[];
      const cols=Math.floor(W/cw), rows=Math.floor(H/chh);
      const ox=(W-cols*cw)/2, oy=(H-rows*chh)/2;
      for(let r=0;r<rows;r++) for(let c=0;c<cols;c++){
        const px=ox+(c+0.5)*cw, py=oy+(r+0.5)*chh;
        const nx=(px-W/2)/Rp, ny=(H/2-py)/Rp;     // ny flipped so north is up
        const rr=nx*nx+ny*ny;
        if(rr>1) continue;
        cells.push({px,py,nx,ny,nz:Math.sqrt(1-rr),limb:rr>0.9});
      }
    };
    layout();

    let a=0, last=0, running=false, visible=true, raf=0;
    const draw=(time:number)=>{
      // ~22fps cap — a slow, legible rotation that stays cheap.
      if(time-last>=45){
        last=time; a=time*0.00018;          // ~35s per revolution
        const cosA=Math.cos(a), sinA=Math.sin(a);
        ctx.clearRect(0,0,W,H);
        ctx.fillStyle="#FFFFFF"; ctx.fillRect(0,0,W,H);
        ctx.font=`${fs}px 'JetBrains Mono', ui-monospace, monospace`;
        // graticule + limb
        for(let i=0;i<cells.length;i++){
          const g=cells[i]!;
          if(g.limb){ ctx.fillStyle="rgba(16,16,16,0.5)"; ctx.fillText("·",g.px,g.py); continue; }
          const wx=g.nx*cosA-g.nz*sinA, wy=g.ny, wz=g.nx*sinA+g.nz*cosA;
          const latD=Math.asin(wy<-1?-1:wy>1?1:wy)/DEG;
          const lonD=Math.atan2(wx,wz)/DEG;
          const dLat=Math.abs(latD-LAT_STEP*Math.round(latD/LAT_STEP));
          const dLon=Math.abs(lonD-LON_STEP*Math.round(lonD/LON_STEP));
          const onLat=dLat<2.4, onLon=dLon<2.4 && Math.abs(latD)<74;
          if(!onLat && !onLon) continue;
          ctx.fillStyle=`rgba(16,16,16,${0.18+g.nz*0.18})`;
          ctx.fillText(onLat&&onLon?"+":"·",g.px,g.py);
        }
        // live country markers (front hemisphere only)
        const F=filesRef.current;
        ctx.font=`${fs*1.05}px 'JetBrains Mono', ui-monospace, monospace`;
        for(const code in GEO){
          const f=F[code]; if(!f) continue;
          const [latd,lond]=GEO[code]!;
          const lat=latd*DEG, lon=lond*DEG;
          const wx=Math.cos(lat)*Math.sin(lon), wy=Math.sin(lat), wz=Math.cos(lat)*Math.cos(lon);
          const vz=-wx*sinA+wz*cosA;
          if(vz<=0.04) continue;                 // hidden on the far side
          const vx=wx*cosA+wz*sinA;
          const px=W/2+vx*Rp, py=H/2-wy*Rp;
          ctx.fillStyle="#101010";
          ctx.fillText(GLYPH[f.level],px,py);
          if(f.level==="HIGH"||f.level==="SEVERE"){  // label the hotspots
            ctx.font=`${Math.max(7,fs*0.6)}px 'JetBrains Mono', ui-monospace, monospace`;
            ctx.fillStyle="rgba(16,16,16,0.7)";
            ctx.fillText(code,px+fs*0.95,py);
            ctx.font=`${fs*1.05}px 'JetBrains Mono', ui-monospace, monospace`;
          }
        }
      }
      if(running) raf=requestAnimationFrame(draw);
    };
    const start=()=>{ if(!running && !reduce){ running=true; raf=requestAnimationFrame(draw); } };
    const stop =()=>{ running=false; cancelAnimationFrame(raf); };
    if(reduce){ last=-9999; draw(performance.now()); }   // single static frame
    const ro=new ResizeObserver(()=>{ layout(); if(reduce){ last=-9999; draw(performance.now()); } });
    ro.observe(canvas.parentElement||canvas);
    const io=new IntersectionObserver(([e])=>{ visible=e.isIntersecting; (visible&&!document.hidden)?start():stop(); },{threshold:0});
    if(!reduce) io.observe(canvas);
    const onVis=()=>{ document.hidden?stop():(visible&&start()); };
    document.addEventListener("visibilitychange",onVis);
    return()=>{ stop(); ro.disconnect(); io.disconnect(); document.removeEventListener("visibilitychange",onVis); };
  },[]);
  return <canvas ref={ref} aria-label="Rotating world risk globe" role="img" className="select-none block" style={{display:"block"}}/>;
});

/* White terminal housing the ASCII globe — same hardware framing as HwPanel but a
   clean white interior, per the “white terminal / black ASCII” brief. */
function GlobeTerminal(){
  const {files:FILES,meta}=useVH();
  const n=Object.keys(FILES).length;
  return(
    <div className="border-2 border-[#101010] bg-white flex flex-col" style={{boxShadow:"4px 4px 0 #101010"}}>
      <div className="flex items-center justify-between border-b-2 border-[#101010] px-3 py-[5px] bg-[#E9E5DA]">
        <div className="flex items-center gap-2">
          <div className="w-[7px] h-[7px] border border-[#101010]" style={{background:"#2F5F5F"}}/>
          <span className={`${m} text-[10px] tracking-[0.18em] font-bold text-[#101010]`}>WORLD RISK GLOBE</span>
        </div>
        <span className={`${m} text-[9px] text-[#6B6660]`}>ASCII · {meta.live?"● LIVE":"SNAPSHOT"}</span>
      </div>
      <div className="bg-white flex-1 flex items-center justify-center overflow-hidden">
        <AsciiGlobe/>
      </div>
      <div className={`${m} flex items-center justify-between flex-wrap gap-x-4 gap-y-1 border-t-2 border-[#101010] px-3 py-2 bg-white text-[8px] tracking-[0.08em] text-[#6B6660]`}>
        <span>{n} NATIONS · LIVE FROM /risk/compare</span>
        <span className="text-[#101010]">· LOW&nbsp;&nbsp;+ WATCH&nbsp;&nbsp;o ELEV&nbsp;&nbsp;O HIGH&nbsp;&nbsp;# SEVERE</span>
      </div>
    </div>
  );
}

function SignalModule(){
  const {files:FILES,meta}=useVH();
  const top=Object.entries(FILES).sort((a,b)=>b[1].score-a[1].score).slice(0,16);
  return(
    <section id="signal" className="border-t-2 border-[#101010] py-14 bg-[#F4F2EA]">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12">
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-6">
          <div>
            <div className={`${m} text-[9px] tracking-[0.18em] text-[#6B6660] mb-1`}>001 · SIGNAL DESK</div>
            <div className="font-['Inter',sans-serif] font-black uppercase leading-none text-[#101010]" style={{fontSize:"clamp(20px,3vw,32px)"}}>GLOBAL RISK MONITOR</div>
          </div>
          <div className={`${m} flex items-center gap-2 text-[9px] tracking-[0.12em] text-[#6B6660] self-start sm:self-end`}>
            <span style={{width:7,height:7,borderRadius:9,background:meta.live?"#4A6840":"#A08A54",boxShadow:meta.live?"0 0 5px #4A6840":"none",display:"inline-block"}}/>
            {meta.live?`LIVE${meta.asOf?` · ${meta.asOf}`:""}`:"SNAPSHOT"}
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-4 mb-4 items-stretch">
          <GlobeTerminal/>
          <HwPanel title="LIVE SIGNAL FEED" code="" accent="#4A6840">
            <div className="p-2"><SignalFeed/></div>
          </HwPanel>
        </div>
        <div className="mb-4">
          <HwPanel title="RISK CHANNEL STRIP" code="" accent="#8D2F2F">
            <div className="p-4">
              <div className="flex flex-wrap gap-[6px]">
                {top.map(([code])=><VUMeter key={code} code={code}/>)}
              </div>
              <div className={`${m} flex justify-between text-[8px] mt-4 pt-3 border-t border-[#D8D4C9] text-[#6B6660]`}>
                <span>0</span><span>25</span><span>50</span><span>75</span><span>100</span>
              </div>
            </div>
          </HwPanel>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <HwPanel title="RISK MAGNITUDE" code="" accent="#A08A54">
            <div className="p-4">
              {Object.entries(FILES).sort((a,b)=>b[1].score-a[1].score).slice(0,11).map(([c,f])=>(
                <AnimBar key={c} score={f.score} label={c} color={LVL_INK[f.level]}/>
              ))}
            </div>
          </HwPanel>
          <HwPanel title="7-DAY DELTA" code="" accent="#2F5F5F">
            <div className="p-4">
              {Object.entries(FILES).sort((a,b)=>Math.abs(b[1].delta)-Math.abs(a[1].delta)).slice(0,11).map(([c,f])=>(
                <div key={c} className={`${m} flex items-baseline gap-3 text-[12px] py-[2px]`}>
                  <span className="w-7 shrink-0 text-[#6B6660]">{c}</span>
                  <span className="flex-1 text-[10px]" style={{color:f.delta>0?"#8D2F2F":f.delta<0?"#4A6840":"#A09A8E"}}>{f.delta>0?"▲":f.delta<0?"▼":"→"} {Math.abs(f.delta).toFixed(1)}</span>
                  <span className="tabular-nums text-[#101010]">{f.score.toFixed(1)}</span>
                </div>
              ))}
            </div>
          </HwPanel>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DRAWER CABINET  ·  animated filing drawer + country index
═══════════════════════════════════════════════════════════════════════════ */
const CAB=[
  {s:"A",rows:[["AFG","001"],["AGO","002"],["ALB","003"],["ARG","004"],["ARM","005"],["AUS","006"]]},
  {s:"B",rows:[["BDI","007"],["BEL","008"],["BFA","009"],["BGD","010"],["BOL","011"],["BRA","012"]]},
  {s:"C",rows:[["CAN","013"],["CHL","014"],["CHN","015"],["COL","016"]]},
  {s:"E",rows:[["ECU","017"],["EGY","018"],["ETH","019"],["ESP","020"]]},
  {s:"G",rows:[["GAB","021"],["GBR","022"],["GHA","023"],["GRC","024"]]},
  {s:"I",rows:[["IDN","025"],["IND","026"],["IRN","027"],["IRQ","028"]]},
  {s:"M",rows:[["MAR","029"],["MEX","030"],["MWI","031"],["MOZ","032"]]},
  {s:"N",rows:[["NAM","033"],["NER","034"],["NGA","035"],["NIC","036"]]},
  {s:"P",rows:[["PAK","037"],["PAN","038"],["PER","039"],["PHL","040"]]},
  {s:"R",rows:[["ROU","041"],["RUS","042"],["RWA","043"]]},
  {s:"T",rows:[["TCD","044"],["THA","045"],["TUN","046"],["TUR","047"]]},
  {s:"U",rows:[["UGA","048"],["UKR","049"],["USA","050"],["UZB","051"]]},
  {s:"V",rows:[["VEN","052"],["VNM","053"]]},
  {s:"Z",rows:[["ZAF","054"],["ZMB","055"],["ZWE","056"]]},
] as const;

function Cabinet(){
  const {files:FILES,meta}=useVH();
  const [open,setOpen]=useState(false);
  const [active,setActive]=useState<string|null>(null);
  const af=active?FILES[active]:null;

  return(
    <section id="cabinet" className="border-t-2 border-[#101010] py-14 bg-[#E9E5DA]">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12">
        <div className="grid grid-cols-1 xl:grid-cols-[1fr_300px] gap-8 items-start">

          {/* Drawer unit */}
          <div>
            {/* Depth layers */}
            <div className="relative">
              <div className="absolute inset-0 translate-x-[6px] translate-y-[6px] border-2 border-[#C5C1B8] bg-[#C5C1B8]"/>
              <div className="absolute inset-0 translate-x-[3px] translate-y-[3px] border-2 border-[#C5C1B8] bg-[#CCCAB8]"/>
              <div className="relative border-2 border-[#101010]" style={{boxShadow:"4px 4px 0 #101010"}}>

                {/* ── DRAWER FACE (clickable) ── */}
                <button
                  className="w-full flex items-center bg-[#E9E5DA] border-b-2 border-[#101010] px-5 py-0 hover:bg-[#E0DDD4] transition-colors duration-[120ms]"
                  style={{height:56}}
                  onClick={()=>setOpen(o=>!o)}
                  aria-expanded={open}
                  aria-label={open?"Close country index":"Open country index"}
                >
                  {/* Left label */}
                  <div className={`${m} text-left`}>
                    <div className="text-[9px] tracking-[0.14em] text-[#6B6660]">002</div>
                    <div className="text-[11px] font-bold tracking-[0.1em] text-[#101010]">COUNTRY INDEX</div>
                  </div>
                  {/* Centre handle */}
                  <div className="flex-1 flex items-center justify-center gap-2">
                    <div className="h-[2px] w-12 bg-[#B8B4AB]"/>
                    <div className="w-7 h-4 border-2 border-[#101010] bg-[#D8D4C9] flex items-center justify-center" style={{boxShadow:"1px 1px 0 #101010"}}>
                      <div className="w-3 h-[2px] bg-[#101010]"/>
                    </div>
                    <div className="h-[2px] w-12 bg-[#B8B4AB]"/>
                  </div>
                  {/* Right meta + arrow */}
                  <div className={`${m} text-right flex items-center gap-4`}>
                    <div>
                      <div className="text-[9px] tracking-[0.1em] text-[#6B6660]">{meta.scored?`${meta.scored} FILES`:"PUBLIC INDEX"}</div>
                      <div className="text-[9px] tracking-[0.08em] text-[#A08A54]">{open?"OPEN":"CLOSED"}</div>
                    </div>
                    <span className={`text-[#101010] text-[16px] transition-transform duration-[380ms] ${open?"rotate-90":""}`}
                      style={{transitionTimingFunction:"cubic-bezier(0.2,0,0,1)"}}>▶</span>
                  </div>
                </button>

                {/* ── DRAWER CONTENTS (slide open) ── */}
                <div
                  className="overflow-hidden transition-all duration-[380ms]"
                  style={{maxHeight:open?1800:0,transitionTimingFunction:"cubic-bezier(0.2,0,0,1)"}}
                >
                  <div className="bg-[#D8D4C9] p-[5px]">
                    <div className="h-3 bg-[#C5C1B8] border-2 border-[#101010] mb-[3px]"/>
                    {CAB.map(sec=>{
                      const pairs:(readonly[string,string])[][]=[];
                      for(let i=0;i<sec.rows.length;i+=2)pairs.push(sec.rows.slice(i,i+2) as any);
                      return(
                        <div key={sec.s}>
                          <div className="flex items-center bg-[#101010] text-[#F4F2EA] mt-[2px]">
                            <div className={`${m} flex items-center gap-2 px-3 py-[4px] border-r border-[#2A2926] shrink-0`}>
                              <span className="text-[13px] font-black w-4">{sec.s}</span>
                              <span className="text-[10px] text-[#D8D4C9]">{String(sec.rows.length).padStart(3,"0")}</span>
                            </div>
                            <div className="flex-1"/>
                          </div>
                          {pairs.map((pair,pi)=>(
                            <div key={pi} className="flex gap-[2px] mt-[2px]">
                              {pair.map(([code,num])=>{const f=FILES[code];const isA=active===code;return(
                                <button key={code}
                                  className={`flex-1 flex items-center gap-3 px-3 py-[5px] border border-[#B8B4AB] cursor-pointer transition-all duration-[200ms] ${isA?"translate-x-2":""}`}
                                  style={{background:isA?"#101010":"#F4F2EA",borderColor:isA?"#101010":"#B8B4AB",boxShadow:"1px 1px 0 #C0BCB3",transitionTimingFunction:"cubic-bezier(0.2,0,0,1)"}}
                                  onMouseEnter={e=>{if(!isA){(e.currentTarget as HTMLElement).style.transform="translateX(6px)";(e.currentTarget as HTMLElement).style.background="#E9E5DA";}}}
                                  onMouseLeave={e=>{if(!isA){(e.currentTarget as HTMLElement).style.transform="";(e.currentTarget as HTMLElement).style.background="#F4F2EA";}}}
                                  onClick={()=>setActive(c=>c===code?null:code)} aria-pressed={isA}>
                                  <span className={`${m} text-[11px] font-semibold tracking-[0.06em] w-8 shrink-0`} style={{color:isA?"#F4F2EA":"#101010"}}>{code}</span>
                                  {f&&<span className={`${m} text-[9px] shrink-0 tabular-nums`} style={{color:isA?"#F4F2EA":LVL_INK[f.level]}}>{f.score.toFixed(1)}</span>}
                                  <span className={`${m} text-[9px] flex-1 text-right`} style={{color:isA?"#C5C1B8":"#A08A54"}}>{num}</span>
                                </button>
                              );})}
                              {pair.length===1&&<div className="flex-1"/>}
                            </div>
                          ))}
                        </div>
                      );
                    })}
                    <div className="mt-[3px] bg-[#B8B4AB] border-2 border-[#101010] px-3 py-[3px]">
                      <span className={`${m} text-[9px] tracking-[0.1em] text-[#6B6660]`}>VISIBLEHAND PUBLIC INDEX · VH-000</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Country file card */}
          <div className="xl:sticky xl:top-[64px]">
            {af&&active?(
              <div key={active} style={{animation:"vhFade 120ms ease-out"}}>
                <MacWin title={`FILE VH-${active}`}>
                  <div className={`${m} p-4`}>
                    <div className="text-[18px] font-bold tracking-[0.04em] mb-3 text-[#101010]">{af.name.toUpperCase()}</div>
                    <div className="grid grid-cols-2 gap-4 mb-4 border-t border-[#D8D4C9] pt-3">
                      <div>
                        <div className="text-[9px] tracking-[0.1em] text-[#6B6660] mb-1">RISK SCORE</div>
                        <div className="text-[42px] font-black leading-none tabular-nums" style={{color:LVL_INK[af.level]}}>{af.score.toFixed(1)}</div>
                      </div>
                      <div>
                        <div className="text-[9px] tracking-[0.1em] text-[#6B6660] mb-1">STATUS</div>
                        <div className="text-[12px] font-semibold" style={{color:LVL_INK[af.level]}}>{af.level}</div>
                        <div className="text-[11px] mt-2" style={{color:LVL_INK[af.level]}}>{bar(af.score,11)}</div>
                        <div className="text-[9px] mt-2" style={{color:af.delta>0?"#8D2F2F":af.delta<0?"#4A6840":"#A09A8E"}}>7D: {af.delta>0?`+${af.delta.toFixed(1)}`:af.delta.toFixed(1)}</div>
                      </div>
                    </div>
                    <div className="border-t border-[#D8D4C9] pt-3">
                      <div className="text-[9px] tracking-[0.12em] text-[#6B6660] mb-2">PRIMARY DRIVERS</div>
                      {af.drivers.map((d,i)=>(
                        <div key={d} className="flex gap-3 py-[5px] border-b border-[#E9E5DA] text-[11px]">
                          <span className="text-[#A08A54] w-4 shrink-0">0{i+1}</span>
                          <span className="uppercase tracking-[0.04em] text-[#101010]">{d}</span>
                        </div>
                      ))}
                    </div>
                    <button onClick={()=>setActive(null)}
                      className={`${m} mt-4 w-full border-2 border-[#101010] py-2 text-[10px] tracking-[0.1em] uppercase text-[#101010] hover:bg-[#101010] hover:text-[#F4F2EA] transition-all duration-[120ms]`}>
                      CLOSE FILE
                    </button>
                  </div>
                </MacWin>
              </div>
            ):(
              <div className={`${m} border-2 border-dashed border-[#D8D4C9] p-6 text-[10px] tracking-[0.12em] text-[#A08A54]`}>
                {open?"SELECT A FILE":"OPEN THE DRAWER"}<br/>
                <span className="text-[9px] text-[#D8D4C9]">{open?"click any tab ↑":"click the handle ←"}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAC DESKTOP  ·  image-2 draggable methodology windows
═══════════════════════════════════════════════════════════════════════════ */
function MacDesktop(){
  const {meta}=useVH();
  const W=meta.weights;
  const wf=(v:number|undefined,fb:string)=>(typeof v==="number"?v.toFixed(2):fb);
  const calib=meta.calibration
    ? `ROC-AUC ${meta.calibration.auc.toFixed(2)} · Brier ${meta.calibration.brier.toFixed(2)}`
    : "ROC-AUC 0.81 · Brier 0.14";
  const WINS=[
    {id:"ECON",title:"ECONOMIC SCORER",dp:{x:20,y:45},w:240,content:[["SOURCE","World Bank WDI"],["SOURCE","IMF WEO · BIS · ILO"],["WEIGHT",wf(W?.economic,"0.45")],["DRIVERS","GDP · inflation · fiscal · CA"]]},
    {id:"NLP", title:"NLP SIGNAL",     dp:{x:288,y:18},w:228,content:[["SOURCE","Central-bank text"],["MODEL","FinBERT + lexicon"],["WEIGHT",wf(W?.nlp,"0.20")],["DRIVERS","tone · hawkish / dovish"]]},
    {id:"POL", title:"POLITICAL",      dp:{x:155,y:240},w:238,content:[["SOURCE","GDELT · ACLED"],["WEIGHT",wf(W?.political,"0.25")],["DRIVERS","conflict · protests · escalation"]]},
    {id:"GOV", title:"GOVERNANCE",     dp:{x:418,y:155},w:228,content:[["SOURCE","V-Dem · WJP · FH"],["WEIGHT",wf(W?.governance,"0.10")],["DRIVERS","rule of law · corruption · press"]]},
    {id:"COMP",title:"COMPOSITE ENGINE",dp:{x:55,y:400},w:340,content:[["INPUTS","ECON + NLP + POL + GOV"],["OUTPUT","0–100 risk score"],["CALIB",calib],["REPO","github.com/nenticul/VisibleHand"]]},
  ];
  const [order,setOrder]=useState(WINS.map(w=>w.id));
  const focus=useCallback((id:string)=>setOrder(p=>[...p.filter(i=>i!==id),id]),[]);
  const zFor=(id:string)=>(order.indexOf(id)+1)*10;
  return(
    <section id="desktop" className="border-t-2 border-[#101010] py-0">
      <div className={`${m} flex items-center gap-5 px-4 h-[22px] border-b-2 border-[#101010] text-[10px] tracking-[0.06em] font-bold select-none`}
        style={{background:"repeating-linear-gradient(90deg,#E0DDD4 0,#E0DDD4 1px,#D4D1C8 1px,#D4D1C8 2px)"}}>
        <span className="text-[#8D2F2F]">●</span>
        {["File","Edit","View","Special"].map(i=><span key={i} className="cursor-default px-1 text-[#101010] hover:bg-[#101010] hover:text-[#F4F2EA] transition-colors duration-[100ms]">{i}</span>)}
        <span className="ml-auto text-[9px] text-[#6B6660]">METHODOLOGY DOSSIER · VH-020</span>
      </div>
      <div className="relative overflow-hidden bg-[#D8D4C9]" style={{height:620,backgroundImage:"radial-gradient(circle,#C0BCB380 1px,transparent 1px)",backgroundSize:"10px 10px"}}>
        <div className="absolute top-3 right-3 flex flex-col items-center gap-1 cursor-default">
          <div className="w-12 h-10 border-2 border-[#101010] bg-[#F4F2EA] flex flex-col items-center justify-center" style={{boxShadow:"2px 2px 0 #101010"}}>
            <div className="w-8 h-[2px] bg-[#101010] mb-[3px]"/><div className="w-8 h-[2px] bg-[#101010] mb-[3px]"/>
            <div className="w-2 h-2 border border-[#101010] rounded-full"/>
          </div>
          <span className={`${m} text-[8px] bg-[#101010] text-[#F4F2EA] px-1`}>VH ARCHIVE</span>
        </div>
        <div className="hidden md:block absolute inset-0">
          {WINS.map(win=>(
            <DragWin key={win.id} title={win.title} dp={win.dp} zIdx={zFor(win.id)} onFocus={()=>focus(win.id)} w={win.w}>
              <div className={`${m} text-[10px] p-3`}>
                {win.content.map(([k,v])=>(
                  <div key={k+v} className="flex gap-3 py-[4px] border-b border-[#E9E5DA] last:border-0">
                    <span className="text-[#A08A54] tracking-[0.08em] w-14 shrink-0">{k}</span>
                    <span className="text-[#101010]">{v}</span>
                  </div>
                ))}
              </div>
            </DragWin>
          ))}
        </div>
        <div className="md:hidden p-4 flex flex-col gap-3">
          {WINS.map(win=>(
            <MacWin key={win.id} title={win.title}>
              <div className={`${m} text-[10px] p-3`}>
                {win.content.map(([k,v])=>(<div key={k+v} className="flex gap-3 py-[4px] border-b border-[#E9E5DA] last:border-0"><span className="text-[#A08A54] w-14 shrink-0">{k}</span><span className="text-[#101010]">{v}</span></div>))}
              </div>
            </MacWin>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   API TERMINAL
═══════════════════════════════════════════════════════════════════════════ */
function ApiTerminal(){
  const {files:FILES,meta,sample}=useVH();
  const br=FILES["BRA"];
  const status=(sample&&sample.risk_level)||(br.level.charAt(0)+br.level.slice(1).toLowerCase());
  const drivers=(sample&&Array.isArray(sample.top_drivers)&&sample.top_drivers.length?sample.top_drivers:br.drivers).slice(0,3);
  const PY=`from visiblehand import Client\n\nc = Client()\ns = c.risk("BR")\n\nprint(s.composite)      # ${br.score.toFixed(1)}\nprint(s.risk_level)     # "${status}"\nprint(s.top_drivers)    # list[str]\nprint(c.history("BR"))  # list[HistoryPoint]`;
  const JSON_R=JSON.stringify({
    country: sample?.country ?? "BR",
    date: meta.asOf ?? new Date().toISOString().slice(0,10),
    composite: sample?.composite ?? br.score,
    risk_level: status,
    confidence: sample?.confidence ?? 0.9,
    top_drivers: drivers,
  }, null, 2);
  const [tab,setTab]=useState<"py"|"json">("py");
  const [typed,setTyped]=useState("");const[done,setDone]=useState(false);
  const src=tab==="py"?PY:JSON_R;
  useEffect(()=>{setTyped("");setDone(false);let i=0;const t=setInterval(()=>{i++;setTyped(src.slice(0,i));if(i>=src.length){setDone(true);clearInterval(t);}},9);return()=>clearInterval(t);},[tab,src]);
  return(
    <section id="terminal" className="border-t-2 border-[#101010] py-14 bg-[#F4F2EA]">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12">
        <div className={`${m} text-[9px] tracking-[0.18em] text-[#6B6660] mb-10 flex items-center gap-4 flex-wrap`}>
          <span>004</span><span className="text-[#D8D4C9]">·</span><span>API SPECIMEN</span>
          <span className="text-[#D8D4C9]">·</span><span>PUBLIC INTERFACE</span>
          <div className="ml-auto"><Stamp text="PUBLIC" color="#4A6840" angle={5}/></div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-6 items-start">
          <MacWin title={`RETRIEVAL SLIP · GET /risk/BR${meta.asOf?` · ${meta.asOf}`:""}`}>
            <div>
              <div className="flex border-b border-[#D8D4C9] px-3 pt-2 gap-2 bg-[#F4F2EA]">
                {(["py","json"] as const).map(t=>(
                  <button key={t} onClick={()=>setTab(t)}
                    className={`${m} text-[9px] tracking-[0.1em] uppercase px-2 py-1 border-b-2 transition-colors duration-[100ms]`}
                    style={{borderBottomColor:tab===t?"#101010":"transparent",color:tab===t?"#101010":"#6B6660"}}>
                    {t==="py"?"PYTHON SDK":"JSON"}
                  </button>
                ))}
              </div>
              <pre className={`${m} text-[12px] leading-[1.75] p-5 overflow-x-auto text-[#2A2926] min-h-[210px] bg-[#F4F2EA]`}>
                {typed}{!done&&<span className="animate-pulse text-[#8D2F2F]">▌</span>}
              </pre>
            </div>
          </MacWin>
          <div className={`${m} border-2 border-[#101010] text-[11px] bg-[#F4F2EA]`} style={{boxShadow:"4px 4px 0 #101010"}}>
            <div className="px-4 py-2 border-b-2 border-[#101010] bg-[#E9E5DA]">
              <div className="text-[9px] tracking-[0.14em] text-[#6B6660]">INTERFACE RECORD</div>
            </div>
            <div className="p-4">
              {[["FORMAT","Python SDK + REST"],["AUTH","None required"],["COVERAGE",meta.scored?`${meta.scored} countries`:"Open universe"],["HISTORY","2000 — present"],["CADENCE","Daily update"]].map(([k,v])=>(
                <div key={k} className="flex justify-between py-2 border-b border-[#E9E5DA] gap-4 last:border-0">
                  <span className="text-[#6B6660] tracking-[0.06em] shrink-0">{k}</span>
                  <span className="text-right text-[#101010]">{v}</span>
                </div>
              ))}
              <a href={`${API_BASE}/docs`} target="_blank" rel="noopener noreferrer"
                className={`${m} block mt-5 bg-[#8D2F2F] text-[#F4F2EA] px-4 py-3 text-[11px] tracking-[0.14em] uppercase hover:bg-[#732525] transition-colors duration-[120ms] text-center`}>
                TEST THE API ↗
              </a>
              <div className="grid grid-cols-2 gap-2 mt-2">
                <a href={`${API_BASE}/risk/BR`} target="_blank" rel="noopener noreferrer"
                  className={`${m} border-2 border-[#101010] px-2 py-2 text-[10px] tracking-[0.1em] uppercase text-[#101010] hover:bg-[#101010] hover:text-[#F4F2EA] transition-colors duration-[120ms] text-center`}>
                  RUN /risk/BR ↗
                </a>
                <a href="https://github.com/nenticul/VisibleHand" target="_blank" rel="noopener noreferrer"
                  className={`${m} border-2 border-[#101010] px-2 py-2 text-[10px] tracking-[0.1em] uppercase text-[#101010] hover:bg-[#101010] hover:text-[#F4F2EA] transition-colors duration-[120ms] text-center`}>
                  REPOSITORY ↗
                </a>
              </div>
              <div className={`${m} mt-3 text-[9px] tracking-[0.06em] text-[#A09A8E] text-center`}>
                interactive docs · runs in your browser
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   NUMBERS
═══════════════════════════════════════════════════════════════════════════ */
function Metric({value,dec,label,note}:{value:number;dec:number;label:string;note:string}){
  const [ref,val]=useCountUp(value,dec);
  return(
    <div className="p-5 md:p-8 border-r-2 border-b-2 border-[#101010] last:border-r-0 bg-[#F4F2EA]">
      <div className={`${m} text-[44px] md:text-[58px] font-black leading-none tabular-nums mb-1 text-[#101010]`}><span ref={ref}>{val.toFixed(dec)}</span></div>
      <div className={`${m} text-[10px] tracking-[0.1em] font-semibold uppercase mb-1 text-[#6B6660]`}>{label}</div>
      <div className={`${m} text-[10px] text-[#A08A54]`}>{note}</div>
    </div>
  );
}
function Numbers(){
  const {meta}=useVH();
  const cal=meta.calibration;
  return(
    <section className="border-t-2 border-[#101010] py-14 bg-[#E9E5DA]">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12">
        <div className="mb-10 flex items-center justify-between">
          <span className={`${m} text-[9px] tracking-[0.18em] text-[#6B6660]`}>VALIDATION RECORD</span>
          <Stamp text="VALIDATED" color="#8D2F2F" angle={-3}/>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 border-l-2 border-t-2 border-[#101010]">
          <Metric value={cal?cal.auc:1.0}       dec={2} label="ROC-AUC"          note="Heuristic crisis backtest"/>
          <Metric value={cal?cal.brier:0.07}    dec={2} label="Brier Score"      note="Probabilistic calibration"/>
          <Metric value={cal?cal.nEvents:99}    dec={0} label="Stress Events"    note="Out-of-sample validation"/>
          <Metric value={2000} dec={0} label="Backtest Start"   note="2000–2023 test window"/>
          <Metric value={meta.confidenceFloor??0.7} dec={2} label="Confidence Floor" note="Median file confidence"/>
          <Metric value={meta.scored??44} dec={0} label="Countries"        note="Live scored universe"/>
        </div>
        <div className="mt-8 border-l-2 border-[#101010] pl-4">
          <p className="font-['EB_Garamond',serif] italic text-[19px] text-[#2A2926] leading-[1.5]">
            "A risk score without a calibration record is an opinion, not a measurement."
          </p>
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SOURCES
═══════════════════════════════════════════════════════════════════════════ */
const SRCS=[
  ["WB-WDI","World Bank WDI","ECONOMIC","Development indicators"],["IMF-WEO","IMF World Economic Outlook","MACRO","Fiscal and macro forecasts"],
  ["BIS","BIS Statistics","FINANCIAL","Cross-border banking flows"],["ILO","ILOSTAT","LABOUR","Employment and labour data"],
  ["IMF-FSI","IMF Financial Soundness","FINANCIAL","Banking-system indicators"],["GDELT-2","GDELT 2.0","EVENTS","Global event database"],
  ["ACLED","ACLED","CONFLICT","Armed conflict event data"],["V-DEM","V-Dem Institute","GOVERNANCE","Varieties of democracy"],
  ["WJP","World Justice Project","GOVERNANCE","Rule of Law Index"],["TI-CPI","Transparency Intl","GOVERNANCE","Corruption Perceptions"],
  ["FH","Freedom House","GOVERNANCE","Freedom in the World"],["UCDP","UCDP","CONFLICT","Uppsala conflict program"],
];
function Sources(){
  return(
    <section className="border-t-2 border-[#101010] py-14 bg-[#F4F2EA]">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12">
        <div className={`${m} text-[9px] tracking-[0.18em] text-[#6B6660] mb-10`}>EVIDENCE SHELF</div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 border-l-2 border-t-2 border-[#101010]">
          {SRCS.map(([id,name,type,desc])=>(
            <div key={id} className={`${m} p-4 border-r-2 border-b-2 border-[#101010] bg-[#F4F2EA] hover:bg-[#101010] hover:text-[#F4F2EA] transition-colors duration-[120ms] group cursor-default`}>
              <div className="text-[9px] tracking-[0.1em] text-[#A08A54] group-hover:text-[#D8D4C9] mb-1 uppercase">{type}</div>
              <div className="text-[11px] font-semibold tracking-[0.04em] uppercase mb-1">{name}</div>
              <div className="text-[10px] text-[#6B6660] group-hover:text-[#D8D4C9]">{desc}</div>
            </div>
          ))}
        </div>
        <div className={`${m} mt-6 text-[12px] leading-[2] text-[#6B6660]`}>
          No proprietary analyst panel.  No hidden model feed.  No paywalled methodology.
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   VAULT
═══════════════════════════════════════════════════════════════════════════ */
function Vault(){
  const [open,setOpen]=useState(false);
  const ref=useRef<HTMLElement>(null);const fired=useRef(false);
  const cols=[1,2,4,6,8,9,8,7,6,5,4,2,1,2,4,6,5,3,2,1,2,3,2,1];
  useEffect(()=>{
    const obs=new IntersectionObserver(([e])=>{if(e.isIntersecting&&!fired.current){fired.current=true;setTimeout(()=>setOpen(true),280);}},{threshold:0.3});
    if(ref.current)obs.observe(ref.current);return()=>obs.disconnect();
  },[]);
  return(
    <section ref={ref} className="border-t-2 border-[#101010] py-14 bg-[#101010] text-[#F4F2EA]">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12">
        <div className={`${m} text-[9px] tracking-[0.18em] text-[#2A2926] mb-10`}>
          <span>999</span><span className="mx-4 text-[#1A1A1A]">·</span><span>REPOSITORY VAULT</span>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-10 items-start">
          <div>
            <button className="w-full flex items-center justify-between border-2 border-[#2A2926] px-5 py-4 hover:border-[#C8C4BA] transition-colors duration-[120ms] bg-[#0A0A0A]"
              onClick={()=>setOpen(o=>!o)} aria-expanded={open}>
              <span className={`${m} text-[11px] tracking-[0.12em] uppercase`}>DRAWER 999 — REPOSITORY</span>
              <span className={`text-[14px] transition-transform duration-[220ms] text-[#8D2F2F] ${open?"rotate-90":""}`} style={{transitionTimingFunction:"cubic-bezier(0.2,0,0,1)"}}>▶</span>
            </button>
            <div className="border-l-2 border-r-2 border-b-2 border-[#2A2926] overflow-hidden transition-all duration-[420ms]"
              style={{maxHeight:open?200:0,transitionTimingFunction:"cubic-bezier(0.2,0,0,1)"}}>
              <div className="grid grid-cols-4">
                {["README","SDK","API","SCORERS","CALIBRATION","TESTS","ISSUES","CHANGELOG"].map(f=>(
                  <div key={f} className={`${m} border-b border-r border-[#1A1A1A] px-4 py-4 hover:bg-[#111] transition-colors duration-[100ms]`}>
                    <div className="text-[9px] text-[#2A2926] mb-1">FILE</div>
                    <div className="text-[11px] tracking-[0.06em]">{f}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div>
            <div className="font-['Inter',sans-serif] font-black uppercase leading-[0.95] mb-6 text-[#F4F2EA]" style={{fontSize:"clamp(26px,4vw,42px)"}}>
              THE ARCHIVE<br/>IS NOT<br/>BEHIND A<br/>SALES FORM.
            </div>
            <div className="flex flex-col gap-3">
              <MagBtn href="https://github.com/nenticul/VisibleHand" dark ext>OPEN REPOSITORY →</MagBtn>
              <a href="https://github.com/nenticul/VisibleHand" target="_blank" rel="noopener noreferrer"
                className={`${m} border-2 border-[#2A2926] text-[#C8C4BA] px-5 py-3 text-[11px] tracking-[0.12em] uppercase hover:border-[#C8C4BA] transition-colors duration-[120ms] text-center`}>
                STAR THE PROJECT
              </a>
            </div>
          </div>
        </div>
        <div className="mt-16 flex gap-[3px] items-end pointer-events-none overflow-hidden" aria-hidden>
          {cols.map((h,i)=>(
            <div key={i} className="w-3 shrink-0 bg-[#1A1A1A]"
              style={{height:open?`${h*12}px`:"2px",transition:`height 500ms cubic-bezier(0.2,0,0,1) ${i*28}ms`}}/>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   FOOTER
═══════════════════════════════════════════════════════════════════════════ */
function Footer(){
  return(
    <footer className="border-t-2 border-[#101010] py-10 bg-[#F4F2EA]">
      <div className="max-w-[1440px] mx-auto px-6 md:px-12">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-8">
          <div className={`${m} text-[10px] tracking-[0.1em] leading-[2.2] text-[#6B6660] col-span-2 md:col-span-1`}>
            <div className="font-black text-[#101010] mb-1 text-[11px] tracking-[0.2em]">VISIBLEHAND</div>
            <div>PUBLIC ARCHIVE</div><div>FILE: VH-FOOTER</div><div>STATUS: OPEN</div><div>SOURCE: GITHUB</div>
          </div>
          {[["INDEX",["001 Signal","002 Archive","003 Method","999 Repo"]],["FILES",["BRA","EGY","PAK","RUS","USA"]],["RECORD",["Methodology","Calibration","API Specimen","Sources"]]].map(([title,items])=>(
            <div key={title as string}>
              <div className={`${m} text-[9px] tracking-[0.14em] text-[#6B6660] mb-2`}>{title as string}</div>
              {(items as string[]).map(it=><div key={it} className={`${m} text-[11px] py-[2px] text-[#2A2926]`}>{it}</div>)}
            </div>
          ))}
        </div>
        <div className="border-t-2 border-[#101010] pt-6 flex flex-col md:flex-row md:items-baseline md:justify-between gap-3">
          <p className="font-['EB_Garamond',serif] italic text-[15px] text-[#6B6660]">Made by Anes&nbsp;Tamtam</p>
          <p className={`${m} text-[10px] tracking-[0.08em] text-[#6B6660]`}>© VISIBLEHAND {new Date().getFullYear()} · OPEN SOURCE</p>
        </div>
      </div>
    </footer>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   APP
═══════════════════════════════════════════════════════════════════════════ */
export default function App(){
  useEffect(()=>{document.body.style.cursor="none";return()=>{document.body.style.cursor="";};}, []);
  return(
    <VHProvider>
    <div className="min-h-screen bg-[#F4F2EA] text-[#101010]" style={{fontFamily:"'Inter','Helvetica Neue',Arial,sans-serif",cursor:"none"}}>
      <style>{`
        html{scroll-behavior:smooth}
        html,body{overflow-x:clip;max-width:100%}
        @keyframes vhTick  { from{transform:translateX(0)} to{transform:translateX(-50%)} }
        @keyframes vhFade  { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
        @media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{transition:none!important;animation:none!important;}}
        ::-webkit-scrollbar{width:4px;height:4px}
        ::-webkit-scrollbar-track{background:transparent}
        ::-webkit-scrollbar-thumb{background:#D8D4C9}
        *{scrollbar-width:thin;scrollbar-color:#D8D4C9 transparent}
        a,button{cursor:none}
      `}</style>
      <CustomCursor/>
      <Nav/>
      <main style={{paddingTop:44}}>
        <Hero/>
        <Ticker/>
        <SignalModule/>
        <Cabinet/>
        <MacDesktop/>
        <ApiTerminal/>
        <Numbers/>
        <Sources/>
        <Vault/>
      </main>
      <Footer/>
    </div>
    </VHProvider>
  );
}
