const esbuild=require('esbuild');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
Promise.all(['login','discovery','overview','admin','help','sales-ops'].map(name=>esbuild.build({entryPoints:[path.join(root,'web','react-'+name+'.jsx')],outfile:path.join(root,'static','react-'+name+'.js'),bundle:true,minify:true,sourcemap:false,legalComments:'linked',target:['es2020'],define:{'process.env.NODE_ENV':'"production"'}}))).catch(error=>{console.error(error.message);process.exitCode=1;});
