import * as PDFLib from 'pdf-lib';
import fontkit from '@pdf-lib/fontkit';
// The existing, tested browser report is a UMD/CommonJS module without a .d.ts.
// @ts-expect-error Keep the same visual template as the local report studio.
import RadarReport from '../../static/radar-report.js';
import { ApiError, type Env, type Row } from './runtime';
import type { commercialAnalytics } from './sales-analytics';

interface ReportTemplate {
  create(profile:string,data:ReturnType<typeof commercialAnalytics>,options:{title:string;company:string;notes:string;sections:string[]},libraries:{PDFLib:typeof PDFLib;fontkit:typeof fontkit},fonts:{regular:Uint8Array;bold:Uint8Array}):Promise<Uint8Array>;
}

/** Reuse the Radar report studio's vector layout and local Inter assets. */
export async function commercialPdf(env:Env,origin:string,profile:string,data:ReturnType<typeof commercialAnalytics>,branding:Row):Promise<Uint8Array> {
  if(data.summary.total>10000)throw new ApiError(413,'Restrinja o período ou campanha para até 10 mil leads');
  const fonts=await Promise.all(['Regular','Bold'].map(async weight=>{
    const response=await env.ASSETS.fetch(new Request(new URL('/fonts/Inter-'+weight+'.ttf',origin)));
    if(!response.ok)throw new ApiError(503,'Fonte Inter indisponível para gerar PDF');
    const bytes=new Uint8Array(await response.arrayBuffer());
    if(bytes.length<1024||bytes.length>2*1024*1024)throw new ApiError(503,'Fonte Inter indisponível para gerar PDF');
    return bytes;
  }));
  const bytes=await (RadarReport as ReportTemplate).create(profile,data,{
    title:String(branding.report_title||'Relatório comercial'),company:String(branding.site_name||'Radar CNPJ'),notes:'',sections:['performance','queue','quality'],
  },{PDFLib,fontkit},{regular:fonts[0],bold:fonts[1]});
  // Retain the configured private-use footer while keeping the studio's brand.
  if(!branding.report_footer)return bytes;
  const doc=await PDFLib.PDFDocument.load(bytes);doc.registerFontkit(fontkit);
  const font=await doc.embedFont(fonts[0],{subset:true});
  const allowed=new Set(font.getCharacterSet());
  const footer=Array.from(String(branding.report_footer)).filter(c=>allowed.has(c.codePointAt(0)!)).join('').slice(0,120);
  for(const page of doc.getPages()) {
    // The original date and page counter remain in their existing positions.
    page.drawText(footer,{x:36,y:42,font,size:7,color:PDFLib.rgb(.38,.34,.38),maxWidth:690});
  }
  return doc.save();
}
