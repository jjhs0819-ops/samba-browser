// 패션플러스 주소록 정리 — 기본배송지 하나만 남기고 나머지(삭제 버튼 있는 항목)를 지운다. 주문서는 건드리지 않는다.
// 주문마다 새 배송지를 등록하면 주소록이 계속 늘어난다(무신사는 240개쯤에서 저장이 막혔다, 2026-10-26).
// 패플은 주문서 배송지 창의 '수정'이 눌리지 않아(가려짐) 작업용 항목을 고쳐 쓰지 못한다 — 등록 직전에 비워 1~2개로 유지한다(사용자 2026-10-26)
// 한 번에 최대 args.max(기본 6)개 — run_script 시간 제한. 남은 수(left)를 돌려주면 하네스가 다시 부른다
// args: profile, tab(끝나고 돌아갈 주문서 탭), max · 반환 {ok, deleted, left, note}
const H = 'https://www.fashionplus.co.kr'
const P = args.profile ? { profile: args.profile } : {}
const max = Math.max(1, parseInt(args.max, 10) || 6)
const lines = async () => (await page.get({})).tree.split('PAGE TEXT')[0].split('\n').filter(l => /^\[\d+\]/.test(l))
const tid = (String(await tabs.open({ ...P, url: `${H}/mypage/receive-address` })).match(/tab (\S+)/) || [])[1]
if (!tid) return { ok: false, deleted: 0, left: null, note: 'tab not opened' }
await tabs.switch(tid)
await page.waitFor('배송지 추가하기', 10000)
// 목록은 '배송지 추가하기'보다 늦게 그려진다 — 항목의 '수정'이 보일 때까지
for (let k = 0; k < 25 && !(await lines()).some(l => /\] link "수정"/.test(l)); k++) await sleep(300)
// 목록이 보여도 버튼 동작은 몇 초 뒤에 붙는다(실기: 바로 누르면 확인창이 안 뜬다)
await sleep(4000)
let deleted = 0, note = null
for (let i = 0; i < max; i++) {
  const d = (await lines()).find(l => /\] button "삭제"$/.test(l))
  if (!d) break
  let t = ''
  for (let a = 0; a < 2 && !/삭제하시겠습니까/.test(t); a++) {
    try { await page.click(parseInt(d.slice(1))) } catch (e) {}
    for (let k = 0; k < 12 && !/삭제하시겠습니까/.test(t); k++) { await sleep(400); t = (await page.get({})).tree }
  }
  if (!/삭제하시겠습니까/.test(t)) { note = '삭제 확인창 안 뜸'; break }
  const yes = (await lines()).filter(l => /\] button "확인"$/.test(l)).pop()
  if (!yes) { note = '확인 버튼 없음'; break }
  try { await page.click(parseInt(yes.slice(1))) } catch (e) {}
  for (let k = 0; k < 15; k++) { await sleep(400); if (!/삭제하시겠습니까/.test((await page.get({})).tree)) break }
  await sleep(1500)
  deleted++
}
const left = (await lines()).filter(l => /\] button "삭제"$/.test(l)).length
try { await tabs.close(tid) } catch (e) {}
if (args.tab) { try { await tabs.switch(args.tab) } catch (e) {} }
return { ok: !note, deleted, left, note }
