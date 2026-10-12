"""실제 FlyWire FAFB 커넥톰에서 감각->운동 서브그래프를 추출한다 (M0, 진짜 데이터 버전).

데이터 출처:
- 뉴런 분류: flyconnectome/flywire_annotations (Supplemental_file1_neuron_annotations.tsv)
- 시냅스 연결: FlyWire proofread_connections (Zenodo 10.5281/zenodo.10676866), CC-BY-4.0

방법:
1. 감각(후각/기계감각/시각) 뉴런과 하행(descending) 뉴런에서 각각 일부를 시드로 뽑는다.
2. 시드에서 central(중간) 뉴런을 거쳐 실제 시냅스로 연결되는 경로를 BFS로 찾는다
   (정방향: 감각->central, 역방향: central->하행). 양쪽에서 다 도달 가능한 central
   뉴런을 '다리' 역할로 우선 채택한다.
3. 최종 뉴런 집합 내부의 모든 실제 edge를 모아 subgraph_nodes.csv / subgraph_edges.csv /
   groups.json으로 저장한다 (기존 가짜 데이터와 동일한 스키마).

업데이트(2026-10-11): 하행뉴런(운동 출력)을 더 이상 무작위로 뽑지 않는다. 실제 활성화
행동 스크리닝 문헌에서 기능이 보고된 특정 DN 타입만 골라서 네 그룹에 배정한다 — 즉
"어느 하행뉴런이 뭘 담당하는가"도 이제 과학적 근거가 있는 매핑이다. 출처:
- Cheong, Eichler, Stürner, Namiki, Dickson 등, "Transforming descending input into
  behavior" / "Networks of descending neurons transform command-like signals into
  population-based behavioral control" (Nature 2024, biorxiv 2023.09.11.557103):
  DNp09=전진 보행, DNa01/DNa02/DNb02=회전(턴), MDN=후진 보행(Moonwalker)
- Giant Fiber(DNp01) 이륙/점프 회로: von Reyn et al.; 미들다리 신경포로 직결
- DNp03 비행 새케이드(collision-avoidance 급선회) 허브: Current Biology 2025
  (Ibbotson/Card 계열 연구)
매핑: legs(이동/회피)=DNp09(전진)+DNa02(턴), wings(필살기)=DNp03(비행 새케이드),
approach(돌진)=DNp01/Giant Fiber(폭발적 이륙을 "돌진 버스트"로 재해석 — 창작적 적용,
원 논문은 "탈출 이륙"이지 "공격"이 아님을 명시해둠), flee(후퇴/방어)=MDN(실제 후진
보행, 가장 직접적으로 맞는 매핑). FAFB는 암컷 뇌라서 수컷 특이적인 pIP10(구애
날개노래) 같은 타입은 애초에 존재하지 않음 — 찾아봤지만 당연히 없었음.

감각(후각/기계감각/시각) 쪽은 원래부터 cell_class 분류 자체가 실제 감각 양식이라
행동 라벨 문제가 없었음(후각 뉴런은 그냥 진짜 후각 뉴런).
"""
import csv
import gc
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import pyarrow.feather as feather

REAL_DATA_DIR = Path(__file__).resolve().parent.parent / "real_data"
OUT_DIR = Path(__file__).resolve().parent.parent / "data"

SEED = 7
SENSORY_PER_MODALITY = 4
MAX_HOPS = 3
MAX_HIDDEN = 60  # 너무 커지면 UI(점/선 그래프)가 감당 못 하므로 상한
PER_SEEDGROUP_HIDDEN = 8  # 감각 모달리티/운동 그룹마다 최소 이만큼은 hidden을 확보

