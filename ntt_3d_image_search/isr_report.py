"""Offline HTML reports for ISR retrieval and held-out rendering evaluation.

Preview JPEGs are generated from the original images without modifying them.
All report images use paths relative to the HTML so the whole output directory
can be copied to another machine and viewed without a server or network access.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


PRIMARY_DISTANCE_M = 3.0

_STYLE = """
:root{color-scheme:light;--ink:#183049;--muted:#526578;--line:#dce4ec;--paper:#fff;
--bg:#f2f5f8;--blue:#174f85;--green:#126b45;--red:#a33335;--amber:#8a5909}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.7 system-ui,-apple-system,"Segoe UI","Meiryo",sans-serif}
main{max-width:1540px;margin:auto;padding:32px 24px 64px}h1{font-size:28px;margin:0 0 8px}
h2{font-size:21px;margin:28px 0 12px}h3{font-size:17px;margin:0 0 10px}p{margin:8px 0}
a{color:var(--blue)}.muted{color:var(--muted)}.eyebrow{font-size:12px;letter-spacing:.08em;
color:var(--blue);font-weight:700}.panel,.query{background:var(--paper);border:1px solid var(--line);
border-radius:12px;padding:20px;margin:18px 0}.notice{background:#fff8e7;border-left:4px solid #d59721;
padding:14px 18px;border-radius:4px;margin:20px 0}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.stat{padding:16px;background:var(--paper);border:1px solid var(--line);border-radius:10px}
.stat strong{font-size:26px;display:block}.stat span{color:var(--muted);font-size:13px}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:#edf2f7;font-size:13px}td{font-size:14px}.primary-row{background:#edf6ff}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:14px}
.card{margin:0;border:1px solid var(--line);border-radius:9px;overflow:hidden;min-width:0;background:#fff}
.card.query-card{border:2px solid var(--blue)}.card img{display:block;width:100%;height:auto;aspect-ratio:16/9;
object-fit:contain;background:#16202b}.caption{padding:12px}.caption strong{display:block;overflow-wrap:anywhere}
.caption p{font-size:13px;margin:5px 0}.caption .coordinates{font-variant-numeric:tabular-nums}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:700;margin:0 6px 5px 0}
.success{background:#e4f5ec;color:var(--green)}.top5{background:#e4effc;color:var(--blue)}
.failure{background:#fbe7e8;color:var(--red)}.uncovered{background:#fff1d6;color:var(--amber)}
.unknown,.split{background:#edf0f4;color:var(--muted)}.query-head{display:flex;gap:12px;align-items:flex-start;justify-content:space-between}
.query-head h3{overflow-wrap:anywhere}.reference{max-width:460px;margin-top:12px}.query-nav{display:flex;flex-wrap:wrap;gap:8px 16px}
.query-nav a{overflow-wrap:anywhere;font-size:13px}details{margin:12px 0}summary{cursor:pointer;color:var(--blue)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f9;border-radius:8px;padding:16px;font-size:12px;max-height:550px;overflow:auto}
.footer{font-size:12px;color:var(--muted);margin-top:32px}.empty-image{aspect-ratio:16/9;display:grid;place-items:center;background:#edf0f4;color:var(--muted)}
@media(max-width:900px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){main{padding:20px 12px 40px}.panel,.query{padding:14px}.cards{grid-template-columns:1fr}.query-head{display:block}h1{font-size:23px}}
@media print{body{background:white}main{max-width:none;padding:0}.query{break-inside:avoid}.query-nav{display:none}details:not([open]){display:none}.cards{grid-template-columns:repeat(3,minmax(0,1fr))}}
"""


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "—"
    return f"{number:.{digits}f}" if math.isfinite(number) else "—"


def _percentage(value: Any) -> str:
    return "—" if value is None else f"{_number(float(value) * 100, 1)}%"


def _count_rate(row: dict, conditional: bool = False) -> str:
    if not row:
        return "—"
    total = row.get("conditional_total") if conditional else row.get("total")
    rate = row.get("conditional_rate") if conditional else row.get("rate")
    count = row.get("successes", row.get("count", 0))
    return f"{_escape(count)} / {_escape(total)}（{_escape(_percentage(rate))}）"


def _coordinates(record: dict) -> str:
    position = record.get("position_m")
    if position is None or len(position) != 3:
        return "位置情報なし"
    return "XYZ = (" + ", ".join(_number(value) for value in position) + ") m"


def _threshold(rows: list[dict], distance: float = PRIMARY_DISTANCE_M) -> dict | None:
    return next((row for row in rows if math.isclose(float(row["distance_m"]), distance,
                                                   rel_tol=0.0, abs_tol=1e-9)), None)


def _selected_distance(metrics: dict) -> float:
    """Prefer 3 m; otherwise use the nearest actually evaluated threshold."""
    distances = [float(row["distance_m"]) for row in metrics.get("thresholds", [])]
    return min(distances, key=lambda value: (abs(value - PRIMARY_DISTANCE_M), value)) if distances else PRIMARY_DISTANCE_M


def _distance_label(distance: float) -> str:
    return format(distance, ".12g")


class _Previews:
    """Cache one image preview per source path within one report generation."""

    def __init__(self, out_dir: Path, prefix: str) -> None:
        self.asset_dir = out_dir / f"{prefix}_assets"
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        self.cache: dict[Path, str] = {}

    def image(self, source_path: str | Path, label: str) -> str:
        source = Path(source_path).resolve()
        if source not in self.cache:
            # A digest prevents unsafe filenames and duplicate names from
            # different folders colliding. Re-render on each report run.
            name = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:24] + ".jpg"
            destination = self.asset_dir / name
            with Image.open(source) as original:
                preview = ImageOps.exif_transpose(original).convert("RGB")
                preview.thumbnail((720, 480), Image.Resampling.LANCZOS)
                preview.save(destination, "JPEG", quality=88, optimize=True)
            self.cache[source] = (Path(self.asset_dir.name) / name).as_posix()
        return f'<img src="{_escape(self.cache[source])}" alt="{_escape(label)}" loading="lazy">'


def _card(record: dict, previews: _Previews, title: str, *, match: dict | None = None,
          query: bool = False, note: str = "") -> str:
    identifier = record.get("id", record.get("database_id", Path(record["image_path"]).name))
    image_html = previews.image(record["image_path"], f"{title}: {identifier}")
    rows = [f'<strong>{_escape(title)}</strong>', f'<p>{_escape(identifier)}</p>']
    if match is not None:
        if "similarity" in match:
            rows.append(f'<p>コサイン類似度：{_escape(_number(match["similarity"], 4))}</p>')
        if "distance_m" in match:
            rows.append(f'<p>位置誤差：{_escape(_number(match["distance_m"]))} m ／ '
                        f'向きの差：{_escape(_number(match.get("yaw_error_deg"), 1))}°</p>')
    rows.append(f'<p class="coordinates">{_escape(_coordinates(record))}<br>'
                f'yaw = {_escape(_number(record.get("yaw_deg"), 1))}° ／ '
                f'地点 {_escape(record.get("point_id", "—"))}</p>')
    if note:
        rows.append(f'<p class="muted">{_escape(note)}</p>')
    classes = "card query-card" if query else "card"
    return f'<figure class="{classes}">{image_html}<figcaption class="caption">{"".join(rows)}</figcaption></figure>'


def _document(title: str, body: str) -> str:
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" '
            'content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
            f'<title>{_escape(title)}</title><style>{_STYLE}</style></head><body><main>{body}'
            '<p class="footer">この HTML と付属の assets フォルダを一緒に保存してください。'
            '外部通信は行いません。表示画像はサムネイルで、元画像は変更していません。</p>'
            '</main></body></html>')


def _run_details(run_info: dict) -> str:
    content = json.dumps(run_info, ensure_ascii=False, indent=2, default=str)
    return '<details><summary>実行条件・再現情報</summary><pre>' + _escape(content) + '</pre></details>'


def _metrics_table(metrics: dict, angle: float, primary_distance: float) -> str:
    rows = []
    for threshold in metrics.get("thresholds", []):
        distance = float(threshold["distance_m"])
        for key, label in (("place", "場所"), ("place_and_yaw", f"場所＋向き ≤ {_distance_label(angle)}°")):
            condition = threshold[key]
            recall = condition.get("recall", {})
            cells = [f'{_escape(_distance_label(distance))} m', _escape(label), _count_rate(condition.get("coverage", {}))]
            cells += [_count_rate(recall.get(str(k), {})) for k in (1, 5, 10)]
            cells += [_count_rate(recall.get(str(k), {}), conditional=True) for k in (1, 5, 10)]
            row_class = ' class="primary-row"' if math.isclose(distance, primary_distance) else ""
            rows.append(f'<tr{row_class}>' + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    heads = ["距離条件", "正解条件", "DB 正解候補保有率", "Recall@1", "Recall@5", "Recall@10",
             "候補ありのみ @1", "候補ありのみ @5", "候補ありのみ @10"]
    return ('<div class="table-wrap"><table><thead><tr>' + "".join(f"<th>{_escape(h)}</th>" for h in heads)
            + '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')


def _top1_table(metrics: dict) -> str:
    rows = []
    for key, label in (("distance_m", "1 位の位置誤差（m）"), ("yaw_error_deg", "1 位の向きの差（°）")):
        stats = metrics.get("top1", {}).get(key, {})
        rows.append('<tr><td>' + _escape(label) + '</td>'
                    + "".join(f'<td>{_escape(_number(stats.get(stat)))}</td>' for stat in ("mean", "median", "p90", "max"))
                    + '</tr>')
    return ('<div class="table-wrap"><table><thead><tr><th>誤差</th><th>平均</th><th>中央値</th>'
            '<th>90 パーセンタイル</th><th>最大</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')


def _split_table(metrics: dict, primary_distance: float) -> str:
    rows = []
    for split, split_metrics in metrics.get("by_split", {}).items():
        if not split_metrics:
            continue
        selected = _threshold(split_metrics.get("thresholds", []), primary_distance)
        place = selected.get("place", {}) if selected else {}
        recall = place.get("recall", {})
        counts = split_metrics.get("counts", {})
        label = {"dev": "改善用（dev）", "test": "最終評価用（test）"}.get(split, str(split))
        rows.append('<tr><td>' + _escape(label) + '</td>'
                    + f'<td>{_escape(counts.get("queries", "—"))}</td><td>{_escape(counts.get("query_points", "—"))}</td>'
                    + f'<td>{_count_rate(place.get("coverage", {}))}</td>'
                    + f'<td>{_count_rate(recall.get("1", {}))}</td><td>{_count_rate(recall.get("5", {}))}</td>'
                    + f'<td>{_escape(_number(split_metrics.get("top1", {}).get("distance_m", {}).get("median")))}</td></tr>')
    if not rows:
        return '<p class="muted">dev / test 別の集計は入力されていません。</p>'
    return ('<div class="table-wrap"><table><thead><tr><th>区分</th><th>クエリ数</th><th>地点数</th>'
            '<th>DB 正解候補保有率</th><th>Recall@1</th><th>Recall@5</th><th>位置誤差中央値（m）</th>'
            '</tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')


def _query_status(query_metrics: dict, primary_distance: float = PRIMARY_DISTANCE_M) -> tuple[str, str]:
    threshold = _threshold(query_metrics.get("thresholds", []), primary_distance)
    distance = _distance_label(primary_distance)
    if threshold is None:
        return "unknown", f"{distance} m 条件の集計なし"
    place = threshold["place"]
    if place.get("positive_count", 0) == 0:
        return "uncovered", "DB に正解候補なし"
    hits = place.get("hits", {})
    if hits.get("1", False):
        return "success", f"成功：1 位が {distance} m 以内"
    if hits.get("5", False):
        return "top5", "1 位は失敗／上位 5 件で成功"
    return "failure", "失敗：上位 5 件に正解なし"


def _nearest_reference(query: dict, database: list[dict]) -> tuple[dict, dict] | None:
    if not database:
        return None
    qx, qy = map(float, query["position_m"][:2])
    qyaw = float(query["yaw_deg"])
    candidates = []
    for row in database:
        x, y = map(float, row["position_m"][:2])
        distance = math.hypot(x - qx, y - qy)
        yaw_error = abs((float(row["yaw_deg"]) - qyaw + 180) % 360 - 180)
        candidates.append((distance, yaw_error, str(row["id"]), row))
    distance, yaw_error, _, record = min(candidates, key=lambda item: item[:3])
    return record, {"distance_m": distance, "yaw_error_deg": yaw_error}


def write_evaluation_report(out_dir: Path, metrics: dict, database_records: list[dict],
                            query_records: list[dict], run_info: dict) -> Path:
    """Write a self-contained directory of evaluation HTML and image previews."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    previews = _Previews(out_dir, "report")
    database = {row["id"]: row for row in database_records}
    queries = {row["id"]: row for row in query_records}
    counts = metrics.get("counts", {})
    angle = float(metrics.get("definitions", {}).get("angle_threshold_deg", 30.0))
    primary_distance = _selected_distance(metrics)
    primary_label = _distance_label(primary_distance)
    primary = _threshold(metrics.get("thresholds", []), primary_distance)
    primary_recall = primary.get("place", {}).get("recall", {}).get("1", {}) if primary else {}
    parts = ['<div class="eyebrow">ISR · RENDERING RETRIEVAL EVALUATION</div>',
             '<h1>レンダリング画像の検索評価</h1>',
             '<p class="muted">DB に含まれないクエリ画像を検索し、既知の撮影位置・向きと照合します。</p>',
             f'<div class="notice"><strong>主分類は「距離 {_escape(primary_label)} m 以内」という暫定条件です。</strong>'
             '<p>業務上の合格基準は未確定です。正解はクエリの撮影座標・向きであり、類似度ではありません。'
             '本結果はレンダリング同士の検索評価です。実写での精度と、連続的なカメラ位置・姿勢の精密推定は未検証です。</p></div>',
             '<div class="stats">']
    for label, value in (("DB 画像", counts.get("database_images", len(database_records))),
                         ("評価クエリ", counts.get("queries", len(query_records))),
                         ("評価地点", counts.get("query_points", len({r["point_id"] for r in query_records}))),
                         (f"暫定 {primary_label} m・Recall@1", _percentage(primary_recall.get("rate")))):
        parts.append(f'<div class="stat"><strong>{_escape(value)}</strong><span>{_escape(label)}</span></div>')
    parts.append('</div><section class="panel"><h2>全体指標</h2><p>位置誤差は XY 平面上の距離、'
                 '向きの差は yaw の最小角度差です。境界値を含みます。類似度は正解確率ではありません。</p>')
    parts.append(_metrics_table(metrics, angle, primary_distance))
    parts.append('<p class="muted">Recall@K は「上位 K 件に正解が 1 件以上あるクエリ」の割合です。'
                 '主集計の分母は全クエリで、DB に正解候補がない場合も失敗として含みます。'
                 '「候補ありのみ」は正解候補が存在するクエリに限った参考値です。該当クエリが 0 件の割合は — と表示します。</p>')
    parts.append(_top1_table(metrics))
    parts.append('<p class="muted">1 位の誤差統計は成功・失敗を含む全クエリで算出しています。'
                 '向きの差は共通して見える面積や遮蔽を表しません。</p></section>')
    parts.append('<section class="panel"><h2>dev / test 別の概要</h2>'
                 f'<p>場所の正解条件は暫定 {_escape(primary_label)} m 以内です。改善用と最終評価用の結果を分けて確認します。</p>')
    parts.append(_split_table(metrics, primary_distance))
    parts.append('</section><h2>全クエリの結果</h2>'
                 '<p>青枠がクエリ、続く画像が検索順位順の上位 5 件です。候補の座標は、その DB 画像に付属する撮影座標です。</p>')
    navigation = []
    query_sections = []
    for index, detail in enumerate(metrics.get("queries", []), 1):
        query_id = detail["query_id"]
        query = queries[query_id]
        status, status_label = _query_status(detail, primary_distance)
        anchor = f"query-{index}"
        navigation.append(f'<a href="#{anchor}">{_escape(query_id)}</a>')
        split = query.get("split", "未指定")
        body = [f'<article class="query" id="{anchor}"><div class="query-head"><h3>{_escape(query_id)}</h3><div>',
                f'<span class="badge split">{_escape(split)}</span><span class="badge {status}">{_escape(status_label)}</span></div></div>',
                f'<p>1 位の位置誤差：<strong>{_escape(_number(detail.get("top1_distance_m")))} m</strong> ／ '
                f'向きの差：{_escape(_number(detail.get("top1_yaw_error_deg"), 1))}° ／ '
                f'DB の最寄り地点まで：{_escape(_number(detail.get("nearest_db_distance_m")))} m</p>']
        selected = _threshold(detail.get("thresholds", []), primary_distance)
        if selected:
            place = selected["place"]
            joint = selected["place_and_yaw"]
            body.append(f'<p class="muted">{_escape(primary_label)} m 以内の正解候補：{_escape(place.get("positive_count", 0))} 枚 ／ '
                        f'向きの差 {_escape(_distance_label(angle))}° 以内も満たす候補：{_escape(joint.get("positive_count", 0))} 枚 ／ '
                        f'場所の正解候補が最初に出る順位：{_escape(place.get("first_positive_rank") or "なし")}</p>')
        body.append('<div class="cards">')
        body.append(_card(query, previews, "クエリ（正解の撮影位置）", query=True))
        for match in detail.get("ranking", [])[:5]:
            record = database[match["database_id"]]
            body.append(_card(record, previews, f'検索 {match["rank"]} 位', match=match))
        body.append('</div>')
        nearest = _nearest_reference(query, database_records)
        if nearest:
            reference, reference_errors = nearest
            body.append('<details><summary>正解位置に最も近い DB 画像を確認する</summary>'
                        '<p class="muted">正解座標から選んだ比較用の画像です。検索順位には使っていません。'
                        '同じ距離ならクエリに近い向きを選んでいます。DB に近い候補があるのに検索で見逃したかを確認できます。</p>'
                        '<div class="reference">')
            body.append(_card(reference, previews, "DB 内の最寄り地点（参考）", match=reference_errors,
                              note=f"最寄りでも {primary_label} m を超える場合、暫定条件の正解候補ではありません。"))
            body.append('</div></details>')
        body.append('</article>')
        query_sections.append("".join(body))
    parts.append('<nav class="query-nav" aria-label="クエリ一覧">' + "".join(navigation) + '</nav>')
    parts.extend(query_sections)
    parts.append(_run_details(run_info))
    destination = out_dir / "report.html"
    destination.write_text(_document("ISR レンダリング検索評価", "".join(parts)), encoding="utf-8")
    return destination


def write_search_report(out_dir: Path, query_path: Path, matches: list[dict], run_info: dict) -> Path:
    """Write one unlabelled query and its ranked DB candidates without scoring accuracy."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    query_path = Path(query_path)
    previews = _Previews(out_dir, "search")
    parts = ['<div class="eyebrow">ISR · IMAGE RETRIEVAL</div><h1>入力画像から場所の候補を検索</h1>',
             f'<p class="muted">入力：{_escape(query_path.name)} ／ 検索候補：{_escape(len(matches))} 件</p>',
             '<div class="notice"><strong>表示する座標は、検索された DB 画像の撮影座標です。</strong>'
             '<p>入力写真の位置・向きを精密に推定した値ではありません。正解位置が与えられていないため、'
             'この検索画面では成功・失敗や位置誤差を判定しません。実写での精度は未検証です。'
             'コサイン類似度は正解確率ではありません。</p></div><div class="cards">']
    query = {"id": query_path.name, "image_path": query_path}
    parts.append(_card(query, previews, "入力画像", query=True, note="撮影位置・向きは未指定"))
    for match in matches:
        record = dict(match)
        record["id"] = match.get("database_id", Path(match["image_path"]).name)
        parts.append(_card(record, previews, f'検索 {match.get("rank", "—")} 位', match=match))
    parts.append('</div>')
    if not matches:
        parts.append('<p>検索候補がありません。</p>')
    parts.append(_run_details(run_info))
    destination = out_dir / "report.html"
    destination.write_text(_document("ISR 画像検索結果", "".join(parts)), encoding="utf-8")
    return destination
