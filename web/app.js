/* =====================================================================
 * 온가족 한상 · 공통 스크립트
 *  - 저장: localStorage (AI·서버 연동 전 단계의 샘플 동작)
 *  - 재료 사전 / 샘플 레시피 / 규칙 엔진(분량·안전 검사·구성원별 변형)
 *  - 상단 메뉴(PC) · 하단 탭(모바일) · 토스트
 * ===================================================================== */
(function () {
  'use strict';

  /* ---------------- 1. 저장소 ---------------- */
  var P = 'hansang.';
  function load(k, d) {
    try { var v = localStorage.getItem(P + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; }
  }
  function save(k, v) {
    try { localStorage.setItem(P + k, JSON.stringify(v)); return true; } catch (e) { return false; }
  }
  function remove(k) { try { localStorage.removeItem(P + k); } catch (e) {} }

  /* ---------------- 2. DOM 유틸 ---------------- */
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
  var toastTimer;
  function toast(msg) {
    var t = $('toast');
    if (!t) { t = el('div', { id: 'toast', class: 'toast', role: 'status', 'aria-live': 'polite' }); document.body.appendChild(t); }
    t.textContent = msg; t.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove('show'); }, 2400);
  }
  function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  function fmtDate(ts) { var d = new Date(ts); return d.getFullYear() + '.' + (d.getMonth() + 1) + '.' + d.getDate(); }

  /* ---------------- 3. 내비게이션 ---------------- */
  var PAGES = [
    { key: 'home', href: 'index.html', label: '홈', icon: '<path d="M3.5 11 12 3.5 20.5 11v9.5h-5.5v-6h-6v6H3.5z"/>' },
    { key: 'family', href: 'family.html', label: '가족', icon: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.6 2.7-6 6-6s6 2.4 6 6"/><circle cx="17" cy="9" r="2.4"/><path d="M16 14.2c2.9.1 5 2.2 5 5.3"/>' },
    { key: 'ingredients', href: 'ingredients.html', label: '재료', icon: '<path d="M4 9h16l-1.6 10.2a1.5 1.5 0 0 1-1.5 1.3H7.1a1.5 1.5 0 0 1-1.5-1.3z"/><path d="M8.5 9 11 3.5M15.5 9 13 3.5"/>' },
    { key: 'recipes', href: 'recipes.html', label: '추천', icon: '<path d="M6 13.5a4 4 0 1 1 2.6-7A4.5 4.5 0 0 1 17 7a3.6 3.6 0 0 1 1 6.5V20H6z"/><path d="M6 17h12"/>' },
    { key: 'saved', href: 'saved.html', label: '보관함', icon: '<path d="M6 3.5h12v17l-6-4-6 4z"/>' },
    { key: 'share', href: 'share.html', label: '공유', icon: '<path d="M12 20s-7.5-4.4-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.6-7.5 10-7.5 10z"/>' }
  ];
  function session() { return load('session', null); }
  function mount(key) {
    var s = session();
    // 로그인하지 않은 채 다른 화면을 열면 둘러보기 모드로 샘플 데이터를 채워요
    if (!s && key !== 'home') { startGuest(); s = session(); }

    var top = $('topbar');
    if (top) {
      top.className = 'topbar';
      var nav = el('nav', { class: 'topnav', 'aria-label': '주요 메뉴' });
      PAGES.forEach(function (p) {
        nav.appendChild(el('a', { href: p.href, 'aria-current': p.key === key ? 'page' : null, text: p.label }));
      });
      var who = s ? el('span', { class: 'who', text: s.guest ? '둘러보기 중' : s.email }) : null;
      top.appendChild(el('div', { class: 'topbar-in' }, [
        el('a', { class: 'brand', href: 'index.html' }, [el('span', { class: 'brand-mark', 'aria-hidden': 'true', text: '한' }), '온가족 한상']),
        nav, who
      ]));
      if (s && s.guest && key !== 'home') {
        top.appendChild(el('div', { class: 'guest-banner' }, ['둘러보기 중이에요. 샘플 가족과 재료로 흐름을 확인할 수 있어요. ',
          el('a', { href: 'index.html#signup', text: '가입하기' })]));
      }
    }
    var tab = $('tabbar');
    if (tab) {
      tab.className = 'tabbar';
      tab.setAttribute('aria-label', '하단 메뉴');
      PAGES.forEach(function (p) {
        var a = el('a', { href: p.href, 'aria-current': p.key === key ? 'page' : null });
        a.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true">' + p.icon + '</svg>';
        a.appendChild(el('span', { text: p.label }));
        tab.appendChild(a);
      });
    }
  }

  /* ---------------- 4. 선택지 ---------------- */
  var AGES = ['성인', '어린이', '노인', '환자(회복식)'];
  var ALLERGENS = ['땅콩', '견과류', '우유', '달걀', '밀', '대두', '갑각류', '생선'];
  var CONDITIONS = ['일반식', '당뇨식', '저염식', '유동식', '이유식'];
  var EXPERT_ONLY = ['유동식', '이유식'];          // 자동 검증 범위 밖 → 전문가 기준 확인 전까지 보류
  var CHARACTERS = ['아빠', '아빠2', '엄마1', '할아버지', '할머니', '오빠', '형', '언니1', '언니2', '누나1',
    '남동생', '여동생1', '동생1', '동생2', '아기'];
  var CHAR_FILES = {"영유아_남": "infant_m", "영유아_여": "infant_f", "어린이_남": "child_m", "어린이_여": "child_f", "청소년_남": "teen_m", "청소년_여": "teen_f", "성인_남": "adult_m", "성인_여": "adult_f", "어르신_남": "senior_m", "어르신_여": "senior_f", "아빠": "dad", "아빠2": "dad2", "엄마1": "mom1", "아들": "son", "딸": "daughter", "아기": "baby", "형": "older_brother_hyung", "오빠": "older_brother_oppa", "남동생": "younger_brother", "누나1": "older_sister_nuna1", "언니1": "older_sister_eonni1", "언니2": "older_sister_eonni2", "여동생1": "younger_sister1", "동생1": "sibling1", "동생2": "sibling2", "할머니": "grandma", "할아버지": "grandpa"};
  function charSrc(c) { return 'img/characters/' + (CHAR_FILES[c] || encodeURIComponent(c)) + '.png'; }

  /* ---------------- 5. 재료 사전 ----------------
   * ex: 1교환단위량(g, 가식부) · u: 끼니 배분 교환단위 수 → 1인분 기준량 = ex × u
   * unit: 개당 중량(g) · edible: 가식부 비율(구입량 환산) · na/sugar/carb: 100g당 (임시값, 식약처 DB 연동 전)
   * kind: fresh(신선 식재료) / season(양념, 재고 제외) / processed(가공식품, 재고 제외)
   * composite: 성분이 제품마다 다른 복합 재료 → 보류
   * 알레르기 성분은 식약처 알레르기 표시 대상 고시와 대조해 팀이 관리해요. [검토] */
  var DICT = {
    '두부':     { grp: '어육류', ex: 80, u: 1, allergens: ['대두'], na: 7, sugar: 0.6, carb: 2.4 },
    '달걀':     { grp: '어육류', ex: 55, u: 1, unit: 55, allergens: ['달걀'], na: 140, sugar: 0.4, carb: 0.7, alias: ['계란'] },
    '닭가슴살': { grp: '어육류', ex: 40, u: 2, allergens: [], na: 50, sugar: 0, carb: 0 },
    '소고기':   { grp: '어육류', ex: 40, u: 1.5, allergens: [], na: 55, sugar: 0, carb: 0, alias: ['쇠고기', '국거리'] },
    '연어':     { grp: '어육류', ex: 50, u: 1.5, allergens: ['생선'], na: 60, sugar: 0, carb: 0 },
    '새우':     { grp: '어육류', ex: 50, u: 1, allergens: ['갑각류'], na: 190, sugar: 0, carb: 0 },
    '쌀':       { grp: '곡류', ex: 30, u: 2, allergens: [], na: 2, sugar: 0.1, carb: 79 },
    '현미':     { grp: '곡류', ex: 30, u: 2, allergens: [], na: 3, sugar: 0.7, carb: 74 },
    '감자':     { grp: '곡류', ex: 140, u: 0.5, unit: 150, edible: 0.9, allergens: [], na: 3, sugar: 0.8, carb: 16 },
    '애호박':   { grp: '채소', ex: 70, u: 1, unit: 300, edible: 0.95, allergens: [], na: 1, sugar: 2.1, carb: 4.5 },
    '양파':     { grp: '채소', ex: 70, u: 0.5, unit: 200, edible: 0.94, allergens: [], na: 2, sugar: 4.6, carb: 8 },
    '당근':     { grp: '채소', ex: 70, u: 0.5, unit: 150, edible: 0.9, allergens: [], na: 40, sugar: 4.7, carb: 8.5 },
    '대파':     { grp: '채소', ex: 70, u: 0.25, unit: 100, edible: 0.85, allergens: [], na: 3, sugar: 2.3, carb: 6 },
    '무':       { grp: '채소', ex: 70, u: 1, edible: 0.9, allergens: [], na: 15, sugar: 2.5, carb: 4 },
    '브로콜리': { grp: '채소', ex: 70, u: 0.5, edible: 0.8, allergens: [], na: 20, sugar: 1.5, carb: 6 },
    '시금치':   { grp: '채소', ex: 70, u: 0.5, edible: 0.9, allergens: [], na: 55, sugar: 0.4, carb: 3.6 },
    '버섯':     { grp: '채소', ex: 50, u: 0.5, edible: 0.9, allergens: [], na: 5, sugar: 1, carb: 4, alias: ['표고버섯', '느타리버섯'] },
    '콩나물':   { grp: '채소', ex: 70, u: 0.5, allergens: ['대두'], na: 6, sugar: 0.5, carb: 3 },
    '배추':     { grp: '채소', ex: 70, u: 1, edible: 0.85, allergens: [], na: 9, sugar: 1.4, carb: 3 },
    '고구마':   { grp: '곡류', ex: 70, u: 1, unit: 200, edible: 0.9, allergens: [], na: 15, sugar: 6, carb: 30 },
    '우유':     { grp: '우유', ex: 200, u: 1, allergens: ['우유'], na: 40, sugar: 4.8, carb: 4.8, liquid: true },
    '호두':     { grp: '지방', ex: 8, u: 1, allergens: ['견과류'], na: 2, sugar: 2.6, carb: 14 },
    '땅콩':     { grp: '지방', ex: 8, u: 1, allergens: ['땅콩'], na: 6, sugar: 4, carb: 16 },
    '밀가루':   { grp: '곡류', ex: 30, u: 1, allergens: ['밀'], na: 2, sugar: 0.3, carb: 76 },
    '마늘':     { grp: '채소', ex: 5, u: 1, edible: 0.9, allergens: [], na: 3, sugar: 1, carb: 25, alias: ['다진마늘'] },
    // 양념 (재고 제외, 1회 섭취참고량 기준 · 표시 단위 mL/큰술)
    '간장':     { kind: 'season', ml: 3.75, allergens: ['대두', '밀'], na: 5700 },
    '국간장':   { kind: 'season', ml: 3.75, allergens: ['대두', '밀'], na: 6900 },
    '된장':     { kind: 'season', ml: 7.5, allergens: ['대두'], na: 4400 },
    '소금':     { kind: 'season', ml: 0.3, allergens: [], na: 39000 },
    '참기름':   { kind: 'season', ml: 1.25, allergens: [], na: 0 },
    '식용유':   { kind: 'season', ml: 3.75, allergens: [], na: 0 },
    '고춧가루': { kind: 'season', ml: 1.25, allergens: [], na: 20 },
    '고추장':   { kind: 'season', ml: 3.75, allergens: ['밀', '대두'], na: 2500 },
    '설탕':     { kind: 'season', ml: 1.25, allergens: [], na: 0 },
    '케첩':     { kind: 'season', ml: 3.75, allergens: [], na: 1000 },
    '마요네즈': { kind: 'season', ml: 3.75, allergens: ['달걀'], na: 700 },
    // 가공식품 (재고 제외)
    '햄':       { kind: 'processed', allergens: ['대두', '밀'], composite: true },
    '소시지':   { kind: 'processed', allergens: ['대두', '밀'], composite: true },
    '어묵':     { kind: 'processed', allergens: ['생선', '밀'], composite: true },
    '치즈':     { kind: 'processed', allergens: ['우유'] },
    '두유':     { kind: 'processed', allergens: ['대두'] },
    '라면':     { kind: 'processed', allergens: ['밀', '대두'], composite: true },
    '만두':     { kind: 'processed', allergens: ['밀', '대두'], composite: true },
    '요거트':   { kind: 'processed', allergens: ['우유'] }
  };
  var ALIAS = {};
  Object.keys(DICT).forEach(function (k) { (DICT[k].alias || []).forEach(function (a) { ALIAS[a] = k; }); });
  function norm(name) { var n = String(name || '').trim().replace(/\s+/g, ''); return ALIAS[n] || n; }
  function info(name) { return DICT[norm(name)] || null; }
  function isStock(name) { var d = info(name); return !d || !d.kind || d.kind === 'fresh'; }

  /* ---------------- 6. 분량 규칙 (AI가 정하지 않음) ----------------
   * 4인분 = 성인 1인분 × 4 · 반올림: g 5단위, mL 10단위, 개수·큰술 0.5단위(팀 결정안) */
  var SERVINGS = 4;
  function r5(g) { return Math.max(5, Math.round(g / 5) * 5); }
  function r10(ml) { return Math.max(10, Math.round(ml / 10) * 10); }
  function rHalf(x) { return Math.max(0.5, Math.round(x * 2) / 2); }
  function portion(name, scale) {
    var d = info(name); scale = scale || 1;
    if (!d) return { name: name, text: '분량 확인 필요', g: null, missing: true };
    if (d.kind === 'season') {
      var ml = d.ml * SERVINGS * scale, text;
      if (ml >= 7.5) { var tb = rHalf(ml / 15); text = tb + '큰술(' + Math.round(tb * 15) + 'mL)'; }
      else if (ml >= 2.5) { var ts = rHalf(ml / 5); text = ts + '작은술(' + Math.round(ts * 5) + 'mL)'; }
      else text = '약간';
      return { name: name, text: text, g: ml, season: true };
    }
    if (d.ex == null) return { name: name, text: '분량 확인 필요', g: null, missing: true };
    var g = d.ex * d.u * SERVINGS * scale;
    if (d.liquid) { var m = r10(g); return { name: name, text: m + 'mL', g: m }; }
    var gg = r5(g), t = gg + 'g';
    if (d.unit) t = rHalf(gg / d.unit) + '개(' + gg + 'g)';
    var buy = d.edible && d.edible < 1 ? r5(gg / d.edible) : null;
    return { name: name, text: t, g: gg, buy: buy };
  }

  /* ---------------- 7. 샘플 레시피 ----------------
   * AI 연동 전 샘플 데이터예요. AI는 재료·조리법만 제안하고, 분량은 위 규칙으로 채워요.
   * base: 공통 베이스 재료 · season: 양념 · water: 물(mL)
   * addOn: 1차 조리 후 해당 알레르기가 없는 구성원 몫에만 추가하는 재료
   * saltAt: 간을 하는 공통 조리 단계(0부터) → 저염식·이유식·유동식 몫은 그 전에 덜어요 */
  var RECIPES = [
    { id: 'zucchini-tofu-soup', name: '애호박 두부 된장국', img: 'img/food/zucchini-tofu-soup.jpg', min: 20, soft: true,
      base: ['두부', '애호박', '양파', '대파'], season: ['된장', '마늘'], water: 800,
      steps: ['냄비에 물을 붓고 양파를 넣어 끓여요.', '애호박과 두부를 한입 크기로 깍둑 썰어 넣어요.', '된장과 마늘을 풀고 5분 더 끓여요.', '대파를 넣고 불을 꺼요.'],
      saltAt: 2, caution: ['된장은 제품마다 나트륨이 달라요. 성분표를 확인하세요.'] },
    { id: 'chicken-porridge', name: '닭고기 채소죽', img: 'img/food/chicken-porridge.jpg', min: 40, soft: true,
      base: ['쌀', '닭가슴살', '당근', '애호박', '양파'], season: ['참기름', '소금'], water: 1200,
      steps: ['쌀을 30분 불려요.', '닭가슴살을 삶아 잘게 찢고, 채소는 잘게 다져요.', '참기름에 쌀과 채소를 볶다가 닭 삶은 물을 부어요.', '약불에서 저으며 20분 끓이고 닭고기를 넣어요.', '소금으로 간해요.'],
      saltAt: 4, caution: ['닭고기는 속까지 완전히 익혀요.'] },
    { id: 'braised-tofu', name: '대파 두부조림', img: 'img/food/braised-tofu.jpg', min: 20,
      base: ['두부', '대파', '당근', '양파'], season: ['간장', '마늘', '식용유'], water: 200,
      addOn: [{ name: '고춧가루', how: '매콤하게 드실 분 몫에 고춧가루를 뿌려요.', spicy: true }],
      steps: ['두부를 도톰하게 썰어 식용유에 노릇하게 구워요.', '양파와 당근을 깔고 두부를 올려요.', '간장·마늘·물을 섞어 붓고 7분 졸여요.', '대파를 올리고 2분 더 졸여요.'],
      saltAt: 2, caution: ['간장에는 대두와 밀이 들어 있어요.'] },
    { id: 'tofu-bibimbap', name: '두부 채소비빔밥', img: 'img/food/tofu-bibimbap.jpg', min: 30,
      base: ['현미', '두부', '애호박', '당근', '시금치'], season: ['참기름', '간장'], water: 0,
      addOn: [{ name: '달걀', how: '달걀프라이를 따로 부쳐 이분 그릇에만 올려요.' }],
      steps: ['현미밥을 지어요.', '두부는 으깨 팬에 수분을 날리며 볶아요.', '애호박·당근은 채 썰어 볶고 시금치는 데쳐요.', '밥 위에 재료를 올리고 간장·참기름을 곁들여요.'],
      saltAt: 3, caution: ['달걀은 공통 요리에 넣지 않고 마지막에 따로 올려요.'] },
    { id: 'beef-radish-soup', name: '소고기 뭇국', img: 'img/food/beef-radish-soup.jpg', min: 35, soft: true,
      base: ['소고기', '무', '대파'], season: ['국간장', '마늘', '참기름'], water: 1000,
      steps: ['소고기를 참기름에 볶아요.', '나박 썬 무를 넣고 함께 볶아요.', '물을 붓고 20분 끓이며 거품을 걷어요.', '국간장과 마늘로 간하고 대파를 넣어요.'],
      saltAt: 3, caution: ['국간장은 나트륨이 높아요. 간은 마지막에 조금씩 맞춰요.'] },
    { id: 'chicken-veggie-stirfry', name: '닭고기 채소볶음', img: 'img/food/chicken-veggie-stirfry.jpg', min: 25,
      base: ['닭가슴살', '양파', '당근', '브로콜리'], season: ['간장', '마늘', '식용유'], water: 0,
      addOn: [{ name: '호두', how: '다진 호두를 이분 그릇에만 뿌려요.' }],
      steps: ['닭가슴살은 한입 크기로 썰고 브로콜리는 데쳐요.', '식용유에 마늘과 닭고기를 볶아요.', '양파·당근·브로콜리를 넣고 볶아요.', '간장으로 간해요.'],
      saltAt: 3, caution: ['견과류 토핑은 알레르기가 없는 구성원 그릇에만 올려요. 도마·숟가락을 따로 써요.'] },
    { id: 'salmon-brown-rice', name: '연어 현미덮밥', img: 'img/food/salmon-brown-rice.jpg', min: 30,
      base: ['현미', '연어', '양파', '브로콜리'], season: ['간장', '식용유'], water: 0,
      steps: ['현미밥을 지어요.', '연어를 앞뒤로 노릇하게 구워요.', '양파와 브로콜리를 볶아요.', '밥 위에 올리고 간장을 곁들여요.'],
      saltAt: 3, caution: ['연어 가시를 꼼꼼히 발라내요.'] },
    { id: 'tofu-zucchini-egg', name: '두부 애호박 달걀찜', img: 'img/food/tofu-zucchini-egg.jpg', min: 25, soft: true,
      base: ['두부', '애호박', '달걀'], season: ['소금'], water: 200,
      steps: ['두부는 으깨고 애호박은 잘게 다져요.', '달걀을 풀어 물과 재료를 섞어요.', '소금으로 간해요.', '중불에서 12분 쪄요.'],
      saltAt: 2, caution: ['달걀은 완전히 익혀요.'] },
    { id: 'veggie-omelet', name: '채소 달걀말이', img: 'img/food/carrot-omelet-roll.jpg', min: 15,
      base: ['달걀', '당근', '대파', '시금치'], season: ['소금', '식용유'], water: 0,
      steps: ['채소를 잘게 다져요.', '달걀을 풀어 채소와 섞어요.', '소금으로 간해요.', '약불에서 돌돌 말아 익힌 뒤 썰어요.'],
      saltAt: 2, caution: [] },
    { id: 'zucchini-egg-stirfry', name: '애호박 달걀볶음', img: 'img/food/zucchini-egg-stirfry.jpg', min: 15,
      base: ['애호박', '달걀', '양파'], season: ['소금', '식용유'], water: 0,
      steps: ['애호박은 반달 모양으로 썰어요.', '양파와 애호박을 볶다가 숨이 죽으면 달걀을 풀어 넣어요.', '소금으로 간하고 1분 더 볶아요.'],
      saltAt: 2, caution: [] }
  ];
  function recipeById(id) { for (var i = 0; i < RECIPES.length; i++) if (RECIPES[i].id === id) return RECIPES[i]; return null; }

  /* ---------------- 8. 가족 정보 해석 ---------------- */
  function allergiesOf(m) { return (m.allergies || []).filter(function (a) { return a !== '없음'; }).concat(m.allergyCustom ? splitList(m.allergyCustom) : []); }
  function conditionsOf(m) { return (m.conditions || []).concat(m.conditionCustom ? splitList(m.conditionCustom) : []); }
  function splitList(s) { return String(s || '').split(/[,，、]/).map(function (x) { return x.trim(); }).filter(Boolean); }
  function avoidsOf(m) { return splitList(m.notes).map(norm); }
  function ingAllergens(name) { var d = info(name); return d ? d.allergens || [] : null; }
  function hitsAllergy(name, allergy) {       // 재료가 해당 알레르기에 걸리는지 (true / false / null=판단 불가)
    if (norm(name) === norm(allergy)) return true;
    var a = ingAllergens(name);
    if (a == null) return null;
    if (ALLERGENS.indexOf(allergy) === -1) return null;   // 직접 입력한 알레르기 → 사전으로 판단 불가
    return a.indexOf(allergy) !== -1;
  }

  /* ---------------- 9. 안전 검사 (규칙 코드) ----------------
   * 실제 서비스에서는 백엔드가 식약처 식품영양성분DB(수치)와 확정된 PubMed 근거 태그로 검사해요.
   * 판정: exclude(제외) > hold(보류) > pass(통과). 화면에는 결과와 고지만 보여요. */
  var CRITERIA_REVIEWED = false;   // 당뇨식·저염식 수치 기준이 전문가 검수를 마쳤는지 [검토] → 전에는 통과를 내지 않음
  var LIMITS = { naPerServing: 800, sugarPer100: 10 };   // 임시값
  function checkRecipe(r, members, ctx) {
    ctx = ctx || {};
    var reasons = [], result = 'pass';
    function hold(why) { reasons.push('보류: ' + why); if (result === 'pass') result = 'hold'; }
    var all = r.base.concat(r.season);
    // 알레르기: 공통 재료에 들어 있으면 제외
    members.forEach(function (m) {
      allergiesOf(m).forEach(function (al) {
        all.forEach(function (ing) {
          var h = hitsAllergy(ing, al);
          if (h === true) { reasons.push('제외: ' + m.name + ' ' + al + ' ← ' + ing); result = 'exclude'; }
          else if (h === null) hold(m.name + ' ' + al + ' / ' + ing + ' 판단 불가');
        });
      });
    });
    if (result === 'exclude') return { result: result, reasons: reasons };
    all.forEach(function (ing) {
      var d = info(ing);
      if (!d) hold(ing + ' 사전에 없음');
      else if (d.composite) hold(ing + ' 복합 재료');
    });
    var conds = [];
    members.forEach(function (m) { conditionsOf(m).forEach(function (c) { if (conds.indexOf(c) === -1) conds.push(c); }); });
    conds.forEach(function (c) {
      if (EXPERT_ONLY.indexOf(c) !== -1) hold(c + ' 전문가 기준 확인 전');
      else if (CONDITIONS.indexOf(c) === -1) hold(c + ' 자동 검증 불가');
    });
    if (conds.indexOf('저염식') !== -1) {
      var na = 0, missing = false;
      all.forEach(function (ing) {
        var d = info(ing), p = portion(ing);
        if (!d || d.na == null || p.g == null) { missing = true; return; }
        na += d.na * p.g / 100;
      });
      if (missing) hold('나트륨 데이터 없음');
      else if (na / SERVINGS > LIMITS.naPerServing) hold('1인분 나트륨 ' + Math.round(na / SERVINGS) + 'mg');
      if (!CRITERIA_REVIEWED) hold('저염식 기준 전문가 검수 전');
    }
    if (conds.indexOf('당뇨식') !== -1) {
      r.base.forEach(function (ing) { var d = info(ing); if (!d || d.sugar == null) hold(ing + ' 당류 데이터 없음'); else if (d.sugar > LIMITS.sugarPer100) hold(ing + ' 당류 기준 초과'); });
      if (!CRITERIA_REVIEWED) hold('당뇨식 기준 전문가 검수 전');
    }
    if (ctx.unconfirmed) hold('확인하지 않은 의심 재료');
    // 표준 ④(조리식품 레시피 DB)와 비교: 1인분 중량이 상식 범위를 벗어나면 보류 (비교 범위는 팀 결정) [검토]
    var total = r.base.reduce(function (s, ing) { var p = portion(ing); return s + (p.g || 0); }, 0) / SERVINGS;
    if (total < 100 || total > 700) hold('1인분 중량 ' + Math.round(total) + 'g');
    return { result: result, reasons: reasons };
  }

  /* ---------------- 10. 구성원별 변형 ---------------- */
  function addOnAllowed(add, m) {
    var ok = true;
    allergiesOf(m).forEach(function (al) { if (hitsAllergy(add.name, al) !== false) ok = false; });
    if (avoidsOf(m).indexOf(norm(add.name)) !== -1) ok = false;
    return ok;
  }
  function variants(r, members) {
    var saltStep = (r.saltAt || 0) + 1;
    return members.map(function (m) {
      var items = [], why = [], conds = conditionsOf(m), als = allergiesOf(m), avoid = avoidsOf(m);
      var split = conds.indexOf('저염식') !== -1 || conds.indexOf('유동식') !== -1 || conds.indexOf('이유식') !== -1;
      if (split) items.push('공통 조리 ' + saltStep + '단계(간하기) 전에 이분 몫을 먼저 덜어 두세요.');
      if (conds.indexOf('유동식') !== -1) { items.push('덜어 둔 몫을 곱게 갈아 묽게 만들어요. 농도는 전문가 안내를 따라요.'); why.push('유동식'); }
      else if (conds.indexOf('이유식') !== -1) { items.push('덜어 둔 몫을 간 없이 곱게 다져요. 월령별 기준은 전문가 안내를 따라요.'); why.push('이유식'); }
      if (conds.indexOf('저염식') !== -1) { items.push('양념은 공통 양의 절반만, 국물은 적게 담아요.'); why.push('저염식'); }
      if (conds.indexOf('당뇨식') !== -1) {
        items.push(r.base.indexOf('쌀') !== -1 || r.base.indexOf('현미') !== -1 ? '밥·쌀 양을 2/3로 줄이고 채소를 더 담아요.' : '단 양념은 빼고, 밥은 잡곡으로 2/3공기만 곁들여요.');
        why.push('당뇨식');
      }
      if (m.age === '어린이') { items.push('한입 크기로 작게 잘라 담고, 분량은 성인의 약 2/3로 조절해요.'); why.push('어린이'); }
      if (m.age === '노인' || m.age === '환자(회복식)') {
        items.push(r.soft ? '건더기를 잘게 잘라 부드럽게 담아요.' : '이분 몫은 2~3분 더 익혀 부드럽게 만들어요.');
        why.push(m.age === '노인' ? '부드러운 식감' : '회복식');
      }
      (r.addOn || []).forEach(function (a) {
        if (a.spicy && (m.age !== '성인' || split)) return;
        if (addOnAllowed(a, m)) items.push('추가: ' + a.how);
      });
      if (als.length) { items.push(als.join('·') + ' 성분은 처음부터 빼고 만든 공통 요리 그대로 드세요.'); why.push(als.join('·') + ' 제외'); }
      avoid.forEach(function (a) {
        if (r.base.indexOf(a) !== -1) { items.push('기피 재료 ' + a + '은(는) 이분 그릇에서 덜어내요.'); why.push('기피 재료 참고'); }
      });
      if (!items.length) { items.push('공통 요리 그대로, 1인분을 담아요.'); why.push('일반식'); }
      return { member: m, items: items, why: why };
    });
  }

  /* ---------------- 11. 카드 태그 · 추천 이유 ---------------- */
  function tagsFor(r, members, pantry) {
    var t = [];
    r.base.forEach(function (ing) { if (pantry.indexOf(ing) !== -1) t.push({ text: ing, kind: '' }); });
    var conds = {}, als = {}, soft = false, avoid = false;
    members.forEach(function (m) {
      conditionsOf(m).forEach(function (c) { if (c !== '일반식') conds[c] = 1; });
      allergiesOf(m).forEach(function (a) { als[a] = 1; });
      if (m.age === '노인' || m.age === '환자(회복식)' || conditionsOf(m).indexOf('유동식') !== -1) soft = true;
      avoidsOf(m).forEach(function (a) { if (r.base.indexOf(a) !== -1) avoid = true; });
    });
    Object.keys(als).forEach(function (a) { t.push({ text: a + ' 제외', kind: 'warn' }); });
    Object.keys(conds).forEach(function (c) { t.push({ text: c + ' 반영', kind: 'accent' }); });
    if (soft) t.push({ text: '부드러운 식감 참고', kind: 'accent' });
    if (avoid) t.push({ text: '기피 재료 참고', kind: 'accent' });
    return t;
  }
  function reasonFor(r, members, pantry) {
    var have = r.base.filter(function (i) { return pantry.indexOf(i) !== -1; });
    var parts = [];
    if (have.length) parts.push('냉장고의 ' + have.slice(0, 3).join('·') + '을(를) 써요');
    var als = []; members.forEach(function (m) { allergiesOf(m).forEach(function (a) { if (als.indexOf(a) === -1) als.push(a); }); });
    if (als.length) parts.push(als.join('·') + ' 없이 한 번에 조리해요');
    if (r.soft && members.some(function (m) { return m.age === '노인' || m.age === '환자(회복식)'; })) parts.push('부드러워 어르신도 드시기 좋아요');
    return parts.join(', ') + '.';
  }

  /* ---------------- 12. 추천 (3개) ---------------- */
  function recommend(members, pantry, shown, ctx) {
    var excluded = 0, list = [];
    RECIPES.forEach(function (r) {
      var c = checkRecipe(r, members, ctx);
      if (c.result === 'exclude') { excluded++; return; }
      var have = r.base.filter(function (i) { return pantry.indexOf(i) !== -1; }).length;
      var avoidHit = members.some(function (m) { return avoidsOf(m).some(function (a) { return r.base.indexOf(a) !== -1; }); });
      list.push({ r: r, check: c, score: have * 2 - (r.base.length - have) - (avoidHit ? 1 : 0) });
    });
    list.sort(function (a, b) { return b.score - a.score; });
    var fresh = list.filter(function (x) { return shown.indexOf(x.r.id) === -1; });
    var cycled = false;
    if (fresh.length < 3) { cycled = true; fresh = fresh.concat(list.filter(function (x) { return fresh.indexOf(x) === -1; })); }
    return { items: fresh.slice(0, 3), excluded: excluded, cycled: cycled, total: list.length };
  }

  /* ---------------- 13. 세션 / 둘러보기 샘플 ---------------- */
  var SAMPLE_MEMBERS = [
    { id: 'm1', name: '아빠', char: '아빠', age: '성인', allergies: ['없음'], conditions: ['일반식'], notes: '체중 관리', consent: true },
    { id: 'm2', name: '엄마', char: '엄마1', age: '성인', allergies: ['없음'], conditions: ['일반식'], notes: '', consent: true },
    { id: 'm3', name: '민준', char: '남동생', age: '어린이', allergies: ['달걀'], conditions: ['일반식'], notes: '당근', consent: true, proxy: true },
    { id: 'm4', name: '할머니', char: '할머니', age: '노인', allergies: ['없음'], conditions: ['저염식'], notes: '딱딱한 음식', consent: true, proxy: true }
  ];
  var SAMPLE_PANTRY = ['두부', '애호박', '양파', '대파', '당근', '닭가슴살', '쌀', '무', '소고기', '시금치'];
  function startGuest() {
    save('session', { guest: true, at: Date.now() });
    if (!load('members', null)) save('members', SAMPLE_MEMBERS);
    if (!load('pantry', null)) save('pantry', SAMPLE_PANTRY);
  }
  function familyStamp(members) {    // 가족 프로필이 바뀌었는지 비교하는 값
    return JSON.stringify((members || []).map(function (m) { return [m.id, m.age, allergiesOf(m), conditionsOf(m), m.notes]; }));
  }

  /* ---------------- 14. 이미지 다시 그리기 (위치정보 제거) ---------------- */
  function reencode(file, max, quality) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file), img = new Image();
      img.onload = function () {
        var w = img.naturalWidth, h = img.naturalHeight, s = Math.min(1, max / Math.max(w, h));
        var c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(w * s)); c.height = Math.max(1, Math.round(h * s));
        var ctx = c.getContext('2d'); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, c.width, c.height);
        ctx.drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        resolve({ dataUrl: c.toDataURL('image/jpeg', quality || 0.8), width: w, height: h });
      };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('image')); };
      img.src = url;
    });
  }

  window.HS = {
    load: load, save: save, remove: remove, $: $, el: el, clear: clear, toast: toast, uid: uid, fmtDate: fmtDate,
    mount: mount, session: session, startGuest: startGuest, familyStamp: familyStamp, reencode: reencode,
    AGES: AGES, ALLERGENS: ALLERGENS, CONDITIONS: CONDITIONS, EXPERT_ONLY: EXPERT_ONLY, CHARACTERS: CHARACTERS, charSrc: charSrc,
    DICT: DICT, norm: norm, info: info, isStock: isStock, portion: portion, SERVINGS: SERVINGS,
    RECIPES: RECIPES, recipeById: recipeById, allergiesOf: allergiesOf, conditionsOf: conditionsOf, avoidsOf: avoidsOf,
    hitsAllergy: hitsAllergy, splitList: splitList, checkRecipe: checkRecipe, variants: variants,
    tagsFor: tagsFor, reasonFor: reasonFor, recommend: recommend
  };
})();
