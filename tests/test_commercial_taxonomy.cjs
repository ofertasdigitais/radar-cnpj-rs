const assert=require('node:assert/strict');
const taxonomy=require('../static/commercial-taxonomy.js');
assert.equal(taxonomy.areas.length,21);
for(const area of taxonomy.areas){
  assert.equal(taxonomy.areaFor(String(area.min).padStart(2,'0')+'00000'),area.id);
  assert.equal(taxonomy.areaFor(String(area.max).padStart(2,'0')+'99999'),area.id);
}
const items=taxonomy.build([
  {codigo:'4711302',descricao:'Supermercados',empresas:12},
  {codigo:'8630504',descricao:'Atividade odontológica',empresas:8},
  {codigo:'6201501',descricao:'Desenvolvimento de software',empresas:7},
  {codigo:'4120400',descricao:'Construção de edifícios',empresas:6},
  {codigo:'5611201',descricao:'Restaurantes oficiais',empresas:5}
],[{name:'Restaurantes',codes:['5611201'],terms:'restaurante'}]);
assert.equal(items.length,5);
assert.deepEqual(items.filter(item=>item.area==='G').map(item=>item.name),['Supermercados']);
assert.equal(items.find(item=>item.codes[0]==='8630504').area,'Q');
assert.equal(items.find(item=>item.codes[0]==='6201501').area,'J');
assert.equal(items.find(item=>item.codes[0]==='4120400').area,'F');
assert.equal(items.filter(item=>item.codes[0]==='5611201').length,1);
console.log('Taxonomia: 21 áreas classificadas, subcategorias de comércio/saúde/tecnologia/construção e deduplicação verificadas.');
