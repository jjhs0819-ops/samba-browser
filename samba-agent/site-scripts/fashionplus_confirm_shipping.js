// 패션플러스 배송지 확정: set_shipping 이 채우고 하네스가 전화까지 넣은 '새 주소 입력' 폼의 '등록하기'를 눌러 주소록에 등록·선택하고,
// 주문서 배송지를 되읽어 이름·주소를 돌려준다. 기본 배송지로 설정은 켜지 않는다(꺼져 있어야 누른다).
// 실기 2026-10-22~23: 확정 5건이 모두 33초(대기 20회 전부)를 쓰고 '넣은 값과 다르다'로 끝났다 — 등록하기 뒤 창이 안 닫혀
// 주문서에는 예전 배송지가 남아 있었다. 그래서 등록하기 뒤에는
//  ① 사이트 안내(대화상자·레이어·'확인')를 읽어 사유로 남기고 닫는다(창 안 '확인'도 — 예전엔 창 밖만 눌렀다)
//  ② 창이 목록으로 돌아가 있으면 방금 등록한 항목(이름·주소 번호 일치)을 고른다
//  ③ 그래도 주문서가 안 바뀌면 사유를 나눠 돌려준다: 창이 그대로면 '등록하기 뒤 창이 안 닫힘(안내: …)',
//     창은 닫혔는데 주문서가 다르면 '주문서에 받는 분 …'(하네스가 기존 배송지 선택으로 한 번 더 고른다)
// 탭: args.tab > 이 레인의 패션플러스 주문서 탭 하나 · args: name, address, address_detail, profile, tab, name_id, phone_id, zip_id, road_id, detail_id
// 반환 {ok,name,address,zip,order_tab,note}
const OF = /fashionplus\.co\.kr\/order\/\d+(?:[?#]|$)/
// 배송지 창(iframe)이 넘어가는 중에 읽으면 프레임 호출이 시간 초과로 던진다 — 잠깐 쉬고 다시 읽는다
const get = async q => { for (let i = 0; i < 4; i++) { try { return String((await page.get(q || {})).tree || '') } catch (e) { await sleep(1200) } } return '' }
const linesOf = tr => tr.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const textOf = tr => (tr.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const fail = (note, x) => ({ ok: false, note, ...(x || {}) })
const sq = s => String(s || '').replace(/\s+/g, '')
const idOf = l => parseInt(String(l).slice(1))
const name = String(args.name || '').trim(), addr = String(args.address || '').trim(), det = String(args.address_detail || '').trim()
const cand = (await tabs.list()).filter(t => OF.test(t.url || '') && (!args.tab || t.id === args.tab))
if (cand.length !== 1) return fail(cand.length ? `order form ambiguous: ${cand.length} tabs` : 'no order tab')
const tab = cand[0].id
await tabs.switch(tab)
const big = ls => ls.filter(l => /^\[\d{6,}\]/.test(l))
const fr = big(linesOf(await get({})))
const k = fr.findIndex(l => /link "우편번호 찾기"/.test(l))
if (k < 3) return fail('새 주소 입력 폼이 열려 있지 않다', { order_tab: tab })
const valOf = l => ((l || '').match(/value="([^"]*)"/) || [])[1] || ''
// 칸은 set_shipping 이 채운 요소 번호(args.*_id)로 고른다 — 순서로 추측하면 전화를 넣은 뒤 칸 모양이 바뀌어 한 칸씩 밀린다
// (실기 2026-10-22 3건 '폼 이름이 다르다'). 번호가 없거나 못 찾으면 예전 방식: 입력칸만 세서 고른다('지우기' 버튼이 끼어든다, B05369)
const byId = id => (id ? fr.find(l => l.startsWith('[' + id + ']')) : null)
const tb = fr.slice(0, k).filter(l => /textbox/.test(l)).slice(-3)
const nameL = byId(args.name_id) || tb[0], phoneL = byId(args.phone_id) || tb[1], zipL = byId(args.zip_id) || tb[2]
const roadL = byId(args.road_id) || fr.slice(k + 1).find(l => /textbox/.test(l))
const detL = byId(args.detail_id)
// 실패 사유엔 모양만(개인정보 없이) — 글자 수·입력칸 수·번호 일치
const shape = `글자 ${valOf(nameL).length}/${name.length}·입력칸 ${fr.filter(l => /textbox/.test(l)).length}·번호 ${args.name_id ? (byId(args.name_id) ? '일치' : '없음') : '미전달'}`
if (valOf(nameL) !== name) return fail(`폼 이름이 다르다(${shape})`, { order_tab: tab })
if (!valOf(zipL) || !valOf(roadL)) return fail('폼 주소가 비었다', { order_tab: tab })
if (!/value="[^"]+"/.test(phoneL || '')) return fail('전화 칸이 비었다', { order_tab: tab })
// 상세주소가 비어 있으면(주소 선택 콜백이 지운 경우) 다시 넣는다 — 비어 있으면 등록하기가 막힌다
if (det && detL && !valOf(detL)) { try { await page.type(idOf(detL), det, false) } catch (e) {} await sleep(300) }
const def = fr.findIndex(l => /clickable "기본 배송지로 설정"/.test(l))
if (def > 0 && /value="on"/.test(fr[def - 1])) { await page.click(idOf(fr[def])); await sleep(300) }
const reg = fr.find(l => /button "등록하기"/.test(l))
if (!reg) return fail('등록하기 버튼 없음', { order_tab: tab })
// 등록하기 전부터 있던 '확인' 버튼은 안내가 아니다 — 등록하기 뒤에 새로 생긴 것만 누른다
const okBefore = new Set(linesOf(await get({})).filter(l => /button "확인"$/.test(l)).map(idOf))
const dialogOf = r => ((String(r || '').match(/page dialog: "([^"]*)"/) || [])[1] || '')
let msg = ''
try { msg = dialogOf(await page.click(idOf(reg))) } catch (e) { msg = '' }
// 주문서 배송지 블록: '배송지 정보 {이름}배송지 변경 {우편번호} {주소} {전화|배송메모}'
const nums = addr.replace(/^\d{5}\s*/, '').match(/\d+(-\d+)?/g) || []
const sheetOf = t => { const m = t.match(/배송지 정보 (\S+?) ?배송지 변경 (\d{5}) (.+?) (?:0\d{1,2}-?\d{3,4}-?\d{4}|배송메모)/); return m ? { name: m[1], zip: m[2], address: m[3] } : null }
const same = b => !!b && b.name === name && nums.every(n => sq(b.address).includes(n))
let back = null, formOpen = true, picked = false, waited = 0
for (let i = 0; i < 25; i++) {
  await sleep(400)
  waited = i + 1
  const tr = await get({})
  // 화면을 덮은 레이어(사이트 안내) — 문구를 사유로 남기고 닫는다
  const ov = tr.match(/^OVERLAY: "([^"]*)" is covering the page - close ids: \[(\d+)/m)
  if (ov) { msg = msg || ov[1]; try { msg = dialogOf(await page.click(parseInt(ov[2]))) || msg } catch (e) {} continue }
  const ls = linesOf(tr)
  const okBtn = ls.find(l => /button "확인"$/.test(l) && !okBefore.has(idOf(l)))
  // 창 안 안내 레이어 문구를 사유로 남긴다 — '확인 안내'만으로는 거부 사유를 몰랐다(실기 2026-10-25 296757 두 번 실패)
  if (okBtn) { msg = msg || ((textOf(tr).match(/[^.!?]{0,50}(?:요|다|오)[.!]?(?=\s*확인)/) || [])[0] || '확인 안내').trim(); try { msg = dialogOf(await page.click(idOf(okBtn))) || msg } catch (e) {} continue }
  back = sheetOf(textOf(tr))
  if (same(back)) break
  formOpen = ls.some(l => /button "등록하기"/.test(l))
  if (!picked && (!formOpen || i >= 3)) {
    // 창이 배송지 목록으로 돌아왔다(또는 숨은 목록에 새 항목이 생겼다) — 방금 등록한 항목(이름으로 시작하고 주소 번호가
    // 모두 든 줄)을 고른다. 항목을 누르면 창이 넘어가며 클릭이 시간 초과로 던질 수 있다 — 던져도 클릭은 된 것이다
    const hits = big(ls).filter(l => {
      const t = (l.match(/^\[\d+\] link "([^"]*)"/) || [])[1] || ''
      return t.split(/\s+/)[0] === name && nums.every(n => sq(t).includes(n))
    })
    if (hits.length === 1) { picked = true; try { await page.click(idOf(hits[0])) } catch (e) {} continue }
  }
  if (formOpen) continue
  // 창은 닫혔는데 주문서가 아직 옛 값이면 몇 번 더 본다(주문서 갱신이 늦다)
  if (i >= 12) break
}
if (same(back)) return { ok: true, ...back, order_tab: tab, note: null }
const how = `이름 ${back ? (back.name === name ? '같음' : '다름') : '못읽음'}·번호 ${back ? nums.filter(n => sq(back.address).includes(n)).length : 0}/${nums.length}·대기 ${waited}`
const site = msg ? `안내: ${msg.replace(/\s+/g, ' ').slice(0, 40)}` : '안내 없음'
if (formOpen && !picked) return fail(`등록하기 뒤 창이 안 닫힘(${site}·${how})`, { order_tab: tab, ...(back || {}) })
return fail(`주문서에 받는 분이 넣은 값과 다르다(${picked ? '목록 선택함' : '목록 선택 못함'}·${site}·${how})`, { order_tab: tab, ...(back || {}) })
