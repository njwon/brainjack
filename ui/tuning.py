"""튜닝 화면 (M3).

서브그래프를 그려서 엣지(시냅스)를 클릭으로 선택하고, "도파민" 재화를 써서
가중치를 +-30% 범위 안에서 조정하거나 프루닝(제거)한다.
"""
import math

import pygame

from core.brain import GROUP_LABEL_KO
from ui import theme

LAYER_COLOR = theme.LAYER_COLOR
EXCITE_COLOR = theme.EXCITE_COLOR
INHIBIT_COLOR = theme.INHIBIT_COLOR
PRUNED_COLOR = theme.PRUNED_COLOR
SELECT_COLOR = (255, 255, 255)
BG = theme.BG_PANEL
PANEL_BG = theme.BG_PANEL_ALT
TEXT = theme.TEXT
DIM_TEXT = theme.TEXT_DIM

ADJUST_COST = 2
PRUNE_COST = 8


class TuningPanel:
    def __init__(self, rect, brain):
        self.rect = pygame.Rect(rect)
        self.brain = brain
        self.font = theme.font(15)
        self.font_small = theme.font(13)
        self.font_big = theme.font(20, bold=True)

        self.graph_rect = pygame.Rect(self.rect.x, self.rect.y + 40, self.rect.width - 260, self.rect.height - 40)
        self.info_rect = pygame.Rect(self.graph_rect.right + 10, self.rect.y + 40, 250, self.rect.height - 40)

        self.selected_edge_id = None
        self._layout_nodes()
        self._buttons = {}  # name -> pygame.Rect, 매 draw마다 갱신
        self.message = ""
        self.message_timer = 0.0

    def _layout_nodes(self):
        by_layer = {"sensory": [], "hidden": [], "motor": []}
        for n in self.brain.nodes:
            by_layer[n["layer"]].append(n)

        self.positions = {}
        cols = ["sensory", "hidden", "motor"]
        pad = 50
        col_w = (self.graph_rect.width - pad * 2) / (len(cols) - 1)
        for ci, layer in enumerate(cols):
            nodes = by_layer[layer]
            x = self.graph_rect.x + pad + col_w * ci
            step = self.graph_rect.height / (len(nodes) + 1)
            for i, n in enumerate(nodes):
                y = self.graph_rect.y + step * (i + 1)
                self.positions[n["id"]] = (x, y)

    def set_message(self, text):
        self.message = text
        self.message_timer = 2.0

    def update(self, dt):
        if self.message_timer > 0:
            self.message_timer -= dt
            if self.message_timer <= 0:
                self.message = ""

    def _edge_width(self, weight):
        return max(1, min(6, 1 + abs(weight) // 3))

    def edge_at_point(self, pos, threshold=7):
        best_id, best_dist = None, threshold
        for e in self.brain.edges:
            if e["pruned"]:
                continue
            p1 = self.positions[e["src"]]
            p2 = self.positions[e["dst"]]
            d = _point_segment_dist(pos, p1, p2)
            if d < best_dist:
                best_dist = d
                best_id = e["id"]
        return best_id

    def handle_click(self, pos, dopamine):
        """클릭 처리. (new_dopamine, consumed) 반환."""
        for name, rect in self._buttons.items():
            if rect.collidepoint(pos):
                return self._handle_button(name, dopamine)

        if self.graph_rect.collidepoint(pos):
            eid = self.edge_at_point(pos)
            self.selected_edge_id = eid
        return dopamine, False

    def _handle_button(self, name, dopamine):
        if self.selected_edge_id is None:
            return dopamine, False
        edge = self.brain.edges[self.selected_edge_id]

        if name == "plus" or name == "minus":
            step = 1 if name == "plus" else -1
            if not self.brain.can_adjust(edge, direction=step):
                self.set_message("더 이상 조정 불가 (한도 초과 또는 범위 끝)")
                return dopamine, False
            if dopamine < ADJUST_COST:
                self.set_message("도파민 부족")
                return dopamine, False
            ok = self.brain.adjust_edge(self.selected_edge_id, step)
            if not ok:
                self.set_message("이미 한계치 (+-30%)")
                return dopamine, False
            self.set_message(f"가중치 {edge['weight']:+d}로 조정")
            return dopamine - ADJUST_COST, True

        if name == "prune":
            if dopamine < PRUNE_COST:
                self.set_message("도파민 부족")
                return dopamine, False
            if edge["pruned"]:
                return dopamine, False
            self.brain.prune_edge(self.selected_edge_id)
            self.set_message("시냅스 프루닝 완료")
            return dopamine - PRUNE_COST, True

        return dopamine, False

    def draw(self, surface, dopamine):
        theme.panel(surface, self.rect, radius=10)

        title = self.font_big.render("실험실 — 시냅스를 클릭해서 직접 조작", True, TEXT)
        surface.blit(title, (self.rect.x + 14, self.rect.y + 8))
        dop = self.font.render(f"도파민: {dopamine}", True, theme.GOLD)
        surface.blit(dop, (self.rect.right - dop.get_width() - 16, self.rect.y + 10))
        legend = self.font_small.render(
            "초록선=흥분성  빨간선=억제성  선 굵기=세기  흰색=선택됨  "
            "결과 예측 불가 — 성향 다이얼과 달리 안전성 검증 안 됨", True, DIM_TEXT)
        surface.blit(legend, (self.rect.x + 14, self.rect.y + 26))

        theme.panel(surface, self.graph_rect, radius=8, bg=PANEL_BG, border=None)
        labels = ["감각", "은닉", "운동"]
        for ci, label in enumerate(labels):
            col_w = (self.graph_rect.width - 100) / 2
            x = self.graph_rect.x + 50 + col_w * ci
            surface.blit(self.font_small.render(label, True, DIM_TEXT), (x - 10, self.graph_rect.y + 4))

        for e in self.brain.edges:
            p1 = self.positions[e["src"]]
            p2 = self.positions[e["dst"]]
            if e["pruned"]:
                pygame.draw.line(surface, PRUNED_COLOR, p1, p2, 1)
                continue
            color = EXCITE_COLOR if e["weight"] >= 0 else INHIBIT_COLOR
            width = self._edge_width(e["weight"])
            if e["id"] == self.selected_edge_id:
                pygame.draw.line(surface, SELECT_COLOR, p1, p2, width + 3)
            pygame.draw.line(surface, color, p1, p2, width)

        for n in self.brain.nodes:
            px, py = self.positions[n["id"]]
            pygame.draw.circle(surface, LAYER_COLOR[n["layer"]], (int(px), int(py)), 7)
            pygame.draw.circle(surface, (10, 10, 14), (int(px), int(py)), 7, width=1)

        self._draw_info_panel(surface, dopamine)

        if self.message:
            msg_surf = self.font.render(self.message, True, (255, 220, 140))
            surface.blit(msg_surf, (self.graph_rect.x + 10, self.graph_rect.bottom - 24))

    def _draw_info_panel(self, surface, dopamine):
        rect = self.info_rect
        theme.panel(surface, rect, radius=8, bg=PANEL_BG, border=None)
        self._buttons = {}

        if self.selected_edge_id is None:
            hint_lines = [
                "왼쪽 그래프에서",
                "점과 점을 잇는",
                "'선'을 클릭하세요.",
                "",
                "선택하면 여기에",
                "+1/-1/프루닝",
                "버튼이 나와요.",
            ]
            y = rect.y + 16
            for line in hint_lines:
                surface.blit(self.font_small.render(line, True, DIM_TEXT), (rect.x + 12, y))
                y += 20
            return

        edge = self.brain.edges[self.selected_edge_id]
        src_node = self.brain.id_to_node[edge["src"]]
        dst_node = self.brain.id_to_node[edge["dst"]]
        src_label = self.brain.display_name(edge["src"])
        dst_label = self.brain.display_name(edge["dst"])
        lo, hi = self.brain.edge_bounds(edge)
        sign_word = "흥분성(+)" if edge["weight"] >= 0 else "억제성(-)"

        lines = [
            f"{src_label}  ->  {dst_label}",
            sign_word,
            f"현재 가중치: {edge['weight']:+d}",
            f"원본 {edge['original_weight']:+d}  범위 {lo:+d}~{hi:+d}",
            f"조정 횟수: {edge['adjust_count']}/{self.brain.MAX_ADJUSTMENTS}",
            "프루닝됨" if edge["pruned"] else "",
        ]
        y = rect.y + 14
        for line in lines:
            if not line:
                continue
            surf = self.font_small.render(line, True, TEXT)
            surface.blit(surf, (rect.x + 12, y))
            y += 18

        # 은닉 뉴런이 걸려있으면 '정확히 어디서 와서 어디로 가는지'를 풀어서 보여줌
        extra = []
        if dst_node["layer"] == "hidden":
            motors = self.brain.reachable_motor_groups(edge["dst"])
            if motors:
                names = ", ".join(GROUP_LABEL_KO.get(g, g) for g in sorted(motors))
                extra.append(f"{dst_label} 최종 영향 -> {names}")
            else:
                extra.append(f"{dst_label}는 아직 출력과 안 이어짐")
        if src_node["layer"] == "hidden":
            sensors = self.brain.reachable_sensory_groups(edge["src"])
            if sensors:
                names = ", ".join(GROUP_LABEL_KO.get(g, g) for g in sorted(sensors))
                extra.append(f"{src_label}로 들어오는 입력 <- {names}")

        if extra:
            y += 4
            max_w = rect.width - 24
            for line in extra:
                for wrapped in self._wrap_text(line, max_w):
                    surf = self.font_small.render(wrapped, True, (170, 200, 255))
                    surface.blit(surf, (rect.x + 12, y))
                    y += 18
            y += 6

        y += 10
        btn_w, btn_h = 60, 32
        plus_rect = pygame.Rect(rect.x + 12, y, btn_w, btn_h)
        minus_rect = pygame.Rect(rect.x + 12 + btn_w + 10, y, btn_w, btn_h)
        self._draw_button(surface, plus_rect, f"+1 ({ADJUST_COST})", tuple(c // 2 for c in theme.GOOD))
        self._draw_button(surface, minus_rect, f"-1 ({ADJUST_COST})", tuple(c // 2 for c in theme.DANGER))
        self._buttons["plus"] = plus_rect
        self._buttons["minus"] = minus_rect

        y += btn_h + 14
        prune_rect = pygame.Rect(rect.x + 12, y, btn_w * 2 + 10, btn_h)
        label = "프루닝됨" if edge["pruned"] else f"프루닝 ({PRUNE_COST})"
        self._draw_button(surface, prune_rect, label, tuple(c // 2 for c in theme.PURPLE))
        self._buttons["prune"] = prune_rect

    def _wrap_text(self, text, max_width):
        words = text.split(" ")
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if self.font_small.size(trial)[0] <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def _draw_button(self, surface, rect, label, color):
        pygame.draw.rect(surface, color, rect, border_radius=6)
        pygame.draw.rect(surface, (255, 255, 255), rect, width=1, border_radius=6)
        text = self.font_small.render(label, True, TEXT)
        surface.blit(text, (rect.centerx - text.get_width() / 2, rect.centery - text.get_height() / 2))


def _point_segment_dist(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)
