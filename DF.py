import Rhino.Geometry as rg
import random
import math

# ============================================================
# Stanford Bunny Neural-Network Lattice Generator for FDM
# Surface + Inner Network + Base + No Floating Parts + No Node Overlap
#
# Input:
#   M : Rhino.Geometry.Mesh
# Output:
#   a : list of Breps
#
# Grasshopper構成:
#   Mesh parameter -> Python3 Script
#
# 入力:
#   M
#
# 出力:
#   a
#
# 注意:
#   「全パーツが台座に接続される」ことは保証します。
#   ただし、FDMでサポート材なしで絶対印刷可能、までは保証しません。
# ============================================================


# ============================================================
# 変数ブロック
# ここだけ変えればOK
# ============================================================

# ---------- 全体サイズ ----------
SCALE_TO_TARGET = True

# 本体だけの最大サイズ。
# 台座込みで約50mmにしたいなら 44〜46mm くらいがおすすめ。
TARGET_MAX_SIZE = 46.0


# ---------- ランダム ----------
RANDOM_SEED = 42


# ---------- ノード密度 ----------
# 5cmサイズでノードをくっつけたくないなら、
# いきなり500はかなり厳しいです。
# まずはこのくらいがおすすめ。
SURFACE_NODE_COUNT = 100
INNER_NODE_COUNT = 200

# ニューラルネットっぽい層数
LAYER_COUNT = 9


# ---------- ノード同士の最小距離 ----------
AVOID_NODE_OVERLAP = True

# NODE_RADIUS=1.6なら、球同士が接しない理論値は3.2mm以上。
# 少し余裕を見て3.6〜4.0mmくらい。
SURFACE_NODE_MIN_DISTANCE = 3.8

# INNER_NODE_RADIUS=1.3, NODE_RADIUS=1.6なら、表面-内部の接触回避は2.9mm以上。
# 余裕を見て3.2〜3.5mmくらい。
INNER_NODE_MIN_DISTANCE = 3.3


# ---------- FDM向け寸法 ----------
NODE_RADIUS = 1.6
INNER_NODE_RADIUS = 1.3

EDGE_RADIUS = 0.85
INNER_EDGE_RADIUS = 0.75

# 連結保証のために追加されるエッジ
CONNECTOR_EDGE_RADIUS = 0.9

# 台座への支柱
SUPPORT_RADIUS = 0.95
EXTRA_SUPPORT_RADIUS = 1.0


# ---------- エッジ長 ----------
MIN_EDGE_LENGTH = 2.0
MAX_EDGE_LENGTH = 9.0
MAX_INNER_EDGE_LENGTH = 10.0


# ---------- 接続数 ----------
CONNECTIONS_PER_NODE = 4
INNER_CONNECTIONS_PER_NODE = 4


# ---------- 連結性保証 ----------
FORCE_ALL_CONNECTED_TO_BASE = True

# 接続済みネットワークから遠すぎる未接続ノードは、
# 追加で台座へ垂直支柱を落とす。
ALLOW_EXTRA_VERTICAL_SUPPORTS = True
EXTRA_SUPPORT_IF_FARTHER_THAN = 14.0


# ---------- 内部点生成 ----------
USE_TRUE_INSIDE_TEST = True
INSIDE_TEST_TOLERANCE = 0.01

# 内部候補点をどれくらい多めに試すか
INNER_SAMPLE_TRIAL_MULTIPLIER = 100

# メッシュが閉じておらず IsPointInside がうまくいかない場合、
# 表面点を中心方向へ寄せて疑似内部点を作る。
FALLBACK_INNER_FROM_SURFACE = True
FALLBACK_INNER_RATIO_MIN = 0.25
FALLBACK_INNER_RATIO_MAX = 0.70


# ---------- 台座 ----------
ADD_BASE = True
BASE_HEIGHT = 4.0
BASE_MARGIN = 5.0
BASE_RADIUS_SCALE = 0.55


