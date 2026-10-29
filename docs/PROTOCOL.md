# PicGo AI Image Generator v2.0.8 (Premium) — 协议还原报告

> 静态逆向 + 只读动态探测，2026-10-29。所有结论标注证据等级：`已验证`（实际请求观察）/ `静态确认`（读反编译代码）/ `合理推断`。

## 0. 结论速览

| 维度 | 结论 |
|---|---|
| 应用归因 | 包名伪装成 `com.aiart.aigenerator.aifilter.aieditor`，真实代码包 `com.prox.global.aiart`，发行方 proxglobal / nowtechpro 系 |
| 业务层混淆 | **未混淆**（Kotlin + Hilt + Retrofit + Moshi，Clean Architecture 分层完整可读） |
| 鉴权 | `POST /api/v3/token` **完全不校验请求内容**，任意 body 直接签出合法 JWT（TTL 180s）— `已验证` |
| 生成算力 | **全灭**：9 个 runpod 代理 404、结果存储 MinIO(9000) 503、主 API 域名仅剩静态资源 — `已验证` |
| 可用生成能力 | **0**。文生图/图生图/视频/扩图/换装全部死路 — `已验证` |
| 数据面 | 风格模板 50 条 + 配置 + Firebase Remote Config(111 键) 全部可读 — `已验证` |
| 可否作为 new-api 渠道 | **否**（详见 `NEW-API-INTEGRATION.md`） |

---

## 1. APK 基础信息 `静态确认`

| 项 | 值 |
|---|---|
| 文件 | `PicGo AI Image Generator v2.0.8 (Premium).apk`（93,933,436 B） |
| package | `com.aiart.aigenerator.aifilter.aieditor` |
| 真实代码包 | `com.prox.global.aiart` |
| versionName / Code | 2.0.8 / 202（`AiArt-ver2.0.8_prodRelease`） |
| minSdk / targetSdk / compileSdk | 见 `apktool.yml`；compileSdk 35 |
| 架构 | Kotlin 2.x + Hilt(Dagger) + Retrofit2 + Moshi + Room + Coroutines/Flow |
| dex | 8 个（`classes.dex`…`classes8.dex`，约 40 MB）+ `assets/audience_network.dex` |
| native | `libnms.so`、`libpglarmor.so`、`libapminsighta/b.so`(AppDynamics)、`libucrop.so`、`libtt_ugen_layout.so`(Pangle) 等 — 无自研保护壳，业务逻辑全在 dex |
| 入口 | `com.prox.global.aiart.ui.splash.splash.SplashActivity` → `ui.main.MainActivity` |
| 变现 | Coin(credit) 内购 + 广告聚合（AppLovin MAX / Pangle / InMobi / Fyber / Unity / Vungle / IronSource / DigitalTurbine）+ Qonversion + AppsFlyer |

反编译产物：`apktool_out/`（smali + 资源）、`jadx_out/`（Java）。

---

## 2. 后端矩阵与 Retrofit 实例映射 `静态确认`

`com.prox.global.aiart.data.remote.ServiceGenerator` 构造了 7 个 Retrofit 实例：

| 实例 | baseUrl | 承载的 Service（路径） | 2026-10-29 状态 |
|---|---|---|---|
| `retrofit` | `http://art12.procyoni.com/` | `GetIntroService`(`art-ai/now/intro`)、`AIArtService` | **停放页**（200 但跳 `/lander`） |
| `retrofitApp` | `https://ai-art.proxglobal.co/` | `DataStyleService`(`ai-art/styles/{image,fashion,video}`)、`AITextToImageService`(`ai-art/generate/text-to-image`)、`TransferImgToImgService`(`ai-art/generate/img2img/{gemini,banana}`、`ai-art/image-to-art`)、`AIToolService`(`ai-art/expand`)、`AIVideoService`(`ai-art/generate/video`、`ai-art/video/check/{taskId}`)、`AiFashionService`(`ai-art/fashion/generate`) | **API 全 404**，仅静态资源 200 |
| `retrofitGenImage` | `http://69.10.54.174:8005/` | `GenImageService`(`api/v2.0/generator/txt2img`)、`GenImageV3Service`(`api/v3/txt2img-turbo`)、`GenTokenImageService`(`api/v3/token`)、`GenTokenImageV2Service`(`api/v2.0/token`) | **活**（FastAPI，自带 `/openapi.json`） |
| `retrofitGenYearBook` | `http://69.10.54.174:8006/` | `UploadYearbookService`(`api/v1.0/aiyearbook/upload`) | **503** |
| `retrofitOB` | `http://199.231.188.59:5000/now/v1/` | `DataOBService`(`app-data/video-data.json`) | **活**（Express，`status:ok db:connected`），该 JSON 404 |
| `retrofitGemini` | `https://generativelanguage.googleapis.com/` | `GeminiService`(`v1beta/models/gemini-1.5-flash-latest:generateContent?key=`) | Google 官方，非本应用资产 |
| `retrofitTranslate` | `https://translate.googleapis.com/` | `TranslateService` | Google 官方 |

