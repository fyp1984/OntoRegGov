// 自写轻量 SVG 力导向（无第三方库）
const CLASS_COLOR = {
  Law:'#1B4FE4', Clause:'#5b83f0', Obligation:'#d99a16', Control:'#1a9e5c',
  DataAsset:'#d23b3b', EvidenceRequirement:'#7a5bd0', EvidenceRecord:'#8a93a6',
  CheckItem:'#0aa', Finding:'#d23b3b', KnowledgeGapProposal:'#e0679a', Assessment:'#333'
};
async function drawGraph() {
  const g = await fetch('/api/graph?root=law-jg24&depth=3').then(r=>r.json());
  const svg = document.getElementById('graph');
  svg.innerHTML = '';
  const W = svg.clientWidth || 900, H = 520;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  const nodes = g.nodes.map((n,i)=>({id:n.id, x:W/2+Math.cos(i)*120, y:H/2+Math.sin(i)*120, vx:0, vy:0}));
  const idx = Object.fromEntries(nodes.map((n,i)=>[n.id,i]));
  const edges = g.edges.filter(e=>idx[e.source]!=null&&idx[e.target]!=null)
    .map(e=>({s:idx[e.source], t:idx[e.target]}));
  // 简单力迭代
  for (let it=0; it<120; it++) {
    for (let i=0;i<nodes.length;i++){
      for (let j=i+1;j<nodes.length;j++){
        let dx=nodes[i].x-nodes[j].x, dy=nodes[i].y-nodes[j].y;
        let d=Math.hypot(dx,dy)||1; let f=9000/(d*d);
        nodes[i].vx+=dx/d*f; nodes[i].vy+=dy/d*f;
        nodes[j].vx-=dx/d*f; nodes[j].vy-=dy/d*f;
      }
    }
    edges.forEach(e=>{
      let dx=nodes[e.t].x-nodes[e.s].x, dy=nodes[e.t].y-nodes[e.s].y;
      nodes[e.s].vx+=dx*0.02; nodes[e.s].vy+=dy*0.02;
      nodes[e.t].vx-=dx*0.02; nodes[e.t].vy-=dy*0.02;
    });
    nodes.forEach(n=>{n.vx*=0.8;n.vy*=0.8;n.x+=n.vx;n.y+=n.vy;
      n.x=Math.max(20,Math.min(W-20,n.x));n.y=Math.max(20,Math.min(H-20,n.y));});
  }
  const el = (tag,attrs)=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);
    for(const k in attrs)e.setAttribute(k,attrs[k]);return e;};
  edges.forEach(e=>svg.appendChild(el('line',{x1:nodes[e.s].x,y1:nodes[e.s].y,x2:nodes[e.t].x,y2:nodes[e.t].y,stroke:'#cdd5e3'})));
  nodes.forEach(n=>{
    const type = n.id.split('/')[1]? n.id.split('/')[1].split('/')[0]: 'x';
    const c = CLASS_COLOR[type]||'#1B4FE4';
    const circ = el('circle',{cx:n.x,cy:n.y,r:7,fill:c});
    const lbl = el('text',{x:n.x+9,y:n.y+3,'font-size':10,fill:'#333'});
    lbl.textContent = decodeURIComponent(n.id.split('/').pop());
    svg.appendChild(circ); svg.appendChild(lbl);
  });
}
