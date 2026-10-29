"""PicGo v2.0.8 单点冒烟（不做并发压测）。

口径：每个端点只打一次，记录真实状态码/耗时/响应片段，写 evidence/smoke_<ts>.json。
判定逻辑：
  * 协议面（token / styles / config）必须通过；
  * 生成面必须被正确识别为 upstream_dead —— 如果哪天它们真的出图了，本脚本会 FAIL 提醒上游复活。

用法:
    python scripts/smoke.py                 # 默认跳过 41s 的 video 端点
    python scripts/smoke.py --with-video    # 额外打一次 video（恒返回模板，约 41s）
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gateway.picgo_client import PicGoClient, UpstreamDead, upstream_matrix  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EVID = os.path.join(HERE, "..", "evidence")
TEST_IMAGE = os.path.join(HERE, "..", "test_face.jpg")


def _jpg_bytes() -> bytes:
    if os.path.exists(TEST_IMAGE):
        with open(TEST_IMAGE, "rb") as fh:
            return fh.read()
    from PIL import Image, ImageDraw

    buf = os.path.join(EVID, "_tmp_face.jpg")
    os.makedirs(EVID, exist_ok=True)
    im = Image.new("RGB", (512, 512), (240, 240, 240))
    draw = ImageDraw.Draw(im)
    draw.ellipse((100, 80, 412, 392), fill=(200, 160, 120))
    im.save(buf, quality=90)
    with open(buf, "rb") as fh:
        return fh.read()


def jwt_claims(token: str) -> dict:
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-video", action="store_true", help="额外调用 41s 的 video 端点")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    os.makedirs(EVID, exist_ok=True)
    client = PicGoClient()
    rows: list[dict] = []
    failures: list[str] = []

    def record(name: str, expect: str, fn) -> None:
        started = time.time()
        row = {"check": name, "expect": expect}
        try:
            value = fn()
            row.update(ok=True, elapsed_ms=int((time.time() - started) * 1000), result=value)
            print(f"[PASS] {name:26s} {row['elapsed_ms']:>5}ms  {json.dumps(value, ensure_ascii=False)[:110]}")
        except UpstreamDead as exc:
            row.update(ok=(expect == "upstream_dead"), elapsed_ms=int((time.time() - started) * 1000),
                       error=str(exc))
            tag = "PASS" if row["ok"] else "FAIL"
            print(f"[{tag}] {name:26s} {row['elapsed_ms']:>5}ms  upstream_dead: {str(exc)[:90]}")
            if not row["ok"]:
                failures.append(f"{name}: 上游意外可用，交付结论需更新")
        except Exception as exc:  # noqa: BLE001
            row.update(ok=False, elapsed_ms=int((time.time() - started) * 1000),
                       error=f"{type(exc).__name__}: {exc}")
            print(f"[FAIL] {name:26s} {row['elapsed_ms']:>5}ms  {row['error'][:110]}")
            failures.append(f"{name}: {row['error']}")
        rows.append(row)

    def check_token():
        data = client.forge_token("smoke")
        claims = jwt_claims(data["access_token"])
        assert "unique" in claims and claims.get("app") == "prox_app", claims
        return {"token_type": data.get("token_type"), "claims": claims,
                "ttl_sec": claims["exp"] - data["_issued_at"]}

    def check_sha256():
        data = client.sha256("picgo")
        assert len(data.get("hash", "")) == 64, data
        return data

    def check_style_list():
        data = client.style_list()
        return {"count": len(data.get("names", [])), "names": data.get("names", [])[:5]}

    def check_transfer_styles():
        names = client.transfer_styles()
        return {"count": len(names), "sample": names[:5]}

    def check_transfer_config():
        data = client.transfer_config()
        urls = sorted({u for v in data.get("STYLES", {}).values() for u in v.get("service_urls", [])})
        return {"styles": len(data.get("STYLES", {})), "unique_upstreams": urls,
                "const_img2img": data.get("CONST", {}).get("img2img_urls", [])}

    def check_txt2img():
        token = client.forge_token()["access_token"]
        return client.txt2img(prompt="a red apple", negative_prompt="blurry", style_name="realistic",
                              token=token)

    def check_transfer():
        token = client.forge_token()["access_token"]
        return client.transfer(_jpg_bytes(), style="anime", token=token)

    def check_video():
        return client.video_generate(_jpg_bytes(), prompt="a cat running")

    record("token(forged)", "ok", check_token)
    record("sha256", "ok", check_sha256)
    record("style_list.txt2img", "ok", check_style_list)
    record("style_list.img2img", "ok", check_transfer_styles)
    record("transfer.config", "ok", check_transfer_config)
    record("txt2img", "upstream_dead", check_txt2img)
    record("img2img(transfer)", "upstream_dead", check_transfer)
    if args.with_video:
        record("video-generate", "template_only", check_video)

    matrix = upstream_matrix()
    print("\n上游存活矩阵:")
    for row in matrix:
        print(f"  {row['target']:20s} http={str(row.get('http')):>5} "
              f"bytes={str(row.get('bytes', '-')):>8} {row['elapsed_ms']:>5}ms")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = os.path.join(EVID, f"smoke_{stamp}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": stamp, "checks": rows, "upstream_matrix": matrix,
                   "failures": failures}, fh, ensure_ascii=False, indent=2)
    print(f"\n证据已写入 {out}")
    print("结论：" + ("全部符合预期（协议面可用 / 生成面 upstream_dead）" if not failures
                     else f"{len(failures)} 项不符预期"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
