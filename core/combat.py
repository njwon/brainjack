"""자동 전투 로직 (M6 — 전투 = 뇌 건너뛰기 암살).

플레이어는 초파리가 아니라 숙주(F-01)의 뇌에 사는 기생충이다. 적도 전부 다른
개체/변종 초파리라서, "공격"은 데미지 숫자 계산이 아니라 접촉한 적의 뇌 속으로
순간이동해 작은 미니 뇌(core/combat.py의 Enemy.mini_nodes)에서 시냅스를 몇 번
감염시키는 미니 게임이다. 실제 감염 처리(히트 등록, 침투 모드 진입/탈출)는
main.py가 담당하고, 여기서는 적의 미니 뇌 데이터와 접촉 감지만 제공한다.
"""
import math
import random

BASE_HP_REGEN = 2.0          # 초당 기본 회복량 (가만히 있어도 이만큼은 회복)
HP_REGEN_PER_DEFENSE = 4.0   # defense(0~0.7) 비례 추가 회복량

# 변이체별 미니 뇌 규모와 기본 필요 감염 횟수.
# "boss"는 일반 스폰 풀(VARIANT_WEIGHTS)에는 안 넣고 구역 타이머가 끝날 때
# main.py가 Battle.spawn_boss()로 직접 1개체만 꽂아넣는다 — 기존 뇌 건너뛰기
# 메커니즘을 그대로 재사용하면서 "더 크고 더 오래 버티는" 미니 뇌로 체감 차이만 줌
# (새 텔레그래프/패턴 시스템은 만들지 않음 — 과설계 방지).
VARIANTS = {
    "agile": {"name": "민첩 변이체", "nodes": 3, "hits": 1, "speed": (70, 95), "hp": 14},
    "alert": {"name": "경보 변이체", "nodes": 5, "hits": 2, "speed": (45, 60), "hp": 20},
    "tough": {"name": "방어 변이체", "nodes": 7, "hits": 3, "speed": (30, 45), "hp": 26},
    "boss": {"name": "보스", "nodes": 13, "hits": 5, "speed": (20, 30), "hp": 60},
}
VARIANT_WEIGHTS = {"agile": 0.4, "alert": 0.35, "tough": 0.25}

HOP_TIME_LIMIT = 3.0        # 뇌 침투 모드 1회 제한시간(초) — 못 끝내면 강제로 쫓겨나고 피해를 입는다
HOP_TIMEOUT_DAMAGE = 10.0   # 제한시간 초과 시 기본 피해(방어로 감소)


def stats_from_brain_output(out: dict) -> dict:
    legs = out.get("legs", 0.0)
    approach = out.get("approach", 0.0)
    flee = out.get("flee", 0.0)

    return {
        "move_speed": 60 + legs * 40,
        "evasion": min(0.6, legs * 0.06),
        "defense": min(0.7, flee * 0.08),
        # 0.11이었을 때 "철벽" 스킬 한 번만 찍어도 flee가 임계값(0.5)을 넘어서
        # 영구 후퇴 상태(공격 불가)에 빠지는 버그가 있었음 — 0.08로 낮춰서
        # flee가 cap(5.0)까지 가도 0.4로 임계값 아래 머물게 고침.
        "retreat_bias": min(1.0, flee * 0.08),
        "attack_power": 4 + approach * 2.5,
        # attack_range는 더 이상 공격 사거리가 아니라 "뇌 침투 트리거 거리" —
        # 멀리서도 적의 뇌 속으로 뛰어들 수 있게 해준다(적에게 덜 노출됨).
        "attack_range": 45 + approach * 12,
    }


# (내부 키, 화면 표시 이름, 표시 포맷, "이 정도는 바뀌어야 표시한다" 기준값)
STAT_DISPLAY = [
    ("move_speed", "속도", "{:.1f}", 0.05),
    ("evasion", "회피", "{:.1%}", 0.0005),
    ("defense", "방어", "{:.1%}", 0.0005),
    ("attack_power", "공격력", "{:.1f}", 0.05),
    ("attack_range", "침투사거리", "{:.1f}", 0.05),
]


def describe_stat_changes(before: dict, after: dict) -> list:
    """스킬 카드 선택 전/후 스탯을 비교해서 "속도 72→84 (+12)" 같은 줄들을 만든다.
    변화가 기준값(eps)보다 작으면(=반올림해도 안 보일 정도면) 그 줄은 생략한다."""
    lines = []
    for key, label, fmt, eps in STAT_DISPLAY:
        b, a = before.get(key, 0.0), after.get(key, 0.0)
        if abs(a - b) < eps:
            continue
        sign = "+" if a >= b else ""
        lines.append(f"{label} {fmt.format(b)} -> {fmt.format(a)} ({sign}{fmt.format(a - b)})")
    return lines


def _make_mini_brain(rng, n_nodes):
    """적의 미니 뇌 레이아웃(순수 시각/상호작용용, 실제 Brain 시뮬레이션 아님)을
    만든다. 노드는 작은 원형 영역 안에 흩뿌리고, 이웃끼리 선으로 느슨하게 연결."""
    nodes = []
    for i in range(n_nodes):
        angle = rng.uniform(0, 6.283)
        r = rng.uniform(20, 70)
        nodes.append({
            "id": i,
            "x": 100 + r * math.cos(angle),
            "y": 90 + r * math.sin(angle),
            "infected": False,
        })
    edges = []
    for i in range(1, n_nodes):
        j = rng.randint(0, i - 1)
        edges.append((i, j))
    return nodes, edges


