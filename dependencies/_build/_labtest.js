const fs=require('fs');const {JSDOM}=require('jsdom');
const file=process.argv[2];
const html=fs.readFileSync(file,'utf8');
const m=html.match(/<script>([\s\S]*)<\/script>/);
let s=m[1];
const snip=`\nwindow.__Q=(typeof QUESTIONS!=='undefined')?QUESTIONS:undefined;window.__load=(typeof loadItem!=='undefined')?loadItem:undefined;\n`;
const re=/\}\)\(\);\s*$/;
s=re.test(s)?s.replace(re,x=>snip+x):s+snip;
const ph=html.slice(0,m.index)+'<script>'+s+'</script>'+html.slice(m.index+m[0].length);
const dom=new JSDOM(ph,{runScripts:'dangerously',url:'http://localhost/',pretendToBeVisual:true});
const w=dom.window,d=w.document;
setTimeout(()=>{
  const Q=w.__Q, load=w.__load;
  const idxOf=id=>Q.findIndex(q=>q.id===id);
  for(const id of [19,42,43]){
    const idx=idxOf(id); load(idx);
    const stem=d.getElementById('question-stem');
    const tables=[...stem.querySelectorAll('table.stem-lab-table')];
    console.log('===== id',id,'(idx',idx,') leaked-marker:',/\[\[LAB_TABLE/.test(stem.textContent),'=====');
    tables.forEach((t,ti)=>{console.log(' table',ti,'multicol='+t.classList.contains('multicol'));
      [...t.querySelectorAll('tr')].forEach(tr=>console.log('   ',[...tr.children].map(c=>c.tagName+':'+JSON.stringify(c.textContent)).join('  |  ')));});
  }
  let leak=[];
  for(let i=0;i<Q.length;i++){load(i);if(/\[\[LAB_TABLE/.test(d.getElementById('question-stem').textContent))leak.push(Q[i].id);}
  console.log('\nANY LEAKED LITERAL MARKERS:',leak.length?leak:'NONE');
  // highlight sanity: select-all within stem of item 42 and ensure no crash
  console.log('DONE');
},400);
