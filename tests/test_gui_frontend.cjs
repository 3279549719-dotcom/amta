const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const html = fs.readFileSync('src/amta/gui/static/index.html', 'utf8');
function setup() {
  const readers = [], nodes = new Map(), forms = [], opened = [];
  function node() { return {style:{}, dataset:{}, classList:{add(){},remove(){},toggle(){}}, addEventListener(k,v){this[k]=v;}, appendChild(){}, insertBefore(){}, querySelector(){return null;}, remove(){}}; }
  const png = node(); png.dataset.format = 'png';
  const document = {body:node(), getElementById(id){if(!nodes.has(id)) nodes.set(id,node()); return nodes.get(id);}, querySelectorAll(s){return s === '.export-item' ? [png] : [];}, createElement:node, addEventListener(k,v){this[k]=v;}};
  let tick;
  const context = {document, console, setTimeout(){}, clearInterval(){}, setInterval(fn){tick=fn; return 1;}, FileReader:class {constructor(){readers.push(this);} readAsDataURL(file){this.file=file;}}, FormData:class {constructor(){this.fields=[]; forms.push(this);} append(...args){this.fields.push(args);}}, window:{open(url){opened.push(url);}}, fetch:async url=>({ok:true,json:async()=>url==='/api/upload'?{src_dir:'input',pages:[1,2]}:url==='/api/translate'?{job_id:'job'}:url.startsWith('/api/jobs/')?{status:'done'}:{artifacts:[{page:'1',url:'/1.png'},{page:'2',url:'/2.png'}]}})};
  vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
  return {readers,nodes,forms,opened,document,png,tick:()=>tick()};
}
async function flush(){for(let i=0;i<20;i++) await Promise.resolve();}
function files(s){s.nodes.get('fileInput').change({target:{files:[{name:'a.png',type:'image/png'},{name:'b.png',type:'image/png'}]}});}
test('FileReader completion does not reorder submitted pages', async()=>{
 const s=setup(); files(s);
 s.readers[1].onload({target:{result:'data:b'}}); s.readers[0].onload({target:{result:'data:a'}}); await flush();
 s.nodes.get('translateBtn').click();
 assert.deepEqual(s.forms[0].fields.filter(x=>x[0]==='files').map(x=>x[2]),['a.png','b.png']);
});
test('export retains uploaded page identity after deleting first page',async()=>{
 const s=setup(); files(s); s.readers.forEach((r,i)=>r.onload({target:{result:'data:'+i}})); await flush();
 s.nodes.get('translateBtn').click(); await flush(); s.tick(); await flush();
 s.document.keydown({key:'Delete'}); s.png.click();
 assert.match(s.opened[0], /\/2\/png$/);
});
test('selection cannot allow a second concurrent translation',async()=>{
 const s=setup(); files(s); s.readers.forEach((r,i)=>r.onload({target:{result:'data:'+i}})); await flush();
 s.nodes.get('translateBtn').click(); s.nodes.get('translateBtn').click();
 assert.equal(s.forms.length,1);
});
