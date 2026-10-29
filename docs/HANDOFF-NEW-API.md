# PicGo AI Image Generator v2.0.8 → new-api 对接指南

> 交接文档（自包含）。交付方已完成：APK 逆向、协议还原、本地网关、demo 页、单点冒烟、GitHub 归档。
> **对接动作由你自己/另开会话执行**，本文给出可直接照做的步骤、判据和红线。
>
> 仓库：https://github.com/lza6/PicGo-AI-Image-Generator-APK-RE （public，默认分支 `main`）
> 本地：`D:/apk-analysis/picgo208/`（网关 + 脚本 + 证据 + 文档全集）

---

## 0. 一页结论（先看这个，再决定要不要动手）

| 判断 | 事实 | 证据 |
|---|---|---|
| **协议 100% 还原** | token 签发 / 14 文生图风格 / 50 图生图风格 / 上游算力配置 全部可复现 | `evidence/smoke_20261029T214612Z.json` |
| **生成能力 0** | 9 个 runpod SD-WebUI 代理全 404；`txt2img` 返回 `image_url:null`；`transfer` 返回 202 `{"detail":"Error!"}` | 同上 + `evidence/upstream_matrix_*.json` |
| **结果存储已下线** | MinIO `69.10.54.174:9000` → 503，video 端点给的 URL 打不开 | 同上 |
| **不能直接挂渠道** | 挂上去用户请求 100% 失败 | — |

**所以：现在唯一值得做的对接是「路线 C：自建算力接管」。**
路线 A（网关直连）是给"上游哪天复活"预留的开关，10 秒就能切；路线 B 必须等路线 C 落地。

---

## 1. 30 秒自己复检（不信我的结论就先跑这三条）

```bash
cd D:/apk-analysis/picgo208
python scripts/probe_upstreams.py     # 期望：存活 2/17（只剩 8005 FastAPI 与 ob-5000）
python scripts/smoke.py               # 期望：7/7 PASS（协议面过 / 生成面 upstream_dead）
curl -s -m 30 -X POST "http://69.10.54.174:8005/api/v2.0/generator/txt2img" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"a red apple","negative_prompt":"blurry","style_name":"realistic"}'
# 期望：{"msg":"Finish","content":{"image_url":null}}   ← image_url 是 null 就是死的
```

判活口诀：**`image_url` 有值 = 活了，可以立刻走路线 A；`null` 或 `Error!` = 继续走路线 C。**

---

## 2. 路线 A —— 网关直连（上游复活 / 或你已经接好自建算力之后）

### 2.1 启动网关

```bash
cd D:/apk-analysis/picgo208
pip install fastapi uvicorn requests
# 建议绑定内网/回环 + 开入站鉴权
PICGO_GATEWAY_KEY=<自己设一个强口令> \
python -m uvicorn gateway.server:app --host 0.0.0.0 --port 8985
```

### 2.2 网关对外接口

| 用途 | 端点 | 说明 |
|---|---|---|
| 健康 | `GET /health` | 免鉴权 |
| 能力清单 | `GET /v1/models` | 每个模型带 `metadata.status`（`live` / `upstream_dead` / `template_only`） |
| 文生图 | `POST /v1/images/generations` | OpenAI 形状：`{"prompt":"…","style":"realistic","size":"512x512"}` |
| 图生图 | `POST /v1/images/edits` | multipart：`image` + `style` + `prompt` |
| 原生风格 | `GET /picgo/styles?kind=txt2img\|img2img` | 实时打上游 |
| 原生配置 | `GET /picgo/config` | 50 风格 + 上游算力地址 |
| 原生签发 | `POST /picgo/token` | 任意 body 签 JWT（上游不校验，见 §7 红线） |
| 存活矩阵 | `GET /upstream/matrix` | 免鉴权，只读探测 |
| 演示页 | `GET /` | 免鉴权；若开了鉴权，页面底部填 Gateway Key 即可 |

鉴权：设了 `PICGO_GATEWAY_KEY` 后，除 `/`、`/health`、`/docs`、`/openapi.json`、`/upstream/matrix` 外，
所有端点都要 `Authorization: Bearer <key>`。