公共拦截器（`ServiceGenerator` 内联 lambda）：仅补 `Content-Type: application/json` + `Accept: application/json`；`okHttpBuilder` 连接/读超时 60s，`okHttpBuilderImgToImg` 2min 且 HTTP/1.1 单协议。

---

## 3. 鉴权协议 `已验证`

### 3.1 请求

```http
POST http://69.10.54.174:8005/api/v3/token
Content-Type: application/json

{"content": "<任意字符串>", "hash": "<任意字符串>"}
```

后端 schema（`openapi.json` → `TokenSchemaReq`）只要求两字段存在，**不验值**。

### 3.2 响应

```json
{"access_token":"<JWT>","token_type":"bearer"}
```

JWT 载荷（实测解码）：

```json
{"unique":"4c689e02-091d-4b85-972e-dbf683c6d89b","app":"prox_app","exp":<now+180s>}
```

* 签名算法 `HS256`，密钥在服务端；`unique` 由服务端随机生成，请求方无法控制。
* **TTL = 180 秒**，`exp` 与签发时间差恒为 180s（两次不同时间点签发均验证）。
* 生成端点（`/api/v2.0/generator/txt2img`）带不带这个 token 返回完全一致 → **token 目前是装饰品**，不是访问闸门。

### 3.3 另一套头（`retrofitApp` 那批 `ai-art/*` 端点用，宿主已死）

| Header | 语义 | 来源 |
|---|---|---|
| `token` | 上面签出的 `access_token` | `GenTokenImage*Service` |
| `timestamps` | 当前毫秒时间戳 | 客户端本地时间 |
| `type` | 风格类别（`image`/`fashion`/`video`） | 调用方传入 |
| `Authorization` | 部分端点用 `Bearer <token>`；`GeminiService` 走 `?key=` | — |

`RequestToken{content,hash}` 实体 + `key_hash_hmac_sha512`（Remote Config）说明设计意图是 HMAC 签名，但该 v2 token 流程在 2.0.8 里已成死代码（`GetTokenUseCase` 无任何调用方）。

---

## 4. 端点全集（`69.10.54.174:8005`，来自上游 `/openapi.json`）`已验证`

> 这是全应用唯一活着的 API 宿主，共 40 个路由。下表按能力分组，`实测` 列为单独调用一次的真实结果。

### 4.1 元数据（全部可读）

| 方法 | 路径 | 说明 | 实测 |
|---|---|---|---|
| GET | `/api/v1.0/style_list` | 文生图 14 个风格 + 每风格 prompt/negative 模板 | **200** |
| GET | `/api/v1/transfer/list_styles` | 图生图 50 个风格名 | **200** |
| GET | `/api/v1/transfer/config` | 全量风格配置 + 上游算力地址 + CONST | **200** |
| GET | `/api/v1/transfer/style?style_name=` | 单风格展开（prompt/denoise/sampler/服务地址） | **200** |
| PUT | `/api/v1/transfer/style?style_name=` | 改单风格配置 | 未测（写操作） |
| GET/PUT | `/api/v1/transfer/config` | 改全量配置 | 未测（写操作） |
| GET | `/api/sha256?content=` | 服务端 sha256（token 签名辅助） | **200** |
| GET | `/demo_expand` | Swagger 演示表单 | 200 |
| GET | `/r/{content}` | 307 跳 `http://qrart-ai.com/` | 307 |
| GET | `/openapi.json`、`/docs` | FastAPI 自描述 | 200 |

### 4.2 生成（全部 `upstream_dead`）

