"""온가족 한상 백엔드 (FastAPI).

실행:  uvicorn main:app --reload        (backend 폴더에서)
화면:  http://localhost:8000/today-meal.html   (프론트 파일도 같이 서비스해요)
"""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))   # safety.py가 환경변수를 읽기 전에 불러와요

from fastapi import FastAPI, HTTPException                     # noqa: E402
from fastapi.middleware.cors import CORSMiddleware             # noqa: E402
from fastapi.staticfiles import StaticFiles                    # noqa: E402
from pydantic import BaseModel, Field                          # noqa: E402

import safety                                                  # noqa: E402

log = logging.getLogger("hansang")
app = FastAPI(title="온가족 한상 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"], allow_headers=["*"],
)


class Member(BaseModel):
    name: str = Field("", max_length=20)
    age: str | None = None
    allergies: list[str] = Field(default_factory=list, max_length=20)
    conditions: list[str] = Field(default_factory=list, max_length=12)
    traits: list[str] = Field(default_factory=list, max_length=8)
    goals: list[str] = Field(default_factory=list, max_length=8)


class Recipe(BaseModel):
    id: str | None = None
    title: str = Field(..., max_length=60)
    ingredients: list[str] = Field(default_factory=list, max_length=30)
    steps: list[str] = Field(default_factory=list, max_length=20)


class ReportReq(BaseModel):
    recipe: Recipe
    members: list[Member] = Field(..., min_length=1, max_length=10)


@app.get("/api/health")
def health():
    return {"ok": True, "llm": bool(os.getenv("OPENAI_API_KEY")), "model": safety.MODEL}


@app.post("/api/safety-report")
async def safety_report(req: ReportReq):
    try:
        return await safety.build_report(req.recipe.model_dump(), [m.model_dump() for m in req.members])
    except safety.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception:
        log.exception("safety report failed")
        raise HTTPException(502, "보고서를 만들지 못했어요. 잠시 후 다시 시도해 주세요.")


# 프론트 화면 파일 (../파이널) — API 경로보다 뒤에 붙여야 /api 가 가려지지 않아요
FRONT = Path(__file__).resolve().parent.parent / "파이널"
if FRONT.is_dir():
    app.mount("/", StaticFiles(directory=FRONT, html=True), name="front")
