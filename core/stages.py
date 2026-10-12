"""던전 구역별 자극 조합 (스토리: F-01이 구역을 돌파하며 자극이 바뀜).

main.py(실제 게임 루프)와 ui/dials.py(다이얼 후보 검증용 오프라인 시뮬레이션)가
같은 자극 세트를 기준으로 삼아야 "4구역 전부에서 안전하다"는 검증이 실제 플레이와
일치하므로, 한 군데에만 정의해서 공유한다.
"""

STIM_STAGES = [
    {"name": "부엌 (후각)", "stim": {"smell": 2.2, "vibration": 0.2, "light": 0.0},
     "boss_name": "집게벌레 수문장"},
    {"name": "창고 (시각)", "stim": {"smell": 0.3, "vibration": 0.2, "light": 2.5},
     "boss_name": "거미줄 거미"},
    {"name": "실험실 (진동/통각)", "stim": {"smell": 0.2, "vibration": 2.5, "light": 0.5},
     "boss_name": "로봇팔"},
    {"name": "보스: 거미", "stim": {"smell": 1.0, "vibration": 1.5, "light": 1.5},
     "boss_name": "왕거미"},
]
STAGE_DURATION = 12.0  # seconds
