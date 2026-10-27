// 패션플러스 적립금 사용 해제 — 새 배송지 등록 직전에 '적립금 모두사용'을 끄고 사용액을 0원으로 만든다. 결제 없음.
// 실기 2026-10-27: 적립금 7,550원을 쓴 주문서에서 새 배송지 5건이 모두 실패했다 — '등록하기' 뒤 사이트 안내
// '적립금 7,550 원을 사용 합니다.'가 뜨고 창이 안 닫힌 채 주소록에도 저장되지 않음(3건), 우편번호를 골라도 주소가 폼에
// 안 들어감(2건). 적립금 0원 주문서의 새 배송지는 통과했다(10-25). 하네스가 배송지 확정 뒤 order_prep 으로 다시 적용한다.
// 탭: args.tab > 이 레인의 패션플러스 주문서 탭 하나 · args: profile, tab
// 반환 {ok, used_before, total_before, used, total, order_tab, note}
const OF = /fashionplus\.co\.kr\/order\/\d+(?:[?#]|$)/
const num = s => parseInt(String(s || '').replace(/[^\d]/g, ''), 10) || 0
const get = async () => { for (let i = 0; i < 4; i++) { try { return String((await page.get({})).tree || '') } catch (e) { await sleep(1200) } } return '' }
const linesOf = tr => tr.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const textOf = tr => (tr.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const fail = (note, x) => ({ ok: false, note, ...(x || {}) })
const cand = (await tabs.list()).filter(t => OF.test(t.url || '') && (!args.tab || t.id === args.tab))
if (cand.length !== 1) return fail(cand.length ? `order form ambiguous: ${cand.length} tabs` : 'no order tab')
const tab = cand[0].id
await tabs.switch(tab)
const read = async () => {
  const tr = await get(), t = textOf(tr)
  return {
    tr,
    used: num((t.match(/적립금 사용액 - ([\d,]+)/) || [])[1]),
    total: num((t.match(/총 결제 예상금액 \(\d+건\) ([\d,]+)/) || [])[1])
  }
}
// 화면을 덮은 안내 레이어는 닫는다(문구만 사유로 남긴다)
const notes = []
const closeOverlay = async tr => {
  const ov = tr.match(/^OVERLAY: "([^"]*)" is covering the page - close ids: \[(\d+)/m)
  if (!ov) return false
  notes.push(ov[1].replace(/\s+/g, ' ').slice(0, 40))
  try { await page.click(parseInt(ov[2])) } catch (e) {}
  await sleep(400)
  return true
}
// 라벨 바로 앞 체크박스 — 요소 번호(라벨-1)로 찾는다(order_prep 과 같은 방식, 2026-10-26)
const near = (ls, lab, d) => { const l = ls.find(x => x.includes(`clickable "${lab}"`)); return l ? ls.find(x => x.startsWith(`[${parseInt(l.slice(1)) + d}] `)) || '' : '' }
let r = await read()
const usedBefore = r.used, totalBefore = r.total
if (!usedBefore) return { ok: true, used_before: 0, total_before: totalBefore, used: 0, total: totalBefore, order_tab: tab, note: null }

// 1) '적립금 모두사용'이 켜져 있으면 끈다
let ls = linesOf(r.tr)
const lab = ls.find(x => x.includes('clickable "적립금 모두사용"'))
const box = near(ls, '적립금 모두사용', -1)
if (lab && /value="on"/.test(box)) { try { await page.click(parseInt(lab.slice(1))) } catch (e) {} }
for (let i = 0; i < 8; i++) { await sleep(400); r = await read(); if (await closeOverlay(r.tr)) continue; if (!r.used) break }

// 2) 그래도 남았으면 사용 칸에 0을 넣고 '적용'
if (r.used) {
  ls = linesOf(r.tr)
  const input = near(ls, '적립금 모두사용', 1)
  const ap = ls.find(l => /button "적용"$/.test(l))
  if (/textbox/.test(input)) {
    try { await page.type(parseInt(input.slice(1)), '0', false) } catch (e) {}
    if (ap) { try { await page.click(parseInt(ap.slice(1))) } catch (e) {} }
    for (let i = 0; i < 8; i++) { await sleep(400); r = await read(); if (await closeOverlay(r.tr)) continue; if (!r.used) break }
  }
}
const note = notes.length ? `안내: ${notes.join(' / ')}` : null
if (r.used) return fail(`적립금 해제 안 됨(사용 ${r.used}원 남음)`, { used_before: usedBefore, total_before: totalBefore, used: r.used, total: r.total, order_tab: tab })
return { ok: true, used_before: usedBefore, total_before: totalBefore, used: r.used, total: r.total, order_tab: tab, note }
