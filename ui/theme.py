"""공용 색/폰트/그리기 헬퍼 (UI 비주얼 통일용).

이전엔 각 ui/*.py 파일마다 BG, TEXT, LAYER_COLOR 같은 색을 따로 정의해서
(예: monitor.py는 BG=(18,18,24), tuning.py는 BG=(16,16,22), main.py는
또 다른 값) 화면마다 톤이 미묘하게 어긋났다. 여기 한 군데서 팔레트와
자주 쓰는 그리기 패턴(패널, 막대그래프)을 정의해서 전부 같은 곳에서 가져다 쓴다.
"""
import functools

import pygame

FONT_FAMILY = "nanumgothic,notosanscjkkr,dejavusans"

# ---- 팔레트 ----
BG_DEEP = (9, 10, 15)          # 화면 맨 바탕
BG_PANEL = (19, 20, 28)        # 패널 채우기
BG_PANEL_ALT = (25, 27, 37)    # 패널 안의 중첩 패널(정보창 등)
BORDER = (55, 58, 76)          # 기본 패널 테두리
BORDER_BRIGHT = (95, 100, 128)  # 선택/강조 테두리

TEXT = (228, 230, 240)
TEXT_DIM = (150, 153, 170)
TEXT_FAINT = (104, 107, 126)

GOLD = (247, 197, 101)      # 도파민/통화/주의
GOOD = (108, 224, 150)      # 회복/흥분성/긍정
DANGER = (235, 102, 110)    # 피해/억제성/경고
INFO = (100, 176, 250)      # 감각/이동 계열
PURPLE = (189, 140, 240)    # 방어/생존 계열

LAYER_COLOR = {
    "sensory": INFO,
    "hidden": (214, 198, 110),
    "motor": (240, 140, 96),
}
EXCITE_COLOR = GOOD
INHIBIT_COLOR = DANGER
PRUNED_COLOR = (70, 70, 78)

VARIANT_COLOR = {
    "agile": (224, 150, 92),
    "alert": (222, 206, 92),
    "tough": (158, 116, 224),
    "boss": GOLD,
}


@functools.lru_cache(maxsize=None)
def font(size, bold=False):
    return pygame.font.SysFont(FONT_FAMILY, size, bold=bold)


def panel(surface, rect, radius=10, bg=BG_PANEL, border=BORDER, border_width=1):
    rect = pygame.Rect(rect)
    pygame.draw.rect(surface, bg, rect, border_radius=radius)
    if border is not None and border_width > 0:
        pygame.draw.rect(surface, border, rect, width=border_width, border_radius=radius)
    return rect


def bar(surface, rect, ratio, fg, bg=(44, 45, 56), radius=3):
    """배경 막대 위에 ratio(0~1)만큼 fg 색으로 채운 막대."""
    rect = pygame.Rect(rect)
    ratio = max(0.0, min(1.0, ratio))
    pygame.draw.rect(surface, bg, rect, border_radius=radius)
    if ratio > 0:
        fill = pygame.Rect(rect.x, rect.y, max(1, int(rect.width * ratio)), rect.height)
        pygame.draw.rect(surface, fg, fill, border_radius=radius)


def hp_color(ratio):
    """체력 비율에 따라 초록->주황->빨강으로 자연스럽게 경고."""
    if ratio > 0.5:
        return GOOD
    if ratio > 0.25:
        return GOLD
    return DANGER


def text(surface, s, pos, size=15, color=TEXT, bold=False):
    surf = font(size, bold).render(s, True, color)
    surface.blit(surf, pos)
    return surf