# central 뿐 아니라 광학엽(optic lobe) 계열도 중간 경유 허용. 안 그러면 시각(light)
# 입력은 central로 가기 전에 optic 쪽 여러 홉을 거치는 실제 해부학적 경로라서
# central만 허용하면 전혀 연결이 안 잡힘.
HIDDEN_SUPERCLASSES = {"central", "optic", "visual_projection", "visual_centrifugal"}
# 가중치는 log2(synapse수+1)*WEIGHT_LOG_K 로 압축한다. 실측해보니 synapse count가
# 1~161까지 매우 heavy-tailed(중앙값 2, 그런데 PVLP010->DNp01처럼 113짜리도 있음)라
# 그냥 나누기만 하면 두 가지 실패를 다 겪는다: 나눗수를 크게 하면(/6) 74%가 가중치 1로
# 뭉개져서 decay(0.8)^4 누적 감쇠를 못 버티고 신호가 죽고, 나눗수 없이 그대로 쓰면(/1)
# 113 같은 값이 ReLU 전에 다른 입력을 다 압도해버려서 그 출력이 영원히 0이 돼버림
# (약한 흥분 신호 몇 개가 강한 억제 신호 하나한테 항상 지는 구조). log 압축하면
# 1~161이 대략 2~15 범위로 들어와서 양쪽 문제가 다 풀림.
WEIGHT_LOG_K = 2
TARGET_IN_SUM = 4  # 노드 하나가 받는 "들어오는 가중치 절댓값 합"의 상한(정규화 기준)

MOTOR_GROUPS = ["legs", "wings", "approach", "flee"]

# 행동 스크리닝 문헌에서 기능이 보고된 실제 DN cell_type. (문헌 근거는 모듈 docstring 참고)
BEHAVIOR_DN_TYPES = {
    "legs": ["DNp09", "DNa02"],       # 전진 보행 + 턴(회피/조향)
    "wings": ["DNp03"],               # 비행 새케이드(충돌회피 급선회)
    "approach": ["DNp01"],            # Giant Fiber: 폭발적 이륙 -> "돌진 버스트"로 재해석
    "flee": ["MDN"],                  # Moonwalker: 실제 후진 보행
}
MAX_PER_DN_TYPE = 2  # 타입당 좌/우 한 쌍 정도만

NT_SIGN = {"acetylcholine": 1, "gaba": -1, "glutamate": -1}  # GDD: ACh=흥분, GABA/Glu=억제. 그 외는 +1 기본값


