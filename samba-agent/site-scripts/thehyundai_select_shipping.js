// 더현대Hi 주문서 '배송정보 변경' 목록에서 이름·주소가 같은 기존 배송지를 '선택'해 주문서에 반영한다(새로 만들지 않음). 2026-10-28.
// 목록 글자: '<이름> / <이름> [기본 배송지] 수정 [삭제] <전화> [우편번호] <주소> [배송요청사항: …] 선택' 이 항목마다 반복된다.
// args: name, address, address_detail, profile, tab · 반환 {ok,name,address,zip,order_tab,note}
const OF = /thehyundai\.com\/shop\/order(?:[?#]|$)/
const tree = async () => String((await page.get({})).tree || '')
const linesOf = tr => tr.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const textOf = tr => (tr.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const norm = s => String(s || '').replace(/[\s()·,-]/g, '')
const key = s => { const m = String(s || '').match(/([가-힣A-Za-z0-9.]+(?:로|길))\s*(\d+(?:-\d+)?)/); return m ? m[1] + m[2] : '' }
const fail = (note, x) => ({ ok: false, note, ...(x || {}) })
const name = String(args.name || '').trim(), addr = String(args.address || '').trim(), det = String(args.address_detail || '').trim()
const cand = (await tabs.list()).filter(t => OF.test(t.url || '') && (!args.tab || t.id === args.tab))
if (cand.length !== 1) return fail(cand.length ? 'order form ambiguous' : 'no order tab')
const tab = cand[0].id
await tabs.switch(tab)
const close = async () => { const m = (await tree()).match(/^OVERLAY: "배송지 목록[^"]*" .*close ids: \[(\d+)/m); if (m) { try { await page.click(parseInt(m[1])) } catch (e) {} await sleep(500) } }
const open = linesOf(await tree()).find(l => /\] button "배송정보 변경"$/.test(l))
if (!open) return fail('배송정보 변경 버튼 없음', { order_tab: tab })
await page.click(parseInt(open.slice(1)))
if (!(await page.waitFor('배송지 추가', 6000))) return fail('배송지 목록 안 열림', { order_tab: tab })
await sleep(500)
const tr = await tree()
const t = textOf(tr)
const body = t.slice(t.indexOf('배송지 추가') + 6)
// 항목 = '선택' 으로 끝나는 덩어리. '선택' 버튼은 화면 순서대로 항목과 짝이다
const blocks = body.split(/ 선택(?= |$)/).map(s => s.trim()).filter(s => / \/ /.test(s))
const pickBtns = linesOf(tr).filter(l => /\] button "선택"$/.test(l))
if (!blocks.length || blocks.length !== pickBtns.length) { await close(); return fail(`목록 해석 실패(${blocks.length}/${pickBtns.length})`, { order_tab: tab }) }
const wantKey = key(addr), wantDet = norm(det)
let hit = -1
blocks.forEach((b, i) => {
  if (hit >= 0) return
  const nm = b.split(' / ')[0].trim()
  if (norm(nm) !== norm(name)) return
  const tail = b.replace(/ 배송요청사항:.*$/, '')
  if (!wantKey || key(tail) !== wantKey) return
  if (wantDet && !norm(tail).includes(wantDet)) return
  hit = i
})
if (hit < 0) { await close(); return fail('목록에 없음', { order_tab: tab }) }
await page.click(parseInt(pickBtns[hit].slice(1)))
await sleep(1500)
await close()
// 주문서 '배송지 정보' 되읽기
const ot = textOf(await tree())
const sec = (ot.split('배송지 정보')[1] || '').split('배송정보 변경')[0].trim()
const zip = (sec.match(/\((\d{5})\)/) || [])[1] || null
const shownName = sec.split(/ |기본/)[0]
const shownAddr = sec.replace(/^.*?\(\d{5}\)\s*/, '')
return { ok: true, name: shownName, address: shownAddr, zip, order_tab: tab, note: null }
