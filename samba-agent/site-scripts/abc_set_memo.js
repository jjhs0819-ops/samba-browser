// ABC마트·그랜드스테이지 주문서 '배송시 요청사항'을 '직접입력'으로 바꾸고 args.memo 를 그대로 넣은 뒤 되읽는다. 결제 없음.
// Lazada 배대지 주문의 '[해외묶음번호-…]'는 빠지면 묶음 배송이 안 된다 — 무조건 넣는다(사용자 2026-10-26)
// args: memo, tab · 반환 {ok, memo, note}
const memo = String(args.memo || '').trim()
if (!memo) return { ok: true, memo: '', note: 'no memo' }
if (memo.length > 40) return { ok: false, memo: null, note: '메모가 40자를 넘는다' }
const isOrderUrl = u => /^https:\/\/(abcmart|grandstage)\.a-rt\.com\/order(?:[?#]|$)/.test(u || '')
const cand = ((await tabs.list()) || []).filter(t => isOrderUrl(t.url) && (!args.tab || t.id === args.tab))
if (cand.length !== 1) return { ok: false, memo: null, note: cand.length ? `order form ambiguous: ${cand.length} tabs` : 'no order tab' }
await tabs.switch(cand[0].id)
const lines = async () => (await page.get({ interactive: true })).tree.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const idOf = l => parseInt(String(l).slice(1))
const val = l => ((l || '').match(/value="([^"]*)"/) || [])[1] || ''
const box = async () => (await lines()).find(l => /\] textbox "배송 메시지/.test(l))
let fb = await box()
if (!fb) {
  const cb = (await lines()).find(l => /\] combobox "배송 시 요청사항/.test(l))
  if (!cb) return { ok: false, memo: null, note: '배송시 요청사항 칸 없음' }
  try { await page.click(idOf(cb)) } catch (e) {}
  let op = null
  for (let i = 0; i < 10 && !op; i++) { await sleep(300); op = (await lines()).filter(l => /\] option "직접입력"$/.test(l)).pop() }
  if (!op) return { ok: false, memo: null, note: '직접입력 선택지 없음' }
  try { await page.click(idOf(op)) } catch (e) {}
  for (let i = 0; i < 10 && !(fb = await box()); i++) await sleep(300)
}
if (!fb) return { ok: false, memo: null, note: '배송 메시지 칸이 안 열림' }
await page.type(idOf(fb), memo, false)
await sleep(400)
const got = val((await lines()).find(l => l.startsWith('[' + idOf(fb) + ']')))
return { ok: got === memo, memo: got, note: got === memo ? null : '되읽은 메모가 다르다' }
