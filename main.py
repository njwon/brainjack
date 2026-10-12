"""뉴런 브레인 서바이벌 - M6 프로토타입 (기생충 반전 + 뇌 건너뛰기 전투).

실제 FlyWire 커넥톰 서브그래프로 구동. 플레이어는 숙주(F-01) 뇌에 사는 기생충이고,
적은 전부 다른 초파리 개체(변종)다. 적과 접촉하면 그 적의 작은 미니 뇌 속으로
순간이동해(뇌 침투 모드) 시냅스를 몇 번 감염시켜 처치한다.
실행: python main.py (최초 1회 tools/extract_flywire.py 필요)
"""
import math
import sys
from pathlib import Path

import pygame

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.brain import Brain
from core.combat import (
    Battle, HOP_TIME_LIMIT, stats_from_brain_output, describe_stat_changes,
    BASE_HP_REGEN, HP_REGEN_PER_DEFENSE,
)
from core.stages import STIM_STAGES, STAGE_DURATION
from core.progress import load_progress, save_progress
from ui.monitor import BrainMonitor, OutputBars
from ui.tuning import TuningPanel
from ui.dials import DialPanel, DIAL_DEFS, DIAL_STEP_COST, build_all_dial_plans
from ui.gamble import pick_gamble_candidate, apply_gamble, draw_gamble_card
from ui import theme

DATA_DIR = Path(__file__).resolve().parent / "data"
PROGRESS_PATH = DATA_DIR / "research_progress.json"
BRAIN_TICK_DT = 0.1  # 10Hz
DOPAMINE_PER_KILL = 2
DOPAMINE_PER_STAGE = 5
HOP_CURSOR_SPEED = 220.0   # 뇌 침투 모드에서 기생충 커서 이동속도(px/s)
HOP_HIT_RADIUS = 20.0      # 커서가 이 거리 안이면 시냅스 감염 가능
HOP_SCALE = 2.3            # 미니 뇌 로컬 좌표 -> 화면 좌표 확대 배율
WINDOW_W, WINDOW_H = 980, 630