### 2.3 new-api 侧填表（**只有 §1 复检通过才执行**）

| 字段 | 值 |
|---|---|
| 渠道类型 | **OpenAI 兼容（type 1）** |
| Base URL | `http://<网关主机>:8985`（new-api 与网关同机就用 `127.0.0.1`） |
| 密钥 | 你在 `PICGO_GATEWAY_KEY` 里设的那个值（未设则随便填非空串） |
| 模型名 | `picgo-txt2img`（图生图另配 `picgo-img2img`） |
| 分组/倍率 | 上游是 coin 制，接进来按你自己的定价换算，别透传 coin |
| 超时 | 上游连接 60s / 读 2min，new-api 侧建议 ≥ 180s |

### 2.4 错误映射（网关已经返回结构化错误，new-api 侧照这个映射）

```json
HTTP 502
{"error":{"type":"upstream_dead","code":"picgo_upstream_dead",
          "message":"upstream returned empty content: {'msg': 'Finish', 'content': {'image_url': None}}",
          "hint":"上游算力（9 个 runpod 代理 / MinIO）已销毁，见 docs/UPSTREAM-STATUS.md"}}
```

| 网关 | new-api 应该表现 |
|---|---|
| 502 `picgo_upstream_dead` | 渠道标记异常 / 自动禁用该渠道，不要当成用户侧错误扣费 |
| 401 `unauthorized` | 配置问题（key 填错），日志告警 |
| 400/413 | 透传给用户（prompt 空 / 图片超 12MB） |

---

## 3. 路线 B —— 独立渠道类型（Go 原生，等路线 C 通了再做）

不需要照抄任何数字，先自查渠道类型号：

```bash
cd <new-api 仓库> && rg -n "ChannelType\w+\s*=\s*[0-9]+" constant/ | tail -20
```

必须实现的东西（按 new-api 现有惯例）：

1. `constant/channel.go` 加渠道类型常量 + 名称映射 + 默认 base_url；
2. `relay/channel/<name>/adaptor.go`（`Init`/`GetRequestURL`/`SetupRequestHeader`/`ConvertImageRequest`/`DoResponse`）；
3. `relay/channel/<name>/dto.go`（请求/响应结构，注意 new-api 里 `*dto.Usage` 断言陷阱 ——
   历史踩坑：`DoResponse` 返回 `dto.Usage` 值而非指针会 panic，见 new-api 提交 `ebe27fd59`）；
4. `web/` 里加渠道图标与表单（可选）；
5. 计费换算：coin → quota，别直接透传。

**验收**：`/v1/images/generations` 走渠道返回真实 URL；失败返回渠道错误而非 500。

---

## 4. 路线 C —— 自建算力接管（**推荐，唯一能真出图的路径**）

### 4.1 原理

这个 App 的"AI 能力"本质是 **一层 SD-WebUI 转发 + 风格 prompt 模板**：

* 上游 3 个 runpod 实例 = `sd-webui` 的 `/sdapi/v1/img2img`；
* 50 个图生图风格的 prompt / negative_prompt / denoising_strength / sampler_index **全在活着的配置里**；
* 我们已把它们导出：`D:/apk-analysis/picgo208/exports/styles_export.json`。

也就是说：**模型可以换、算力可以自建，风格配方是现成的。**

### 4.2 落地步骤

1. 起一台带 `--api` 的 SD-WebUI（1.5/SDXL 均可），装 4 个 LoRA：
   `more_details`、`lego_lora`、`ghibli_style_offset`、`wanostyle_2_offset`（缺了只掉画风不报错）。
   采样器只需 `DPM++ 2M Karras`、`Euler a` 两种；基准档 `512×512`，大图档 `768`。
2. 用 `exports/styles_export.json` 的 `img2img_styles[<style>]` 填模板。
3. 改网关的转发目标（**一处改动**）：
   `gateway/picgo_client.py` 的 `transfer()` 里
   `self._json("POST", "api/v2.0/transfer", ...)` → 换成直连你自己的
   `http://<sd-webui>/sdapi/v1/img2img`，请求体按 §4.3；`_DEAD_MARKERS` 与 `_dead_reason()` 不用动。