def load_annotations():
    by_id = {}
    with open(REAL_DATA_DIR / "neuron_annotations.tsv", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            by_id[int(row["root_id"])] = row
    return by_id


def pick_seeds(annotations, rng):
    sensory_pool = {"smell": [], "vibration": [], "light": []}
    by_cell_type = {}
    for rid, row in annotations.items():
        if row["super_class"] == "sensory":
            if row["cell_class"] == "olfactory":
                sensory_pool["smell"].append(rid)
            elif row["cell_class"] == "mechanosensory":
                sensory_pool["vibration"].append(rid)
            elif row["cell_class"] == "visual":
                sensory_pool["light"].append(rid)
        ct = row["cell_type"] or row["hemibrain_type"]
        if ct:
            by_cell_type.setdefault(ct, []).append(rid)

    sensory_seeds = {}
    for modality, pool in sensory_pool.items():
        pool.sort()
        sensory_seeds[modality] = rng.sample(pool, min(SENSORY_PER_MODALITY, len(pool)))

    motor_seeds = {}
    for group, dn_types in BEHAVIOR_DN_TYPES.items():
        ids = []
        for dn_type in dn_types:
            candidates = sorted(by_cell_type.get(dn_type, []))
            if not candidates:
                print(f"  경고: 문헌상 DN 타입 '{dn_type}'를 이 연결체에서 못 찾음", flush=True)
                continue
            ids.extend(candidates[:MAX_PER_DN_TYPE])
        motor_seeds[group] = ids

    return sensory_seeds, motor_seeds


def load_connections(conn_path):
    """pre/post/syn_count 세 컬럼만 pandas로 로드 (dict-of-list 안 만듦 — 메모리 절약 핵심)."""
    table = feather.read_table(conn_path, columns=["pre_pt_root_id", "post_pt_root_id", "syn_count"])
    df = table.to_pandas()
    gc.collect()
    return df


def bfs_collect_vectorized(start_ids, df, id_col, other_col, central_ids, max_hops):
    """start_ids에서 출발해 매 홉마다 pandas isin()으로 벡터 필터링하며 central 뉴런을
    모은다 (파이썬 dict/list로 전체 그래프를 들고 있지 않아 메모리를 아낀다).
    {central_root_id: depth} 반환."""
    visited = {}
    frontier = set(start_ids)
    seen = set(start_ids)
    for depth in range(1, max_hops + 1):
        if not frontier:
            break
        mask = df[id_col].isin(frontier)
        next_ids = set(df.loc[mask, other_col].unique().tolist())
        next_central = (next_ids & central_ids) - seen
        for nid in next_central:
            visited[nid] = depth
        seen |= next_central
        frontier = next_central
        print(f"    hop {depth}: 새로 도달한 central 뉴런 {len(next_central)}개 (누적 {len(visited)})", flush=True)
    return visited


def shortest_path(start_ids, goal_ids, df, annotations, max_hops=6, excitatory_only=False):
    """start_ids -> goal_ids 로 가는 실제 최단 경로 하나를 찾아 노드 리스트로 반환.
    '양쪽에서 다 도달 가능한 뉴런'을 모아도, 그 뉴런들 '사이'에 실제 edge가 남아있다는
    보장은 없다(중간에 선택 안 된 central 뉴런을 거쳐야 할 수도 있음) — 그래서 다리
    뉴런을 모으는 것과 별개로, 각 (감각,운동) 조합마다 끊기지 않는 실제 경로를
    최소 하나는 명시적으로 확보해야 한다.

    excitatory_only=True면 presynaptic 뉴런이 acetylcholine(흥분성)인 edge만 타고
    간다 — 억제성 edge를 섞어서 아무 경로나 잡으면, 그 경로가 실제 신호 전파에서
    ReLU에 의해 상쇄/차단돼 버릴 수 있다는 걸 디버깅으로 확인해서 추가함. 흥분성만
    탄 경로를 우선 찾고, 그게 없을 때만 부호 무관 경로로 폴백한다."""
    start_ids, goal_ids = set(start_ids), set(goal_ids)
    if start_ids & goal_ids:
        hit = next(iter(start_ids & goal_ids))
        return [hit]

    parent = {}
    visited = set(start_ids)
    frontier = set(start_ids)
    for _ in range(max_hops):
        if not frontier:
            break
        mask = df["pre_pt_root_id"].isin(frontier)
        sub = df.loc[mask, ["pre_pt_root_id", "post_pt_root_id"]]
        new_frontier = set()
        goal_hit = None
        for pre, post in zip(sub["pre_pt_root_id"].tolist(), sub["post_pt_root_id"].tolist()):
            if post in visited:
                continue
            if excitatory_only:
                nt = (annotations.get(pre, {}).get("top_nt") or "").lower()
                if nt != "acetylcholine":
                    continue
            if post not in parent:
                parent[post] = pre
            new_frontier.add(post)
            if goal_hit is None and post in goal_ids:
                goal_hit = post
        visited |= new_frontier
        frontier = new_frontier
        if goal_hit is not None:
            path = [goal_hit]
            cur = goal_hit
            while cur not in start_ids:
                cur = parent[cur]
                path.append(cur)
            path.reverse()
            return path
    return None


def ensure_end_to_end_paths(sensory_seeds, motor_seeds, df, annotations):
    """감각 모달리티 x 운동그룹 조합마다 실제로 끊기지 않는 경로가 있는지 확인하고,
    없으면 전체 그래프에서 최단 경로를 찾아 중간 뉴런들을 반환한다."""
    extra_hidden = set()
    for modality, s_ids in sensory_seeds.items():
        for group, m_ids in motor_seeds.items():
            if not m_ids:
                continue
            path = shortest_path(s_ids, m_ids, df, annotations, excitatory_only=True)
            tag = "흥분성 전용"
            if path is None:
                path = shortest_path(s_ids, m_ids, df, annotations, excitatory_only=False)
                tag = "부호무관 폴백"
            if path is None:
                print(f"  경고: {modality} -> {group} 실제 경로를 못 찾음(6홉 이내)", flush=True)
                continue
            middle = path[1:-1]  # 양끝(감각 시드, 운동 시드) 빼고 중간만
            extra_hidden.update(middle)
            print(f"  {modality} -> {group}: {len(path)}홉 경로 확보({tag}, 중간 {len(middle)}개)", flush=True)
    return extra_hidden


def main():
    rng = random.Random(SEED)
    print("주석 로딩...", flush=True)
    annotations = load_annotations()
    print(f"  뉴런 {len(annotations)}개")

    sensory_seeds, motor_seeds = pick_seeds(annotations, rng)
    for k, v in sensory_seeds.items():
        print(f"  감각 시드 {k}: {v}", flush=True)
    for k, v in motor_seeds.items():
        print(f"  운동 시드 {k}: {v}", flush=True)

    hidden_eligible = {rid for rid, row in annotations.items() if row["super_class"] in HIDDEN_SUPERCLASSES}
    print(f"  hidden 후보 풀(central+optic 등): {len(hidden_eligible)}개", flush=True)

    print("연결 테이블 로딩 (pandas, 필요한 3개 컬럼만)...", flush=True)
    df = load_connections(REAL_DATA_DIR / "proofread_connections_783.feather")
    print(f"  {len(df)}행 로드 완료", flush=True)

    # 모달리티별 / 운동그룹별로 따로 BFS해서, 하나가 다른 걸 밀어내지 않고
    # 각자 최소한의 hidden 다리를 확보하게 한다 (안 그러면 연결이 적은 모달리티가
    # 전역 랭킹에서 밀려서 완전히 끊긴 입력이 돼버림 — 1차 추출 때 실제로 발생함).
    forward_by_modality = {}
    for modality, seeds in sensory_seeds.items():
        print(f"정방향 BFS: {modality}...", flush=True)
        forward_by_modality[modality] = bfs_collect_vectorized(
            seeds, df, "pre_pt_root_id", "post_pt_root_id", hidden_eligible, MAX_HOPS)
        print(f"  {modality} 도달: {len(forward_by_modality[modality])}", flush=True)

    backward_by_group = {}
    for group, seeds in motor_seeds.items():
        print(f"역방향 BFS: {group}...", flush=True)
        backward_by_group[group] = bfs_collect_vectorized(
            seeds, df, "post_pt_root_id", "pre_pt_root_id", hidden_eligible, MAX_HOPS)
        print(f"  {group} 도달: {len(backward_by_group[group])}", flush=True)

    overall_backward = set().union(*backward_by_group.values()) if backward_by_group else set()
    overall_forward = set().union(*forward_by_modality.values()) if forward_by_modality else set()

    hidden_pool = set()
    for modality, hits in forward_by_modality.items():
        bridge = set(hits) & overall_backward
        ranked = sorted(bridge, key=lambda rid: hits[rid])
        picked = ranked[:PER_SEEDGROUP_HIDDEN]
        print(f"  {modality} 전용 다리 뉴런 {len(picked)}개 확보 (후보 {len(bridge)}개 중)", flush=True)
        hidden_pool.update(picked)
    for group, hits in backward_by_group.items():
        bridge = set(hits) & overall_forward
        ranked = sorted(bridge, key=lambda rid: hits[rid])
        picked = ranked[:PER_SEEDGROUP_HIDDEN]
        print(f"  {group} 전용 다리 뉴런 {len(picked)}개 확보 (후보 {len(bridge)}개 중)", flush=True)
        hidden_pool.update(picked)

    if len(hidden_pool) > MAX_HIDDEN:
        hidden_pool = set(sorted(hidden_pool)[:MAX_HIDDEN])

    # '양쪽에서 다 닿을 수 있는 뉴런을 모았다'는 게 '그 뉴런들 사이에 실제 edge가
    # 남아있다'는 뜻은 아니다 — 모아놓은 55개 중 어느 둘도 서로 안 이어져 있으면
    # 감각->운동 신호가 아예 안 건너간다(실제로 legs/approach/flee가 전부 0으로
    # 죽는 현상이 나서 발견함). 조합마다 최단 경로를 명시적으로 찾아 중간 뉴런을
    # 강제로 끼워넣어서 적어도 한 줄기는 끊기지 않게 보장한다.
    print("감각 x 운동 조합별 끊김없는 경로 확인...", flush=True)
    extra_hidden = ensure_end_to_end_paths(sensory_seeds, motor_seeds, df, annotations)
    new_hidden = extra_hidden - hidden_pool
    print(f"  경로 보강으로 추가되는 hidden 뉴런: {len(new_hidden)}개", flush=True)
    hidden_pool |= extra_hidden

    bridge = hidden_pool
    print(f"  최종 hidden 뉴런: {len(bridge)}", flush=True)

    # ---- 노드 구성 ----
    nodes = []
    id_map = {}  # root_id -> local id

    def add_node(root_id, group, layer):
        local_id = len(nodes)
        id_map[root_id] = local_id
        idx = sum(1 for n in nodes if n["group"] == group)
        nodes.append({
            "id": local_id, "name": f"{group}_{idx}", "group": group, "layer": layer,
            "root_id": root_id, "cell_type": annotations.get(root_id, {}).get("cell_type", ""),
        })

    for modality, ids in sensory_seeds.items():
        for rid in ids:
            add_node(rid, modality, "sensory")
    for rid in sorted(bridge):
        add_node(rid, "hidden", "hidden")
    for group, ids in motor_seeds.items():
        for rid in ids:
            add_node(rid, group, "motor")

    print(f"총 노드 {len(nodes)}개")

    # ---- 엣지 구성: 최종 노드 집합 내부의 모든 실제 연결 (pandas로 벡터 처리) ----
    node_set = set(id_map)
    mask = df["pre_pt_root_id"].isin(node_set) & df["post_pt_root_id"].isin(node_set)
    sub = df.loc[mask]
    agg = (
        sub.groupby(["pre_pt_root_id", "post_pt_root_id"], as_index=False)["syn_count"]
        .sum()
    )
    del df, sub, mask
    gc.collect()

    edges = []
    for pre, post, syn_sum in zip(agg["pre_pt_root_id"], agg["post_pt_root_id"], agg["syn_count"]):
        pre, post = int(pre), int(post)
        if pre == post:
            continue
        pre_nt = (annotations.get(pre, {}).get("top_nt") or "").lower()
        sign = NT_SIGN.get(pre_nt, 1)
        w = max(1, round(math.log2(int(syn_sum) + 1) * WEIGHT_LOG_K)) * sign
        edges.append({"src": id_map[pre], "dst": id_map[post], "weight": w})

    # ---- 입력 총합 정규화 (항상 TARGET_IN_SUM에 맞춤) ----
    # 시도 1: "TARGET 넘으면만 줄이고 최소 1 보장" -> in-degree 큰 노드(legs 24개)는
    #   바닥(min 1) 때문에 아무리 줄여도 실질 합이 edge 개수 밑으로 안 내려가서 항상
    #   포화, 자극과 무관한 고정점에 박힘.
    # 시도 2: "넘으면만 줄이고 0 되면 버림" -> 바닥 문제는 풀렸지만, 이번엔 원래
    #   TARGET 이하였던(=연결이 약한) 노드는 전혀 안 건드려서 신호가 너무 약해
    #   아무 데도 안 퍼짐(smell/vibration 경로가 전부 죽음).
    # 그래서 항상(넘든 안 넘든) 모든 노드의 "들어오는 가중치 절댓값 합"을
    # TARGET_IN_SUM 근처로 맞춘다 — 약한 노드는 끌어올리고 강한 노드는 끌어내려서,
    # 모든 노드가 비슷한 스케일의 입력을 받게 만든다(신경망의 weight normalization과
    # 같은 발상).
    in_sum = defaultdict(float)
    for e in edges:
        in_sum[e["dst"]] += abs(e["weight"])
    kept = []
    for e in edges:
        total = in_sum[e["dst"]]
        if total <= 0:
            continue
        scale = TARGET_IN_SUM / total
        sign = 1 if e["weight"] >= 0 else -1
        new_w = sign * round(abs(e["weight"]) * scale)
        if new_w == 0:
            continue
        e["weight"] = new_w
        kept.append(e)
    edges = kept

    print(f"총 엣지 {len(edges)}개")

    # ---- 저장 ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "subgraph_nodes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "name", "group", "layer", "root_id", "cell_type"])
        w.writeheader()
        w.writerows(nodes)

    with open(OUT_DIR / "subgraph_edges.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["src", "dst", "weight"])
        w.writeheader()
        w.writerows(edges)

    groups = {
        "sensory": {g: [n["id"] for n in nodes if n["group"] == g] for g in ("smell", "vibration", "light")},
        "motor": {g: [n["id"] for n in nodes if n["group"] == g] for g in MOTOR_GROUPS},
    }
    with open(OUT_DIR / "groups.json", "w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=2)

    print("저장 완료:", OUT_DIR)


if __name__ == "__main__":
    main()