def main():
    if not (DATA_DIR / "subgraph_nodes.csv").exists():
        print("연결체 데이터가 없어요. 먼저 실행: python tools/extract_flywire.py")
        return

    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("뉴런 브레인 서바이벌 - 프로토타입")
    clock = pygame.time.Clock()
    font = theme.font(16)
    font_small = theme.font(13)
    big_font = theme.font(28, bold=True)

    screen.fill(theme.BG_DEEP)
    loading = big_font.render("뇌 배선 안전성 검증 중...", True, theme.TEXT_DIM)
    screen.blit(loading, (340, 280))
    pygame.display.flip()
    dial_plans = build_all_dial_plans(DATA_DIR)

    progress = load_progress(PROGRESS_PATH)  # 역대 최고 생존시간 등 (M6 메타 진행)

    brain = Brain(DATA_DIR)
    battle = Battle()
    monitor = BrainMonitor((660, 40, 300, 300), brain)
    bars = OutputBars((660, 360, 300, 180))
    tuning_panel = TuningPanel((20, 20, 940, 560), brain)

    field_rect = pygame.Rect(20, 20, 620, 400)
    # 전장 밑 HUD 띠 — 예전엔 쌓인 텍스트 줄이 다이얼 패널과 겹쳤어서(4줄*20px=80px인데
    # 틈은 68px뿐) 창 높이를 넉넉히 늘리고 이 두 영역의 세로 공간을 명시적으로 나눴다.
    hud_rect = pygame.Rect(field_rect.x, field_rect.bottom + 6, field_rect.width, 80)
    dial_panel = DialPanel((20, hud_rect.bottom + 6, 620, WINDOW_H - (hud_rect.bottom + 6) - 10), dial_plans)

    brain_accum = 0.0
    stage_timer = 0.0
    stage_idx = 0
    current_stats = stats_from_brain_output(brain.output_summary())
    dopamine = 0
    prev_score = 0
    tuning_mode = False
    show_intro = True
    stat_change_title = ""
    stat_change_lines = []
    stat_change_timer = 0.0

    brain_hop_mode = False
    hop_target = None
    hop_timer = 0.0
    hop_cursor_x, hop_cursor_y = 0.0, 0.0
    hop_flash = ""
    hop_flash_timer = 0.0

    # 보스전 + 승리 조건(M6) — 구역 타이머가 끝나도 바로 다음 구역으로 넘어가지
    # 않고, 그 구역 보스를 전장에 꽂아넣고 "보스 대기" 상태로 들어간다. 일반 몹은
    # 그대로 계속 스폰되므로(Battle.update가 알아서 처리) 보스를 피해다녀도
    # 도파민 벌이는 계속 가능 — 소프트락 방지.
    boss_pending = False
    boss_enemy = None
    game_won = False
    death_saved = False  # 죽음 1회당 진행도 저장 1번만 (반복 저장 방지)

    gamble_card = None  # 보스 격파 보상 카드 (dict) — None이면 안 떠 있음

    dial_key_to_id = {
        pygame.K_1: DIAL_DEFS[0]["id"],
        pygame.K_2: DIAL_DEFS[1]["id"],
        pygame.K_3: DIAL_DEFS[2]["id"],
    }

    intro_lines = [
        "당신은 초파리가 아니라, 숙주(F-01)의 뇌에 사는 기생충입니다.",
        "",
        "① 적도 전부 다른 초파리(변종)입니다. 접촉하면 자동으로 그 적의 뇌 속으로 뛰어듭니다 — '뇌 침투'.",
        "② 뇌 침투 중: 방향키로 기생충 이동, 스페이스로 가까운 시냅스 감염. 필요 횟수만큼 감염시키면 처치.",
        f"   제한시간({HOP_TIME_LIMIT:.0f}초) 안에 못 끝내면 쫓겨나며 피해를 입습니다 — 빠르게!",
        "③ 평소(비접촉 시)엔 화면 아래 '성향 다이얼' 3개 — 숫자키 1/2/3으로 도파민을 써서 숙주 자신의 뇌를 강화합니다.",
        "④ T키 — 숙주의 '실험실'(뇌 내부 자유탐험). 결과를 예측할 수 없습니다 — 진짜 신경과학이 그렇습니다.",
        "⑤ 각 구역(부엌/창고/실험실/거미굴) 끝에는 그 구역의 보스가 등장합니다 —",
        "   4번째 보스(왕거미)까지 전부 처치하면 '탈출 성공', 진짜 승리입니다!",
        "⑥ 보스를 처치하면 '위험한 선택' 카드를 받습니다 — 검증 안 된 배선에 도박(Y/N), 효과는 미지수.",
        "",
        "R: 처음부터 다시 시작    H: 이 설명 다시 보기    아무 키나 눌러서 시작!",
    ]
    if progress["best_survival_time"] > 0:
        intro_lines.insert(-1, f"역대 최고 생존시간: {progress['best_survival_time']:.1f}s"
                                f"  (누적 처치 {progress['total_kills_all_time']}, "
                                f"격파한 보스 {len(progress['bosses_ever_defeated'])}/{len(STIM_STAGES)})")

    def reset_run():
        nonlocal battle, stage_idx, stage_timer, dopamine, prev_score
        nonlocal stat_change_title, stat_change_lines, stat_change_timer
        nonlocal brain_hop_mode, hop_target, hop_timer
        nonlocal boss_pending, boss_enemy, game_won, death_saved, gamble_card
        battle = Battle()
        brain.reset()
        brain.reset_edges()
        dial_panel.reset()
        stage_idx, stage_timer = 0, 0.0
        dopamine = 0
        prev_score = 0
        stat_change_title = ""
        stat_change_lines = []
        stat_change_timer = 0.0
        brain_hop_mode = False
        hop_target = None
        hop_timer = 0.0
        boss_pending = False
        boss_enemy = None
        game_won = False
        death_saved = False
        gamble_card = None

    def invest_in_dial(dial_id):
        nonlocal dopamine, current_stats, stat_change_title, stat_change_lines, stat_change_timer
        before_stats = current_stats
        dopamine, msg = dial_panel.invest(brain, dial_id, dopamine)
        dial_panel.set_message(msg)
        brain.propagate(STIM_STAGES[stage_idx]["stim"], substeps=8)
        current_stats = stats_from_brain_output(brain.output_summary())
        title = next(d["title"] for d in DIAL_DEFS if d["id"] == dial_id)
        stat_change_title = f"[{title}] {msg}"
        stat_change_lines = describe_stat_changes(before_stats, current_stats)
        if not stat_change_lines:
            stat_change_lines = ["지금 당장은 측정 가능한 변화 없음"]
        stat_change_timer = 4.0

    def approach_bonus():
        # 접근(approach) 성향에 1칸이라도 투자했으면 모든 변이체의 필요 감염
        # 횟수가 1 줄어든다 — 연속된 수치 공식이 아니라 "투자 여부" 이산 기준을
        # 쓰는 이유: attack_power를 그대로 공식에 넣으면 이 서브그래프의
        # approach 베이스라인이 이미 높아서(과거 공격쿨타임 실험 때 확인) 투자
        # 여부와 무관하게 보너스가 적용돼버린다.
        return 1 if dial_panel.levels.get("approach", 0) >= 1 else 0

    def enter_hop(target):
        nonlocal brain_hop_mode, hop_target, hop_timer, hop_cursor_x, hop_cursor_y
        brain_hop_mode = True
        hop_target = target
        hop_timer = 0.0
        hop_cursor_x = field_rect.centerx
        hop_cursor_y = field_rect.centery

    def exit_hop(killed):
        nonlocal brain_hop_mode, hop_target, hop_flash, hop_flash_timer
        brain_hop_mode = False
        if killed:
            battle.score += 1
            if hop_target in battle.enemies:
                battle.enemies.remove(hop_target)
            hop_flash, hop_flash_timer = "감염 완료 — 처치!", 1.2
        hop_target = None

    def record_run_end():
        # 사망/승리 시 1회 호출 — 역대 최고 생존시간/누적 처치수를 갱신하고 저장.
        if battle.time_survived > progress["best_survival_time"]:
            progress["best_survival_time"] = battle.time_survived
        progress["total_kills_all_time"] += battle.score
        save_progress(PROGRESS_PATH, progress)

    def offer_gamble_card():
        nonlocal gamble_card
        gamble_card = pick_gamble_candidate(brain, dial_plans)
        # 탈락 풀이 전부 비어있으면(모든 edge가 다이얼에 채택된 극단적 경우)
        # None이 돌아오고, 그냥 카드 없이 넘어간다 — 크래시 안 남.

    def accept_gamble():
        nonlocal gamble_card, current_stats, stat_change_title, stat_change_lines, stat_change_timer
        card = gamble_card
        gamble_card = None
        before_stats = current_stats
        applied, desc = apply_gamble(brain, card)
        brain.propagate(STIM_STAGES[stage_idx]["stim"], substeps=8)
        current_stats = stats_from_brain_output(brain.output_summary())
        stat_change_title = f"[도박 — {card['label']}] {desc}"
        stat_change_lines = describe_stat_changes(before_stats, current_stats)
        if not stat_change_lines:
            stat_change_lines = ["지금 당장은 측정 가능한 변화 없음"]
        stat_change_timer = 4.0

    def decline_gamble():
        nonlocal gamble_card
        gamble_card = None

    def handle_boss_defeated():
        # 보스가 죽은 "그" 순간 호출됨 (뇌 침투 중 register_hit이 killed=True를
        # 반환한 대상이 boss_enemy였을 때만). 마지막 구역(인덱스 끝)이면 그대로
        # 진짜 승리(game_won) 처리하고 더 이상 구역을 안 넘긴다.
        nonlocal boss_pending, boss_enemy, stage_idx, stage_timer, dopamine, game_won
        boss_name = STIM_STAGES[stage_idx].get("boss_name", "보스")
        if boss_name not in progress["bosses_ever_defeated"]:
            progress["bosses_ever_defeated"].append(boss_name)
        save_progress(PROGRESS_PATH, progress)

        boss_pending = False
        boss_enemy = None
        dopamine += DOPAMINE_PER_STAGE

        if stage_idx >= len(STIM_STAGES) - 1:
            game_won = True
            record_run_end()
        else:
            stage_idx += 1
            stage_timer = 0.0
            offer_gamble_card()

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif show_intro:
                if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                    show_intro = False
            elif gamble_card is not None:
                # 도박 카드가 떠 있는 동안은 다른 입력(실험실 토글, 다이얼 투자 등)
                # 전부 막는다 — tuning_mode/brain_hop_mode와 동일한 모달 패턴.
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_y, pygame.K_RETURN):
                        accept_gamble()
                    elif event.key in (pygame.K_n, pygame.K_ESCAPE):
                        decline_gamble()
            elif brain_hop_mode:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        exit_hop(killed=False)
                    elif event.key == pygame.K_SPACE and hop_target is not None:
                        ox = field_rect.centerx - 100 * HOP_SCALE
                        oy = field_rect.centery - 90 * HOP_SCALE
                        for n in hop_target.mini_nodes:
                            if n["infected"]:
                                continue
                            nx, ny = ox + n["x"] * HOP_SCALE, oy + n["y"] * HOP_SCALE
                            if (nx - hop_cursor_x) ** 2 + (ny - hop_cursor_y) ** 2 <= HOP_HIT_RADIUS ** 2:
                                was_boss = hop_target is boss_enemy
                                killed = hop_target.register_hit(n["id"], approach_bonus())
                                if killed:
                                    exit_hop(killed=True)
                                    if was_boss:
                                        handle_boss_defeated()
                                break
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    reset_run()
                elif event.key == pygame.K_t:
                    tuning_mode = not tuning_mode
                elif event.key == pygame.K_h:
                    show_intro = True
                elif event.key == pygame.K_ESCAPE:
                    if tuning_mode:
                        tuning_mode = False
                    else:
                        running = False
                elif not tuning_mode and event.key in dial_key_to_id:
                    invest_in_dial(dial_key_to_id[event.key])
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and tuning_mode:
                dopamine, _ = tuning_panel.handle_click(event.pos, dopamine)

        if stat_change_timer > 0:
            stat_change_timer = max(0.0, stat_change_timer - dt)
        if hop_flash_timer > 0:
            hop_flash_timer = max(0.0, hop_flash_timer - dt)
        dial_panel.update(dt)

        if show_intro:
            pass
        elif gamble_card is not None:
            pass  # 도박 카드 선택 중엔 전투/타이머 전부 일시정지 (tuning_mode와 동일 패턴)
        elif tuning_mode:
            tuning_panel.update(dt)
        elif brain_hop_mode:
            keys = pygame.key.get_pressed()
            mvx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
            mvy = (keys[pygame.K_DOWN] or keys[pygame.K_s]) - (keys[pygame.K_UP] or keys[pygame.K_w])
            if mvx or mvy:
                norm = (mvx ** 2 + mvy ** 2) ** 0.5
                hop_cursor_x += HOP_CURSOR_SPEED * dt * mvx / norm
                hop_cursor_y += HOP_CURSOR_SPEED * dt * mvy / norm
                hop_cursor_x = max(field_rect.left + 10, min(field_rect.right - 10, hop_cursor_x))
                hop_cursor_y = max(field_rect.top + 10, min(field_rect.bottom - 10, hop_cursor_y))

            hop_timer += dt
            if hop_timer >= HOP_TIME_LIMIT:
                battle.take_hop_timeout_damage(current_stats)
                hop_flash, hop_flash_timer = "침투 실패 — 피해!", 1.0
                exit_hop(killed=False)
                if not battle.player.alive and not death_saved:
                    record_run_end()
                    death_saved = True
        elif not game_won:
            stage_timer += dt
            # 구역 타이머가 끝나면 바로 다음 구역으로 넘기지 않고, 그 구역 보스를
            # 전장에 1회 꽂아넣고 "보스 대기" 상태로 들어간다 — 실제 구역 전환은
            # handle_boss_defeated()에서 보스가 죽어야 일어난다. 일반 몹 스폰은
            # Battle.update()가 알아서 계속하므로(아래) 보스를 피해도 도파민은
            # 계속 벌 수 있다 — 소프트락 방지.
            if stage_timer >= STAGE_DURATION and not boss_pending:
                boss_pending = True
                boss_enemy = battle.spawn_boss(STIM_STAGES[stage_idx].get("boss_name", "보스"))

            brain_accum += dt
            while brain_accum >= BRAIN_TICK_DT:
                brain_accum -= BRAIN_TICK_DT
                brain.propagate(STIM_STAGES[stage_idx]["stim"], substeps=4)
                current_stats = stats_from_brain_output(brain.output_summary())

            if battle.player.alive:
                contact = battle.update(dt, current_stats)
                if battle.score > prev_score:
                    dopamine += (battle.score - prev_score) * DOPAMINE_PER_KILL
                    prev_score = battle.score
                if contact is not None:
                    enter_hop(contact)
            elif not death_saved:
                record_run_end()
                death_saved = True
        # game_won True면 여기서 완전히 멈춤 — 구역/전투 로직이 더 이상 돌지 않음.

        # ---- 렌더 ----
        screen.fill((10, 10, 14))

        if show_intro:
            overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
            overlay.fill((8, 8, 12, 235))
            screen.blit(overlay, (0, 0))

            card = pygame.Rect(40, 36, WINDOW_W - 80, WINDOW_H - 72)
            theme.panel(screen, card, radius=14, bg=(16, 17, 24), border=theme.BORDER_BRIGHT, border_width=2)

            title = big_font.render("뉴런 브레인 서바이벌 - 플레이 방법", True, theme.GOLD)
            screen.blit(title, (card.x + 24, card.y + 20))
            pygame.draw.line(screen, theme.BORDER, (card.x + 24, card.y + 62),
                              (card.right - 24, card.y + 62), 1)

            y = card.y + 80
            for line in intro_lines:
                is_point = line.startswith(("①", "②", "③", "④", "⑤", "⑥"))
                is_cta = line.startswith("R:")
                is_record = line.startswith("역대")
                if is_cta:
                    color = theme.GOOD
                elif is_record:
                    color = theme.GOLD
                elif is_point:
                    color = theme.TEXT
                else:
                    color = theme.TEXT_DIM
                screen.blit(font.render(line, True, color), (card.x + 24, y))
                y += 28
        elif gamble_card is not None:
            draw_gamble_card(screen, gamble_card, font, font_small, big_font)
        elif tuning_mode:
            tuning_panel.draw(screen, dopamine)
            hint = font.render("T: 전투로 복귀   Esc: 전투로 복귀", True, theme.TEXT_DIM)
            screen.blit(hint, (20, WINDOW_H - 24))
        elif brain_hop_mode and hop_target is not None:
            is_boss = hop_target is boss_enemy
            accent = theme.GOLD if is_boss else theme.DANGER
            theme.panel(screen, field_rect, radius=10, bg=(26, 16, 18), border=accent, border_width=2 if is_boss else 1)

            ox = field_rect.centerx - 100 * HOP_SCALE
            oy = field_rect.centery - 90 * HOP_SCALE
            for a, b in hop_target.mini_edges:
                na = hop_target.mini_nodes[a]
                nb = hop_target.mini_nodes[b]
                pygame.draw.line(screen, (90, 50, 55),
                                  (ox + na["x"] * HOP_SCALE, oy + na["y"] * HOP_SCALE),
                                  (ox + nb["x"] * HOP_SCALE, oy + nb["y"] * HOP_SCALE), 1)
            for n in hop_target.mini_nodes:
                px, py = ox + n["x"] * HOP_SCALE, oy + n["y"] * HOP_SCALE
                color = theme.GOOD if n["infected"] else theme.DANGER
                pygame.draw.circle(screen, color, (int(px), int(py)), 11)
                pygame.draw.circle(screen, (20, 20, 24), (int(px), int(py)), 11, width=1)

            pygame.draw.circle(screen, (230, 230, 100), (int(hop_cursor_x), int(hop_cursor_y)), 7)
            pygame.draw.circle(screen, (90, 90, 30), (int(hop_cursor_x), int(hop_cursor_y)), 7, width=1)

            need = hop_target.hits_needed(approach_bonus())
            bar = pygame.Rect(field_rect.x + 10, field_rect.bottom - 34, field_rect.width - 20, 16)
            frac = max(0.0, 1 - hop_timer / HOP_TIME_LIMIT)
            theme.bar(screen, bar, frac, theme.DANGER if frac < 0.3 else theme.GOLD, bg=(50, 30, 32), radius=4)
            for seg in range(1, need):
                sx = bar.x + bar.width * (seg / need)
                pygame.draw.line(screen, (20, 12, 14), (sx, bar.y), (sx, bar.y + bar.height))
            name_color = theme.GOLD if is_boss else theme.TEXT
            label = font.render(
                f"뇌 침투: {hop_target.name} — 감염 {hop_target.hits_taken}/{need}  "
                f"(화살표 이동, 스페이스로 감염, Esc로 후퇴)", True, name_color)
            screen.blit(label, (field_rect.x + 10, field_rect.y + 8))
        else:
            theme.panel(screen, field_rect, radius=10, bg=(24, 24, 30))

            ox, oy = field_rect.x, field_rect.y
            p = battle.player
            p_color = theme.GOOD if p.alive else theme.DANGER
            pygame.draw.circle(screen, p_color, (int(ox + p.x), int(oy + p.y)), 12)
            pygame.draw.circle(screen, (255, 255, 255), (int(ox + p.x), int(oy + p.y)),
                                int(current_stats["attack_range"]), width=1)
            php_ratio = p.hp / p.max_hp if p.max_hp else 0.0
            php_bar = pygame.Rect(int(ox + p.x - 14), int(oy + p.y - 24), 28, 4)
            theme.bar(screen, php_bar, php_ratio, theme.hp_color(php_ratio), bg=(40, 40, 46), radius=2)

            pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 180.0)  # 보스 링 숨쉬기 효과
            for e in battle.enemies:
                color = theme.VARIANT_COLOR.get(e.variant, theme.DANGER)
                radius = 15 if e.variant == "boss" else 9
                ex, ey = int(ox + e.x), int(oy + e.y)
                if e.variant == "boss":
                    glow_r = radius + 5 + int(3 * pulse)
                    pygame.draw.circle(screen, color, (ex, ey), glow_r, width=2)
                pygame.draw.circle(screen, color, (ex, ey), radius)
                if e.variant == "boss":
                    pygame.draw.circle(screen, (255, 255, 255), (ex, ey), radius, width=2)

                # 처치 진행도를 글자 대신 칸(pip)으로 — 숫자 안 읽어도 한눈에 "몇 번 남았는지" 보임
                needed = e.hits_needed(approach_bonus())
                pip_w, pip_gap = 7, 2
                total_w = needed * pip_w + (needed - 1) * pip_gap
                pip_y = ey - radius - 10
                for i in range(needed):
                    px_ = ex - total_w / 2 + i * (pip_w + pip_gap)
                    filled = i < e.hits_taken
                    pygame.draw.rect(screen, color if filled else (60, 60, 66), (px_, pip_y, pip_w, 4), border_radius=1)
                if e.variant == "boss":
                    tag = font_small.render(e.name, True, theme.GOLD)
                    screen.blit(tag, (ex - tag.get_width() / 2, pip_y - 16))

            # 전장 위에 잠깐 뜨는 전투 피드백(처치/침투 실패) — 아래 HUD 줄에 끼워넣지 않고
            # 눈에 바로 띄도록 전장 상단 중앙에 큼직하게 띄운다.
            if hop_flash_timer > 0:
                # 좌상단은 stat_change 토스트가 쓰므로, 겹치지 않게 우상단에 띄운다.
                flash_color = theme.GOOD if "완료" in hop_flash else theme.DANGER
                flash_surf = font.render(hop_flash, True, flash_color)
                alpha = min(255, int(255 * min(1.0, hop_flash_timer / 0.3)))
                flash_surf.set_alpha(alpha)
                screen.blit(flash_surf, (field_rect.right - flash_surf.get_width() - 10, field_rect.y + 10))

            if game_won:
                stage_hud = "탈출 성공! F-01의 뇌를 완전히 장악했습니다."
                stage_color = theme.GOOD
            elif boss_pending:
                stage_hud = (f"구역: {STIM_STAGES[stage_idx]['name']}  보스 등장: "
                             f"{STIM_STAGES[stage_idx].get('boss_name', '보스')} (접촉하면 뇌 침투 시작)")
                stage_color = theme.GOLD
            else:
                stage_hud = (f"구역: {STIM_STAGES[stage_idx]['name']}  "
                             f"(다음 전환까지 {STAGE_DURATION - stage_timer:4.1f}s)")
                stage_color = theme.TEXT

            # ---- 하단 HUD 띠: 구역/보상 줄, 체력 바, 보조 스탯 줄 — 3개 고정 행으로 정리 ----
            theme.panel(screen, hud_rect, radius=8)
            row_y = hud_rect.y + 7
            screen.blit(font.render(stage_hud, True, stage_color), (hud_rect.x + 10, row_y))
            hint = font_small.render("[T] 실험실   [H] 설명", True, theme.TEXT_FAINT)
            screen.blit(hint, (hud_rect.right - hint.get_width() - 10, row_y + 2))
            dop = font_small.render(f"도파민 {dopamine}", True, theme.GOLD)
            screen.blit(dop, (hud_rect.right - hint.get_width() - dop.get_width() - 24, row_y + 2))

            row_y += 24
            hp_bar_rect = pygame.Rect(hud_rect.x + 10, row_y + 2, 220, 14)
            theme.bar(screen, hp_bar_rect, php_ratio, theme.hp_color(php_ratio), radius=4)
            hp_label = font_small.render(f"HP {p.hp:.0f}/{p.max_hp:.0f}", True, theme.TEXT)
            screen.blit(hp_label, (hp_bar_rect.x + 6, hp_bar_rect.y - 1))
            regen = BASE_HP_REGEN + current_stats["defense"] * HP_REGEN_PER_DEFENSE
            meta = font_small.render(
                f"(+{regen:.1f}/s)   생존 {battle.time_survived:.1f}s   처치 {battle.score}",
                True, theme.TEXT_DIM)
            screen.blit(meta, (hp_bar_rect.right + 12, row_y + 2))

            row_y += 24
            stat_line = (
                f"속도 {current_stats['move_speed']:.0f}  회피 {current_stats['evasion']*100:.0f}%  "
                f"방어 {current_stats['defense']*100:.0f}%  공격력 {current_stats['attack_power']:.1f}  "
                f"침투사거리 {current_stats['attack_range']:.0f}")
            screen.blit(font_small.render(stat_line, True, theme.TEXT_FAINT), (hud_rect.x + 10, row_y))

            if stat_change_timer > 0:
                box_h = 26 + len(stat_change_lines) * 20
                box = pygame.Rect(field_rect.x + 10, field_rect.y + 10, 400, box_h)
                overlay = pygame.Surface(box.size, pygame.SRCALPHA)
                overlay.fill((15, 15, 22, 230))
                screen.blit(overlay, box.topleft)
                pygame.draw.rect(screen, theme.GOLD, box, width=1, border_radius=6)
                screen.blit(font.render(stat_change_title, True, theme.GOLD), (box.x + 10, box.y + 6))
                for i, line in enumerate(stat_change_lines):
                    color = theme.GOOD if "+" in line else theme.TEXT
                    screen.blit(font.render(line, True, color), (box.x + 10, box.y + 26 + i * 20))

            if game_won:
                msg = big_font.render("탈출 성공! - R로 다시 플레이", True, theme.GOOD)
                screen.blit(msg, (field_rect.centerx - msg.get_width() / 2, field_rect.centery - 50))
                summary_lines = [
                    f"생존시간: {battle.time_survived:.1f}s   감염 처치: {battle.score}",
                    f"다이얼 레벨 — 공격 {dial_panel.levels['approach']}/{dial_panel.max_level('approach')}  "
                    f"기동 {dial_panel.levels['legs']}/{dial_panel.max_level('legs')}  "
                    f"생존 {dial_panel.levels['flee']}/{dial_panel.max_level('flee')}",
                    f"역대 최고 생존시간: {progress['best_survival_time']:.1f}s"
                    f"   누적 처치: {progress['total_kills_all_time']}",
                ]
                for i, line in enumerate(summary_lines):
                    surf = font.render(line, True, theme.TEXT)
                    screen.blit(surf, (field_rect.centerx - surf.get_width() / 2, field_rect.centery + 2 + i * 22))
            elif not p.alive:
                msg = big_font.render("GAME OVER - R로 재시작", True, theme.DANGER)
                screen.blit(msg, (field_rect.centerx - msg.get_width() / 2, field_rect.centery - 40))
                over_line = font.render(
                    f"역대 최고 생존시간: {progress['best_survival_time']:.1f}s"
                    f"   누적 처치: {progress['total_kills_all_time']}",
                    True, theme.TEXT_DIM)
                screen.blit(over_line, (field_rect.centerx - over_line.get_width() / 2, field_rect.centery + 4))

            dial_panel.draw(screen, dopamine)

            monitor.draw(screen)
            bars.draw(screen, brain.output_summary(), cap=brain.cap)
            screen.blit(font.render("뇌 신호 모니터", True, theme.TEXT_DIM), (660, 10))
            screen.blit(font.render("출력(모터) 그룹", True, theme.TEXT_DIM), (660, 340))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
