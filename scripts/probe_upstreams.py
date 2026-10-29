"""上游存活矩阵探测（只读，每个目标一次）。

覆盖：
  1. 应用硬编码的 5 个后端基址（ServiceGenerator 里的 7 个 Retrofit 实例）
  2. /api/v1/transfer/config 里暴露的全部 runpod 算力代理（img2img / controlnet / faceswap / blending / turbo）

用法:
    python scripts/probe_upstreams.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gateway.picgo_client import PicGoClient  # noqa: E402

EVID = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evidence")

BASES = [
    ("genimage-8005", "http://69.10.54.174:8005/openapi.json"),
    ("yearbook-8006", "http://69.10.54.174:8006/"),
    ("minio-9000", "http://69.10.54.174:9000/"),
    ("ob-5000", "http://199.231.188.59:5000/now/v1/"),
    ("start-procyoni", "http://art12.procyoni.com/"),
    ("app-proxglobal", "https://ai-art.proxglobal.co/"),
    ("app-proxglobal-static", "https://ai-art.proxglobal.co/app-data/video-data.json"),
    ("chatgpt-proxglobal", "https://chatgpt.proxglobal.co/"),
]


def collect_runpod(client: PicGoClient) -> list[tuple[str, str]]:
    """从 transfer config 抽取所有 runpod 算力地址。"""
    try:
        cfg = client.transfer_config()
    except Exception as exc:  # noqa: BLE001
        print(f"  ! 拉取 transfer config 失败: {exc}")
        return []
    urls: set[str] = set(cfg.get("CONST", {}).get("img2img_urls", []))
    urls.update(cfg.get("CONST", {}).get("txt2img_turbo", []))
    urls.update(cfg.get("SERVICES_CONTROLNET", []))
    urls.update(cfg.get("SERVICE_FACESWAP", []))
    urls.update(cfg.get("SERVICE_BLENDING", []))
    dev = cfg.get("DEV", {})
    if isinstance(dev, dict) and dev.get("service"):
        urls.add(dev["service"])
    for bucket in cfg.get("STYLE_USE_CONTROLNET", {}).values():
        urls.update(bucket)
    for style in cfg.get("STYLES", {}).values():
        urls.update(style.get("service_urls", []))
    return [(f"runpod:{u.split('//')[1].split('.')[0]}", u) for u in sorted(urls)]


def probe(target: str, url: str, timeout: int = 15) -> dict:
    started = time.time()
    try:
        resp = requests.get(url, timeout=timeout)
        body = resp.content
        note = None
        if b'window.location.href="/lander"' in body:
            note = "parked_lander"  # 域名已停放，HTTP 200 但不提供服务
        return {"target": target, "url": url, "http": resp.status_code, "bytes": len(body),
                "note": note, "alive": resp.status_code < 400 and note is None,
                "elapsed_ms": int((time.time() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"target": target, "url": url, "http": None, "error": type(exc).__name__,
                "alive": False, "elapsed_ms": int((time.time() - started) * 1000)}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(EVID, exist_ok=True)
    client = PicGoClient()
    targets = list(BASES)
    runpod = collect_runpod(client)
    print(f"从 transfer config 抽取到 {len(runpod)} 个算力地址")
    targets.extend(runpod)

    rows = []
    for target, url in targets:
        row = probe(target, url)
        rows.append(row)
        flag = "OK " if row.get("alive") else "DIE"
        if row.get("note"):
            flag = "DIE"
        print(f"  [{flag}] {target:34s} http={str(row.get('http')):>5} "
              f"bytes={str(row.get('bytes', '-')):>9} {row['elapsed_ms']:>5}ms  "
              f"{row.get('note') or ''} {url[:64]}")

    alive = [r for r in rows if r.get("alive")]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(EVID, f"upstream_matrix_{stamp}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": stamp, "total": len(rows), "alive": len(alive), "rows": rows},
                  fh, ensure_ascii=False, indent=2)
    print(f"\n存活 {len(alive)}/{len(rows)}，证据写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
