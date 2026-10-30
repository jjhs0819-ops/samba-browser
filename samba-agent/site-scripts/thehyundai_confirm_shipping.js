// 더현대Hi 배송지 확정 — set_shipping 이 채우고 하네스가 전화까지 넣은 폼을 '배송지 저장'으로 저장하고, 목록에서 그 항목을
// '선택'해 주문서에 반영한 뒤 주문서 '배송지 정보'를 되읽는다. 2026-10-28.
// args: name, address, address_detail, profile, tab, name_id, phone_id, road_id, detail_id · 반환 {ok,name,address,zip,order_tab,note}
const OF = /thehyundai\.com\/shop\/order(?:[?#]|$)/
const tree = async () => String((await page.get({})).tree || '')
const linesOf = tr => tr.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const textOf = tr => (tr.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const idOf = l => parseInt(String(l).slice(1))
const valOf = l => ((l || '').match(/value="([^"]*)"/) || [])[1] || ''
const norm = s => String(s || '').replace(/[\s()·,-]/g, '')
const key = s => { const m = String(s || '').match(/([가-힣A-Za-z0-9.]+(?:로|길))\s*(\d+(?:-\d+)?)/); return m ? m[1] + m[2] : '' }
const fail = (note, x) => ({ ok: false, note, ...(x || {}) })
const name = String(args.name || '').trim(), addr0 = String(args.address || '').trim(), det0 = String(args.address_detail || '').trim()
// 주소에 건물번호가 없고 상세가 번호로 시작하면('…도척로' + '404-6, 101동…') 번호를 주소로 옮긴다(실기 10-29 356764)
const n0 = key(addr0) ? null : det0.match(/^\s*(\d+(?:-\d+)?)\s*,?\s*/)
const addr = n0 ? `${addr0} ${n0[1]}` : addr0, det = n0 ? det0.slice(n0[0].length).trim() : det0
const cand = (await tabs.list()).filter(t => OF.test(t.url || '') && (!args.tab || t.id === args.tab))
if (cand.length !== 1) return fail(cand.length ? 'order form ambiguous' : 'no order tab')
const tab = cand[0].id
await tabs.switch(tab)
let tr = await tree()
// 폼 되읽기 — 넣은 칸이 그대로인지(번호로)
const byId = id => linesOf(tr).find(l => l.startsWith(`[${id}] `)) || ''
if (args.name_id && norm(valOf(byId(args.name_id))) !== norm(name)) return fail('폼 이름이 넣은 값과 다르다', { order_tab: tab })
if (args.phone_id && valOf(byId(args.phone_id)).replace(/\D/g, '').length < 10) return fail('폼 전화가 비었다', { order_tab: tab })
if (args.road_id && key(valOf(byId(args.road_id))) !== key(addr)) return fail('폼 주소가 넣은 값과 다르다', { order_tab: tab })
// 주소록이 쌓이면 요소 목록(150개 상한)에서 폼 맨 끝 '배송지 저장'이 잘린다(실기 10-30 3B2507: 0개) — 없으면 찾기로 찾는다
let save = linesOf(tr).filter(l => /\] button "배송지 저장"$/.test(l))
if (!save.length) save = linesOf(String(await page.find('배송지 저장'))).filter(l => /\] button "배송지 저장"/.test(l))
if (save.length !== 1) return fail(`배송지 저장 버튼 ${save.length}개`, { order_tab: tab })
await page.click(idOf(save[0]))
// 저장 뒤 목록으로 돌아온다(안내창이 뜨면 문구를 남기고 닫는다)
let notes = []
for (let i = 0; i < 12; i++) {
  await sleep(500); tr = await tree()
  const ov = tr.match(/^OVERLAY: "([^"]*)" .*close ids: \[(\d+)/m)
  if (linesOf(tr).some(l => /textbox .*name=receiver/.test(l))) {
    const ok = linesOf(tr).filter(l => /\] button "확인"$/.test(l)).pop()
    if (ok && i > 2) { notes.push(textOf(tr).slice(-60)); await page.click(idOf(ok)); await sleep(400) }
    continue
  }
  if (/배송지 추가/.test(textOf(tr))) break
  if (ov && !/배송지 목록/.test(ov[1])) { notes.push(ov[1].slice(0, 40)); try { await page.click(parseInt(ov[2])) } catch (e) {} }
}
if (linesOf(tr).some(l => /textbox .*name=receiver/.test(l))) return fail('배송지 저장 뒤 폼이 안 닫힘' + (notes.length ? `(안내: ${notes.join(' / ')})` : ''), { order_tab: tab })
// 목록에서 그 항목 '선택' — 줄 모양 '배송지명 / 받는 분 …[우편번호] 주소'. 저장 직후 목록이 다시 그려지는 중에 읽으면
// 엉뚱한 줄을 누른다(실기 10-29: 고객 대신 사무실 줄이 선택됨) — 고른 뒤 주문서를 되읽어 다르면 목록을 다시 열어 고른다
const zip = String(args.postal_code || '').replace(/\D/g, '')
const secOf = ot => (ot.split('배송지 정보')[1] || '').split('배송정보 변경')[0].trim()
const same = sec => norm(sec.split(/ |기본/)[0]) === norm(name) && (zip ? sec.includes(`(${zip})`) : key(sec) === key(addr))
let sec = ''
for (let k = 0; k < 3; k++) {
  if (k) {
    const chg = linesOf(await tree()).filter(l => /\] button "배송정보 변경"$/.test(l)).pop()
    if (!chg) break
    await page.click(idOf(chg))
    for (let i = 0; i < 10 && !/배송지 추가/.test(textOf(tr = await tree())); i++) await sleep(500)
  }
  await sleep(800); tr = await tree()
  const t = textOf(tr)
  const blocks = t.slice(t.indexOf('배송지 추가') + 6).split(/ 선택(?= |$)/).map(s => s.trim()).filter(s => / \/ /.test(s))
  const picks = linesOf(tr).filter(l => /\] button "선택"$/.test(l))
  let hit = -1
  if (blocks.length >= picks.length) blocks.slice(0, picks.length).forEach((b, i) => {
    if (hit >= 0) return
    const who = (b.split(' / ')[1] || '').split(/ 기본| 수정/)[0]
    const tail = b.replace(/ 배송요청사항:.*$/, '')
    if (norm(who) === norm(name) && (zip ? tail.includes(`[${zip}]`) : key(tail) === key(addr)) && (!det || norm(tail).includes(norm(det)))) hit = i
  })
  if (hit < 0) return fail('저장 뒤 목록에 없음', { order_tab: tab })
  await page.click(idOf(picks[hit])); await sleep(1500)
  const m = (await tree()).match(/^OVERLAY: "배송지 목록[^"]*" .*close ids: \[(\d+)/m)
  if (m) { try { await page.click(parseInt(m[1])) } catch (e) {} await sleep(500) }
  sec = secOf(textOf(await tree()))
  if (same(sec)) break
  notes.push(`선택 ${k + 1}회째 주문서 다름`)
}
return { ok: true, name: sec.split(/ |기본/)[0], address: sec.replace(/^.*?\(\d{5}\)\s*/, ''), zip: (sec.match(/\((\d{5})\)/) || [])[1] || null, order_tab: tab, note: notes.join(' / ') || null }
