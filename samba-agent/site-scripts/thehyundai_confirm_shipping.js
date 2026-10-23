// 더현대Hi 직배 배송지 확정 — set_shipping 이 채우고 하네스가 전화(업무폰)까지 넣은 폼을 저장·적용해 주문서에 반영하고,
// 주문서에서 받는 분·주소를 되읽는다. 기본 배송지로 설정은 켜지 않는다. 2026-10-23 초안(로그인 뒤 화면 실측 필요).
// args: name, address, profile, tab, name_id, phone_id · 반환 {ok,name,address,note}
function pe(t) { return t.split('PAGE TEXT')[0].split('\n').map(l => l.match(/^\[(\d+)\] (\S+)(?: "([^"]*)")?(.*)$/)).filter(Boolean).map(m => ({ id: +m[1], role: m[2], t: (m[3] || '').trim(), rest: m[4] || '' })) }
const Q = async q => pe((await page.get({ query: q })).tree)
const L = (a, f) => { const c = a.filter(f); return c.length ? c[c.length - 1] : null }
const text = async () => ((await page.get({})).tree.split('PAGE TEXT:')[1] || '').replace(/\s+/g, ' ')
const A = args || {}
const name = String(A.name || '').trim(), addr = String(A.address || '').trim()
const R = { ok: false, name: null, address: null }
if (!name || !addr) return { ...R, note: 'name/address missing' }
if (A.tab) { try { await tabs.switch(String(A.tab)) } catch (e) { return { ...R, note: 'tab not found' } } }
// 전화 칸이 비어 있으면 저장하지 않는다(업무폰을 못 넣은 채 반영되면 안 된다)
if (A.phone_id) { const p = (await page.get({})).tree.split('\n').find(l => l.startsWith(`[${A.phone_id}] `)); if (p && /value=""/.test(p)) return { ...R, note: '전화 칸이 비어 있다 — 저장 안 함' } }
// '기본 배송지로 설정'은 켜지 않는다(켜져 있으면 끈다)
const def = L(await Q('기본 배송지'), e => /checkbox/.test(e.role))
if (def && /value="on"|checked/.test(def.rest)) { await page.click(def.id); await sleep(300) }
const saveRe = /^(저장|저장하기|등록|등록하기|적용|적용하기|확인|입력 ?완료|배송지 ?저장|이 주소로 배송|선택)$/
const btn = async () => L(await Q('저장'), e => /button|link|clickable/.test(e.role) && saveRe.test(e.t)) || L(await Q('등록'), e => /button|link|clickable/.test(e.role) && saveRe.test(e.t)) || L(await Q('적용'), e => /button|link|clickable/.test(e.role) && saveRe.test(e.t)) || L(await Q('확인'), e => /button|link|clickable/.test(e.role) && saveRe.test(e.t))
const b = await btn()
if (!b) return { ...R, note: 'save button not found(실측 필요)' }
await page.click(b.id); await sleep(1500)
const ov = ((await page.get({})).tree.match(/OVERLAY: "([^"]{0,80})/) || [])[1]
if (ov && /입력|확인해|올바르|필수/.test(ov)) return { ...R, note: '저장 거부: ' + ov }
// 목록 창으로 돌아오면 방금 항목을 고른다(이름이 같은 줄의 '선택')
const pickBtn = L(await Q('선택'), e => /button|clickable/.test(e.role) && /^(선택|이 배송지 선택|배송지 선택)$/.test(e.t))
if (pickBtn && (await text()).includes(name)) { await page.click(pickBtn.id); await sleep(1200) }
await page.waitFor(/결제하기/, 8000)
const t = await text()
const NS = s => String(s).replace(/\s+/g, '')
const road = (addr.match(/[가-힣A-Za-z0-9.]+(?:로|길)(?=\s*\d)/) || addr.match(/[가-힣]+(?:동|리|가)(?=\s+\d)/) || [''])[0]
const nameAt = t.indexOf(name)
const roadAt = road ? t.indexOf(road) : -1
if (nameAt < 0) return { ...R, note: '주문서에 받는 분 이름이 없다' }
if (roadAt < 0) return { ...R, note: '주문서에 도로명이 없다: ' + NS(road).slice(0, 12) }
// 되읽은 주소 — 주문서 글자에서 도로명 앞뒤를 잘라 돌려준다(입력값을 그대로 돌려주지 않는다)
const from = Math.max(0, t.lastIndexOf(' ', Math.max(0, roadAt - 24)))
const seg = t.slice(from, roadAt + road.length + 14).trim()
return { ...R, ok: true, name, address: seg, saved: true }
