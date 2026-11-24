"""엔티티 → (벽/문/창/기타, 신뢰도). 규칙 기반 베이스라인.

ML 분류기를 붙일 때는 classify()와 같은 시그니처로 교체한다.
신뢰도가 낮은 엔티티는 사용자에게 확인을 요청하는 대상이 된다.
규칙 표(KEYWORDS)는 classify(e, rules)로 바꿔 쓸 수 있다.
"""
from dataclasses import dataclass

from .entities import Entity

KEYWORDS = {
    "wall": ("wall", "벽"),
    "door": ("door", "문"),
    "window": ("window", "glaz", "창"),
}
NOT_KEYWORDS = ("outdoor", "indoor", "문자", "문서", "창고")  # 키워드를 우연히 포함하는 흔한 레이어명 (야외, 텍스트, 창고)


@dataclass
class Prediction:
    label: str  # wall | door | window | unknown
    confidence: float


def classify(e: Entity, rules: dict[str, tuple[str, ...]] = KEYWORDS) -> Prediction:
    text = f"{e.layer} {e.block or ''}".lower()
    for w in NOT_KEYWORDS:
        text = text.replace(w, " ")
    for label, words in rules.items():
        if any(w.lower() in text for w in words):
            return Prediction(label, 0.9)
    if e.kind == "ARC":  # 문 열림 호일 가능성, 단독으로는 불확실
        return Prediction("door", 0.5)
    return Prediction("unknown", 0.0)
