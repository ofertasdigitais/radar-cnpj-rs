const { build } = require('esbuild');
const fs = require('node:fs');
const path = require('node:path');
async function main() {
  await build({entryPoints:['tools/browser-dependencies.js'],bundle:true,minify:true,target:['es2020'],outfile:'static/vendor/radar-libraries.js',legalComments:'linked'});
  for (const name of ['charts','pdf']) await build({entryPoints:[name==='charts'?'tools/chart-dependencies.js':'tools/pdf-dependencies.js'],bundle:true,minify:true,target:['es2020'],outfile:`static/vendor/radar-${name}.js`,legalComments:'linked'});
  const packages=[],seen=new Set();
  function visit(name){if(seen.has(name))return;seen.add(name);const pkg=JSON.parse(fs.readFileSync(path.join('node_modules',name,'package.json'),'utf8'));packages.push(name);Object.keys(pkg.dependencies||{}).forEach(visit);}
  Object.keys(require('../package.json').dependencies).forEach(visit);
  const notices=packages.map(name=>{
    const dir=path.join('node_modules',name),pkg=JSON.parse(fs.readFileSync(path.join(dir,'package.json'),'utf8'));
    const licenses=fs.readdirSync(dir).filter(n=>/^licen[sc]e|^notice/i.test(n)&&fs.statSync(path.join(dir,n)).isFile());
    return `${name} ${pkg.version} | ${pkg.license}\n${licenses.map(n=>fs.readFileSync(path.join(dir,n),'utf8')).join('\n')}`;
  });
  fs.writeFileSync('static/vendor/THIRD-PARTY-LICENSES.txt',notices.join('\n\n'+'='.repeat(72)+'\n\n'));
  const crypto=require('node:crypto');
  const manifest={packages:Object.fromEntries(packages.map(name=>[name,JSON.parse(fs.readFileSync(path.join('node_modules',name,'package.json'),'utf8')).version])),assets:{}};
  for(const filename of ['radar-libraries.js','radar-charts.js','radar-pdf.js'])manifest.assets[filename]=crypto.createHash('sha256').update(fs.readFileSync('static/vendor/'+filename)).digest('hex');
  fs.writeFileSync('static/vendor/manifest.json',JSON.stringify(manifest,null,2)+'\n');
  console.log('Bibliotecas locais compiladas; licenças preservadas.');
}
main().catch(e=>{console.error(e);process.exitCode=1});
