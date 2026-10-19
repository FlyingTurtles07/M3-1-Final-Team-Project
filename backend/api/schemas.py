"""요청·응답 모양과 입력 검사. (화면 family.html 의 입력 항목과 맞춰 두었어요)

화면 ↔ API 이름 대응:  name→nickname, char→avatar, allergyCustom→allergy_custom, conditionCustom→condition_custom,
                       proxy→proxy_consent, notes→notes (consent 체크는 동의 API로 따로 보내요)
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .constants import AGES, ALLERGENS, CONDITIONS, CONSENT_TYPES, NO_ALLERGY, NORMAL_DIET

ConsentType = Literal["terms", "privacy", "health", "share", "notification"]

# 암호화해서 저장하는 건강 관련 항목 (연령대에 '환자(회복식)'이 있어 함께 암호화)
HEALTH_FIELDS = ("age", "allergies", "allergy_custom", "conditions", "condition_custom", "avoid_ingredients", "notes")


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nickname: str = Field(min_length=1, max_length=10, description="이름 대신 별칭 (예: 엄마, 민준)")
    avatar: str | None = Field(default=None, max_length=40, description="고른 캐릭터 이름")
    age: str = Field(description="연령대: " + " / ".join(AGES))
    allergies: list[str] = Field(default_factory=list, max_length=20, description="표준 목록에서 고른 알레르기. 없으면 ['없음']")
    allergy_custom: str = Field(default="", max_length=30, description="목록에 없는 알레르기(쉼표로 구분)")
    conditions: list[str] = Field(default_factory=lambda: [NORMAL_DIET], max_length=12, description="식사 조건: " + " / ".join(CONDITIONS))
    condition_custom: str = Field(default="", max_length=30)
    avoid_ingredients: list[str] = Field(default_factory=list, max_length=30, description="기피 재료")
    notes: str = Field(default="", max_length=200, description="식단 목표·메모")
    proxy_consent: bool = Field(default=False, description="다른 가족 정보를 대신 입력하며 그 가족(법정대리인)의 동의를 받았는지")

    @field_validator("age")
    @classmethod
    def _age(cls, v: str) -> str:
        if v not in AGES:
            raise ValueError(f"age 는 {', '.join(AGES)} 중 하나여야 해요.")
        return v

    @field_validator("allergies")
    @classmethod
    def _allergies(cls, v: list[str]) -> list[str]:
        v = _unique([a.strip() for a in v])
        bad = [a for a in v if a not in ALLERGENS and a != NO_ALLERGY]
        if bad:
            raise ValueError(f"표준 목록에 없는 알레르기예요: {', '.join(bad)} (목록에 없으면 allergy_custom 에 적어 주세요)")
        return v

    @field_validator("conditions")
    @classmethod
    def _conditions(cls, v: list[str]) -> list[str]:
        v = _unique([c.strip() for c in v])
        bad = [c for c in v if c not in CONDITIONS]
        if bad:
            raise ValueError(f"식사 조건 목록에 없는 값이에요: {', '.join(bad)} (직접 적으려면 condition_custom 사용)")
        return v

    @field_validator("avoid_ingredients")
    @classmethod
    def _avoid(cls, v: list[str]) -> list[str]:
        v = _unique([x.strip() for x in v if x.strip()])
        if any(len(x) > 20 for x in v):
            raise ValueError("기피 재료 이름은 20자 이하여야 해요.")
        return v

    @model_validator(mode="after")
    def _cross(self) -> "MemberIn":
        if NO_ALLERGY in self.allergies and (len(self.allergies) > 1 or self.allergy_custom):
            raise ValueError("'없음'은 다른 알레르기와 함께 선택할 수 없어요.")
        if NORMAL_DIET in self.conditions and (len(self.conditions) > 1):
            raise ValueError("'일반식'은 다른 식사 조건과 함께 선택할 수 없어요.")
        if not self.conditions and not self.condition_custom:
            self.conditions = [NORMAL_DIET]   # 화면과 같은 규칙: 아무것도 없으면 일반식
        return self


class MemberOut(BaseModel):
    id: UUID
    nickname: str
    avatar: str | None
    age: str
    allergies: list[str]
    allergy_custom: str
    conditions: list[str]
    condition_custom: str
    avoid_ingredients: list[str]
    notes: str
    proxy_consent: bool
    created_at: datetime
    updated_at: datetime


class ConsentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent_type: ConsentType
    granted: bool


class ConsentUpdate(BaseModel):
    """가입 때 여러 항목을 한 번에 보내거나, 철회처럼 한 항목만 보낼 수 있어요."""
    model_config = ConfigDict(extra="forbid")
    items: list[ConsentItem] = Field(min_length=1, max_length=len(CONSENT_TYPES))

    @field_validator("items")
    @classmethod
    def _no_dupes(cls, v: list[ConsentItem]) -> list[ConsentItem]:
        types = [i.consent_type for i in v]
        if len(set(types)) != len(types):
            raise ValueError("같은 동의 항목을 두 번 보낼 수 없어요.")
        return v


class ConsentState(BaseModel):
    granted: bool
    updated_at: datetime | None = None
    policy_version: str | None = None


class ConsentStatus(BaseModel):
    policy_version: str = Field(description="서버가 지금 받는 동의 문구 버전")
    consents: dict[str, ConsentState]
    can_use_service: bool = Field(description="terms·privacy·health 가 모두 동의 상태 → 서비스 화면에 들어갈 수 있음")


class ConsentEvent(BaseModel):
    consent_type: str
    granted: bool
    policy_version: str
    created_at: datetime
