# PicGo v2.0.8 → new-api 对接指南

> 面向"另一个会话来执行接入"的自包含交接文档。
> 结论先行：**本轮不可接入**。下面给出可执行的三条路线，路线 C 是唯一能真正拿到出图能力的方案。

---

## 0. 结论与证据（截至 2026-10-29）

| 判断 | 证据 |
|---|---|
| 上游生成算力全灭 | 9 个 runpod 代理全 404；`txt2img` 返回 `{"msg":"Finish","content":{"image_url":null}}`；`transfer` 返回 202 `{"detail":"Error!"}`（`evidence/smoke_*.json`） |
| 结果存储已下线 | MinIO `69.10.54.174:9000` 503，video 端点返回的 URL 打不开 |
| 数据面仍可用 | `/api/v1.0/style_list`(14)、`/api/v1/transfer/list_styles`(50)、`/api/v1/transfer/config`(50 风格) 全部 200 |
| token 不是闸门 | `POST /api/v3/token` 任意 body 签发 JWT，TTL 180s；生成端点带不带都同样失败 |

**因此：如果直接把本渠道挂进 new-api，用户请求会 100% 失败。不要接。**

---

## 1. 路线 A —— 网关直连（上游复活当天即可用，零改造）

本地网关已经把协议封好，OpenAI 兼容：

```bash
cd D:/apk-analysis/picgo208
python -m uvicorn gateway.server:app --host 0.0.0.0 --port 8985
```

| 用途 | 端点 |
|---|---|
| 文生图 | `POST /v1/images/generations`（`{"prompt":"…","style":"anime","size":"512x512"}`） |
| 图生图 | `POST /v1/images/edits`（multipart：`image` + `style` + `prompt`） |
| 协议面 | `GET /picgo/styles?kind=txt2img|img2img`、`GET /picgo/config`、`POST /picgo/token` |
| 健康 | `GET /health`、`GET /upstream/matrix` |

new-api 侧（**仅当 `GET /v1/images/generations` 不再返回 502 时才执行**）：

| 字段 | 值 |
|---|---|
| 渠道类型 | OpenAI 兼容（type 1） |
| Base URL | `http://<网关主机>:8985` |
| 密钥 | 任意非空字符串（网关不校验入站 key；如需鉴权请自行加 `GATEWAY_API_KEY`） |
| 模型 | `picgo-txt2img`（列表见 `GET /v1/models`） |

失败时的响应契约（供 new-api 侧做错误映射）：

```json
HTTP 502
{"error":{"type":"upstream_dead","code":"picgo_upstream_dead","message":"…","hint":"…"}}
```

**验收**：`curl -s -X POST http://127.0.0.1:8985/v1/images/generations -H 'Content-Type: application/json' -d '{"prompt":"a red apple"}'` —— 复活后应返回 `data[0].url`。

---

## 2. 路线 B —— 独立渠道类型（Go 原生实现）

需要一个当前**不存在**的能力（出图），所以只有在路线 C 落地后才值得做。要点：

* 建议渠道类型号在接入时用 `grep -rn "ChannelType.*= [0-9]" constant/` 现查，不要照抄本文档的数字。
* 必须实现：`provider` 元数据、`/v1/images/generations` 与 `/v1/images/edits` 两条 relay、错误码映射（`upstream_dead` → 503/`channel_error`）、超时（上游 60s 连接 / 2min 读）。
* 计费：上游是 coin 制，接进来要换算成 new-api 的 quota，别直接透传 coin。

---

## 3. 路线 C —— 自建算力接管（**推荐，唯一能出图的路径**）

上游的实现本质就是**一层 SD-WebUI 转发 + 风格 prompt 模板**。模板全在活着的 config 里，导出即可自持：

```bash
python scripts/export_styles.py     # → exports/styles_export.json（50 img2img + 14 txt2img 模板）
```

### 3.1 上游 img2img 的真实语义（静态确认）

```http
POST http://<sd-webui>/sdapi/v1/img2img
{
  "init_images": ["<base64>"],
  "prompt": "<style.prompt> + 用户输入?",
  "negative_prompt": "<style.negative_prompt>",
  "denoising_strength": 0.55,
  "sampler_index": "DPM++ 2M Karras",
  "steps": 20,
  "cfg_scale": 10,
  "width": 512, "height": 512
}
```

* 上游是 **3 个 SD-WebUI 实例轮询**（`…-8040/-8041/-8042`），宽 512（大模型档 768）。
* 采样器只有两种：`DPM++ 2M Karras`、`Euler a`。
* 4 个 LoRA 依赖：`more_details`、`lego_lora`、`ghibli_style_offset`、`wanostyle_2_offset`（自建时需自备权重，缺失只会掉画风不会报错）。
* 特例：`STYLE_USE_CONTROLNET` 里 `_anime_naruto` / `_anime_onepiece` 走独立 pod；`SERVICE_FACESWAP`(`/api/v1.0/face-swaper/single`)、`SERVICE_BLENDING`(`/api/v1.0/add_filter`) 是两条独立微服务。

### 3.2 落地步骤

1. 起一个 SD-WebUI（`--api`），装 `more_details` 等 4 个 LoRA。
2. 用 `exports/styles_export.json` 的 `img2img_styles[*]` 在网关里做模板填充（网关里 `gateway/picgo_client.py` 的 `transfer()` 只差把 `service_urls` 指向你自己的 WebUI，把「请求上游 8005」换成「直连 WebUI」）。
3. 需要文生图就用 `txt2img_styles`（14 条含完整 prompt/negative）。
4. 出图后再走路线 A 挂进 new-api。

**验收**：任意一张 512×512 输入 + `style=pawpatrol` → WebUI 返回 base64 → 网关落盘/回 URL，端到端 < 30s。

---

## 4. 红线（必须在后续会话继续遵守）

1. **不要使用** APK 的 Firebase Remote Config 里的 `config_api_key`（294 个 OpenAI `sk-` key）/ `config_api_key_gemini`（9 个 Gemini key）做任何真实调用 —— 第三方付费凭证。
2. **不要** `PUT /api/v1/transfer/style`、`PUT /api/v1/transfer/config`（会改写上游线上配置）。
3. **不要**对 `199.231.188.59:5000/api`（Basic 认证面）做凭据爆破。
4. 上游还是活的资产，探测一律单点只读，不要压测。

---

## 5. 回滚

本地全新增文件（`D:/apk-analysis/picgo208/gateway/`、`scripts/`、`docs/`），未触碰 new-api 仓库任何代码 → 回滚 = 不启动网关、不配置渠道。
