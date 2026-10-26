/* 온가족 한상 · 화면 연결 (모든 화면 공통)
 * 순서: 회원가입/로그인 → 가족 프로필 → 홈(재료 사진) → 재료 확인 → 오늘의 한상
 *       → 식사 후 의견 → 식사 사진 기록 → 다른 집 한상 / 나만의 레시피북
 * 하단 탭(.tab[data-tab])을 눌렀을 때 해당 화면으로 이동해요. 각 화면 스크립트 뒤에 넣어 주세요. */
(function () {
  var TAB_ROUTES = {
    '홈': 'home.html', 'home': 'home.html',
    '레시피': 'saved-recipes.html', 'recipes': 'saved-recipes.html',
    '기록': 'recipe-book.html',
    '둘러보기': 'browse.html',
    '냉장고 촬영': 'home.html', 'camera': 'home.html',
    '내 정보': 'my-info.html', 'me': 'my-info.html'
  };
  var here = decodeURIComponent(location.pathname.split('/').pop() || 'index.html');
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab[data-tab]'));
  var matched = tabs.some(function (t) { return TAB_ROUTES[t.getAttribute('data-tab')] === here; });

  tabs.forEach(function (t) {
    var to = TAB_ROUTES[t.getAttribute('data-tab')];
    if (!to) return;
    if (to === here) {                      // 지금 화면의 탭은 원래 동작(맨 위로, 카메라 등)을 그대로 둬요
      if (matched) t.setAttribute('aria-current', 'page');
      return;
    }
    var fresh = t.cloneNode(true);          // "준비 중" 안내 동작을 지우고 이동만 하게 해요
    if (matched) fresh.removeAttribute('aria-current');
    fresh.addEventListener('click', function () { location.href = to; });
    t.parentNode.replaceChild(fresh, t);
  });
})();
