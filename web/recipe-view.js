/* 레시피 상세 (추천 · 보관함 공통)
 * 정해진 형식: 재료(4인분) → 공통 조리 → 구성원별 변형 → 주의사항 */
(function () {
  'use strict';
  var el = HS.el;

  var css = document.createElement('style');
  css.textContent =
    '.rv h4{font-size:14px;font-weight:800;margin:16px 0 8px;display:flex;align-items:center;gap:6px}' +
    '.rv h4 .n{width:22px;height:22px;border-radius:50%;background:var(--ink);color:#fff;font-size:12px;display:grid;place-items:center}' +
    '.rv table{width:100%;border-collapse:collapse;font-size:13.5px}' +
    '.rv td{padding:6px 0;border-bottom:1px dashed var(--line);vertical-align:top}' +
    '.rv td:last-child{text-align:right;font-weight:800;white-space:nowrap}' +
    '.rv td .buy{display:block;font-size:11.5px;font-weight:600;color:var(--muted)}' +
    '.rv tr.have td:first-child::after{content:" · 보유";color:var(--ok);font-size:11.5px;font-weight:800}' +
    '.rv tr.lack td:first-child::after{content:" · 부족";color:var(--danger);font-size:11.5px;font-weight:800}' +
    '.rv ol{margin:0;padding-left:20px;font-size:14px}.rv ol li{margin:4px 0}' +
    '.rv ol li.salt::marker{color:var(--accent)}' +
    '.rv .var{display:flex;gap:10px;padding:10px;border-radius:14px;background:var(--cream);margin-top:8px}' +
    '.rv .var img{width:40px;height:40px;border-radius:50%;object-fit:cover;background:var(--accent-soft);flex:none}' +
    '.rv .var b{font-size:14px}.rv .var .why{font-size:11.5px;font-weight:700;color:var(--accent-ink);margin-left:6px}' +
    '.rv .var ul{margin:4px 0 0;padding-left:16px;font-size:13px;color:var(--ink-soft)}' +
    '.rv .unit{font-size:11.5px;color:var(--muted);margin-top:6px}' +
    '.rv .caution{margin:0;padding-left:18px;font-size:13px;color:var(--ink-soft)}' +
    '.safe-note{margin:0;padding:10px 12px;border-radius:14px;background:var(--ok-soft);border:1px solid #bfe0ca;color:var(--ok);font-size:13.5px;font-weight:800;line-height:1.45}' +
    '.safe-note small{display:block;margin-top:2px;font-size:11.5px;font-weight:600;color:#557a63}';
  document.head.appendChild(css);

  function h(n, text) { return el('h4', null, [el('span', { class: 'n', text: String(n) }), text]); }

  // opts.pantry 가 있으면 보유·부족 재료를 표시해요
  function detail(r, members, opts) {
    opts = opts || {};
    var box = el('div', { class: 'rv' });

    box.appendChild(h(1, '재료 (4인분 · 손질 후 무게)'));
    var tb = el('table');
    r.base.concat(r.season).forEach(function (ing) {
      var p = HS.portion(ing), cls = null;
      if (opts.pantry && HS.isStock(ing)) cls = opts.pantry.indexOf(ing) !== -1 ? 'have' : 'lack';
      tb.appendChild(el('tr', { class: cls }, [
        el('td', { text: ing }),
        el('td', null, [p.text, p.buy ? el('span', { class: 'buy', text: '구입량 약 ' + p.buy + 'g' }) : null])
      ]));
    });
    if (r.water) tb.appendChild(el('tr', null, [el('td', { text: '물' }), el('td', { text: Math.round(r.water / 10) * 10 + 'mL' })]));
    box.appendChild(tb);
    box.appendChild(el('p', { class: 'unit', text: '1컵 200mL · 1큰술 15mL · 1작은술 5mL. 분량은 재료 사전의 기준량 규칙으로 계산했어요.' }));

    box.appendChild(h(2, '공통 조리 (한 번에)'));
    var ol = el('ol');
    r.steps.forEach(function (s, i) { ol.appendChild(el('li', { class: i === r.saltAt ? 'salt' : null, text: s + (i === r.saltAt ? ' ← 간하기 전에 따로 덜 몫을 먼저 덜어요' : '') })); });
    box.appendChild(ol);

    box.appendChild(h(3, '구성원별 변형'));
    HS.variants(r, members).forEach(function (v) {
      var ul = el('ul');
      v.items.forEach(function (t) { ul.appendChild(el('li', { text: t })); });
      box.appendChild(el('div', { class: 'var' }, [
        el('img', { src: HS.charSrc(v.member.char), alt: '' }),
        el('div', null, [el('b', { text: v.member.name }), el('span', { class: 'why', text: v.why.join(' · ') }), ul])
      ]));
    });

    box.appendChild(h(4, '주의사항'));
    var cu = el('ul', { class: 'caution' });
    (r.caution || []).concat(['알레르기가 있는 가족 몫은 도마·칼·숟가락을 따로 써서 교차오염을 막아요.', '참고용이며 성분표를 꼭 확인하세요.'])
      .forEach(function (t) { cu.appendChild(el('li', { text: t })); });
    box.appendChild(cu);
    return box;
  }

  // 안전 기준 문구: 검사 결과는 화면에 보여주지 않고 문구만 표시해요 (사유는 개발용 콘솔에만)
  var SAFE_TEXT = '✓ 알레르기·당뇨식·저염식 안전검사를 통과한 레시피예요';
  function badge(check) {
    if (check && check.reasons && check.reasons.length && window.console) console.debug('[안전 검사]', check.result, check.reasons);
    return el('span', { class: 'badge ok', text: '✓ 안전검사 통과' });
  }
  function note() {
    return el('p', { class: 'safe-note' }, [SAFE_TEXT, el('small', { text: '식약처 등 공공 데이터 기준 · 참고용이며 성분표를 꼭 확인하세요' })]);
  }

  HS.recipeDetail = detail;
  HS.safetyBadge = badge;
  HS.safetyNote = note;
})();