# ---------- 最初から入れる支柱 ----------
ADD_SUPPORT_POSTS = True
SUPPORT_POST_COUNT = 26


# ---------- 見た目 ----------
ADD_SURFACE_RIBS = True
SURFACE_RIB_PROBABILITY = 0.22

ADD_INNER_RANDOM_RIBS = True
INNER_RIB_PROBABILITY = 0.50


# ---------- デバッグ情報 ----------
# 出力bを作っていない場合でも、Grasshopperのoutに出ることがあります。
PRINT_INFO = True


# ============================================================
# Utility functions
# ============================================================

def duplicate_and_prepare_mesh(mesh):
    m = mesh.DuplicateMesh()
    m.Vertices.CombineIdentical(True, True)
    m.Weld(math.radians(180.0))
    m.Normals.ComputeNormals()
    m.FaceNormals.ComputeFaceNormals()
    m.Compact()
    return m


def scale_mesh_to_target(mesh, target_size):
    bbox = mesh.GetBoundingBox(True)

    size_x = bbox.Max.X - bbox.Min.X
    size_y = bbox.Max.Y - bbox.Min.Y
    size_z = bbox.Max.Z - bbox.Min.Z

    current_max = max(size_x, size_y, size_z)

    if current_max <= 0:
        return mesh

    scale = target_size / current_max
    center = bbox.Center

    xf = rg.Transform.Scale(center, scale)
    mesh.Transform(xf)

    return mesh


def triangle_area(a, b, c):
    return 0.5 * rg.Vector3d.CrossProduct(b - a, c - a).Length


def random_point_on_triangle(a, b, c):
    r1 = random.random()
    r2 = random.random()

    sr1 = math.sqrt(r1)

    u = 1.0 - sr1
    v = sr1 * (1.0 - r2)
    w = sr1 * r2

    return rg.Point3d(
        u * a.X + v * b.X + w * c.X,
        u * a.Y + v * b.Y + w * c.Y,
        u * a.Z + v * b.Z + w * c.Z
    )


def get_face_triangles(mesh):
    tris = []

    for f in mesh.Faces:
        a = rg.Point3d(mesh.Vertices[f.A])
        b = rg.Point3d(mesh.Vertices[f.B])
        c = rg.Point3d(mesh.Vertices[f.C])

        if f.IsTriangle:
            tris.append((a, b, c))
        else:
            d = rg.Point3d(mesh.Vertices[f.D])
            tris.append((a, b, c))
            tris.append((a, c, d))

    return tris


def sample_points_on_mesh(mesh, count):
    tris = get_face_triangles(mesh)

    if not tris:
        return []

    areas = []
    total_area = 0.0

    for tri in tris:
        area = triangle_area(tri[0], tri[1], tri[2])
        areas.append(area)
        total_area += area

    if total_area <= 0:
        return []

    cumulative = []
    s = 0.0

    for area in areas:
        s += area
        cumulative.append(s)

    pts = []

    for _ in range(count * 4):
        if len(pts) >= count:
            break

        r = random.random() * total_area

        idx = 0
        lo = 0
        hi = len(cumulative) - 1

        while lo <= hi:
            mid = (lo + hi) // 2

            if cumulative[mid] < r:
                lo = mid + 1
            else:
                idx = mid
                hi = mid - 1

        a, b, c = tris[idx]
        p = random_point_on_triangle(a, b, c)

        pts.append(p)

    return pts


def sample_points_inside_mesh(mesh, count):
    bbox = mesh.GetBoundingBox(True)
    pts = []

    trial_limit = max(1000, count * INNER_SAMPLE_TRIAL_MULTIPLIER)
    trials = 0

    while len(pts) < count and trials < trial_limit:
        trials += 1

        x = random.uniform(bbox.Min.X, bbox.Max.X)
        y = random.uniform(bbox.Min.Y, bbox.Max.Y)
        z = random.uniform(bbox.Min.Z, bbox.Max.Z)

        p = rg.Point3d(x, y, z)

        try:
            inside = mesh.IsPointInside(p, INSIDE_TEST_TOLERANCE, True)
        except:
            inside = False

        if inside:
            pts.append(p)

    return pts