4. 出图后走路线 A 挂进 new-api。

### 4.3 上游真实请求体（照抄即可，静态确认自 `transfer/config` + `RemoteAPI`）

```http
POST http://<sd-webui>:7860/sdapi/v1/img2img
Content-Type: application/json

{
  "init_images": ["<在网关里把上传图 base64，去掉 data: 前缀>"],
  "prompt":       "<styles[style].prompt>",
  "negative_prompt": "<styles[style].negative_prompt>",
  "denoising_strength": 0.55,
  "sampler_index": "DPM++ 2M Karras",
  "steps": 20,
  "cfg_scale": 10,
  "seed": -1,
  "width": 512,
  "height": 512
}
```

响应取 `images[0]`（base64）→ 自己落盘/上传对象存储 → 回 URL 给 new-api。

### 4.4 文生图（14 个风格，可直接用）

`exports/styles_export.json` 的 `txt2img_styles` 每条都带完整 `prompt` + `negative_prompt`，
对应上游 `/sdapi/v1/txt2img`，参数 `steps=20 / cfg_scale=10 / 512×512`。

### 4.5 特例（要做完整功能才需要）

| 能力 | 上游实现 | 说明 |
|---|---|---|
| 换脸 | `…/api/v1.0/face-swaper/single` | 独立微服务，不在 SD 里 |
| 扩图 | `…/api/v1.0/add_filter` | 同上，multipart `file` + `ratio`（如 `2:3`） |
| 特化风格 | `_anime_naruto` / `_anime_onepiece` | 用了 controlnet 的独立 pod |

---

## 5. 验收清单（逐条打勾才算完成）

- [ ] `python scripts/smoke.py` 7/7 PASS（协议面没问题）
- [ ] 路线 A：`curl /v1/images/generations` 返回 `data[0].url` 且图片能打开
- [ ] 路线 A：故意传空 prompt → 400；传 >12MB 图 → 413
- [ ] 网关开了 `PICGO_GATEWAY_KEY` 时，无 key 401 / 有 key 200
- [ ] 演示页浏览器控制台 **0 error**（生成失败时那一条 502 是预期的）
- [ ] new-api 侧：渠道测试通过 → 发 3 张图 → 余额扣减正确 → 失败时渠道被标记而不是扣费
- [ ] 不把 `upstream_dead` 的错误算成用户额度

---

## 6. 回滚

* 网关是独立进程，不启动即等于不存在；`kill` 掉 uvicorn 就完成回滚。
* new-api 侧只需删除/禁用该渠道，无数据库迁移、无 schema 变更。
* 全部交付文件集中在 `D:/apk-analysis/picgo208/`，删目录即恢复原状。

---

## 7. 红线（后续会话必须继续遵守）

1. **禁止**使用 APK 里 Firebase Remote Config 的 `config_api_key`（**294 个 OpenAI `sk-` key**）、
   `config_api_key_gemini`（9 个 Gemini key）发起任何真实请求 —— 那是第三方付费凭证。
   仓库里已脱敏，`rc.json` 已 `gitignore`。
2. **禁止** `PUT /api/v1/transfer/style`、`PUT /api/v1/transfer/config`（会改写上游线上配置）。
3. **禁止**对 `199.231.188.59:5000/api`（Basic 认证面）做凭据爆破。
4. 上游仍是活资产：探测只做**单点只读**，不压测、不并发。

---

## 8. 给对接会话的启动 prompt（复制粘贴即可）

