/* Seções CNAE 2.0: mesmos intervalos usados por importer.py. Subcategorias
   específicas são obtidas dos códigos e descrições disponíveis na base. */
(function(root){
  const areas=[
    ['A','Agropecuária',1,3],['B','Indústrias extrativas',5,9],
    ['C','Indústria',10,33],['D','Energia',35,35],['E','Água e saneamento',36,39],
    ['F','Construção',41,43],['G','Comércio',45,47],['H','Transporte e logística',49,53],
    ['I','Alimentação e hospedagem',55,56],['J','Tecnologia e comunicação',58,63],
    ['K','Finanças e seguros',64,66],['L','Imobiliário',68,68],
    ['M','Serviços profissionais',69,75],['N','Serviços administrativos',77,82],
    ['O','Administração pública',84,84],['P','Educação',85,85],['Q','Saúde',86,88],
    ['R','Cultura e lazer',90,93],['S','Outros serviços',94,96],
    ['T','Serviços domésticos',97,97],['U','Organismos internacionais',99,99]
  ].map(([id,name,min,max])=>({id,name,min,max}));
  const areaFor=code=>{const division=Number(String(code).replace(/\D/g,'').slice(0,2));return areas.find(area=>division>=area.min&&division<=area.max)?.id||'other';};
  const build=(official,curated)=>{
    const covered=new Set(curated.flatMap(item=>item.codes));
    return [...curated.map(item=>({...item,area:areaFor(item.codes[0])})),
      ...official.filter(item=>!covered.has(String(item.codigo))).map(item=>({
        name:item.descricao||`Atividade CNAE ${item.codigo}`,codes:[String(item.codigo)],
        terms:item.segmento||'',area:areaFor(item.codigo),companies:Number(item.empresas||0)
      }))];
  };
  const api={areas,areaFor,build};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.RadarCommercialTaxonomy=api;
})(typeof window!=='undefined'?window:globalThis);
