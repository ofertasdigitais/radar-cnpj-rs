const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');
const PDFLib=require('pdf-lib'),fontkit=require('@pdf-lib/fontkit'),report=require('../static/radar-report.js');
const fontBytes={regular:fs.readFileSync('static/fonts/Inter-Regular.ttf'),bold:fs.readFileSync('static/fonts/Inter-Bold.ttf')};
const empty={summary:{total:0,active:0,contacted:0,won:0,conversion_pct:0,pipeline_cents:0,closed_cents:0,overdue:0},period:{},generated_at:'2026-10-05T14:00:00',stages:[],breakdown:{campaign:[],segmento:[],persona:[],lead_origin:[]},queue:[],quality:{invalid_phone:0,whatsapp_confirmed:0,missing_followup:0,missing_loss_reason:0},loss_reasons:[]};
test('PDF sem leads tem quatro seções legíveis; fonte Inter incorporada',async()=>{
  const bytes=await report.create('Vendedor',empty,{sections:['performance','queue','quality'],notes:'Acentuação: ação e próxima etapa.'},{PDFLib,fontkit},fontBytes);
  assert.equal(Buffer.from(bytes).subarray(0,5).toString(),'%PDF-');assert.equal((await PDFLib.PDFDocument.load(bytes)).getPageCount(),4);
});
test('PDF executivo suporta título longo, símbolos sem glifo e notas personalizadas',async()=>{
  const bytes=await report.create('Perfil com nome longo',empty,{title:'Relatório de prospecção e gestão comercial com texto extenso para conferir quebra de linhas',sections:[],notes:'Emoji não suportado: 🚀. Campo privado e acentuação preservados.'},{PDFLib,fontkit},fontBytes);
  assert.equal((await PDFLib.PDFDocument.load(bytes)).getPageCount(),1);
});
