import test from 'node:test';
import assert from 'node:assert/strict';
import {allowedUrl,publicAddress} from '../safe-http.mjs';
import {extractContacts,enrich} from '../enrich.mjs';
test('SSRF: private, loopback, mapped and credential URLs blocked',()=>{
 for(const value of ['127.0.0.1','10.0.0.1','192.168.1.5','169.254.169.254','::1','fc00::1','::ffff:127.0.0.1','0.0.0.0','100.64.0.1','224.0.0.1'])assert.equal(publicAddress(value),false,value);
 assert.equal(publicAddress('1.1.1.1'),true);
 for(const url of ['http://localhost','http://127.1','http://0x7f000001','http://2130706433','http://[::1]','https://user:pass@example.com','file:///tmp/a','http://example.com:8080'])assert.throws(()=>allowedUrl(url),url);
 assert.throws(()=>allowedUrl('https://other.example.com','example.com'));assert.equal(allowedUrl('https://example.com/contact','example.com').hostname,'example.com');
 assert.equal(allowedUrl('https://www.example.com/contato','example.com').hostname,'www.example.com');
 assert.equal(allowedUrl('https://example.com/contato','www.example.com').hostname,'example.com');
 assert.throws(()=>allowedUrl('https://example.com.evil.invalid','example.com'));
});
test('robots unavailable blocks crawling and no secret area is accessed',async()=>{
 const calls=[];
 const get=async(url)=>{calls.push(url);return {status:503,headers:{},url,text:''};};
 const rows=await enrich([{id:'closed',website:'https://example.com/'}],{get});
 assert.equal(rows[0].status,'indisponivel');
 assert.deepEqual(calls,['https://example.com/robots.txt']);
 assert.deepEqual(rows[0].phones,[]);
});
test('only published contacts and source links; no guessing',()=>{
 const result=extractContacts('<body><script>fake@example.com</script><a href="mailto:contato@example.com">Contato</a><a href="tel:+5551999999999">Ligar</a><a href="/contato">Contato</a><a href="https://www.instagram.com/loja">Instagram</a><p>CNPJ 11.222.333/0001-81</p></body>','https://example.com');
 assert.deepEqual(result.emails,['contato@example.com']);assert.deepEqual(result.phones,['+5551999999999']);assert.equal(result.cnpj,'11222333000181');assert.equal(result.contactPages[0],'https://example.com/contato');
});
test('Crawlee honors robots and merges public contact pages without network',async()=>{
 const requests=[];const get=async(url)=>{requests.push(url);return {status:200,headers:{'content-type':'text/html'},url,text:url.endsWith('/robots.txt')?'User-agent: *\nDisallow: /privado':url.endsWith('/contato')?'<a href="mailto:vendas@example.com">Contato</a>':'<a href="/contato">Fale conosco</a>'};};
 const rows=await enrich([{id:'a',website:'https://example.com/'},{id:'b',website:'https://example.com/privado'},{id:'c',website:'http://127.0.0.1'}],{get});
 assert.equal(rows[0].status,'consultado');assert.deepEqual(rows[0].emails,['vendas@example.com']);assert.equal(rows[1].status,'robots_bloqueado');assert.equal(rows[2].status,'site_bloqueado');assert(!requests.includes('https://example.com/privado'));
});
