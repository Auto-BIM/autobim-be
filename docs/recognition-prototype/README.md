# 인식 v1 프로토타입 (참고 구현)

[../recognition.md](../recognition.md)의 알고리즘을 검증한 코드다. 앱 코드가 아니며 CI의 `pytest`(`testpaths = tests`)는 이 폴더를 돌리지 않는다.
#10 (BE-N1)에서 `app/recognition/`으로 이식한 뒤 **이 폴더를 지운다**(이식 가이드: recognition.md §8).

| 파일 | 내용 |
|---|---|
| `recog_v1.py` | R1~R9: 잡음 제거, 두께 추정, 축 정렬 띠, 같은 선 잇기, 접합부, 열린 끝 연장, 외벽 판정, 개구부 붙이기 |
| `synth.py` | 합성 L자 평면(외벽 24 px, 내벽 14 px, 문 2·창 2), 모델 같은 오류를 넣는 `perturb` |
| `test_recog.py` | 18개 테스트(배율 0.5·1·2 × 깨끗함·잡음, 교란 10시드, 모서리 문, 사선 벽) |

```bash
pip install numpy scipy pytest
cd docs/recognition-prototype && pytest -q      # 18 passed
```
