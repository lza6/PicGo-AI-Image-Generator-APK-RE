"""PicGo v2.0.8 本地网关。

定位：**协议复刻**网关。协议面（token / 风格 / 配置）真实可用；
生成面（txt2img / img2img / video）在当前时点上游算力已全部销毁，
一律返回结构化 502 upstream_dead，绝不伪造图片。

启动:
    python -m uvicorn gateway.server:app --host 127.0.0.1 --port 8985
演示页:
    open http://127.0.0.1:8985/
"""

from __future__ import annotations

import os
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .picgo_client import PicGoClient, UpstreamDead, upstream_matrix

app = FastAPI(title="PicGo v2.0.8 协议网关", version="1.0.0")
client = PicGoClient()

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_IMAGE_BYTES = 12 * 1024 * 1024

# 可选入站鉴权：设置 PICGO_GATEWAY_KEY 后，/v1/* 与 /picgo/* 必须带 Bearer 该值。
# 未设置时不校验（仅建议在 127.0.0.1 绑定下这样跑）。
GATEWAY_KEY = os.environ.get("PICGO_GATEWAY_KEY", "").strip()
OPEN_PATHS = {"/", "/health", "/docs", "/openapi.json", "/upstream/matrix"}


class GatewayAuth(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if GATEWAY_KEY and request.url.path not in OPEN_PATHS:
            header = request.headers.get("authorization", "")
            if header.removeprefix("Bearer ").strip() != GATEWAY_KEY:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"type": "unauthorized", "message": "需要 Bearer <PICGO_GATEWAY_KEY>"}},
                )
        return await call_next(request)


app.add_middleware(GatewayAuth)

# 本地风格名 -> 上游 txt2img 风格（无映射即直传）
CAPABILITIES = [
    {"id": "picgo-txt2img", "kind": "image", "upstream": "api/v2.0/generator/txt2img", "status": "upstream_dead"},
    {"id": "picgo-img2img", "kind": "image", "upstream": "api/v2.0/transfer", "status": "upstream_dead"},
    {"id": "picgo-video", "kind": "video", "upstream": "api/v1/video-generate", "status": "template_only"},
    {"id": "picgo-styles", "kind": "meta", "upstream": "api/v1.0/style_list", "status": "live"},
    {"id": "picgo-transfer-config", "kind": "meta", "upstream": "api/v1/transfer/config", "status": "live"},
    {"id": "picgo-token", "kind": "auth", "upstream": "api/v3/token", "status": "live_but_unchecked"},
]


def _dead(exc: UpstreamDead) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "type": "upstream_dead",
                "code": "picgo_upstream_dead",
                "message": str(exc),
                "hint": "上游算力（9 个 runpod 代理 / MinIO）已销毁，见 docs/UPSTREAM-STATUS.md",
            }
        },
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "gateway": "picgo208", "upstream": "69.10.54.174:8005"}


@app.get("/upstream/matrix")
def matrix() -> dict:
    return {"generated_at": int(time.time()), "rows": upstream_matrix()}


@app.get("/v1/models")
def models() -> dict:
    created = int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": cap["id"],
                "object": "model",
                "created": created,
                "owned_by": "picgo-proxglobal",
                "metadata": {"kind": cap["kind"], "upstream": cap["upstream"], "status": cap["status"]},
            }
            for cap in CAPABILITIES
        ],
    }


@app.post("/picgo/token")
def picgo_token() -> dict:
    try:
        return client.forge_token()
    except UpstreamDead as exc:
        return _dead(exc)


@app.get("/picgo/styles")
def picgo_styles(kind: str = "txt2img") -> dict:
    try:
        if kind == "img2img":
            return {"kind": "img2img", "names": client.transfer_styles()}
        return {"kind": "txt2img", **client.style_list()}
    except UpstreamDead as exc:
        return _dead(exc)


@app.get("/picgo/config")
def picgo_config() -> dict:
    try:
        return client.transfer_config()
    except UpstreamDead as exc:
        return _dead(exc)


@app.post("/picgo/txt2img")
def picgo_txt2img(
    prompt: str = Form(...),
    negative_prompt: str = Form(""),
    style_name: str = Form(""),
    width: int = Form(512),
    height: int = Form(512),
    steps: int = Form(20),
    cfg_scale: int = Form(7),
    seed: int = Form(-1),
) -> JSONResponse:
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    if not (256 <= width <= 1024 and 256 <= height <= 1024):
        raise HTTPException(status_code=400, detail="width/height 需在 256..1024")
    try:
        token = client.forge_token()["access_token"]
        body = client.txt2img(
            prompt=prompt,
            negative_prompt=negative_prompt,
            style_name=style_name,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            token=token,
        )
        return JSONResponse({"msg": body.get("msg"), "content": body.get("content")})
    except UpstreamDead as exc:
        return _dead(exc)


@app.post("/picgo/transfer")
async def picgo_transfer(
    file: UploadFile = File(...),
    style: str = Form("anime"),
    faceswap: bool = Form(False),
    controlnet: bool = Form(False),
) -> JSONResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="file 为空")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 12MB")
    try:
        token = client.forge_token()["access_token"]
        body = client.transfer(
            raw,
            filename=file.filename or "image.jpg",
            style=style,
            token=token,
            faceswap=faceswap,
            controlnet=controlnet,
        )
        return JSONResponse({"msg": body.get("msg"), "content": body.get("content")})
    except UpstreamDead as exc:
        return _dead(exc)


# ------------------------------------------------------- OpenAI 兼容面
@app.post("/v1/images/generations")
def openai_generations(payload: dict) -> JSONResponse:
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    style = payload.get("style") or payload.get("style_name") or ""
    size = str(payload.get("size") or "512x512")
    try:
        width, height = (int(x) for x in size.lower().split("x", 1))
    except ValueError:
        width = height = 512
    try:
        token = client.forge_token()["access_token"]
        body = client.txt2img(
            prompt=prompt,
            negative_prompt=payload.get("negative_prompt", ""),
            style_name=style,
            width=width,
            height=height,
            steps=int(payload.get("steps", 20)),
            cfg_scale=int(payload.get("cfg_scale", 7)),
            seed=int(payload.get("seed", -1)),
            token=token,
        )
        content = body.get("content") or {}
        return JSONResponse(
            {
                "created": int(time.time()),
                "data": [{"url": content.get("image_url"), "b64_json": None}],
                "picgo": {"msg": body.get("msg")},
            }
        )
    except UpstreamDead as exc:
        return _dead(exc)


@app.post("/v1/images/edits")
async def openai_edits(
    image: UploadFile = File(...),
    prompt: str = Form(""),
    style: str = Form("anime"),
) -> JSONResponse:
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="image 为空")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 12MB")
    try:
        token = client.forge_token()["access_token"]
        body = client.transfer(
            raw, filename=image.filename or "image.jpg", style=style, token=token
        )
        content = body.get("content") or {}
        return JSONResponse(
            {
                "created": int(time.time()),
                "data": [
                    {
                        "url": content.get("image_url") or content.get("url"),
                        "b64_json": None,
                    }
                ],
                "request_id": str(uuid.uuid4()),
            }
        )
    except UpstreamDead as exc:
        return _dead(exc)


@app.get("/", response_class=HTMLResponse)
def demo() -> str:
    with open(os.path.join(HERE, "demo.html"), encoding="utf-8") as fh:
        return fh.read()
