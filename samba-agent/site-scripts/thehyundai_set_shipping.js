// 더현대Hi 주문서 배송지 입력 — '배송정보 변경' 목록에서 '배송지 추가'(주소록 최대 10개: 꽉 차면 맨 아래 항목 '수정'으로 덮어쓴다)
// 폼: 받는사람(receiver)·휴대폰(phone, 비워 두고 하네스가 fill_secret)·주소찾기(창 안 검색 → 결과 라디오 → 상세 주소 → 창의 '배송지 저장')
// ·상세주소(detailAddr). 폼의 '배송지 저장'은 누르지 않는다(확정은 thehyundai_confirm_shipping). 2026-10-28.
// args: name, address, address_detail, postal_code, profile, tab
// 반환 {ok,name,address,address_detail,zip,phone_field_id,name_field_id,road_field_id,detail_field_id,phone_formats,order_tab,note}
const OF = /thehyundai\.com\/shop\/order(?:[?#]|$)/
const tree = async () => String((await page.get({})).tree || '')
const linesOf = tr => tr.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const idOf = l => parseInt(String(l).slice(1))
const valOf = l => ((l || '').match(/value="([^"]*)"/) || [])[1] || ''
const norm = s => String(s || '').replace(/[\s()·,-]/g, '')
const key = s => { const m = String(s || '').match(/([가-힣A-Za-z0-9.]+(?:로|길))\s*(\d+(?:-\d+)?)/); return m ? m[1] + m[2] : '' }
const fail = (note, x) => ({ ok: false, note, ...(x || {}) })
const name = String(args.name || '').trim(), addr = String(args.address || '').trim(), det = String(args.address_detail || '').trim()
const zipWant = String(args.postal_code || '').replace(/\D/g, '')
if (!name || !addr) return fail('name/address missing')
const cand = (await tabs.list()).filter(t => OF.test(t.url || '') && (!args.tab || t.id === args.tab))
if (cand.length !== 1) return fail(cand.length ? 'order form ambiguous' : 'no order tab')
const tab = cand[0].id
await tabs.switch(tab)
const L = async re => linesOf(await tree()).filter(l => re.test(l))
const one = async re => (await L(re))[0]

// 1) 목록 → 추가(꽉 차면 맨 아래 항목 수정)
if (!(await one(/\] button "배송지 추가"$/))) {
  const open = await one(/\] button "배송정보 변경"$/)
  if (!open) return fail('배송정보 변경 버튼 없음', { order_tab: tab })
  await page.click(idOf(open))
  if (!(await page.waitFor('배송지 추가', 6000))) return fail('배송지 목록 안 열림', { order_tab: tab })
  await sleep(500)
}
let mode = 'add'
const picks = await L(/\] button "선택"$/)
if (picks.length >= 10) mode = 'edit'
else {
  await page.click(idOf(await one(/\] button "배송지 추가"$/))); await sleep(1200)
  const full = (await tree()).includes('최대 10개까지 등록')
  if (full) { const ok = (await L(/\] button "확인"$/)).pop(); if (ok) { await page.click(idOf(ok)); await sleep(500) } mode = 'edit' }
}
if (mode === 'edit') {
  const edits = await L(/\] button "수정"$/)
  if (edits.length < 2) return fail('덮어쓸 배송지 없음', { order_tab: tab })
  await page.click(idOf(edits[edits.length - 1])); await sleep(1200)
}
if (!(await page.waitFor('받는사람', 6000))) return fail('배송지 폼 안 열림', { order_tab: tab })
await sleep(400)

// 2) 받는사람·휴대폰(비움)·기본 배송지 끔
let nameL = await one(/textbox .*name=receiver/), phoneL = await one(/textbox .*name=phone/)
if (!nameL || !phoneL) return fail('이름/전화 칸 없음', { order_tab: tab })
await page.type(idOf(nameL), name, false); await sleep(200)
await page.type(idOf(phoneL), '', false); await sleep(200)
const defBox = await one(/\] checkbox "기본 배송지로 선택"/)
if (defBox && /value="on"/.test(defBox)) { const lab = await one(/\] label "기본 배송지로 선택"/); await page.click(idOf(lab || defBox)); await sleep(300) }

// 3) 주소찾기 → 검색 → 결과 고르기 → 상세 주소 → 창의 '배송지 저장'
await page.click(idOf(await one(/\] button "주소찾기"$/))); await sleep(1200)
const box = await one(/textbox "주소를 검색해주세요\."/)
if (!box) return fail('주소 검색 칸 없음', { order_tab: tab })
const q = addr.replace(/\s*\(.*$/, '').trim()
await page.type(idOf(box), q, false); await sleep(200)
await page.click(idOf(await one(/\] button "주소 검색"$/))); await sleep(1800)
const results = await L(/\] radio "우편번호\d{5}도로명/)
if (!results.length) return fail('주소 검색 결과 없음', { order_tab: tab })
const wk = key(addr)
let pick = results.filter(l => zipWant && l.includes('우편번호' + zipWant))
if (pick.length !== 1) pick = results.filter(l => wk && key((l.match(/도로명(.*?)지번/) || [])[1]) === wk)
if (pick.length !== 1 && results.length === 1) pick = results
if (pick.length !== 1) return fail(`주소 검색 결과 ${results.length}건 중 하나로 못 고름`, { order_tab: tab })
const zip = (pick[0].match(/우편번호(\d{5})/) || [])[1] || null
await page.click(idOf(pick[0])); await sleep(1000)
const dBox = await one(/textbox "상세 주소 입력"/)
if (dBox) { await page.type(idOf(dBox), det, false); await sleep(200) }
const saves = await L(/\] button "배송지 저장"$/)
if (saves.length < 2) return fail('주소 창 저장 버튼 없음', { order_tab: tab })
await page.click(idOf(saves[saves.length - 1])); await sleep(1200)

// 4) 폼 되읽기
const tr = await tree()
nameL = linesOf(tr).find(l => /textbox .*name=receiver/.test(l)); phoneL = linesOf(tr).find(l => /textbox .*name=phone/.test(l))
const roadL = linesOf(tr).find(l => /textbox .*name=baseAddr/.test(l)), detL = linesOf(tr).find(l => /textbox .*name=detailAddr/.test(l))
if (!nameL || !roadL) return fail('주소 창 저장 뒤 폼이 닫힘(폼 안 보임)', { order_tab: tab })
if (detL && det && norm(valOf(detL)) !== norm(det)) { await page.type(idOf(detL), det, false); await sleep(200) }
const tr2 = await tree()
const g = re => valOf(linesOf(tr2).find(l => re.test(l)))
const road = g(/name=baseAddr/), dt = g(/name=detailAddr/)
if (key(road) !== wk) return fail('주소가 폼에 안 들어감', { order_tab: tab })
return {
  ok: true, name: g(/name=receiver/), address: road, address_detail: dt, zip,
  phone_field_id: idOf(phoneL), name_field_id: idOf(nameL), road_field_id: idOf(roadL), detail_field_id: detL ? idOf(detL) : null,
  phone_formats: ['digits'], mode, order_tab: tab, note: g(/name=phone/) ? 'phone field not empty' : null
}
