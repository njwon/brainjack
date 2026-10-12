"""도박 카드 (M6 — 보스 격파 보상, "위험한 선택지").

ui/dials.py의 build_dial_plan()은 각 그룹(approach/legs/flee)의 edge 후보를
그리디로 검증해서 "4구역 전부에서 절대 손해 안 나는" 안전한 edge만 골라 다이얼에
넣는다. 그 과정에서 탈락한(최소 한 구역에서 음수였거나 효과가 체감 안 되는) edge들은
실제로 숙주 뇌에 존재하는 진짜 시냅스지만 안전성이 검증 안 된 채로 그냥 버려졌다 —
이 모듈은 그 "탈락 풀"에서 하나를 뽑아 보스 격파 보상으로 제시한다. 다이얼과 달리
사전 효과 미리보기가 없다: 받아들이면 그 즉시 실제 brain.adjust_edge()가 적용되고,
좋았는지 나빴는지는 기존 stat-diff 토스트로만 드러난다.
"""
import random

import pygame

from ui import theme
from ui.dials import DIAL_DEFS, _candidates_for_group


def pick_gamble_candidate(brain, dial_plans, rng=random):
    """탈락 풀에서 그룹 하나 + edge 하나를 무작위로 골라 카드 dict를 반환.
    모든 그룹의 탈락 풀이 비어있으면(이론상 가능 — 모든 edge가 다 안전하게
    채택된 경우) None을 반환해서 main.py가 카드를 띄우지 않고 그냥 넘어가게 한다."""
    dial_order = list(DIAL_DEFS)
    rng.shuffle(dial_order)
    for d in dial_order:
        all_cands = _candidates_for_group(brain, d["group"])
        used = {(e["src"], e["dst"], e["action"]) for e in dial_plans.get(d["id"], [])}
        pool = [c for c in all_cands if c not in used]
        if not pool:
            continue
        src, dst, action = rng.choice(pool)
        return {
            "dial_id": d["id"],
            "dial_title": d["title"],
            "src": src,
            "dst": dst,
            "action": action,
            "label": f"{brain.display_name(brain.name_to_id[src])} -> {brain.display_name(brain.name_to_id[dst])}",
        }
    return None


def apply_gamble(brain, card):
    """카드를 실제로 적용. (적용됐는지 bool, action 설명 str) 반환."""
    edge_id = brain.find_edge_id(card["src"], card["dst"])
    if edge_id is None:
        return False, "배선을 찾을 수 없음"
    step = 1 if card["action"] == "strengthen" else -1
    ok = brain.adjust_edge(edge_id, step)
    if not ok:
        return False, "이미 조정 한계치 — 효과 없음"
    verb = "강화" if card["action"] == "strengthen" else "억제 완화"
    return True, verb


def draw_gamble_card(screen, card, font, font_small, big_font):
    screen.fill(theme.BG_DEEP)
    w, h = screen.get_size()
    box = pygame.Rect((w - 500) // 2, (h - 280) // 2, 500, 280)
    theme.panel(screen, box, radius=12, bg=(28, 22, 14), border=theme.GOLD, border_width=2)

    title = big_font.render("위험한 선택 — 보스가 남긴 배선", True, theme.GOLD)
    screen.blit(title, (box.x + 20, box.y + 16))

    dial_color = next((d["color"] for d in DIAL_DEFS if d["id"] == card["dial_id"]), theme.TEXT)
    lines = [
        (f"대상 그룹: {card['dial_title']}", dial_color),
        (f"배선: {card['label']}", theme.TEXT),
        (f"조작: {'강화' if card['action'] == 'strengthen' else '억제 완화'}", theme.TEXT),
        ("", None),
        ("검증되지 않음 — 효과를 미리 알 수 없습니다.", theme.GOLD),
        ("(생존에 도움이 될 수도, 역효과가 날 수도 있습니다)", theme.TEXT_DIM),
        ("", None),
        ("더 깊이 알아보고 싶으면 T키 실험실에서", theme.TEXT_DIM),
        ("이 뉴런을 직접 찾아볼 수 있습니다.", theme.TEXT_DIM),
        ("", None),
        ("Y / Enter: 감행하기        N / Esc: 포기하기", theme.GOLD),
    ]
    y = box.y + 58
    for line, color in lines:
        if line:
            screen.blit(font.render(line, True, color), (box.x + 20, y))
        y += 22
