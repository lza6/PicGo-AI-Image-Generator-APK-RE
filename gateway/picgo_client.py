"""PicGo AI Image Generator v2.0.8 (Premium) protocol client.

纯协议复刻，不依赖任何 APK 运行时。来源于 D:/apk-analysis/picgo208 的静态还原：
  com.prox.global.aiart.data.remote.ServiceGenerator / *Service 接口集合

后端矩阵（2026-10-29 实测）:
  BASE_GENIMAGE  http://69.10.54.174:8005/                      ← 活（FastAPI，本文客户端主体）
  BASE_APP       https://ai-art.proxglobal.co/                   ← 仅静态资源，API 全 404
  BASE_START     http://art12.procyoni.com/                      ← 已变停放页（parked lander）
  BASE_OB        http://199.231.188.59:5000/now/v1/              ← 活，但仅数据面
  BASE_YEARBOOK  http://69.10.54.174:8006/                       ← 503
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import requests

BASE_GENIMAGE = "http://69.10.54.174:8005"
BASE_APP = "https://ai-art.proxglobal.co"
BASE_START = "http://art12.procyoni.com"
BASE_OB = "http://199.231.188.59:5000/now/v1"
BASE_YEARBOOK = "http://69.10.54.174:8006"

# 8005 上所有生成端点在无可用算力时都会返回这些形态
_DEAD_MARKERS = ("Error!", "Failed")


class UpstreamDead(RuntimeError):
    """上游算力不可用（runpod 代理已销毁 / MinIO 已下线）。"""


class PicGoClient:
    def __init__(self, base: str = BASE_GENIMAGE, timeout: int = 180) -> None:
        self.base = base.rstrip("/") + "/"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    # ---------------------------------------------------------------- utils
    def _url(self, path: str) -> str:
        return self.base + path.lstrip("/")

    def _json(self, method: str, path: str, **kw) -> tuple[int, Any]:
        resp = self.session.request(method, self._url(path), timeout=self.timeout, **kw)
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text[:2000]}
        return resp.status_code, body

    @staticmethod
    def _dead_reason(status: int, body: Any) -> str | None:
        if status == 200 and isinstance(body, dict):
            content = body.get("content")
            if isinstance(content, dict):
                # 图/视频生成成功时一定带 url；全 None 说明后端吞了异常
                if all(v is None for v in content.values()):
                    return f"upstream returned empty content: {body}"
            return None
        detail = body.get("detail") if isinstance(body, dict) else body
        if detail:
            return f"upstream {status}: {detail}"
        return f"upstream {status}: {body}"

    # ---------------------------------------------------------------- token
    def forge_token(self, content: str | None = None) -> dict:
        """POST /api/v3/token —— 服务端不校验 content/hash，任意值即发合法 JWT。

        JWT 载荷: {"unique": <uuid>, "app": "prox_app", "exp": <now+180s>}
        """
        payload = {
            "content": content or f"picgo-{int(time.time() * 1000)}",
            "hash": hashlib.sha256(b"picgo").hexdigest(),
        }
        status, body = self._json("POST", "api/v3/token", json=payload)
        if status != 200 or "access_token" not in body:
            raise UpstreamDead(f"token endpoint failed: {status} {body}")
        body["_issued_at"] = int(time.time())
        return body

    def sha256(self, content: str) -> dict:
        status, body = self._json("GET", "api/sha256", params={"content": content})
        if status != 200:
            raise UpstreamDead(f"sha256 failed: {status} {body}")
        return body

    # ---------------------------------------------------------------- 元数据面
    def style_list(self) -> dict:
        """GET /api/v1.0/style_list —— 文生图风格（含 prompt / negative_prompt 模板）。"""
        status, body = self._json("GET", "api/v1.0/style_list")
        if status != 200:
            raise UpstreamDead(f"style_list failed: {status} {body}")
        return body.get("content", body)

    def transfer_styles(self) -> list[str]:
        """GET /api/v1/transfer/list_styles —— 图生图风格名列表。"""
        status, body = self._json("GET", "api/v1/transfer/list_styles")
        if status != 200:
            raise UpstreamDead(f"transfer/list_styles failed: {status} {body}")
        return body.get("data", [])

    def transfer_config(self) -> dict:
        """GET /api/v1/transfer/config —— 全量风格配置 + 上游算力地址（现全部失效）。"""
        status, body = self._json("GET", "api/v1/transfer/config")
        if status != 200:
            raise UpstreamDead(f"transfer/config failed: {status} {body}")
        return body

    def transfer_style(self, name: str) -> dict:
        """GET /api/v1/transfer/style?style_name= —— 单个风格展开。"""
        status, body = self._json("GET", "api/v1/transfer/style", params={"style_name": name})
        if status != 200:
            raise UpstreamDead(f"transfer/style failed: {status} {body}")
        return body

    # ---------------------------------------------------------------- 生成面
    def txt2img(
        self,
        prompt: str,
        negative_prompt: str = "",
        style_name: str = "",
        width: int = 512,
        height: int = 512,
        steps: int = 20,
        cfg_scale: int = 7,
        seed: int = -1,
        token: str | None = None,
    ) -> dict:
        """POST /api/v2.0/generator/txt2img（GenImageService，app 实走路径）。"""
        headers = {}
        if token:
            headers["Authorization"] = token
        payload = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg_scale,
            "seed": seed,
        }
        if style_name:
            payload["style_name"] = style_name
        status, body = self._json(
            "POST",
            "api/v2.0/generator/txt2img",
            params={"translate": "false", "is_dev": "false"},
            json=payload,
            headers=headers,
        )
        reason = self._dead_reason(status, body)
        if reason:
            raise UpstreamDead(reason)
        return body

    def transfer(
        self,
        image_bytes: bytes,
        filename: str = "image.jpg",
        style: str = "anime",
        token: str | None = None,
        faceswap: bool = False,
        controlnet: bool = False,
        app: str = "prox_app",
        version: str = "2.0.8",
    ) -> dict:
        """POST /api/v2.0/transfer?style=&is_dev=&app=&version=&use_b64=&use_auth=（multipart）。"""
        headers = {}
        if token:
            headers["authorization"] = token
        files = {"file": (filename, image_bytes, "image/jpeg")}
        data = {
            "faceswap": "true" if faceswap else "false",
            "controlnet": "true" if controlnet else "false",
        }
        status, body = self._json(
            "POST",
            "api/v2.0/transfer",
            params={
                "style": style,
                "is_dev": "false",
                "app": app,
                "version": version,
                "use_b64": "false",
                "use_auth": "true",
            },
            files=files,
            data=data,
            headers=headers,
        )
        reason = self._dead_reason(status, body)
        if reason:
            raise UpstreamDead(reason)
        return body

    def video_generate(
        self, image_bytes: bytes, filename: str = "image.jpg", prompt: str = "animated video"
    ) -> dict:
        """POST /api/v1/video-generate（multipart: image + prompt）。

        注意：实测恒返回 41s + 同一模板 wedding_template.mp4，与输入无关，
        且产物 URL 指向已 503 的 MinIO(9000)。保留仅为协议完整性。
        """
        files = {"image": (filename, image_bytes, "image/jpeg")}
        status, body = self._json(
            "POST", "api/v1/video-generate", files=files, data={"prompt": prompt}
        )
        reason = self._dead_reason(status, body)
        if reason:
            raise UpstreamDead(reason)
        return body


def upstream_matrix(timeout: int = 12) -> list[dict]:
    """只读存活探测：逐个命中后端根路径，返回证据行。"""
    targets = [
        ("genimage-8005", BASE_GENIMAGE + "/openapi.json"),
        ("app-proxglobal", BASE_APP + "/"),
        ("app-static", BASE_APP + "/app-data/video-data.json"),
        ("start-procyoni", BASE_START + "/"),
        ("ob-5000", BASE_OB + "/"),
        ("yearbook-8006", BASE_YEARBOOK + "/"),
        ("minio-9000", "http://69.10.54.174:9000/data/wedding_template.mp4"),
        ("chatgpt-proxglobal", "https://chatgpt.proxglobal.co/"),
    ]
    rows = []
    for name, url in targets:
        started = time.time()
        try:
            resp = requests.get(url, timeout=timeout)
            rows.append(
                {
                    "target": name,
                    "url": url,
                    "http": resp.status_code,
                    "bytes": len(resp.content),
                    "elapsed_ms": int((time.time() - started) * 1000),
                }
            )
        except Exception as exc:  # noqa: BLE001 - 存活探测需要吞掉所有网络异常
            rows.append(
                {
                    "target": name,
                    "url": url,
                    "http": None,
                    "error": type(exc).__name__,
                    "elapsed_ms": int((time.time() - started) * 1000),
                }
            )
    return rows