| 方法 | 路径 | 客户端签名要点 | 实测 |
|---|---|---|---|
| POST | `/api/v2.0/generator/txt2img` | JSON `InputTXT2IMGSchema{prompt,negative_prompt,style_name,steps,cfg_scale,seed,height,width}`；query `translate=false&is_dev=false`；header `Authorization` | **200 `{"msg":"Finish","content":{"image_url":null}}`**（吞异常） |
| POST | `/api/v3/txt2img-turbo` | form：`is_purchase,location,user_session,priority,created_at,style_name`；query `prompt=<必填>` | **500** |
| POST | `/api/v3/txt2img` | form：同上 + `prompt` | **202 `{"detail":"Error!"}`** |
| POST | `/api/v2.0/transfer` | multipart `file` + `controlnet,faceswap`；query `style,is_dev,app,version,use_b64,use_auth`；header `authorization` | **202 `{"detail":"Error!"}`** |
| POST | `/api/v1.0/transfer`、`/api/v1.1/transfer`、`/api/v3/transfer`、`/api/v2.0/transfer_turbo`、`/api/v2.0/transfer_ios` | 同上系列变体 | 202/500 |
| POST | `/api/v3/img2img`、`/api/v1/aipaint/img2img`、`/api/v1/wallpaper/img2img` | multipart `file` + `prompt` | **202 `{"detail":"Failed"}`** |
| POST | `/api/v1.0/generator/txt2img`、`/api/v1.0/aiart/txt2img` | JSON `InputTXT2IMGSchema` / `num_imgs` | **202 `{"detail":"Error!"}`** |
| POST | `/api/v1.0/generator/img2img`、`/api/v2.0/generator/img2img` | `InputTemplate{base64_image,prompt,...}` | 同上 |
| POST | `/api/v1.0/generator/qr_art`、`/api/v2.0/generator/qr_art`、`qr_art_dev` | `QRArtSchema{qr_text_data,art_prompt}` | 同上 |
| POST | `/api/v1.0/aishop/generator`、`/api/v1.0/aiavatar/generator` | 表单 | 同上 |
| POST | `/api/v1/video-generate` | multipart `image` + `prompt`（默认 `animated video`） | **200 但恒返回 `http://69.10.54.174:9000/data/wedding_template.mp4`，41s，与输入无关；该 URL 已 503** |

### 4.3 `ai-art.proxglobal.co` 上那批（宿主已死，仅供协议留存）`静态确认`

| 方法 | 路径 | 头 | 说明 |
|---|---|---|---|
| GET | `/ai-art/styles/image` | `type`,`token`,`timestamps` | 图生图风格列表 |
| GET | `/ai-art/styles/fashion` | 同上 | 时尚风格列表 |
| GET | `/ai-art/styles/video` | 同上 | 视频风格列表 |
| POST | `/ai-art/generate/text-to-image` | `token`,`timestamps` | multipart `style_name`,`text`,`images[]` |
| POST | `/ai-art/generate/img2img/gemini` | `token`,`timestamps` | multipart `style_name`,`images[]` |
| POST | `/ai-art/generate/img2img/banana` | 同上 | Nano-Banana 系列 |
| POST | `/ai-art/image-to-art` | 同上 | 通用图生图 |
| POST | `/ai-art/expand` | 同上 | multipart `image`,`ratio`（2:3 等） |
| POST | `/ai-art/fashion/generate` | 同上 | multipart `image`,`prompt`,`negative_prompt`,`guidance_scale`,`num_inference_steps` |
| POST | `/ai-art/generate/video` | 同上 | multipart `image`,`aspectRatio`,`prompt` |
| GET | `/ai-art/video/check/{taskId}` | 同上 | 视频任务轮询 |

---

## 5. 风格与算力配置（活数据）`已验证`

`GET /api/v1/transfer/config` 顶层键：`CONST` / `STYLES`(50) / `DEV` / `SERVICES_CONTROLNET` / `SERVICE_FACESWAP` / `SERVICE_BLENDING` / `STYLE_USE_CONTROLNET`。

```jsonc
CONST: {
  "width_size": 512, "width_size_large": 768, "style_size_large": [],
  "controlnet": false, "faceswap": false, "HANDLE": false,
  "txt2img_turbo": ["https://1a8nzg21h42bv3-8002.proxy.runpod.net/generate_sync/"],
  "img2img_urls": ["…-8040…/sdapi/v1/img2img", "…-8041…", "…-8042…"]
}
STYLES.anime: {
  "app_name": "Animaker",
  "service_urls": ["…-8040…", "…-8041…", "…-8042…"],
  "prompt": "(8k, super-resolution, masterpiece, best-art, beautiful), (anime style), …",
  "negative_prompt": "dark, low contrast, trim color,sexy, nude",
  "denoising_strength": 0.55,
  "sampler_index": "DPM++ 2M Karras",
  "use_controlnet": false
}
```

