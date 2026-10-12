"""성향 다이얼 UI (M5 — 로그라이크 카드뽑기 폐지, 상시 다이얼로 전환).

이전(M4) 설계의 문제: 유저가 "카드 3장 중 하나"를 고르면 그 뒤에서 특정 시냅스
1~3개가 바뀌는 방식이었는데, ①어떤 시냅스가 뭘 하는지 유저가 알 길이 없고
②재귀 신경망이라 "강화"라고 적어놔도 실제로는 역효과가 나는 조합이 섞여 있었다
(해당 skill이 유효한지 손으로 4구역씩 검증해야 했음).

M5 설계: 유저한테는 "공격 성향 / 기동 성향 / 생존 성향" 다이얼 3개만 보인다.
다이얼을 올리면(도파민 소모) 그 뒤에서 실제 시냅스가 한 번에 하나씩 켜진다 —
단, 어떤 시냅스를 몇 번째로 켤지는 게임 시작 시 `build_dial_plan()`이 자동으로
정한다: 그 그룹으로 들어오는 모든 실제 edge 후보를 하나씩 "4구역 전부에서
non-negative인가"로 검증하면서, 매번 그 시점까지 쌓인 상태 기준으로 제일
효과 좋은 걸 그리디하게 골라 순서를 정한다. 역효과가 나는 edge는 아예 plan에서
빠진다 — 그러니까 유저가 다이얼을 올리는 한 "손해 보는 선택"은 구조적으로 없다.
"""
import pygame

from core.brain import Brain
from core.combat import stats_from_brain_output
from core.stages import STIM_STAGES
from ui import theme

DIAL_STEP_COST = 9  # 다이얼 한 칸 올리는 데 드는 도파민
# (실측: 4였을 때 전략과 무관하게 24초만에 7칸이 전부 끝나버려서, 평균 생존시간
#  52~72초 중 1/3~2/3이 "더 할 게 없는" 구간이 됐었음. 9로 올려서 완주 시점을
#  런 후반부로 늦춤 — 총 비용 63 vs 도파민 수입률 약 1.17/s 기준 완주 약 54초.)
EPS = 0.01  # 이것보다 작은 음수는 "사실상 0"으로 보고 허용(수치 노이즈 방지)

# group: 이 다이얼이 들어오는 edge를 찾을 모터 그룹. stat_fn: 그 그룹의 "대표 성능"을
# 하나의 숫자로 요약(여러 스탯을 합쳐도 됨 — 순서를 매기기 위한 기준일 뿐).
DIAL_DEFS = [
    {
        # 실측 결과: 이 커넥톰 서브그래프에서 approach로 들어오는 실제 edge가
        # legs/flee보다 적고(검증 통과 2개뿐) 개별 효과도 작아서, 생존시간에는
        # 거의 기여하지 못하고(단독 투자 시 베이스라인과 사실상 동일) 공격력/
        # 사거리만 확실히 오른다 — 즉 "오래 버티기"보다 "같은 시간에 더 많이
        # 잡기"에 가깝다. 억지로 수치를 끼워맞추는 대신 이름에서부터 솔직하게
        # 역할을 알려준다.
        "id": "approach",
        "title": "공격 성향 (처치수↑)",
        "group": "approach",
        "stat_fn": lambda s: s["attack_power"] + s["attack_range"] * 0.05,
        "color": theme.GOOD,
    },
    {
        "id": "legs",
        "title": "기동 성향 (생존↑)",
        "group": "legs",
        "stat_fn": lambda s: s["move_speed"] * 0.3 + s["evasion"] * 100,
        "color": theme.INFO,
    },
    {
        "id": "flee",
        "title": "생존 성향 (방어↑)",
        "group": "flee",
        "stat_fn": lambda s: s["defense"] * 100,
        "color": theme.PURPLE,
    },
]


def _candidates_for_group(brain, group):
    cands = []
    for e in brain.edges:
        dst_node = brain.id_to_node[e["dst"]]
        if dst_node["group"] != group:
            continue
        src_name = brain.id_to_node[e["src"]]["name"]
        dst_name = dst_node["name"]
        action = "strengthen" if e["original_weight"] >= 0 else "weaken_inhibit"
        cands.append((src_name, dst_name, action))
    return cands


def _measure(brain, stat_fn, stim):
    brain.reset()
    for _ in range(8):
        brain.propagate(stim, substeps=4)
    return stat_fn(stats_from_brain_output(brain.output_summary()))


def _snapshot(edge):
    return dict(edge)


def _restore(brain, edge_id, snap):
    brain.edges[edge_id].update(snap)
    brain.rebuild_W()


