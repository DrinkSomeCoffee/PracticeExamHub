const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync(process.argv[2],'utf8');
const m=html.match(/<script>([\s\S]*)<\/script>/);
let s=m[1];
const snip=`\nwindow.__Q=(typeof QUESTIONS!=='undefined')?QUESTIONS:undefined;window.__load=(typeof loadItem!=='undefined')?loadItem:undefined;window.__add=(typeof addHighlightRange!=='undefined')?addHighlightRange:undefined;window.__render=(typeof renderStemWithHighlights!=='undefined')?renderStemWithHighlights:undefined;\n`;
const re=/\}\)\(\);\s*$/;s=s.replace(re,x=>snip+x);
const ph=html.slice(0,m.index)+'<script>'+s+'</script>'+html.slice(m.index+m[0].length);
const dom=new JSDOM(ph,{runScripts:'dangerously',url:'http://localhost/',pretendToBeVisual:true});
const w=dom.window,d=w.document;
setTimeout(()=>{
 const Q=w.__Q,load=w.__load;
 const idx=Q.findIndex(q=>q.id===42);
 load(idx);
 const stem=d.getElementById('question-stem');
 const T1=stem.textContent;
 // highlight a range that starts in prose and ends inside the table cells
 const start=T1.indexOf('Hematocrit'); const end=T1.indexOf('12.5')+4;
 console.log('range',start,end,'covers:',JSON.stringify(T1.slice(start,end)));
 w.__add(idx,start,end); w.__render();
 const T2=stem.textContent;
 const marks=[...stem.querySelectorAll('mark.highlighted')];
 const markedText=marks.map(x=>x.textContent).join('');
 console.log('text stable across re-render:',T1===T2);
 console.log('marked text == requested slice:',markedText===T1.slice(start,end));
 console.log('num mark fragments:',marks.length);
 // remove highlight by clicking a fragment, ensure it clears
 marks[0].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
 console.log('after click, marks remaining:',stem.querySelectorAll('mark.highlighted').length);
 console.log('DONE');
},400);
