"""뇌 신호 모니터 UI (M2 최소 버전).

뉴런을 레이어별(sensory/hidden/motor)로 열을 나눠 배치하고,
활성도에 따라 색을 바꿔 그린다. 출력 그룹은 막대 그래프로 별도 표시.
"""
import pygame

from core.brain import GROUP_LABEL_KO
from ui import theme


class BrainMonitor:
    def __init__(self, rect, brain):
        self.rect = pygame.Rect(rect)
        self.brain = brain
        self._layout_nodes()

    def _layout_nodes(self):
        by_layer = {"sensory": [], "hidden": [], "motor": []}
        for n in self.brain.nodes:
            by_layer[n["layer"]].append(n)

        self.positions = {}
        cols = ["sensory", "hidden", "motor"]
        col_w = self.rect.width / (len(cols) + 1)
        for ci, layer in enumerate(cols):
            nodes = by_layer[layer]
            x = self.rect.x + col_w * (ci + 1)
            step = self.rect.height / (len(nodes) + 1)
            for i, n in enumerate(nodes):
                y = self.rect.y + step * (i + 1)
                self.positions[n["id"]] = (x, y)

    def draw(self, surface):
        theme.panel(surface, self.rect, radius=8)

        x = self.brain.x
        cap = self.brain.cap
        for n in self.brain.nodes:
            px, py = self.positions[n["id"]]
            activity = min(1.0, float(x[n["id"]]) / cap)
            base = theme.LAYER_COLOR[n["layer"]]
            color = tuple(int(c * (0.3 + 0.7 * activity)) for c in base)
            radius = 5 + int(5 * activity)
            if activity > 0.6:
                pygame.draw.circle(surface, tuple(min(255, int(c * 1.3)) for c in color),
                                    (int(px), int(py)), radius + 3, width=1)
            pygame.draw.circle(surface, color, (int(px), int(py)), radius)

        labels = ["감각(sensory)", "은닉(hidden)", "운동(motor)"]
        col_w = self.rect.width / (len(labels) + 1)
        for ci, label in enumerate(labels):
            surf = theme.font(14).render(label, True, theme.TEXT_DIM)
            surface.blit(surf, (self.rect.x + col_w * (ci + 1) - surf.get_width() / 2, self.rect.y - 18))


class OutputBars:
    def __init__(self, rect):
        self.rect = pygame.Rect(rect)

    # wings(필살기)는 게임 전투 로직에서 완전히 제외했는데(이 서브그래프에서
    # 외부 자극이 전혀 안 닿는 자기순환 루프라 출력이 항상 0.0) data/groups.json
    # 에는 여전히 모터 그룹으로 남아있어서, 걸러내지 않으면 항상 빈 막대가 뜬다.
    HIDDEN_GROUPS = {"wings"}

    def draw(self, surface, output_summary: dict, cap=5.0):
        theme.panel(surface, self.rect, radius=8)

        groups = [(n, v) for n, v in output_summary.items() if n not in self.HIDDEN_GROUPS]
        row_h = self.rect.height / max(1, len(groups))
        for i, (name, value) in enumerate(groups):
            y = self.rect.y + i * row_h + row_h * 0.2
            bar_h = row_h * 0.6
            ratio = min(1.0, max(0.0, value / cap))
            label = theme.font(14).render(GROUP_LABEL_KO.get(name, name), True, theme.TEXT)
            surface.blit(label, (self.rect.x + 8, y))
            bar_x = self.rect.x + 110
            bar_w = self.rect.width - 120
            theme.bar(surface, (bar_x, y, bar_w, bar_h), ratio, theme.LAYER_COLOR["motor"], radius=2)