def make_fallback_inner_points(surface_points, center, count):
    pts = []

    if not surface_points:
        return pts

    for _ in range(count):
        p = random.choice(surface_points)
        t = random.uniform(FALLBACK_INNER_RATIO_MIN, FALLBACK_INNER_RATIO_MAX)

        inner = rg.Point3d(
            p.X + (center.X - p.X) * t,
            p.Y + (center.Y - p.Y) * t,
            p.Z + (center.Z - p.Z) * t
        )

        pts.append(inner)

    return pts


def is_far_enough_from_points(p, existing_points, min_dist):
    min_dist_sq = min_dist * min_dist

    for q in existing_points:
        dx = p.X - q.X
        dy = p.Y - q.Y
        dz = p.Z - q.Z

        d_sq = dx * dx + dy * dy + dz * dz

        if d_sq < min_dist_sq:
            return False

    return True


def filter_points_by_min_distance(points, target_count, min_dist, existing_points=None):
    if existing_points is None:
        existing_points = []

    accepted = []
    pool = list(points)
    random.shuffle(pool)

    for p in pool:
        if len(accepted) >= target_count:
            break

        if not AVOID_NODE_OVERLAP:
            accepted.append(p)
            continue

        if not is_far_enough_from_points(p, existing_points, min_dist):
            continue

        if not is_far_enough_from_points(p, accepted, min_dist):
            continue

        accepted.append(p)

    return accepted


def make_sphere_brep(center, radius):
    sphere = rg.Sphere(center, radius)
    return sphere.ToBrep()


def make_cylinder_between(p0, p1, radius):
    v = p1 - p0
    length = v.Length

    if length <= 1e-6:
        return None

    v.Unitize()

    plane = rg.Plane(p0, v)
    circle = rg.Circle(plane, radius)
    cylinder = rg.Cylinder(circle, length)

    return cylinder.ToBrep(True, True)


def make_cylinder_base(mesh):
    bbox = mesh.GetBoundingBox(True)

    cx = bbox.Center.X
    cy = bbox.Center.Y
    z0 = bbox.Min.Z - BASE_HEIGHT

    size_x = bbox.Max.X - bbox.Min.X
    size_y = bbox.Max.Y - bbox.Min.Y

    radius = max(size_x, size_y) * BASE_RADIUS_SCALE + BASE_MARGIN

    center = rg.Point3d(cx, cy, z0)
    plane = rg.Plane(center, rg.Vector3d.ZAxis)
    circle = rg.Circle(plane, radius)
    cylinder = rg.Cylinder(circle, BASE_HEIGHT)

    return cylinder.ToBrep(True, True)


def layer_points_by_x(points, layer_count):
    if not points:
        return []

    min_x = min(p.X for p in points)
    max_x = max(p.X for p in points)

    if abs(max_x - min_x) < 1e-9:
        return [list(range(len(points)))]

    layers = [[] for _ in range(layer_count)]

    for i, p in enumerate(points):
        t = (p.X - min_x) / (max_x - min_x)
        idx = int(t * layer_count)

        if idx >= layer_count:
            idx = layer_count - 1

        layers[idx].append(i)

    return layers


def distance(a, b):
    return (a - b).Length


def nearest_candidates(points, source_index, candidate_indices, max_length):
    p = points[source_index]
    result = []

    for j in candidate_indices:
        if source_index == j:
            continue

        q = points[j]
        d = distance(p, q)

        if d >= MIN_EDGE_LENGTH and d <= max_length:
            result.append((d, j))

    result.sort(key=lambda item: item[0])
    return result


def add_edge(edge_set, i, j):
    if i == j:
        return

    a_idx = min(i, j)
    b_idx = max(i, j)

    edge_set.add((a_idx, b_idx))


