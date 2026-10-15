/* Schedule layout writes outside ResizeObserver delivery, never after disposal. */
function observeResize(element, callback, {widthOnly=false}={}) {
  let frame=0,lastSize='',disposed=false;
  const observer=new ResizeObserver(entries=>{
    const size=entries[0]?.contentRect;if(!size)return;
    const key=widthOnly?String(size.width):`${size.width}:${size.height}`;
    if(key===lastSize)return;lastSize=key;
    if(frame)cancelAnimationFrame(frame);
    frame=requestAnimationFrame(()=>{
      frame=0;
      if(!disposed&&element.isConnected&&size.width>0&&(widthOnly||size.height>0))callback(size);
    });
  });
  observer.observe(element);
  return {disconnect(){disposed=true;observer.disconnect();if(frame)cancelAnimationFrame(frame);frame=0;}};
}
module.exports={observeResize};
