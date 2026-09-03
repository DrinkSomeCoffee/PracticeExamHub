const fs=require('fs'); const {JSDOM}=require('jsdom');
const filePath=process.argv[2];
const html=fs.readFileSync(filePath,'utf8');
const m=html.match(/<script>([\s\S]*)<\/script>/);
const snip="\nwindow.__Q=(typeof QUESTIONS!=='undefined')?QUESTIONS:undefined;\nwindow.__loadItem=(typeof loadItem!=='undefined')?loadItem:undefined;\n";
const ps=m[1].replace(/\}\)\(\);\s*$/,(x)=>snip+x);
const dom=new JSDOM(html.slice(0,m.index)+'<script>'+ps+'</script>'+html.slice(m.index+m[0].length),{runScripts:'dangerously',url:'http://localhost/'+filePath,pretendToBeVisual:true});
const {window}=dom, d=window.document;
setTimeout(()=>{
 const Q=window.__Q, L=window.__loadItem; let ok=true;
 [11,24,50].forEach(id=>{
   L(Q.findIndex(q=>q.id===id));
   const stem=d.getElementById('question-stem');
   const tables=stem.querySelectorAll('table').length;
   const lit=stem.textContent.includes('[[LAB_TABLE');
   console.log('item',id,'lab_tables=',tables,'literal_marker=',lit);
   if(tables<1||lit) ok=false;
 });
 [22,41].forEach(id=>{
   L(Q.findIndex(q=>q.id===id));
   const img=d.querySelector('img[src*="assets/"]');
   const p=img?img.getAttribute('src'):'NONE';
   const exists=img?fs.existsSync(require('path').join(require('path').dirname(filePath),p)):false;
   console.log('item',id,'img=',p,'file_exists=',exists);
   if(!img||!exists) ok=false;
 });
 console.log(ok?'RENDER PASS':'RENDER FAIL');
},400);
