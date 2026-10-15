const {test}=require('node:test');const assert=require('node:assert/strict');
const {observeResize}=require('../tools/resize-observer.cjs');
test('resize writes are deferred, coalesced, dimension guarded and cancelled on disposal',()=>{
 const saved={ResizeObserver:global.ResizeObserver,requestAnimationFrame:global.requestAnimationFrame,cancelAnimationFrame:global.cancelAnimationFrame};
 let deliver,next=1,disconnected=false;const frames=new Map(),calls=[];
 global.ResizeObserver=class {constructor(cb){deliver=cb;}observe(){}disconnect(){disconnected=true;}};
 global.requestAnimationFrame=fn=>{const id=next++;frames.set(id,fn);return id;};global.cancelAnimationFrame=id=>frames.delete(id);
 const size=(width,height)=>deliver([{contentRect:{width,height}}]);const flush=()=>{const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn());};
 try{
  const observer=observeResize({isConnected:true},x=>calls.push(x));
  size(100,50);assert.equal(calls.length,0);size(120,60);assert.equal(frames.size,1);flush();assert.deepEqual(calls,[{width:120,height:60}]);
  size(120,60);assert.equal(frames.size,0);size(140,60);observer.disconnect();assert.equal(frames.size,0);assert.equal(disconnected,true);flush();assert.equal(calls.length,1);
  const widthObserver=observeResize({isConnected:true},x=>calls.push(x),{widthOnly:true});
  size(180,0);flush();assert.equal(calls.length,2);size(180,60);assert.equal(frames.size,0);widthObserver.disconnect();
 }finally{Object.assign(global,saved);}
});
