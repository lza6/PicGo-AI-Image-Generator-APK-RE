"""把上游的 50 个图生图风格 + 14 个文生图风格导出成可直接喂给自建 SD-WebUI 的 JSON。

用途：上游 runpod 算力已销毁，但风格模板（prompt / negative_prompt / denoising_strength /
sampler_index / use_controlnet）全部还活着。把它们导出后，自建一个 SD-WebUI，
就能用同一套风格复刻这个 app 的图生图效果。

用法:
    python scripts/export_styles.py
输出:
    exports/styles_export.json
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from gateway.picgo_client import PicGoClient  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "exports")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    client = PicGoClient()

    config = client.transfer_config()
    txt2img = client.style_list()
    img2img_names = client.transfer_styles()

    styles = {}
    for name, cfg in config.get("STYLES", {}).items():
        styles[name] = {
            "app_name": cfg.get("app_name"),
            "prompt": cfg.get("prompt"),
            "negative_prompt": cfg.get("negative_prompt"),
            "denoising_strength": cfg.get("denoising_strength"),
            "sampler_index": cfg.get("sampler_index"),
            "use_controlnet": cfg.get("use_controlnet", False),
            "in_list_styles": name in img2img_names,
            "upstream_dead": True,
        }

    payload = {
        "source": "PicGo AI Image Generator v2.0.8 / 69.10.54.174:8005",
        "captured_at_note": "config 每次拉取可能变化，本文件是一次快照",
        "const": config.get("CONST", {}),
        "styles_controlnet": config.get("STYLE_USE_CONTROLNET", {}),
        "service_faceswap": config.get("SERVICE_FACESWAP", []),
        "service_blending": config.get("SERVICE_BLENDING", []),
        "img2img_styles": styles,
        "txt2img_styles": txt2img.get("details", {}),
        "txt2img_list": txt2img.get("names", []),
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "styles_export.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print(f"img2img 风格 {len(styles)} 个，txt2img 风格 {len(payload['txt2img_styles'])} 个")
    print(f"已写入 {out}")
    missing = [n for n, s in styles.items() if not s["prompt"]]
    if missing:
        print(f"注意：{len(missing)} 个风格没有 prompt 模板: {missing[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
