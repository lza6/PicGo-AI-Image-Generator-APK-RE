# 上游存活状态（2026-10-29）

> 复现命令：
> ```bash
> python scripts/probe_upstreams.py     # 17 个目标，每个只打一次
> python scripts/smoke.py               # 协议面 + 生成面单点冒烟
> ```
> 原始证据：`evidence/upstream_matrix_20261029T214547Z.json`、`evidence/smoke_20261029T214612Z.json`

## 1. 主机矩阵

| 目标 | 地址 | HTTP | 字节 | 判定 |
|---|---|---|---|---|
| genimage-8005 | `http://69.10.54.174:8005/openapi.json` | 200 | 33,738 | **活**（FastAPI，40 端点） |
| ob-5000 | `http://199.231.188.59:5000/now/v1/` | 200 | 66 | **活**（`status:ok, db:connected`），但仅数据面 |
| start-procyoni | `http://art12.procyoni.com/` | 200 | 114 | **死** — 停放页 `window.location.href="/lander"` |
| app-proxglobal | `https://ai-art.proxglobal.co/` | 404 | 27,150 | **死** — Cloudflare Not Found |
| app-proxglobal-static | `…/app-data/video-data.json` | 200 | 6,551 | 仅静态托管可用（API 路径全 404） |
| chatgpt-proxglobal | `https://chatgpt.proxglobal.co/` | 404 | 27,150 | **死**（仅 `/gpt/remote-and/...` 静态图 200） |
| yearbook-8006 | `http://69.10.54.174:8006/` | 503 | 0 | **死** |
| minio-9000 | `http://69.10.54.174:9000/` | 503 | 0 | **死**（结果存储下线，导致 video 返回的 URL 必然打不开） |

> 注：本地网络对 `*.proxy.runpod.net` 与 CF 域名偶发 `http=None`（连接层失败），重跑即恢复为 404 —— 两类结果都指向同一结论：**没有任何可用算力**。

## 2. 算力代理（从 `transfer/config` 自动抽取，9 个）

| 目标 | 用途 | HTTP |
|---|---|---|
| `hqhfk2z3uedo3d-8040/8041/8042` `.proxy.runpod.net/sdapi/v1/img2img` | 50 个 img2img 风格的主力 SD-WebUI | 404 / 404 / 404 |
| `1a8nzg21h42bv3-8002/generate_sync/` | `txt2img_turbo` | 404 |
| `6y0prpfn3bat4r-8003/sdapi/v1/img2img` | `DEV.service` | 404 |
| `0ytxkr57sflrex-8002/api/v1.0/face-swaper/single` | 换脸 | 404 |
| `cqgjr1q1r8y3tj-8005/api/v1.0/add_filter` | 扩图 blending | 404 |
| `cg2ml8w6aozvbg-8002/8003/sdapi/v1/img2img` | `_anime_naruto` / `_anime_onepiece` controlnet | 404 / 404 |

**结论：9/9 全 404（空响应体 = pod 已销毁，runpod 代理不再解析）。**

## 3. 单点冒烟结果（7/7 符合预期）

| 检查 | 期望 | 实测 | 耗时 |
|---|---|---|---|
| `token(forged)` | ok | 200，JWT `{unique, app:prox_app, exp:+180s}` | 833 ms |
| `sha256` | ok | 200，64 hex | 797 ms |
| `style_list.txt2img` | ok | 200，14 个风格 | 791 ms |
| `style_list.img2img` | ok | 200，50 个风格 | 793 ms |
| `transfer.config` | ok | 200，50 风格 + 3 个上游 URL | 1,225 ms |
| `txt2img` | upstream_dead | 200 但 `content.image_url = null`（异常被吞） | 1,863 ms |
| `img2img(transfer)` | upstream_dead | 202 `{"detail":"Error!"}` | 3,210 ms |

补充单点（未纳入自动冒烟，因耗时 41s）：`POST /api/v1/video-generate` → 200，恒返回
`{"video_output_url":"http://69.10.54.174:9000/data/wedding_template.mp4"}`，**两次不同输入（不同图片 + 不同 prompt）返回同一路径**，且该 URL 503 —— 硬编码模板占位，不是真实生成。

## 4. 结论

1. **协议面完整可复现**：token 签发、风格模板（14 + 50 + 全量配置）、sha256 —— 全部实测 200。
2. **生成面 0 可用**：所有生成端点要么 `202 Error!/Failed`、要么 200 但 `image_url:null`、要么返回死链模板。
3. **不可作为 new-api 渠道入池**。网关保留完整协议，一旦上游算力复活（或把 `service_urls` 指向自建 SD-WebUI）即可直接启用。
4. 上游仍在维护的迹象：Firebase RC `templateVersion 1310`（含 ver228 配置键）持续更新 —— 说明**发版侧还在，算力侧先死了**（典型 runpod 计费停机）。
