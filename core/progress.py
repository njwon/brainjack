"""런을 넘어 영속되는 "연구 진행도" (M6 메타 진행, 최소 버전).

작은 JSON 파일 하나로 역대 최고 생존시간/누적 처치수/역대 격파한 보스 이름을
기록한다. 파일이 없거나(최초 실행) 손상됐으면(수동 편집 실수 등) 조용히 기본값
으로 폴백한다 — 메타 진행은 "있으면 좋은" 보너스 기능이라 이것 때문에 게임 자체가
죽으면 안 된다.
"""
import json
from pathlib import Path

DEFAULT_PROGRESS = {
    "best_survival_time": 0.0,
    "total_kills_all_time": 0,
    "bosses_ever_defeated": [],
}


def load_progress(path) -> dict:
    path = Path(path)
    if not path.exists():
        return dict(DEFAULT_PROGRESS)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_PROGRESS)
    if not isinstance(data, dict):
        return dict(DEFAULT_PROGRESS)
    merged = dict(DEFAULT_PROGRESS)
    for key in DEFAULT_PROGRESS:
        if key in data:
            merged[key] = data[key]
    return merged


def save_progress(path, data: dict):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # 저장 실패(디스크 꽉 찼다든지)해도 게임 진행엔 영향 없어야 함