def build_adjacency(node_count, edge_sets):
    adj = {}

    for i in range(node_count):
        adj[i] = []

    for edge_set in edge_sets:
        for i, j in edge_set:
            adj[i].append(j)
            adj[j].append(i)

    return adj


def bfs_connected_from_roots(node_count, edge_sets, roots):
    adj = build_adjacency(node_count, edge_sets)

    visited = set()
    stack = []

    for r in roots:
        if r >= 0 and r < node_count:
            visited.add(r)
            stack.append(r)

    while stack:
        u = stack.pop()

        for v in adj[u]:
            if v not in visited:
                visited.add(v)
                stack.append(v)

    return visited


def find_nearest_index(points, source_index, candidate_indices):
    p = points[source_index]

    best_idx = None
    best_dist = None

    for j in candidate_indices:
        if j == source_index:
            continue

        d = distance(p, points[j])

        if best_dist is None or d < best_dist:
            best_dist = d
            best_idx = j

    return best_idx, best_dist


def force_connect_all_nodes_to_base(
    points,
    normal_edges,
    inner_edges,
    connector_edges,
    support_root_indices
):
    node_count = len(points)

    connected = bfs_connected_from_roots(
        node_count,
        [normal_edges, inner_edges, connector_edges],
        support_root_indices
    )

    if len(connected) == node_count:
        return connected, []

    extra_support_indices = []

    while len(connected) < node_count:
        unconnected = [i for i in range(node_count) if i not in connected]

        best_pair = None
        best_dist = None

        for i in unconnected:
            j, d = find_nearest_index(points, i, list(connected))

            if j is None:
                continue

            if best_dist is None or d < best_dist:
                best_dist = d
                best_pair = (i, j)

        if best_pair is None:
            # ここに来ることはほぼないが、保険として未接続を支柱にする
            if unconnected:
                i = unconnected[0]
                extra_support_indices.append(i)
                support_root_indices.append(i)
                connected.add(i)
            else:
                break

        else:
            i, j = best_pair

            if (
                ALLOW_EXTRA_VERTICAL_SUPPORTS and
                best_dist is not None and
                best_dist > EXTRA_SUPPORT_IF_FARTHER_THAN
            ):
                extra_support_indices.append(i)
                support_root_indices.append(i)
                connected.add(i)
            else:
                connector_edges.add((min(i, j), max(i, j)))

                connected = bfs_connected_from_roots(
                    node_count,
                    [normal_edges, inner_edges, connector_edges],
                    support_root_indices
                )

    return connected, extra_support_indices


# ============================================================
# Main
# ============================================================

random.seed(RANDOM_SEED)

geo = []
info = []

mesh_input = None

try:
    mesh_input = M
except:
    try:
        mesh_input = x
    except:
        mesh_input = None

if mesh_input is None:
    a = []
