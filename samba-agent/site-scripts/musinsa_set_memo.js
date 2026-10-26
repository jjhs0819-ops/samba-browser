// 무신사 주문서 '배송 요청사항'을 직접입력으로 바꾸고 args.memo 를 그대로 넣은 뒤 되읽는다. 결제 없음.
// Lazada 배대지 주문의 '[해외묶음번호-…]'는 빠지면 묶음 배송이 안 된다 — 무조건 넣는다(사용자 2026-10-26)
// args: memo, tab · 반환 {ok, memo, note}
const memo = String(args.memo || '').trim()
if (!memo) return { ok: true, memo: '', note: 'no memo' }
const ofs = (await tabs.list()).filter(t => t.url && t.url.includes('/order/order-form'))
const ot = args.tab ? ofs.find(t => t.id === args.tab) : ofs.length === 1 ? ofs[0] : null
if (!ot) return { ok: false, memo: null, note: ofs.length ? 'order forms ' + ofs.length + ' open — pass args.tab' : 'no order-form tab open' }
await tabs.switch(ot.id)
const lines = async () => (await page.get({ interactive: true })).tree.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const box = async () => (await lines()).find(l => /textbox "최대 50자/.test(l))
const val = l => ((l || '').match(/value="([^"]*)"/) || [])[1] || ''
let fb = await box()
if (!fb) {
  const sel = (await lines()).find(l => /textbox "배송 요청사항/.test(l))
  if (!sel) return { ok: false, memo: null, note: '배송 요청사항 칸 없음' }
  try { await page.click(parseInt(sel.slice(1))) } catch (e) {}
  let di = null
  for (let i = 0; i < 10 && !di; i++) { await sleep(300); di = (await lines()).find(l => /\] button "직접입력"$/.test(l)) }
  if (!di) return { ok: false, memo: null, note: '직접입력 선택지 없음' }
  try { await page.click(parseInt(di.slice(1))) } catch (e) {}
  for (let i = 0; i < 10 && !(fb = await box()); i++) await sleep(300)
}
if (!fb) return { ok: false, memo: null, note: '직접입력 칸이 안 열림' }
const fid = parseInt(fb.slice(1))
await page.type(fid, memo, false)
await sleep(400)
// 입력하면 칸 이름이 입력값으로 바뀐다 — 번호로 되읽는다
const got = val((await lines()).find(l => l.startsWith('[' + fid + ']')))
return { ok: got === memo, memo: got, note: got === memo ? null : '되읽은 메모가 다르다' }
