// 패션플러스 주문서 '배송메모'를 '직접 입력하기(20자 이내)'로 바꾸고 args.memo 를 그대로 넣은 뒤 되읽는다. 결제 없음.
// Lazada 배대지 주문의 '[해외묶음번호-…]'는 빠지면 묶음 배송이 안 된다 — 무조건 넣는다(사용자 2026-10-26)
// args: memo, tab · 반환 {ok, memo, note}
const OF = /fashionplus\.co\.kr\/order\/\d+(?:[?#]|$)/
const memo = String(args.memo || '').trim()
if (!memo) return { ok: true, memo: '', note: 'no memo' }
if (memo.length > 20) return { ok: false, memo: null, note: '메모가 20자를 넘는다' }
const cand = (await tabs.list()).filter(t => OF.test(t.url || '') && (!args.tab || t.id === args.tab))
if (cand.length !== 1) return { ok: false, memo: null, note: cand.length ? `order form ambiguous: ${cand.length} tabs` : 'no order tab' }
await tabs.switch(cand[0].id)
const lines = async () => (await page.get({ interactive: true })).tree.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const idOf = l => parseInt(String(l).slice(1))
const val = l => ((l || '').match(/value="([^"]*)"/) || [])[1] || ''
const cb = (await lines()).find(l => /combobox "배송메모/.test(l))
if (!cb) return { ok: false, memo: null, note: '배송메모 선택칸 없음' }
// 직접 입력 칸은 '직접 입력하기'를 고르면 새로 생기는 입력칸이다 — 고르기 전후 입력칸을 비교해 찾는다
// (번호 순서로 고르면 적립금 칸을 잡는다). 이미 직접 입력이면 다른 항목으로 바꿨다가 다시 고른다
const tbs = async () => (await lines()).filter(l => /\] textbox/.test(l)).map(idOf)
if (/value="직접 입력/.test(cb)) { try { await page.select(idOf(cb), '배송 전 연락 바랍니다') } catch (e) {} await sleep(600) }
const before = new Set(await tbs())
try { await page.select(idOf(cb), '직접 입력하기(20자 이내)') } catch (e) {}
let fid = null
for (let i = 0; i < 10 && !fid; i++) { await sleep(300); fid = (await tbs()).find(id => !before.has(id)) || null }
const c2 = (await lines()).find(l => l.startsWith('[' + idOf(cb) + ']'))
if (!/value="직접 입력/.test(c2 || '')) return { ok: false, memo: null, note: '직접 입력으로 못 바꿈' }
if (!fid) return { ok: false, memo: null, note: '직접 입력 칸이 안 열림' }
const fb = '[' + fid + ']'
await page.type(idOf(fb), memo, false)
await sleep(400)
const got = val((await lines()).find(l => l.startsWith('[' + idOf(fb) + ']')))
return { ok: got === memo, memo: got, note: got === memo ? null : '되읽은 메모가 다르다' }
