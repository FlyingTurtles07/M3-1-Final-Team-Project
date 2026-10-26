"""정책 문서(docs/*.md)를 읽어서 data/recipe_policies.json 을 만들고 Firestore(recipe_policies)에 올려요.

    python upload_policies.py            # JSON 만들고 Firestore에 올리기
    python upload_policies.py --dry-run  # JSON만 만들고 올리지 않기

- 정책 문서의 '### 코드 이름' 아래 첫 코드 블록이 정책 글이에요. 그 글이 그대로 AI에 들어가요.
- 유동식(LQ-*)은 앱에서 아직 받지 못해서 active=False로 올려요.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent / "docs"
POLICY_MD = DOCS / "레시피_추천_정책_22종.md"
GUIDE_MD = DOCS / "recipe_guideline.md"
OUT = HERE / "data" / "recipe_policies.json"
INACTIVE_PREFIX = ("LQ-",)
CATEGORY = {"AL": "알러지", "DM": "당뇨식", "NA": "저염식", "QT": "정량", "LQ": "유동식"}

BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def parse_policies(md: str) -> tuple[str, dict]:
    common = ""
    policies = {}
    # '## ' / '### ' 제목으로 나눠서, 각 구간의 첫 코드 블록을 가져와요
    for sec in re.split(r"\n(?=#{2,3} )", md):
        head = sec.split("\n", 1)[0]
        m = BLOCK.search(sec)
        if not m:
            continue
        text = m.group(1).strip()
        if head.startswith("## 공통 규칙"):
            common = text
            continue
        h = re.match(r"### ([A-Z]{2}-\d{2})\s+(.+)", head)
        if h:
            code = h.group(1)
            policies[code] = {"code": code, "category": CATEGORY.get(code[:2], ""), "title": h.group(2).strip(),
                              "text": text, "active": not code.startswith(INACTIVE_PREFIX)}
    return common, policies


def build() -> dict:
    common, policies = parse_policies(POLICY_MD.read_text(encoding="utf-8"))
    m = BLOCK.search(GUIDE_MD.read_text(encoding="utf-8"))
    guideline = m.group(1).strip() if m else ""
    ver = re.search(r"버전:\s*([\d.]+)", GUIDE_MD.read_text(encoding="utf-8"))
    if not common or not guideline or len(policies) != 22:
        sys.exit(f"문서를 제대로 읽지 못했어요: 공통 규칙 {bool(common)}, 지침 {bool(guideline)}, 정책 {len(policies)}개 (22개여야 해요)")
    return {"version": ver.group(1) if ver else "", "common": common, "guideline": guideline, "policies": policies}


def main() -> None:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    active = sum(p["active"] for p in data["policies"].values())
    print(f"{OUT.name}: 정책 {len(data['policies'])}개 (사용 {active}개), 지침 v{data['version']}")
    if "--dry-run" in sys.argv:
        return
    from dotenv import load_dotenv
    load_dotenv(HERE / ".env")
    import fstore
    n = fstore.put_policies(data)
    print(f"Firestore recipe_policies 에 {n}개 문서를 올렸어요")


if __name__ == "__main__":
    main()
