const host=document.getElementById('pipeline3d');
const fallback=document.getElementById('threeFallback');
const tooltip=document.getElementById('threeTooltip');
const summary=document.getElementById('threeSummary');
let THREE,OrbitControls,threeReady=false;
try{THREE=await import('three');({OrbitControls}=await import('three/addons/controls/OrbitControls.js'));threeReady=true}catch(error){console.warn('Visualização 3D indisponível:',error);if(fallback)fallback.hidden=false}

let renderer,scene,camera,controls,raycaster,pointer,interactive=[],dynamicGroup,hovered;
const palette=[0xb51f43,0xd73458,0xd98b2b,0x6578c8,0x31a46c,0x69717d];
const cssPalette=['#b51f43','#d73458','#d98b2b','#6578c8','#31a46c','#69717d'];
const money=c=>new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL',maximumFractionDigits:0}).format(Number(c||0)/100);
const pct=(a,b)=>b?Math.round(a*1000/b)/10:0;

function webglAvailable(){try{const c=document.createElement('canvas');return Boolean(c.getContext('webgl2')||c.getContext('webgl'))}catch{return false}}
function init(){
  if(!threeReady||!host||!webglAvailable()){if(fallback)fallback.hidden=false;return false}
  scene=new THREE.Scene();scene.background=new THREE.Color(0x0b0a0c);scene.fog=new THREE.Fog(0x0b0a0c,42,78);
  camera=new THREE.PerspectiveCamera(34,host.clientWidth/host.clientHeight,.1,150);camera.position.set(31,25,38);
  renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));renderer.setSize(host.clientWidth,host.clientHeight);renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;host.appendChild(renderer.domElement);
  controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.07;controls.enablePan=false;controls.minDistance=30;controls.maxDistance=64;controls.minPolarAngle=.62;controls.maxPolarAngle=1.34;controls.minAzimuthAngle=-.72;controls.maxAzimuthAngle=.72;controls.target.set(0,2.5,0);
  raycaster=new THREE.Raycaster();pointer=new THREE.Vector2(99,99);
  scene.add(new THREE.HemisphereLight(0xf7f4f6,0x17131a,1.8));const key=new THREE.DirectionalLight(0xffffff,3.4);key.position.set(-10,22,18);scene.add(key);const rim=new THREE.DirectionalLight(0xd1264f,1.8);rim.position.set(22,10,-14);scene.add(rim);
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(68,30),new THREE.MeshStandardMaterial({color:0x0f0d11,roughness:.86,metalness:.08}));floor.rotation.x=-Math.PI/2;floor.position.y=-.08;scene.add(floor);
  const grid=new THREE.GridHelper(68,34,0x352d34,0x201c21);grid.position.y=-.03;grid.material.transparent=true;grid.material.opacity=.42;scene.add(grid);
  renderer.domElement.addEventListener('pointermove',onPointer);renderer.domElement.addEventListener('pointerleave',clearHover);new ResizeObserver(resize).observe(host);animate();return true;
}
function clearData(){interactive=[];hovered=null;if(dynamicGroup)scene.remove(dynamicGroup);dynamicGroup=new THREE.Group();scene.add(dynamicGroup)}
function canvasLabel(title,meta,width=768){const c=document.createElement('canvas'),ctx=c.getContext('2d');c.width=width;c.height=128;ctx.clearRect(0,0,c.width,c.height);ctx.textAlign='center';ctx.fillStyle='#f8f5f7';ctx.font='700 30px Inter,Arial';ctx.fillText(title.toUpperCase(),width/2,48);ctx.fillStyle='#8f868d';ctx.font='600 18px Inter,Arial';ctx.fillText(meta,width/2,82);const map=new THREE.CanvasTexture(c);map.colorSpace=THREE.SRGBColorSpace;const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map,transparent:true,depthWrite:false}));sprite.scale.set(8.4,1.4,1);return sprite}
function connector(x1,x2,width1,width2,color,retention){const length=x2-x1,shape=new THREE.Shape();shape.moveTo(-length/2,-width1/2);shape.lineTo(length/2,-width2/2);shape.lineTo(length/2,width2/2);shape.lineTo(-length/2,width1/2);shape.closePath();const geometry=new THREE.ExtrudeGeometry(shape,{depth:.16,bevelEnabled:false}),material=new THREE.MeshStandardMaterial({color,transparent:true,opacity:.30,roughness:.6,metalness:.1,side:THREE.DoubleSide}),mesh=new THREE.Mesh(geometry,material);mesh.rotation.x=Math.PI/2;mesh.position.set((x1+x2)/2,.32,0);mesh.userData={kind:'flow',retention};return mesh}
function build({leads,stageLabels}){
  if(!scene&&!init())return;clearData();
  const keys=Object.keys(stageLabels),stages=keys.map((key,i)=>{const items=leads.filter(x=>x.profile_lead_status===key);return{key,label:stageLabels[key],items,count:items.length,value:items.reduce((s,l)=>s+Number(l.profile_negotiated_value_cents||l.profile_closed_value_cents||l.profile_offered_value_cents||0),0),color:palette[i%palette.length]}}),maxCount=Math.max(1,...stages.map(s=>s.count)),maxValue=Math.max(1,...stages.map(s=>s.value)),gap=8.8,start=-(keys.length-1)*gap/2;
  stages.forEach((stage,i)=>{const x=start+i*gap,width=2.2+stage.count/maxCount*3.5,height=.8+stage.value/maxValue*5.8,depth=3.1+stage.count/maxCount*5.2;
    if(i<stages.length-1){const next=stages[i+1],nextWidth=2.2+next.count/maxCount*3.5,nextDepth=3.1+next.count/maxCount*5.2,retention=pct(next.count,stage.count),flow=connector(x+width/2,x+gap-nextWidth/2,depth*.72,nextDepth*.72,stage.color,retention);dynamicGroup.add(flow);interactive.push(flow)}
    const geometry=new THREE.BoxGeometry(width,height,depth),material=new THREE.MeshPhysicalMaterial({color:stage.color,roughness:.34,metalness:.16,clearcoat:.45,clearcoatRoughness:.35,transparent:true,opacity:.92}),block=new THREE.Mesh(geometry,material);block.position.set(x,height/2,0);block.userData={kind:'stage',label:stage.label,count:stage.count,value:stage.value,index:i,baseColor:stage.color};dynamicGroup.add(block);interactive.push(block);
    const cap=new THREE.Mesh(new THREE.BoxGeometry(width+.05,.055,depth+.05),new THREE.MeshBasicMaterial({color:0xffffff,transparent:true,opacity:.32}));cap.position.set(x,height+.03,0);dynamicGroup.add(cap);
    const label=canvasLabel(stage.label,`${stage.count} LEADS`);label.position.set(x,-1.25,depth/2+.9);dynamicGroup.add(label);
  });
  stages.slice(0,-1).forEach((stage,i)=>{const next=stages[i+1],retention=pct(next.count,stage.count),loss=Math.max(0,stage.count-next.count),label=canvasLabel(`${String(retention).replace('.',',')}%`,`RETENÇÃO · −${loss}`,560);label.scale.set(4.5,.92,1);label.position.set(start+i*gap+gap/2,.65,-5.4);dynamicGroup.add(label)});
  summary.innerHTML=stages.map((stage,i)=>{const previous=stages[i-1],retention=previous?pct(stage.count,previous.count):100,detail=i?`${String(retention).replace('.',',')}% retidos da etapa anterior`:'Base de entrada do funil';return`<div style="--stage-color:${cssPalette[i%cssPalette.length]}"><span>${stage.label}</span><strong>${stage.count} lead${stage.count===1?'':'s'}</strong><small>${detail}</small></div>`}).join('');
}
function clearHover(){pointer?.set(99,99);if(tooltip)tooltip.hidden=true;if(hovered?.material?.emissive){hovered.material.emissive.setHex(0);hovered.material.emissiveIntensity=0}hovered=null}
function onPointer(e){const r=renderer.domElement.getBoundingClientRect();pointer.x=(e.clientX-r.left)/r.width*2-1;pointer.y=-(e.clientY-r.top)/r.height*2+1;raycaster.setFromCamera(pointer,camera);const hit=raycaster.intersectObjects(interactive,false)[0];if(!hit){clearHover();return}if(hovered!==hit.object){if(hovered?.material?.emissive){hovered.material.emissive.setHex(0);hovered.material.emissiveIntensity=0}hovered=hit.object;if(hovered.material?.emissive){hovered.material.emissive.setHex(hovered.userData.baseColor||0x7d253c);hovered.material.emissiveIntensity=.18}}const d=hit.object.userData;tooltip.hidden=false;tooltip.style.left=`${Math.min(r.width-230,e.clientX-r.left+14)}px`;tooltip.style.top=`${Math.max(8,e.clientY-r.top-12)}px`;tooltip.innerHTML=d.kind==='stage'?`<strong>${d.label}</strong><span>Leads <b>${d.count}</b></span><span>Valor associado <b>${money(d.value)}</b></span>`:`<strong>Passagem de etapa</strong><span>Retenção <b>${String(d.retention).replace('.',',')}%</b></span>`}
function resize(){if(!renderer)return;const w=host.clientWidth,h=host.clientHeight;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h,false)}
function animate(){requestAnimationFrame(animate);controls?.update();if(renderer&&scene&&camera)renderer.render(scene,camera)}
window.addEventListener('radar-bi:data',e=>build(e.detail));if(window.RadarBIData)build(window.RadarBIData);