```text
你的任务：把 PicGo v2.0.8 的本地网关接进 new-api（我自己执行，你只做实现与验证）。

上下文（自包含）：
- 交付仓库：https://github.com/lza6/PicGo-AI-Image-Generator-APK-RE （public, main）
- 本地工作目录：D:/apk-analysis/picgo208/
- 网关：gateway/server.py（FastAPI，:8985，OpenAI 兼容 /v1/images/generations + /v1/images/edits，
  原生 /picgo/*，可选入站鉴权 PICGO_GATEWAY_KEY）
- 客户端：gateway/picgo_client.py（协议全量：token/风格/配置/txt2img/img2img/video）
- 对接指南：D:/apk-analysis/picgo208/docs/NEW-API-INTEGRATION.md（三条路线）
- 存活证据：evidence/smoke_*.json、evidence/upstream_matrix_*.json

已知事实（不要重新推翻，除非你复检发现相反证据）：
- 上游 runpod 算力 9/9 全 404 → 当前零生成能力，生成端点返回 502 picgo_upstream_dead
- 协议面（token 签发 / 14+50 风格 / 配置）全部 200 可用
- token 端点不校验请求内容，任意 body 签发 JWT（TTL 180s）；生成端点带不带都一样 → token 不是闸门

先做这三件事再动手：
1. 跑 python scripts/smoke.py，确认 7/7 PASS
2. 跑 curl 打一次 /v1/images/generations，确认当前是 502 upstream_dead
3. 读 docs/NEW-API-INTEGRATION.md 第 1、4 节，跟我确认走哪条路线

红线：
- 不许用 APK Firebase RC 里的第三方 OpenAI/Gemini key 做任何真实调用
- 不许对上游做写操作（PUT /api/v1/transfer/*）、不许爆破、不许压测
- 不许把"上游已死"包装成"已接好"

交付要求：真实跑通的命令 + 输出；未验证项标"待验证"。
```

---

## 9. 附录：端点速查

### 9.1 活着的数据面（`http://69.10.54.174:8005`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1.0/style_list` | 14 个文生图风格 + prompt 模板 |
| GET | `/api/v1/transfer/list_styles` | 50 个图生图风格名 |
| GET | `/api/v1/transfer/config` | 全量配置（含失效的算力地址） |
| GET | `/api/v1/transfer/style?style_name=` | 单风格展开 |
| GET | `/api/sha256?content=` | 服务端 sha256 |
| POST | `/api/v3/token` | 任意 body 签发 JWT |
| PATCH | `/openapi.json`、`/docs` | FastAPI 自描述（40 端点全览） |

### 9.2 已死的生成面（保留协议，全部 `upstream_dead`）

`POST /api/v2.0/generator/txt2img`、`/api/v3/txt2img`、`/api/v3/txt2img-turbo`、
`/api/v2.0/transfer`（及 v1.0/v1.1/v3/turbo/ios 变体）、`/api/v3/img2img`、
`/api/v1/aipaint/img2img`、`/api/v1/wallpaper/img2img`、`/api/v1/video-generate`（41s 恒返模板）、
`/api/v1/expand`（`Stage 1 failed: API returned 404`）、`qr_art` 系列、
`/api/v1.0/aishop/generator`、`/api/v1.0/aiavatar/generator`。

### 9.3 前端风格清单（前 20，全集见 exports/styles_export.json）

`pawpatrol, disney, deadpool, cartoon, anime, halloween, barbie, lego, popart, vangogh,
halloween_beetlejuice_makeup, paw_beetlejuice_makeup, halloween_wednsday_makeup,
halloween_hogward_wizard, halloween_orgreen_witch, halloween_scary_d3adpool,
halloween_scary_wo1verine, halloween_thenun, halloween_makeup_scary, halloween_makeup_beautiful …`

### 9.4 关键文件索引

| 文件 | 用途 |
|---|---|
| `gateway/server.py` | 网关本体（改这里做鉴权/路由） |
| `gateway/picgo_client.py` | 协议层（改这里换算力目标） |
| `gateway/demo.html` | 演示页（支持填入 Gateway Key） |
| `scripts/smoke.py` | 7 项单点冒烟 |
| `scripts/probe_upstreams.py` | 17 目标存活矩阵 |
| `scripts/export_styles.py` | 重新导出风格模板 |
| `docs/PROTOCOL.md` | 协议还原全报告 |
| `docs/UPSTREAM-STATUS.md` | 存活矩阵 + 证据 |
| `exports/styles_export.json` | 50 + 14 条风格模板（自建算力直接可用） |
