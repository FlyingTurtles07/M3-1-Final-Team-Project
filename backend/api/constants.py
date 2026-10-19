"""화면(web/app.js)에서 쓰는 선택지와 같은 값이에요. 바꿀 때는 프론트와 함께 바꾸세요.

[팀 확정 필요] ALLERGENS 는 지금 화면의 8개 값이에요. 체크리스트 2단계에 따라 최신 식약처 고시 기준 표준 목록으로
교체해야 해요(알레르기 사전은 김지혜 담당). 이 파일의 목록만 바꾸면 서버 검증이 함께 바뀌어요.
"""

AGES = ("성인", "어린이", "노인", "환자(회복식)")
ALLERGENS = ("땅콩", "견과류", "우유", "달걀", "밀", "대두", "갑각류", "생선")
NO_ALLERGY = "없음"
CONDITIONS = ("일반식", "당뇨식", "저염식", "유동식", "이유식")
NORMAL_DIET = "일반식"

# terms=이용약관, privacy=개인정보 수집·이용, health=건강정보(민감정보), share=게시물 공개, notification=알림
CONSENT_TYPES = ("terms", "privacy", "health", "share", "notification")
# 서비스 화면에 들어가려면 필요한 동의
SERVICE_CONSENTS = ("terms", "privacy", "health")

MAX_MEMBERS = 10
