import {BasicCrawler} from '@crawlee/basic';
import {Configuration,log} from '@crawlee/core';
import {load} from 'cheerio';
import robotsParser from 'robots-parser';
import {allowedUrl,safeGet} from './safe-http.mjs';

export function extractContacts(html,base) {
  const $=load(html),result={phones:[],emails:[],socials:[],contactPages:[]};
  $('script,style,noscript').remove();
  $('a[href]').each((_i,element)=>{
    const href=$(element).attr('href')||'';
    if(/^tel:/i.test(href)){const phone=href.slice(4).split('?')[0].replace(/[^\d+]/g,'');if(phone.length>=10&&phone.length<=16)result.phones.push(phone);}
    if(/^mailto:/i.test(href)){const email=href.slice(7).split('?')[0];if(email.length<=180&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))result.emails.push(email);}
    try{
      const url=new URL(href,base);
      if(url.protocol!=='https:'&&url.protocol!=='http:')return;
      if(['instagram.com','www.instagram.com','linkedin.com','www.linkedin.com','facebook.com','www.facebook.com'].includes(url.hostname)&&!url.username&&!url.password)result.socials.push(url.href.slice(0,300));
      if(url.hostname===new URL(base).hostname&&/contato|contact|fale-conosco/i.test(url.pathname)&&!url.search)result.contactPages.push(url.href);
    }catch{}
  });
  const text=$('body').text(),match=text.match(/CNPJ\s*:?\s*([\dA-Z]{2}\.?[\dA-Z]{3}\.?[\dA-Z]{3}\/?[\dA-Z]{4}-?\d{2})/i);
  for(const key of Object.keys(result))result[key]=[...new Set(result[key])].slice(0,5);
  result.cnpj=match?match[1].replace(/[^a-z0-9]/gi,'').toUpperCase():'';
  return result;
}

export async function enrich(seeds,{get=safeGet}={}) {
  log.setLevel(log.LEVELS.OFF);
  const records=new Map(),robots=new Map(),visited=new Map();
  const requests=[];
  for(const seed of seeds.slice(0,10)){
    records.set(seed.id,{id:seed.id,phones:[],emails:[],socials:[],cnpj:'',status:'sem_site',pages:[]});
    if(!seed.website)continue;
    try{const url=allowedUrl(seed.website);requests.push({url:url.href,uniqueKey:seed.id+':root',userData:{id:seed.id,host:url.hostname,depth:0}});records.get(seed.id).status='pendente';}
    catch{records.get(seed.id).status='site_bloqueado';}
  }
  const config=new Configuration({persistStorage:false});
  const crawler=new BasicCrawler({
    maxConcurrency:1,maxRequestsPerCrawl:30,maxRequestsPerMinute:20,maxRequestRetries:0,useSessionPool:false,requestHandlerTimeoutSecs:45,
    async requestHandler({request}){
      const {id,host,depth}=request.userData,row=records.get(id),url=allowedUrl(request.url,host);
      if(!robots.has(url.origin)){
        const response=await get(url.origin+'/robots.txt',host);
        if(response.status===404)robots.set(url.origin,robotsParser(url.origin+'/robots.txt',''));
        else if(response.status===200)robots.set(url.origin,robotsParser(url.origin+'/robots.txt',response.text));
        else throw Error('robots.txt indisponível');
      }
      if(robots.get(url.origin).isAllowed(url.href,'RadarCNPJ')===false){row.status='robots_bloqueado';return;}
      const delay=Math.max(1500,Number(robots.get(url.origin).getCrawlDelay('RadarCNPJ')||0)*1000);
      if(delay>30000){row.status='limite_crawl_delay';return;}
      const last=visited.get(host);if(last)await new Promise(resolve=>setTimeout(resolve,Math.max(0,delay-(Date.now()-last))));visited.set(host,Date.now());
      const response=await get(url.href,host);
      if(response.status!==200||!String(response.headers['content-type']||'').includes('text/html'))throw Error('Página não disponível');
      const found=extractContacts(response.text,response.url);
      for(const key of ['phones','emails','socials'])row[key]=[...new Set([...row[key],...found[key]])].slice(0,5);
      row.cnpj=row.cnpj||found.cnpj;row.pages.push(response.url);row.status='consultado';
      if(depth===0)await crawler.addRequests(found.contactPages.slice(0,2).map(url=>({url,uniqueKey:id+':'+url,userData:{id,host,depth:1}})));
    },
    async failedRequestHandler({request}){const row=records.get(request.userData.id);if(!row.pages.length)row.status='indisponivel';}
  },config);
  if(requests.length)await crawler.run(requests);
  return [...records.values()];
}

if(process.argv[1]&&import.meta.url.endsWith('/enrich.mjs')&&process.argv[1].replace(/\\/g,'/').endsWith('/enrich.mjs')){
  let input='';for await(const chunk of process.stdin){input+=chunk;if(input.length>50000)throw Error('Entrada excede limite');}
  try{const parsed=JSON.parse(input);if(!Array.isArray(parsed.seeds))throw Error('Lista inválida');const results=await enrich(parsed.seeds);process.stdout.write(JSON.stringify({results}));}
  catch{process.stderr.write('Coletor não concluiu a rodada.\n');process.exitCode=1;}
}