* 50 个风格全部指向**同一组 3 个** runpod SD-WebUI 代理（`/sdapi/v1/img2img`）。
* 另有 `SERVICE_FACESWAP`(`…/api/v1.0/face-swaper/single`)、`SERVICE_BLENDING`(`…/api/v1.0/add_filter`)、`STYLE_USE_CONTROLNET`(`_anime_naruto`/`_anime_onepiece`)。
* 文生图 14 风格：`mechanics, league_of_legends, cartoonize, colorized, barbie_doll, sketch, fantasy, fairy, disney, concept, chinese_art, chibi, anime, realistic`（每风格带完整 prompt/negative 模板，可直接复用到自建 SD）。

---

## 6. Firebase Remote Config（可直拉）`已验证`

```http
POST https://firebaseremoteconfig.googleapis.com/v1/projects/ai-art-20bec/namespaces/firebase:fetch?key=AIzaSyCPH9s…（已脱敏）…1VW6w
X-Android-Package: com.aiart.aigenerator.aifilter.aieditor
body: {"app_instance_id":"<任意32位>","app_id":"1:1028603950031:android:5d93b8…（脱敏）", …}
→ 200，111 个键，templateVersion 1310
```

关键键：

| 键 | 内容 | 处理 |
|---|---|---|
| `config_api_key` | **294 个 OpenAI `sk-…3Blbk…` 密钥**（15,877 B） | **仅静态记录，未做任何真实调用**（见 §9 红线） |
| `config_api_key_gemini` / `_test` | 9 个 `AIza…` Gemini 密钥 | 同上 |
| `key_hash_hmac_sha512` | 267 B 疑似 HMAC 密钥串 | 静态记录；v2 token 流程已死，未使用 |
| `config_rate` | 评分弹窗触发规则（越/英/印尼多语） | 变现侧 |
| `config_update_v2` | 强制/可选升级版本码 116–124 | 变现侧 |
| `iap_credit_data` | 6 档 coin 内购（250/600/1300/2800/6300/14000） | 变现侧 |
| `popup_checkin_gift` | 7 天签到奖励（Coin/Style/Video） | 变现侧 |
| `expand_coin=15`、`t2m_coin=15`、`timeout_gen=3600` | 计费/超时 | 计费侧 |
| `config_home` / `config_home_from_ver111` | 首页样式卡（图片直链 `image.lexica.art`，均为**别人家的图床**） | 静态 |
| `remote_config_ads_ver*`（58 个版本键） | 广告位/频次配置 | 静态 |
| `remote_genimage_api=true`、`config_api_v2_v3=true` | 生成接口开关（均走 8005 v2） | 协议 |

APK 内还自带 `assets/credit.json`（内购档位）、`assets/faq.json`、`assets/dic`（多语词典）。

---

## 7. 计费模型 `静态确认`

* 单位 `coin`（credit），生成一次扣 coin：扩图 15、t2m 15（`expand_coin`/`t2m_coin`）。
* 内购 ID：`aiart_iap_{250,600,1300,2800,6300,14000}`；广告奖励补充。
* 客户端本地只做展示与"次数"计数（`data/generatecount`、`CreditDao`），真实扣费在服务端（该服务已随 8006/业务域一起失联）。
* `com.qonversion.android.sdk` 参与订阅校验，`AppsFlyer` 做归因。

---

## 8. 存活矩阵（2026-10-29 两次独立探测）`已验证`

见 `UPSTREAM-STATUS.md` 与 `evidence/upstream_matrix_*.json`、`evidence/smoke_*.json`。

摘要：协议面 5 项 PASS，生成面 2 项如预期 `upstream_dead`；主机存活 2/17（`8005`、`ob-5000`），其中 `art12.procyoni.com` 虽 200 但为停放页（检测到 `window.location.href="/lander"`）。

---

## 9. 红线与未做事项

* **未使用** RC 里那 294 个 OpenAI key / 9 个 Gemini key 发起任何真实请求 — 这是第三方付费凭证，不是交付方资产。
* 未对 `PUT /api/v1/transfer/style`、`PUT /api/v1/transfer/config` 做写操作（会改上游配置）。
* 未尝试 `199.231.188.59:5000/api`（Basic 认证面）的凭据爆破。
* 未做并发压测（按交付口径：只做单点冒烟）。
