const {test}=require('node:test');const assert=require('node:assert/strict');
const {parsePhoneNumberFromString}=require('libphonenumber-js/max');const Papa=require('papaparse');
const core=require('../static/tools-core.js');
test('telefone com DDD 55 não confunde país e revisão não inventa WhatsApp',()=>{
  const south=core.phone('55987654321',parsePhoneNumberFromString);assert.equal(south.e164,'+5555987654321');assert.equal(south.valid,true);
  assert.equal(core.phone('+55 (51) 98765-4321',parsePhoneNumberFromString).e164,'+5551987654321');
  const old=core.phone('5187654321',parsePhoneNumberFromString);assert.equal(old.e164,'');assert.equal(old.suggestion,'+5551987654321');
  assert.equal(core.phone('00999999999',parsePhoneNumberFromString).valid,false);assert.match(south.note,/confirmação/);
});
test('WhatsApp completa apenas celulares antigos e preserva o contrato de validação original',()=>{
  for(const raw of ['5187654321','(51) 8765-4321','+55 (51) 8765-4321','555187654321','05187654321']){
    const result=core.whatsapp(raw,parsePhoneNumberFromString);
    assert.equal(result.e164,'+5551987654321',raw);assert.equal(result.adjusted,true,raw);
    assert.equal(core.phone(raw,parsePhoneNumberFromString).e164,'',raw);
  }
  assert.equal(core.whatsapp('5587654321',parsePhoneNumberFromString).e164,'+5555987654321');
  for(const raw of ['51987654321','+55 (51) 98765-4321','55987654321','5132345678']){
    const result=core.whatsapp(raw,parsePhoneNumberFromString);
    assert.equal(result.e164,core.phone(raw,parsePhoneNumberFromString).e164,raw);assert.equal(result.adjusted,false,raw);
  }
  for(const raw of ['','118765432','0087654321','513234567','+51 87654321','+1 2025550123','5187654321 / 51987654321','telefone 5187654321']){
    assert.equal(core.whatsapp(raw,parsePhoneNumberFromString).e164,'',raw);
  }
});

test('CSV preserva zeros e acentos, mapeia colunas e neutraliza fórmulas no modelo exportado',()=>{
  const parsed=Papa.parse('Empresa;Telefone;CNPJ;Origem\nCafé;0512345678;00123456000100;Indicação',{header:true,dynamicTyping:false});
  const map=core.autoMap(parsed.meta.fields),rows=core.mapped(parsed.data,map,'Evento');
  assert.equal(rows[0].cnpj,'00123456000100');assert.equal(rows[0].source,'Indicação');assert.equal(rows[0].company,'Café');assert.deepEqual(core.validate(rows[0]),[]);
  assert.match(Papa.unparse([{Nome:'=1+1'}],{escapeFormulae:true}),/'=1\+1/);
});
test('URLs perigosas são rejeitadas e links de pesquisa são codificados',()=>{
  assert.ok(core.validate({name:'Teste',website:'javascript:alert(1)'}).length);
  assert.ok(core.validate({name:'Teste',website:'https://user:pass@example.com'}).length);
  assert.deepEqual(core.validate({name:'Teste',website:'https://example.com'}),[]);
  for(const link of core.researchLinks('<empresa>&','Porto Alegre'))assert.ok(new URL(link.url).protocol==='https:');
});
