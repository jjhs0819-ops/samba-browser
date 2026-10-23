// 더현대Hi 주문서 직배 배송지 입력 — '변경' → 신규(직접 입력) 폼에 이름·주소를 넣는다. 2026-10-23 초안(로그인 뒤 화면 실측 필요).
// 전화 칸은 비워 두고 phone_field_id(s) 로 돌려준다 — 하네스가 키마스터 신원정보(업무폰)로 채운다(고객 번호 안 씀).
// 저장·반영은 thehyundai_confirm_shipping 이 한다(전화가 채워진 뒤). 버튼·칸은 글자로만 찾고 못 찾으면 error 로 멈춘다.
// args: name, address, address_detail, postal_code, profile, tab · 반환 {name,address,zip,address_detail,phone_field_id(s),name_field_id,error}
function pe(t) { return t.split('PAGE TEXT')[0].split('\n').map(l => l.match(/^\[(\d+)\] (\S+)(?: "([^"]*)")?/)).filter(Boolean).map(m => ({ id: +m[1], role: m[2], t: (m[3] || '').trim() })) }
const Q = async q => pe((await page.get({ query: q })).tree)
const L = (a, f) => { const c = a.filter(f); return c.length ? c[c.length - 1] : null }
const A = args || {}
const name = String(A.name || '').trim(), addr = String(A.address || '').trim(), det0 = String(A.address_detail || A.detail || '').trim()
const R = { name: null, address: null, saved: false }
if (!name || !addr) return { ...R, error: 'name/address missing' }
if (A.tab) { try { await tabs.switch(String(A.tab)) } catch (e) { return { ...R, error: 'tab not found' } } }
// 검색어 = 도로명+건물번호(지번이면 동·리+번지), 나머지는 상세주소 — 롯데온 배송지 스크립트와 같은 규칙
const joined = !!(det0 && !det0.startsWith(addr) && /^\d/.test(det0) && /(로|길)\s*$/.test(addr))
const full = det0 && det0.startsWith(addr) ? det0 : (joined ? addr + ' ' + det0 : addr)
const cut = full.match(/^(.*?(?:로|길)\s*\d+(?:-\d+)?)(?![\d-])[,\s]*(.*)$/)
const jb = cut ? null : full.match(/^(.*?[가-힣](?:동|리|가)\s+\d+(?:-\d+)?)(?![\d-])[,\s]*(.*)$/)
const query = cut ? cut[1] : (jb ? jb[1] : addr)
const rest = (jb ? jb[2] : '').trim()
const detail = (det0 && !det0.startsWith(addr) && !joined) ? ((rest && !det0.includes(rest) ? rest + ' ' : '') + det0) : (cut ? cut[2] : rest).trim()
await page.waitFor(/배송지|받는 ?분|수령인/, 8000)
// 1) 배송지 변경 → 2) 신규·직접 입력
const addRe = /신규\s*(배송지|입력)?|새\s*배송지|배송지\s*(추가|등록)|직접\s*입력|새로\s*입력/
const findAdd = async () => L(await Q('배송지'), e => /button|link|tab|radio|clickable/.test(e.role) && addRe.test(e.t)) || L(await Q('입력'), e => /button|link|tab|radio|clickable/.test(e.role) && addRe.test(e.t)) || L(await Q('신규'), e => /button|link|tab|radio|clickable/.test(e.role) && addRe.test(e.t))
let add = await findAdd()
if (!add) {
  const ch = L(await Q('변경'), e => /button|link|clickable/.test(e.role) && /^(배송지\s*)?변경$/.test(e.t))
  if (!ch) { const at = String(await page.url()).replace(/^https?:\/\//, '').split('?')[0].slice(0, 60); return { ...R, error: 'change-button-nf @' + at } }
  await page.click(ch.id)
  for (let i = 0; i < 8 && !add; i++) { await sleep(800); add = await findAdd() }
}
if (!add) return { ...R, error: 'add-address-button-nf' }
await page.click(add.id); await sleep(1500)
const tb = e => /textbox|searchbox/.test(e.role)
const n = L(await Q('받는'), tb) || L(await Q('수령인'), tb) || L(await Q('이름'), tb)
if (!n) return { ...R, error: 'name-input-nf' }
await page.type(n.id, name, false)
R.name_field_id = n.id
// 전화 칸 — 휴대폰/연락처 글자가 붙은 입력칸(1~3칸). 번호는 넣지 않는다
let ph = (await Q('휴대폰')).filter(tb)
if (!ph.length) ph = (await Q('연락처')).filter(tb)
if (!ph.length) ph = (await Q('전화')).filter(tb)
ph = ph.filter(e => e.id !== n.id).slice(0, 3)
if (ph.length === 1) R.phone_field_id = ph[0].id; else if (ph.length) R.phone_field_ids = ph.map(e => e.id)
const z = L(await Q('우편번호'), e => /button|link|clickable/.test(e.role)) || L(await Q('주소'), e => /button|link|clickable/.test(e.role) && /주소\s*(찾기|검색)|검색/.test(e.t))
if (!z) return { ...R, error: 'zip-button-nf' }
await page.click(z.id); await sleep(1500)
// 주소 검색창(카카오 우편번호 등, 하위 프레임일 수 있다)
const si = L(await Q('예)'), tb) || L(await Q('도로명'), tb) || L(await Q('검색'), tb)
if (!si) return { ...R, error: 'address-search-input-nf', note: '주소 검색 팝업 안 뜸 또는 입력칸 못 찾음(실측 필요)' }
const nums = s => (String(s).match(/[0-9]+/g) || [])
const want = nums(query)
const NS = s => String(s).replace(/\s+/g, '')
const roadKey = ((full.match(/[가-힣A-Za-z0-9.]+(?:로|길)(?=\s*\d)/) || full.match(/[가-힣]+(?:동|리|가)(?=\s+\d)/) || [''])[0])
const guKeys = (full.match(/[가-힣]{1,6}(?:시|군|구)(?=\s)/g) || []).filter(k => !/(특별자치|광역|특별)시$/.test(k) && !/^(서울|부산|대구|인천|광주|대전|울산|세종)시$/.test(k))
const okLine = t => { const s = NS(t); if (roadKey && !s.includes(NS(roadKey))) return false; if (guKeys.length && !guKeys.some(k => s.includes(k))) return false; return want.length ? want.every(x => nums(t).includes(x)) : true }
async function search(q) {
  await page.type(si.id, q, true)
  for (let i = 0; i < 8; i++) {
    await sleep(700)
    const ls = (await Q(roadKey || q.split(' ').pop())).filter(e => e.id !== si.id && !tb(e) && e.t.length > 6 && okLine(e.t))
    if (ls.length) return ls[0]
  }
  return null
}
let hit = await search(query)
if (!hit) { const sp = query.replace(/([가-힣])(\d)/g, '$1 $2'); if (sp !== query) hit = await search(sp) }
if (!hit) return { ...R, error: 'address-result-nf', note: '주소 검색 결과 없음(도로명·시군구·번호 일치 줄 없음): ' + query }
await page.click(hit.id); await sleep(1500)
const d = L(await Q('상세'), tb)
if (!d) return { ...R, error: 'detail-input-nf' }
if (detail) await page.type(d.id, detail, false)
// 되읽기 대조용 — 넣으려던 주소가 아니라 실제로 고른 검색 결과 줄
R.zip = (hit.t.match(/\b(\d{5})\b/) || [])[1] || (A.postal_code || null)
R.name = name
R.address = hit.t.replace(/\b\d{5}\b/, '').replace(/^(도로명|지번)\s*/, '').trim()
R.address_detail = detail || null
return R