def build_dial_plan(data_dir, group, stat_fn, stim_stages=STIM_STAGES):
    """해당 그룹으로 들어오는 실제 edge들을, '순서대로 하나씩 켰을 때 4구역 전부에서
    손해가 안 나는' 그리디 순서로 정렬해서 반환한다.
    [{"src":..,"dst":..,"action":.., "avg_effect": float}, ...]"""
    working = Brain(data_dir)
    remaining = _candidates_for_group(working, group)
    plan = []

    while remaining:
        best_cand, best_avg, best_edge_id, best_step = None, -1e9, None, None
        for cand in list(remaining):
            src, dst, action = cand
            edge_id = working.find_edge_id(src, dst)
            step = 1 if action == "strengthen" else -1

            before_per_stage = [_measure(working, stat_fn, s["stim"]) for s in stim_stages]
            snap = _snapshot(working.edges[edge_id])
            ok = working.adjust_edge(edge_id, step)
            if not ok:
                remaining.remove(cand)  # 이 edge는 더 이상 조정 여지가 없음 — 후보에서 영구 제외
                continue
            after_per_stage = [_measure(working, stat_fn, s["stim"]) for s in stim_stages]
            _restore(working, edge_id, snap)  # 다음 후보 테스트를 위해 되돌림

            deltas = [a - b for a, b in zip(after_per_stage, before_per_stage)]
            if min(deltas) < -EPS:
                continue  # 한 구역에서라도 손해면 이번 라운드엔 채택 안 함
            avg = sum(deltas) / len(deltas)
            if avg <= EPS:
                continue  # 손해는 아니지만 체감 효과가 사실상 0이면 다이얼 칸으로 안 침
            if avg > best_avg:
                best_cand, best_avg, best_edge_id, best_step = cand, avg, edge_id, step

        if best_cand is None:
            break  # 안전하고 눈에 보이게 다음 한 칸을 켤 edge가 더 이상 없음 — 다이얼 여기서 끝

        working.adjust_edge(best_edge_id, best_step)  # 이번엔 되돌리지 않고 영구 적용
        remaining.remove(best_cand)
        src, dst, action = best_cand
        plan.append({
            "src": src, "dst": dst, "action": action,
            "avg_effect": best_avg,
            "label": f"{working.display_name(working.name_to_id[src])} -> {working.display_name(working.name_to_id[dst])}",
        })

    return plan


def build_all_dial_plans(data_dir):
    return {d["id"]: build_dial_plan(data_dir, d["group"], d["stat_fn"]) for d in DIAL_DEFS}


def apply_dial_step(brain, plan_entry):
    """plan의 한 칸(step)을 실제 brain에 적용한다. (build_dial_plan은 검증용 임시
    Brain에서 돌린 것이므로, 실제 게임에 쓰는 brain에는 따로 적용해야 한다.)"""
    edge_id = brain.find_edge_id(plan_entry["src"], plan_entry["dst"])
    if edge_id is None:
        return False
    step = 1 if plan_entry["action"] == "strengthen" else -1
    return brain.adjust_edge(edge_id, step)


class DialPanel:
    """항상 화면에 떠 있는 다이얼 3개. 숫자키 1/2/3으로 한 칸씩 투자."""

    def __init__(self, rect, dial_plans):
        self.rect = pygame.Rect(rect)
        self.dial_plans = dial_plans  # {dial_id: [plan_entry, ...]}
        self.levels = {d["id"]: 0 for d in DIAL_DEFS}
        self.font = theme.font(14)
        self.font_small = theme.font(12)
        self.message = ""
        self.message_timer = 0.0

    def reset(self):
        self.levels = {d["id"]: 0 for d in DIAL_DEFS}

    def max_level(self, dial_id):
        return len(self.dial_plans.get(dial_id, []))

    def invest(self, brain, dial_id, dopamine):
        """도파민을 써서 다음 칸을 켠다. (new_dopamine, 메세지) 반환."""
        plan = self.dial_plans.get(dial_id, [])
        level = self.levels[dial_id]
        if level >= len(plan):
            return dopamine, "이미 이 성향은 끝까지 켰어요"
        if dopamine < DIAL_STEP_COST:
            return dopamine, "도파민 부족"
        entry = plan[level]
        apply_dial_step(brain, entry)
        self.levels[dial_id] += 1
        return dopamine - DIAL_STEP_COST, f"{entry['label']} 시냅스 활성화"

    def update(self, dt):
        if self.message_timer > 0:
            self.message_timer = max(0.0, self.message_timer - dt)

    def set_message(self, text):
        self.message = text
        self.message_timer = 2.5

    def draw(self, surface, dopamine):
        theme.panel(surface, self.rect, radius=8)

        title = self.font.render(
            f"성향 다이얼 (숫자키 1/2/3, 한 칸당 도파민 {DIAL_STEP_COST})", True, theme.TEXT_DIM)
        surface.blit(title, (self.rect.x + 10, self.rect.y + 6))

        # 아래쪽에 메세지(토스트) 한 줄 자리를 미리 떼어놓는다 — 안 그러면 3번째
        # 다이얼 줄 글자 위에 "도파민 부족" 같은 메세지가 겹쳐서 찍혔었다.
        message_h = 18
        row_h = (self.rect.height - 30 - message_h) / len(DIAL_DEFS)
        for i, d in enumerate(DIAL_DEFS):
            y = self.rect.y + 28 + i * row_h
            level = self.levels[d["id"]]
            total = self.max_level(d["id"])
            maxed = total > 0 and level >= total
            label_color = theme.TEXT if maxed else d["color"]
            suffix = " MAX" if maxed else ""
            label = self.font.render(f"[{i + 1}] {d['title']}  {level}/{total}{suffix}", True, label_color)
            surface.blit(label, (self.rect.x + 10, y))

            bar_x = self.rect.x + 190
            bar_w = self.rect.width - 200
            bar_h = 10
            ratio = (level / total) if total > 0 else 0.0
            theme.bar(surface, (bar_x, y + 3, bar_w, bar_h), ratio, d["color"], radius=3)
            for n in range(1, total):
                notch_x = bar_x + bar_w * (n / total)
                pygame.draw.line(surface, theme.BG_PANEL, (notch_x, y + 3), (notch_x, y + 3 + bar_h))

        if self.message and self.message_timer > 0:
            pygame.draw.line(surface, theme.BORDER, (self.rect.x + 8, self.rect.bottom - 20),
                              (self.rect.right - 8, self.rect.bottom - 20), 1)
            msg = self.font_small.render(self.message, True, theme.GOLD)
            surface.blit(msg, (self.rect.x + 10, self.rect.bottom - 17))
