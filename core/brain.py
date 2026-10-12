"""뇌 신호 전파 코어 (M0).

x(t+1) = clip( ReLU( W . x(t) + stim(t) ) * decay , 0, cap )

W: 뉴런 간 연결 가중치(희소 행렬, 시냅스 수 x 부호)
x: 뉴런 활성 벡터
stim: 외부 자극 벡터 (감각 뉴런에만 값이 들어감)
"""
import csv
import json
from collections import deque
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix

GROUP_LABEL_KO = {
    "smell": "후각",
    "vibration": "진동",
    "light": "빛",
    "hidden": "은닉",
    "legs": "다리(이동)",
    "wings": "날개(필살기)",
    "approach": "돌진(공격)",
    "flee": "도피(방어)",
}


class Brain:
    def __init__(self, data_dir, decay=0.8, cap=5.0):
        data_dir = Path(data_dir)
        self.decay = decay
        self.cap = cap

        self.nodes = self._load_nodes(data_dir / "subgraph_nodes.csv")
        self.name_to_id = {n["name"]: n["id"] for n in self.nodes}
        self.id_to_node = {n["id"]: n for n in self.nodes}
        self.n = len(self.nodes)

        self.edges = self._load_edge_list(data_dir / "subgraph_edges.csv")
        self.rebuild_W()
        with open(data_dir / "groups.json", encoding="utf-8") as f:
            self.groups = json.load(f)

        self.x = np.zeros(self.n, dtype=np.float32)

    @staticmethod
    def _load_nodes(path):
        with open(path, encoding="utf-8") as f:
            return [
                {"id": int(row["id"]), "name": row["name"], "group": row["group"], "layer": row["layer"]}
                for row in csv.DictReader(f)
            ]

    @staticmethod
    def _load_edge_list(path):
        """편집 가능한 엣지 리스트. weight는 int(시냅스 수 x 부호)."""
        edges = []
        with open(path, encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f)):
                w = int(float(row["weight"]))
                edges.append({
                    "id": i,
                    "src": int(row["src"]),
                    "dst": int(row["dst"]),
                    "weight": w,
                    "original_weight": w,
                    "adjust_count": 0,
                    "pruned": False,
                })
        return edges

    def rebuild_W(self):
        """edges 리스트 -> 희소 행렬 W. 프루닝된 엣지는 제외."""
        rows, cols, data = [], [], []
        for e in self.edges:
            if e["pruned"]:
                continue
            rows.append(e["dst"])  # W[dst, src] 형태로 저장 -> W @ x
            cols.append(e["src"])
            data.append(float(e["weight"]))
        self.W = coo_matrix((data, (rows, cols)), shape=(self.n, self.n)).tocsr()

    # ---- 튜닝(M3) ----
    MAX_ADJUSTMENTS = 6
    ADJUST_RATIO = 0.3  # 원본 대비 +-30%

    def edge_bounds(self, edge):
        orig = edge["original_weight"]
        mag = max(1, abs(orig))
        lo = max(1, round(mag * (1 - self.ADJUST_RATIO)))
        hi = max(lo, round(mag * (1 + self.ADJUST_RATIO)))
        # mag이 작으면(특히 1) 반올림 때문에 lo==hi==mag로 수렴해서 아예 조정이
        # 불가능해진다 — 항상 최소 +-1의 여유는 보장한다.
        if hi <= mag:
            hi = mag + 1
        if lo >= mag and mag > 1:
            lo = mag - 1
        sign = 1 if orig >= 0 else -1
        return sign * lo, sign * hi  # (최소크기, 최대크기) 부호 유지

    def can_adjust(self, edge, direction: int = 0):
        """direction: +1=강화 쪽 여유 있는지만, -1=완화 쪽 여유 있는지만, 0(기본)=둘 중
        아무 쪽이든. 반드시 실제로 호출할 방향을 넘길 것 — 0으로 뭉뚱그리면 "강화는
        꽉 찼는데 완화 쪽엔 여유가 있어서" True가 나오는 식으로, 실제로 adjust_edge가
        아무 효과도 못 내는데 '조정 가능'하다고 잘못 보고할 수 있다."""
        if edge["pruned"]:
            return False
        if edge["adjust_count"] >= self.MAX_ADJUSTMENTS:
            return False
        # 원본 가중치가 작은(특히 ±1) edge는 +-30% 범위가 좁아서 한두 번만에
        # 상/하한에 도달한다. adjust_count만 보면 아직 레벨이 남은 것처럼 계속
        # "조정 가능"하다고 나오지만 실제로는 값이 하나도 안 바뀌어서, 스킬
        # 카드가 Lv.6까지 뽑히는데 Lv.2부터는 도파민만 쓰고 아무 효과도 없는
        # 가짜 레벨업 버그가 있었음 — 이미 상/하한이면 더 이상 조정 불가로 처리.
        lo, hi = self.edge_bounds(edge)
        mag = abs(edge["weight"])
        if direction > 0:
            return mag < abs(hi)
        if direction < 0:
            return mag > abs(lo)
        return mag < abs(hi) or mag > abs(lo)

    def adjust_edge(self, edge_id: int, step: int):
        """시냅스 가중치를 step만큼 조정(원본의 +-30% 범위, 부호 유지)."""
        edge = self.edges[edge_id]
        if not self.can_adjust(edge, direction=step):
            return False
        sign = 1 if edge["original_weight"] >= 0 else -1
        lo, hi = self.edge_bounds(edge)
        lo_mag, hi_mag = abs(lo), abs(hi)
        new_mag = abs(edge["weight"]) + step
        new_mag = max(lo_mag, min(hi_mag, new_mag))
        if new_mag == abs(edge["weight"]):
            return False
        edge["weight"] = sign * new_mag
        edge["adjust_count"] += 1
        self.rebuild_W()
        return True

    def prune_edge(self, edge_id: int):
        edge = self.edges[edge_id]
        if edge["pruned"]:
            return False
        edge["pruned"] = True
        self.rebuild_W()
        return True

    def find_edge_id(self, src_name: str, dst_name: str):
        """이름으로 edge 찾기 (스킬 카드가 특정 배선을 지정할 때 사용)."""
        src_id = self.name_to_id[src_name]
        dst_id = self.name_to_id[dst_name]
        for e in self.edges:
            if e["src"] == src_id and e["dst"] == dst_id:
                return e["id"]
        return None

    def display_name(self, node_id: int) -> str:
        """'hidden_4' 같은 내부 이름 대신 '은닉-4' 같은 한글 표시용 이름."""
        node = self.id_to_node[node_id]
        idx = node["name"].rsplit("_", 1)[-1]
        label = GROUP_LABEL_KO.get(node["group"], node["group"])
        return f"{label}-{idx}"

    def _adjacency(self, reverse=False):
        adj = {}
        for e in self.edges:
            if e["pruned"]:
                continue
            a, b = (e["dst"], e["src"]) if reverse else (e["src"], e["dst"])
            adj.setdefault(a, []).append(b)
        return adj

    def reachable_motor_groups(self, node_id: int, max_depth: int = 6) -> set:
        """node_id에서 출발해 도달 가능한 출력(모터) 그룹들 (= 이 뉴런이 영향 주는 곳)."""
        adj = self._adjacency(reverse=False)
        visited = {node_id}
        frontier = deque([(node_id, 0)])
        groups = set()
        while frontier:
            nid, d = frontier.popleft()
            node = self.id_to_node[nid]
            if node["layer"] == "motor":
                groups.add(node["group"])
            if d >= max_depth:
                continue
            for nxt in adj.get(nid, []):
                if nxt not in visited:
                    visited.add(nxt)
                    frontier.append((nxt, d + 1))
        return groups

    def reachable_sensory_groups(self, node_id: int, max_depth: int = 6) -> set:
        """node_id로 들어오는 입력(감각) 그룹들 (= 이 뉴런에 영향 주는 곳)."""
        radj = self._adjacency(reverse=True)
        visited = {node_id}
        frontier = deque([(node_id, 0)])
        groups = set()
        while frontier:
            nid, d = frontier.popleft()
            node = self.id_to_node[nid]
            if node["layer"] == "sensory":
                groups.add(node["group"])
            if d >= max_depth:
                continue
            for prev in radj.get(nid, []):
                if prev not in visited:
                    visited.add(prev)
                    frontier.append((prev, d + 1))
        return groups

    def make_stim_vector(self, stim_by_group: dict) -> np.ndarray:
        """{'smell': 1.5, 'vibration': 0.0, ...} -> 뉴런 수 길이의 자극 벡터."""
        stim = np.zeros(self.n, dtype=np.float32)
        for group, value in stim_by_group.items():
            ids = self.groups["sensory"].get(group)
            if ids is None:
                raise KeyError(f"알 수 없는 감각 그룹: {group}")
            for i in ids:
                stim[i] = value
        return stim

    def step(self, stim: np.ndarray) -> np.ndarray:
        activation = self.W @ self.x + stim
        activation = np.maximum(activation, 0.0)  # ReLU
        activation *= self.decay
        self.x = np.clip(activation, 0.0, self.cap)
        return self.x

    def propagate(self, stim_by_group: dict, substeps: int = 4) -> np.ndarray:
        """전투 틱 1회 = substeps번 전파."""
        stim = self.make_stim_vector(stim_by_group)
        for _ in range(substeps):
            self.step(stim)
        return self.x

    def output_summary(self) -> dict:
        """출력(모터) 그룹별 평균 활성도."""
        return {
            group: float(np.mean(self.x[ids])) if ids else 0.0
            for group, ids in self.groups["motor"].items()
        }

    def reset(self):
        self.x[:] = 0.0

    def reset_edges(self):
        """모든 튜닝/프루닝을 원복 (새 런 시작)."""
        for e in self.edges:
            e["weight"] = e["original_weight"]
            e["adjust_count"] = 0
            e["pruned"] = False
        self.rebuild_W()


if __name__ == "__main__":
    import sys

    data_dir = Path(__file__).resolve().parent.parent / "data"
    brain = Brain(data_dir)
    print(f"neurons={brain.n}, edges={brain.W.nnz}")

    # 가상의 전투 시나리오: 틱마다 자극 조합이 바뀜
    scenario = [
        {"smell": 2.0, "vibration": 0.0, "light": 0.0},
        {"smell": 2.0, "vibration": 1.5, "light": 0.0},
        {"smell": 0.0, "vibration": 3.0, "light": 0.5},
        {"smell": 0.0, "vibration": 0.0, "light": 3.0},
        {"smell": 1.0, "vibration": 1.0, "light": 1.0},
    ]
    for tick, stim in enumerate(scenario):
        brain.propagate(stim)
        out = brain.output_summary()
        formatted = ", ".join(f"{k}={v:.2f}" for k, v in out.items())
        print(f"tick {tick}: stim={stim} -> {formatted}")
