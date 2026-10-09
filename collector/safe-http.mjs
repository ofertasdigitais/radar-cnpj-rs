import dns from 'node:dns/promises';
import http from 'node:http';
import https from 'node:https';
import ipaddr from 'ipaddr.js';

export function publicAddress(address) {
  try {
    let parsed=ipaddr.parse(address);
    if(parsed.kind()==='ipv6' && parsed.isIPv4MappedAddress()) parsed=parsed.toIPv4Address();
    return parsed.range()==='unicast';
  } catch { return false; }
}

export function allowedUrl(raw, hostname) {
  const url=new URL(raw);
  if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.port&&!['80','443'].includes(url.port)) throw Error('URL não permitida');
  const host=url.hostname.replace(/^\[|\]$/g,'').toLowerCase();
  if(host==='localhost'||host.endsWith('.localhost')||host.endsWith('.local')||host.includes('%')||!host.includes('.')&&!host.includes(':')) throw Error('Host não público');
  if(ipaddr.isValid(host)&&!publicAddress(host)) throw Error('IP não público');
  // A commercial site commonly redirects between its apex and www host.
  // No other subdomain/domain is allowed; every DNS answer is still validated.
  if(hostname&&host.replace(/^www\./,'')!==hostname.toLowerCase().replace(/^www\./,'')) throw Error('Redirecionamento fora do domínio');
  return url;
}

// Pin the validated DNS answer in the socket lookup. Check each redirect anew.
export async function safeGet(raw, hostname, redirects=0) {
  const url=allowedUrl(raw,hostname),host=url.hostname.replace(/^\[|\]$/g,'');
  const addresses=await dns.lookup(host,{all:true,verbatim:true});
  if(!addresses.length||addresses.some(a=>!publicAddress(a.address))) throw Error('DNS não público');
  const selected=addresses[0],limit=2*1024*1024;
  const response=await new Promise((resolve,reject)=>{
    const request=(url.protocol==='https:'?https:http).get(url,{
      timeout:10000,headers:{'User-Agent':'RadarCNPJ/1.0 (+public business contacts)','Accept':'text/html,text/plain;q=0.9','Accept-Encoding':'identity'},
      lookup:(_host,options,callback)=>options.all?callback(null,[selected]):callback(null,selected.address,selected.family)
    },res=>{
      if(Number(res.headers['content-length']||0)>limit) {res.destroy();reject(Error('Página excede o limite'));return;}
      let bytes=0,chunks=[];
      res.on('data',chunk=>{bytes+=chunk.length;if(bytes>limit){res.destroy();reject(Error('Página excede o limite'));}else chunks.push(chunk);});
      res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,text:Buffer.concat(chunks).toString('utf8'),url:url.href}));
      res.on('error',reject);
    });
    request.on('timeout',()=>request.destroy(Error('Tempo de consulta excedido')));request.on('error',reject);
  });
  if(response.status>=300&&response.status<400&&response.headers.location){
    if(redirects>=2)throw Error('Muitos redirecionamentos');
    return safeGet(new URL(response.headers.location,url).href,hostname||host,redirects+1);
  }
  if(response.headers['content-encoding']&&response.headers['content-encoding']!=='identity') throw Error('Compressão não autorizada');
  return response;
}
