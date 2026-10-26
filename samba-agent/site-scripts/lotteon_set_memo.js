// 롯데온 주문서 '배송 요청사항'을 '직접 입력'으로 두고 args.memo 를 그대로 넣은 뒤 되읽는다. 결제 없음.
// Lazada 배대지 주문의 '[해외묶음번호-…]'는 빠지면 묶음 배송이 안 된다 — 무조건 넣는다(사용자 2026-10-26)
// 요청사항 칸은 화면 목록엔 안 보이고 글자 찾기(query)로만 잡힌다. 없으면 '배송요청사항' 줄의 '변경'을 눌러 연다
// args: memo, tab · 반환 {ok, memo, note}
function pe(t){const o=[];for(const l of t.split('\n')){const m=l.match(/^\[(\d+)\]\s+(\S+)(?:\s+"([^"]*)")?(?:\s+name=\S+)?(?:\s+value="([^"]*)")?/);if(m)o.push({id:+m[1],role:m[2],text:m[3]||'',value:m[4]!==undefined?m[4]:null});}return o.sort((a,b)=>a.id-b.id);}
const E=async q=>pe((await page.get({query:q})).tree);
const memo=String(args.memo||'').trim();
if(!memo)return{ok:true,memo:'',note:'no memo'};
if(memo.length>25)return{ok:false,memo:null,note:'메모가 25자를 넘는다'};
if(args.tab){try{await tabs.switch(args.tab);}catch(e){}}
const box=async()=>(await E('배송 요청사항 입력')).find(e=>e.role==='textbox')||null;
let tb=await box();
if(!tb){
  const rq=(await E('배송요청사항')).find(e=>/^배송요청사항/.test(e.text));
  const ch=rq&&(await E('변경')).find(e=>e.role==='button'&&e.text==='변경'&&e.id>rq.id);
  if(!ch)return{ok:false,memo:null,note:'배송요청사항 변경 버튼 없음'};
  await page.click(ch.id);
  for(let i=0;i<10&&!(tb=await box());i++)await sleep(300);
}
if(!tb)return{ok:false,memo:null,note:'배송 요청사항 입력칸 없음'};
const di=(await E('직접 입력')).find(e=>e.role==='radio'&&e.text==='직접 입력');
if(di&&di.value!=='on'){await page.click(di.id);await sleep(500);}
await page.type(tb.id,memo,false);await sleep(500);
const got=((await E('배송 요청사항 입력')).find(e=>e.id===tb.id)||(await E(memo)).find(e=>e.id===tb.id)||{}).value;
return{ok:got===memo,memo:got==null?null:got,note:got===memo?null:'되읽은 메모가 다르다'};