class Enemy:
    def __init__(self, x, y, rng, variant=None, hp=None, speed=None):
        self.x, self.y = x, y
        self.variant = variant or rng.choices(
            list(VARIANT_WEIGHTS), weights=list(VARIANT_WEIGHTS.values()))[0]
        spec = VARIANTS[self.variant]
        self.hp = hp if hp is not None else spec["hp"]
        self.max_hp = self.hp
        self.speed = speed if speed is not None else rng.uniform(*spec["speed"])
        self.alive = True
        self.hits_needed_base = spec["hits"]
        self.hits_taken = 0
        self.mini_nodes, self.mini_edges = _make_mini_brain(rng, spec["nodes"])
        # 기본은 변이체 공용 이름("보스" 등) — 보스는 스폰 직후 main.py가 구역별
        # 고유 이름(예: "집게벌레 수문장")으로 덮어써서 뇌 침투 화면에 표시한다.
        self.name = spec["name"]

    def hits_needed(self, approach_bonus_reduction=0):
        return max(1, self.hits_needed_base - approach_bonus_reduction)

    def register_hit(self, node_id, approach_bonus_reduction=0):
        """미니 뇌의 노드 하나를 감염시킨다. 처치됐으면 True."""
        for n in self.mini_nodes:
            if n["id"] == node_id and not n["infected"]:
                n["infected"] = True
                self.hits_taken += 1
                break
        if self.hits_taken >= self.hits_needed(approach_bonus_reduction):
            self.alive = False
            return True
        return False

    def update(self, dt, target_x, target_y):
        dx = target_x - self.x
        dy = target_y - self.y
        dist = max(1e-6, (dx ** 2 + dy ** 2) ** 0.5)
        self.x += self.speed * dt * dx / dist
        self.y += self.speed * dt * dy / dist
        return dist


class Player:
    def __init__(self, x, y, hp=100):
        self.x, self.y = x, y
        self.hp = hp
        self.max_hp = hp
        self.alive = True


class Battle:
    """플레이어(기생충이 조종하는 숙주 몸) 1 + 적(다른 초파리) n으로 이뤄진 루프."""

    FIELD_W, FIELD_H = 640, 360
    CONTACT_DIST = 18  # 이 거리 안으로 들어오면 "접촉" — main.py가 뇌 침투 모드를 연다

    def __init__(self):
        self.player = Player(self.FIELD_W * 0.25, self.FIELD_H * 0.5)
        self.enemies = []
        self.time_survived = 0.0
        self.spawn_timer = 0.0
        self.score = 0
        self.rng = random.Random(42)

    def _spawn_interval(self):
        return 1.8 + min(1.5, self.time_survived * 0.03)

    def spawn_enemy(self):
        y = self.rng.uniform(40, self.FIELD_H - 40)
        self.enemies.append(Enemy(self.FIELD_W - 20, y, self.rng))

    def spawn_boss(self, name):
        """구역 보스 1개체를 꽂아넣는다. 일반 몹 스폰(spawn_enemy)과는 별개 경로라서
        타이머가 끝나도 일반 스폰은 그대로 계속되고(의도적으로 softlock 방지),
        보스는 한 번만 등장한다 — main.py가 반환된 Enemy를 들고 있다가
        register_hit로 죽었는지 추적."""
        boss = Enemy(self.FIELD_W - 30, self.FIELD_H * 0.5, self.rng, variant="boss")
        boss.name = name
        self.enemies.append(boss)
        return boss

    def update(self, dt, stats: dict):
        """main.py가 뇌 침투 모드 중에는 이 함수를 아예 호출하지 않아서, 다른
        적들이 그동안 몰려오지 않는다(이번 설계에서 의도적으로 범위를 좁힌 부분)."""
        if not self.player.alive:
            return None

        self.time_survived += dt
        self.spawn_timer += dt
        if self.spawn_timer >= self._spawn_interval():
            self.spawn_timer = 0.0
            self.spawn_enemy()

        target = self._nearest_enemy()
        retreat = stats["retreat_bias"] > 0.5 and target is not None

        contact = None
        if target is not None:
            dx = target.x - self.player.x
            dy = target.y - self.player.y
            dist = max(1e-6, (dx ** 2 + dy ** 2) ** 0.5)
            direction = -1 if retreat else 1
            self.player.x += direction * stats["move_speed"] * dt * dx / dist
            self.player.y += direction * stats["move_speed"] * dt * dy / dist
            self.player.x = max(10, min(self.FIELD_W - 10, self.player.x))
            self.player.y = max(10, min(self.FIELD_H - 10, self.player.y))

            if dist <= max(self.CONTACT_DIST, stats["attack_range"] * 0.4) and not retreat:
                contact = target

        for e in self.enemies:
            if not e.alive or e is target:
                continue
            e.update(dt, self.player.x, self.player.y)

        self.enemies = [e for e in self.enemies if e.alive]

        if self.player.alive:
            regen = BASE_HP_REGEN + stats["defense"] * HP_REGEN_PER_DEFENSE
            self.player.hp = min(self.player.max_hp, self.player.hp + regen * dt)

        return contact

    def take_hop_timeout_damage(self, stats: dict):
        """뇌 침투 제한시간 초과 — 방어로 감소된 피해를 입는다."""
        dmg = HOP_TIMEOUT_DAMAGE * (1 - stats["defense"])
        self.player.hp = max(0.0, self.player.hp - dmg)
        if self.player.hp <= 0:
            self.player.alive = False

    def _nearest_enemy(self):
        alive = [e for e in self.enemies if e.alive]
        if not alive:
            return None
        return min(alive, key=lambda e: (e.x - self.player.x) ** 2 + (e.y - self.player.y) ** 2)
