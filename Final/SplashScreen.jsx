'use client';
// app/page.jsx 에 그대로 두거나, app/splash/page.jsx 로 옮겨 쓰세요.
// 이미지: public/images/splash.png (함께 드린 splash.png)
import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Image from 'next/image';
// [서버 연동 지점] Supabase 클라이언트 (lib/supabase.js 에서 createClient 해 둔 것)
import { supabase } from '@/lib/supabase';

const MIN_SHOW_MS = 2200; // 최소 노출 시간
const MAX_WAIT_MS = 6000; // 세션 확인이 멈춰도 이 시간 뒤엔 이동

export default function SplashScreen() {
  const router = useRouter();
  const [leaving, setLeaving] = useState(false);
  const targetRef = useRef(null);
  const doneRef = useRef(false);

  const go = (target) => {
    if (doneRef.current) return;
    doneRef.current = true;
    setLeaving(true);
    // replace: 뒤로가기로 스플래시에 다시 오지 않게
    setTimeout(() => router.replace(target === 'home' ? '/home' : '/login'), 450);
  };

  useEffect(() => {
    // [서버 연동 지점 ①] 로그인 세션 확인
    const session = supabase.auth
      .getSession()
      .then(({ data }) => (targetRef.current = data.session ? 'home' : 'login'))
      .catch(() => (targetRef.current = 'login'));

    // [서버 연동 지점 ②] Render 백엔드 미리 깨우기 (콜드스타트 대비)
    fetch(`${process.env.NEXT_PUBLIC_API_BASE}/health`).catch(() => {});

    const minTime = new Promise((r) => setTimeout(r, MIN_SHOW_MS));
    Promise.all([session, minTime]).then(() => go(targetRef.current));
    const maxTimer = setTimeout(() => go(targetRef.current || 'login'), MAX_WAIT_MS);
    return () => clearTimeout(maxTimer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="fixed inset-0 bg-[#F6D9CF]">
      <h1 className="sr-only">온가족 한상</h1>
      <button
        type="button"
        aria-label="온가족 한상 시작 화면. 누르면 바로 넘어갑니다"
        onClick={() => targetRef.current && go(targetRef.current)}
        className={`absolute inset-0 transition duration-[450ms] focus-visible:outline focus-visible:outline-4 focus-visible:outline-[#E0557A] ${
          leaving ? 'opacity-0 scale-[1.03] pointer-events-none' : 'opacity-100'
        }`}
      >
        <Image
          src="/images/splash.png"
          alt="온가족 한상 — 함께 먹는 행복한 시간. 가족이 식탁에 둘러앉아 식사하는 일러스트"
          fill
          priority
          sizes="100vw"
          className="object-cover object-[50%_20%] motion-safe:animate-[settle_1.1s_cubic-bezier(.2,.8,.2,1)_both]"
        />
      </button>
    </main>
  );
}

/* tailwind.config.js 의 theme.extend 에 추가:
   keyframes: { settle: { from: { opacity: 0, transform: 'scale(1.06)' }, to: { opacity: 1, transform: 'none' } } }
*/