else:
    mesh = duplicate_and_prepare_mesh(mesh_input)

    if SCALE_TO_TARGET:
        mesh = scale_mesh_to_target(mesh, TARGET_MAX_SIZE)

    bbox = mesh.GetBoundingBox(True)
    center = bbox.Center

    # --------------------------------------------------------
    # 1. 表面ノード候補を多めに生成
    # --------------------------------------------------------
    surface_candidate_count = SURFACE_NODE_COUNT * 10
    surface_candidates = sample_points_on_mesh(mesh, surface_candidate_count)

    # メッシュ頂点も少し混ぜる
    vertex_sample_count = min(100, mesh.Vertices.Count)

    if vertex_sample_count > 0:
        ids = list(range(mesh.Vertices.Count))
        random.shuffle(ids)

        for i in ids[:vertex_sample_count]:
            surface_candidates.append(rg.Point3d(mesh.Vertices[i]))

    # 近すぎるノードを捨てる
    surface_points = filter_points_by_min_distance(
        surface_candidates,
        SURFACE_NODE_COUNT,
        SURFACE_NODE_MIN_DISTANCE
    )

    # --------------------------------------------------------
    # 2. 内部ノード候補を多めに生成
    # --------------------------------------------------------
    inner_candidates = []

    if USE_TRUE_INSIDE_TEST:
        inner_candidates = sample_points_inside_mesh(
            mesh,
            INNER_NODE_COUNT * 10
        )

    # IsPointInside がうまくいかない場合の疑似内部点
    if len(inner_candidates) < int(INNER_NODE_COUNT * 3) and FALLBACK_INNER_FROM_SURFACE:
        missing_candidate_count = INNER_NODE_COUNT * 10 - len(inner_candidates)

        fallback_pts = make_fallback_inner_points(
            surface_points,
            center,
            missing_candidate_count
        )

        inner_candidates.extend(fallback_pts)

    # 表面ノードとも近すぎないように内部ノードを採用
    inner_points = filter_points_by_min_distance(
        inner_candidates,
        INNER_NODE_COUNT,
        INNER_NODE_MIN_DISTANCE,
        existing_points=surface_points
    )

    # --------------------------------------------------------
    # 3. points統合
    # --------------------------------------------------------
    points = []
    point_kind = []

    for p in surface_points:
        points.append(p)
        point_kind.append("surface")

    for p in inner_points:
        points.append(p)
        point_kind.append("inner")

    surface_indices = [i for i, k in enumerate(point_kind) if k == "surface"]
    inner_indices = [i for i, k in enumerate(point_kind) if k == "inner"]

    # ノードが全然作れなかった場合
    if len(points) == 0:
        a = []
    else:
        # --------------------------------------------------------
        # 4. 層分け
        # --------------------------------------------------------
        layer_indices = layer_points_by_x(points, LAYER_COUNT)

        edges = set()
        inner_edges = set()
        connector_edges = set()

        # --------------------------------------------------------
        # 5. 隣接層へのニューラルネット風接続
        # --------------------------------------------------------
        for li in range(len(layer_indices) - 1):
            current_layer = layer_indices[li]
            next_layer = layer_indices[li + 1]

            if not current_layer or not next_layer:
                continue

            for i in current_layer:
                candidates = nearest_candidates(
                    points,
                    i,
                    next_layer,
                    MAX_EDGE_LENGTH
                )

                for _, j in candidates[:CONNECTIONS_PER_NODE]:
                    if point_kind[i] == "inner" or point_kind[j] == "inner":
                        inner_edges.add((min(i, j), max(i, j)))
                    else:
                        edges.add((min(i, j), max(i, j)))

        # --------------------------------------------------------
        # 6. 表面リブ接続
        # --------------------------------------------------------
        if ADD_SURFACE_RIBS:
            for layer in layer_indices:
                layer_surface = [i for i in layer if point_kind[i] == "surface"]

                if len(layer_surface) < 2:
                    continue

                for i in layer_surface:
                    if random.random() > SURFACE_RIB_PROBABILITY:
                        continue

                    candidates = nearest_candidates(
                        points,
                        i,
                        layer_surface,
                        MAX_EDGE_LENGTH * 0.75
                    )

                    if candidates:
                        j = candidates[0][1]
                        edges.add((min(i, j), max(i, j)))

        # --------------------------------------------------------
        # 7. 内部ノードの近傍接続
        # --------------------------------------------------------
        if ADD_INNER_RANDOM_RIBS and inner_indices:
            all_indices = list(range(len(points)))

            for i in inner_indices:
                if random.random() > INNER_RIB_PROBABILITY:
                    continue

                candidates = nearest_candidates(
                    points,
                    i,
                    all_indices,
                    MAX_INNER_EDGE_LENGTH
                )

                count = 0

                for _, j in candidates:
                    if count >= INNER_CONNECTIONS_PER_NODE:
                        break

                    inner_edges.add((min(i, j), max(i, j)))
                    count += 1

        # --------------------------------------------------------
        # 8. 台座支柱の接続先ノードを決定
        # --------------------------------------------------------
        support_root_indices = []

        if ADD_BASE and ADD_SUPPORT_POSTS and points:
            sorted_indices_by_z = sorted(
                range(len(points)),
                key=lambda i: points[i].Z
            )

            support_root_indices = sorted_indices_by_z[
                :min(SUPPORT_POST_COUNT, len(sorted_indices_by_z))
            ]

        # 支柱がない設定でも、連結判定の根として最低1個は必要
        if not support_root_indices:
            sorted_indices_by_z = sorted(
                range(len(points)),
                key=lambda i: points[i].Z
            )
            support_root_indices = sorted_indices_by_z[:1]

        # --------------------------------------------------------
        # 9. 全ノードを台座接続成分へ強制接続
        # --------------------------------------------------------
        extra_support_indices = []

        if FORCE_ALL_CONNECTED_TO_BASE:
            connected, extra_support_indices = force_connect_all_nodes_to_base(
                points,
                edges,
                inner_edges,
                connector_edges,
                support_root_indices
            )

        # --------------------------------------------------------
        # 10. ノード球を作成
        # --------------------------------------------------------
        for i, p in enumerate(points):
            if point_kind[i] == "inner":
                r = INNER_NODE_RADIUS
            else:
                r = NODE_RADIUS

            brep = make_sphere_brep(p, r)

            if brep:
                geo.append(brep)

        # --------------------------------------------------------
        # 11. エッジ円柱を作成
        # --------------------------------------------------------
        for i, j in edges:
            brep = make_cylinder_between(
                points[i],
                points[j],
                EDGE_RADIUS
            )

            if brep:
                geo.append(brep)

        for i, j in inner_edges:
            brep = make_cylinder_between(
                points[i],
                points[j],
                INNER_EDGE_RADIUS
            )

            if brep:
                geo.append(brep)

        # 連結性保証のために追加されたエッジ
        for i, j in connector_edges:
            brep = make_cylinder_between(
                points[i],
                points[j],
                CONNECTOR_EDGE_RADIUS
            )

            if brep:
                geo.append(brep)

        # --------------------------------------------------------
        # 12. 台座
        # --------------------------------------------------------
        if ADD_BASE:
            base_brep = make_cylinder_base(mesh)

            if base_brep:
                geo.append(base_brep)

        # --------------------------------------------------------
        # 13. 台座支柱
        # --------------------------------------------------------
        if ADD_BASE and points:
            base_bottom_z = bbox.Min.Z - BASE_HEIGHT

            all_support_indices = list(
                set(support_root_indices + extra_support_indices)
            )

            for i in all_support_indices:
                p = points[i]

                p0 = rg.Point3d(p.X, p.Y, base_bottom_z)
                p1 = rg.Point3d(p.X, p.Y, p.Z)

                if i in extra_support_indices:
                    r = EXTRA_SUPPORT_RADIUS
                else:
                    r = SUPPORT_RADIUS

                brep = make_cylinder_between(p0, p1, r)

                if brep:
                    geo.append(brep)

        # --------------------------------------------------------
        # 14. デバッグ情報
        # --------------------------------------------------------
        final_connected = bfs_connected_from_roots(
            len(points),
            [edges, inner_edges, connector_edges],
            support_root_indices + extra_support_indices
        )

        info.append("surface nodes requested: {}".format(SURFACE_NODE_COUNT))
        info.append("surface nodes generated: {}".format(len(surface_points)))
        info.append("inner nodes requested: {}".format(INNER_NODE_COUNT))
        info.append("inner nodes generated: {}".format(len(inner_points)))
        info.append("normal edges: {}".format(len(edges)))
        info.append("inner edges: {}".format(len(inner_edges)))
        info.append("connector edges: {}".format(len(connector_edges)))
        info.append("support posts: {}".format(len(set(support_root_indices + extra_support_indices))))
        info.append("connected nodes: {} / {}".format(len(final_connected), len(points)))
        info.append("geometry count: {}".format(len(geo)))

        if PRINT_INFO:
            for line in info:
                print(line)

        a = geo
