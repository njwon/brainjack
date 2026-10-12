"""가짜 20뉴런 서브그래프 생성기 (M0).

실제 커넥톰 데이터를 구하기 전까지, brain.py와 게임 루프를 먼저 완성하기 위한
더미 데이터 생성기. 출력은 data/ 아래 CSV 2개 + groups.json.

사용법:
    python tools/generate_fake_data.py
"""
import csv
import json
import random
from pathlib import Path

random.seed(7)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 뉴런 그룹 정의: (group_name, layer, count)
#   layer: sensory(입력) / hidden(은닉) / motor(출력)
GROUPS = [
    ("smell", "sensory", 2),
    ("vibration", "sensory", 2),
    ("light", "sensory", 2),
    ("hidden", "hidden", 6),
    ("legs", "motor", 2),
    ("wings", "motor", 2),
    ("approach", "motor", 2),
    ("flee", "motor", 2),
]


def build_nodes():
    nodes = []
    nid = 0
    for group, layer, count in GROUPS:
        for i in range(count):
            nodes.append({"id": nid, "name": f"{group}_{i}", "group": group, "layer": layer})
            nid += 1
    return nodes


def build_edges(nodes):
    sensory = [n["id"] for n in nodes if n["layer"] == "sensory"]
    hidden = [n["id"] for n in nodes if n["layer"] == "hidden"]
    motor = [n["id"] for n in nodes if n["layer"] == "motor"]

    edges = []

    def add_edges(src_ids, dst_ids, density, min_syn=1, max_syn=5, inhib_ratio=0.3):
        for s in src_ids:
            for d in dst_ids:
                if random.random() > density:
                    continue
                syn = random.randint(min_syn, max_syn)
                sign = -1 if random.random() < inhib_ratio else 1
                edges.append({"src": s, "dst": d, "weight": sign * syn})

    # 입력 -> 은닉 (흥분 위주)
    add_edges(sensory, hidden, density=0.5, inhib_ratio=0.15)
    # 은닉 -> 은닉 (재귀, 억제성 비율 높여서 폭주 억제 회로 포함)
    add_edges(hidden, hidden, density=0.25, inhib_ratio=0.45)
    # 은닉 -> 출력
    add_edges(hidden, motor, density=0.4, inhib_ratio=0.25)

    # 자기 자신 연결 제거
    edges = [e for e in edges if e["src"] != e["dst"]]
    return edges


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    nodes = build_nodes()
    edges = build_edges(nodes)

    with open(DATA_DIR / "subgraph_nodes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "group", "layer"])
        w.writeheader()
        w.writerows(nodes)

    with open(DATA_DIR / "subgraph_edges.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["src", "dst", "weight"])
        w.writeheader()
        w.writerows(edges)

    groups = {
        "sensory": {g: [n["id"] for n in nodes if n["group"] == g] for g, layer, _ in GROUPS if layer == "sensory"},
        "motor": {g: [n["id"] for n in nodes if n["group"] == g] for g, layer, _ in GROUPS if layer == "motor"},
    }
    with open(DATA_DIR / "groups.json", "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

    print(f"nodes={len(nodes)} edges={len(edges)}")
    print(f"saved to {DATA_DIR}")


if __name__ == "__main__":
    main()
