/* 온가족 한상 · 서버(API) 연결 (모든 화면 공통)
 * - 서버 주소: 배포 주소 → https://onfamily-hansang-api.onrender.com
 *              내 컴퓨터(localhost·파일로 열기)에서는 http://localhost:8000
 *              바꾸고 싶으면 localStorage 'onfamily_api' 에 주소를 넣어요.
 * - 로그인 토큰은 localStorage 'onfamily_token' 에 저장해요.
 * - 서버가 응답하지 않으면 각 화면은 지금처럼 브라우저 저장소로 동작해요.
 */
(function () {
  var PROD = 'https://onfamily-hansang-api.onrender.com';
  function pickBase() {
    try { var o = localStorage.getItem('onfamily_api'); if (o) return o.replace(/\/+$/, ''); } catch (e) {}
    if (location.protocol === 'file:' || /^(localhost|127\.0\.0\.1)$/.test(location.hostname)) return 'http://localhost:8000';
    return PROD;
  }
  var BASE = pickBase();

  // 다른 사람에게 보내는 화면 주소(링크·QR). 파일로 열었을 때는 배포된 화면 주소를 써요.
  var SITE = 'https://m3-1-final-team-project.onrender.com/';
  function siteUrl(page) {
    if (location.protocol === 'http:' || location.protocol === 'https:') return new URL(page, location.href).href;
    return SITE + page;
  }

  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }

  function token() { return get('onfamily_token'); }
  function user() { try { return JSON.parse(get('onfamily_user') || 'null'); } catch (e) { return null; } }
  function setSession(res) {
    set('onfamily_token', res.token);
    set('onfamily_user', JSON.stringify(res.user));
    set('onfamily_session', JSON.stringify({ email: res.user.email, at: Date.now() }));
  }
  function clearSession() { set('onfamily_token', null); set('onfamily_user', null); set('onfamily_session', null); }

  // 요청: 실패하면 { status, message } 를 던져요 (status 0 = 서버에 닿지 못함)
  // 무료 서버는 한동안 쉬면 처음 응답까지 50초쯤 걸릴 수 있어서 기다리는 시간을 넉넉히 둬요
  async function request(method, path, opts) {
    opts = opts || {};
    var headers = {};
    var t = token();
    if (t) headers.Authorization = 'Bearer ' + t;
    var body;
    if (opts.form) body = opts.form;
    else if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json); }
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, opts.timeout || 70000);
    var res;
    try {
      res = await fetch(BASE + path, { method: method, headers: headers, body: body, signal: ctrl.signal });
    } catch (e) {
      clearTimeout(timer);
      throw { status: 0, message: '서버에 연결하지 못했어요' };
    }
    clearTimeout(timer);
    var data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      if (res.status === 401 && t) clearSession();          // 토큰이 만료됐으면 로그아웃 상태로
      var msg = data && data.detail ? (typeof data.detail === 'string' ? data.detail : '입력한 내용을 확인해 주세요') : '요청을 처리하지 못했어요';
      throw { status: res.status, message: msg };
    }
    return data;
  }

  // 회원별 데이터(가족·재료·보관함): 로그인했을 때만 서버와 맞춰요
  async function loadDoc(key) {
    if (!token()) return null;
    try { var r = await request('GET', '/api/me/data/' + key); return r ? r.data : null; } catch (e) { return null; }
  }
  async function saveDoc(key, data) {
    if (!token()) return false;
    try { await request('PUT', '/api/me/data/' + key, { json: { data: data } }); return true; } catch (e) { return false; }
  }

  // 캐릭터 그림: 저장하는 캐릭터 값은 '성인_남'처럼 그대로 두고, 파일 이름만 영어예요 (characters/adult_m.png)
  var CHAR_FILES = {
    '영유아_남': 'infant_m', '영유아_여': 'infant_f', '어린이_남': 'child_m', '어린이_여': 'child_f',
    '청소년_남': 'teen_m', '청소년_여': 'teen_f', '성인_남': 'adult_m', '성인_여': 'adult_f',
    '어르신_남': 'senior_m', '어르신_여': 'senior_f', '아빠': 'dad', '아빠2': 'dad2',
    '엄마1': 'mom1', '아들': 'son', '딸': 'daughter', '아기': 'baby',
    '형': 'older_brother_hyung', '오빠': 'older_brother_oppa', '남동생': 'younger_brother', '누나1': 'older_sister_nuna1',
    '언니1': 'older_sister_eonni1', '언니2': 'older_sister_eonni2', '여동생1': 'younger_sister1', '동생1': 'sibling1',
    '동생2': 'sibling2', '할머니': 'grandma', '할아버지': 'grandpa'
  };
  function charSrc(c) { return c && CHAR_FILES[c] ? 'characters/' + CHAR_FILES[c] + '.png' : null; }

  window.HansangAPI = {
    base: BASE, token: token, user: user, isLoggedIn: function () { return !!token(); },
    siteUrl: siteUrl, charSrc: charSrc, setSession: setSession, clearSession: clearSession, request: request, loadDoc: loadDoc, saveDoc: saveDoc,
    absUrl: function (u) { return u && /^https?:|^data:|^blob:/.test(u) ? u : u; }
  };
})();
