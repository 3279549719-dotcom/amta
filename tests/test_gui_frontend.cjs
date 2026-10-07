const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {URLSearchParams} = require('node:url');
const {test} = require('node:test');
const html = fs.readFileSync('src/amta/gui/static/index.html', 'utf8');

function setup() {
  const readers = [], nodes = new Map(), forms = [], opened = [], translateBodies = [];
  function node() { return {style:{}, dataset:{}, classList:{add(){},remove(){},toggle(){}}, addEventListener(k,v){this[k]=v;}, appendChild(){}, insertBefore(){}, querySelector(){return null;}, remove(){}, textContent:''}; }
  const png = node(); png.dataset.format = 'png';
  const document = {body:node(), getElementById(id){if(!nodes.has(id)) nodes.set(id,node()); return nodes.get(id);}, querySelectorAll(s){return s === '.export-item' ? [png] : [];}, createElement:node, addEventListener(k,v){this[k]=v;}};
  let tick;
  // New book flow: drop images -> /api/book/match recognizes the book -> /api/translate JSON.
  async function fetchMock(url, opts) {
    if (url === '/api/book/match') {
      return {ok:true, json: async () => ({matched:true, book_id:'bid', work_id:'book-bid', src_dir:'D:/book', glossary:{}, page_count:2, pages:[1,2]})};
    }
    if (url === '/api/translate') { translateBodies.push(JSON.parse(opts.body)); return {ok:true, json: async () => ({job_id:'job'})}; }
    if (String(url).startsWith('/api/jobs/')) return {ok:true, json: async () => ({status:'done'})};
    if (String(url).startsWith('/api/glossary')) return {ok:true, json: async () => ({book_id:'bid', glossary:{}})};
    return {ok:true, json: async () => ({artifacts:[{page:'1',url:'/1.png'},{page:'2',url:'/2.png'}]})};
  }
  const context = {document, console, setTimeout(){}, clearInterval(){}, setInterval(fn){tick=fn; return 1;}, FileReader:class {constructor(){readers.push(this);} readAsDataURL(file){this.file=file;}}, FormData:class {constructor(){this.fields=[]; forms.push(this);} append(...args){this.fields.push(args);}}, window:{open(url){opened.push(url);}, location:{search:''}}, location:{search:''}, URLSearchParams, localStorage:{getItem(){return null;},setItem(){}}, fetch:fetchMock};
  vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
  return {readers,nodes,forms,opened,document,png,tick:()=>tick(),translateBodies};
}
async function flush(){for(let i=0;i<20;i++) await Promise.resolve();}
function files(s){s.nodes.get('fileInput').change({target:{files:[{name:'0001.png',type:'image/png'},{name:'0002.png',type:'image/png'}]}});}

test('translate runs exactly the dropped pages (by filename), not the whole book', async()=>{
 const s=setup(); files(s);
 s.readers.forEach((r,i)=>r.onload({target:{result:'data:'+i}})); await flush();
 s.nodes.get('translateBtn').click(); await flush();
 assert.deepEqual(s.translateBodies[0].pages, [1,2]);
});

test('export uses the book-scoped download route after the run completes',async()=>{
 const s=setup(); files(s); s.readers.forEach((r,i)=>r.onload({target:{result:'data:'+i}})); await flush();
 s.nodes.get('translateBtn').click(); await flush(); s.tick(); await flush();
 s.png.click();
 assert.ok(s.opened.length, 'export should open a download URL');
 assert.match(s.opened[0], /^\/api\/export\/book-bid\/\d+\/png$/);
});

test('selection cannot allow a second concurrent translation',async()=>{
 const s=setup(); files(s); s.readers.forEach((r,i)=>r.onload({target:{result:'data:'+i}})); await flush();
 s.nodes.get('translateBtn').click(); s.nodes.get('translateBtn').click();
 assert.equal(s.translateBodies.length,1);
});
