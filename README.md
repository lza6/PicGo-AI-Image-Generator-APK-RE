# PicGo AI Image Generator v2.0.8 — APK 逆向 / 协议还原 / 网关复刻

`com.aiart.aigenerator.aifilter.aieditor`（真实代码包 `com.prox.global.aiart`）的完整协议还原与本地网关复刻。

## 一句话结论

**协议 100% 还原，但上游算力已经死了 —— 零可用生成能力，不可入池。**
风格模板（14 文生图 + 50 图生图）、token 签发、上游配置全部还活着并且可复现；
但真正跑图的 9 个 runpod SD-WebUI 代理全 404、结果存储 MinIO 已 503 —— 见 [`docs/UPSTREAM-STATUS.md`](docs/UPSTREAM-STATUS.md)。

## 目录结构

```
gateway/
  picgo_client.py     纯协议客户端（token 伪造 / 风格 / 配置 / txt2img / img2img / video）
  server.py           FastAPI 网关：/v1/images/*（OpenAI 兼容）+ /picgo/*（原生协议）
  demo.html           演示页（实时拉上游数据，生成失败就显示真实错误，不伪造图）
scripts/
  probe_upstreams.py  上游存活矩阵（17 个目标，只读单点）
  smoke.py            单点冒烟（协议面必须过 / 生成面必须判定 upstream_dead）
  export_styles.py    导出 50+14 条风格模板 → exports/styles_export.json（供自建 SD 使用）
docs/
  PROTOCOL.md         协议还原报告（端点全集 / 鉴权 / 配置 / Remote Config / 计费）
  UPSTREAM-STATUS.md  存活矩阵与冒烟证据
  NEW-API-INTEGRATION.md  new-api 对接指南（三条路线，结论：本轮不可接）
evidence/             冒烟与探测的原始 JSON + 演示页截图
exports/              风格模板导出
```

## 快速开始

```bash
cd picgo208
pip install fastapi uvicorn requests        # 其余为纯标准库
python scripts/probe_upstreams.py           # 1. 先看上游还活着什么
python scripts/smoke.py                     # 2. 单点冒烟（协议面 PASS / 生成面 upstream_dead）
python -m uvicorn gateway.server:app --host 127.0.0.1 --port 8985
open http://127.0.0.1:8985/                 # 3. 演示页
```

演示页会用真实请求把能力矩阵、上游存活、50 条风格清单全部拉出来；点「跑文生图」会得到真实的上游错误。

## 已验证的行为

| 项 | 结果 |
|---|---|
| `POST /api/v3/token` 任意 body | 200，签出 HS256 JWT `{unique, app:"prox_app", exp:+180s}` |
| `GET /api/v1.0/style_list` | 200，14 个文生图风格（含 prompt 模板） |
| `GET /api/v1/transfer/list_styles` | 200，50 个图生图风格 |
| `GET /api/v1/transfer/config` | 200，50 风格 + 3 个上游算力地址 |
| `POST /api/v2.0/generator/txt2img` | 200 但 `image_url: null`（异常被上游吞掉） |
| `POST /api/v2.0/transfer`（img2img） | 202 `{"detail":"Error!"}` |
| `POST /api/v1/video-generate` | 41s 恒返回同一模板 `wedding_template.mp4`（死链），与输入无关 |
| 9 个 runpod 算力代理 | 404 ×9 |
| 演示页（Playwright 实测） | 6 条能力行 / 14+50 风格实时加载 / 生成按钮返回真实 502 / 唯一 console error 即该 502 |

## 红线（本项目遵守）

* 未使用 APK 内 Firebase Remote Config 里的 **294 个 OpenAI key / 9 个 Gemini key** 发起任何真实请求 —— 第三方付费凭证。
* 未对上游做写操作（`PUT /api/v1/transfer/*`），未做凭据爆破，未压测（只做单点冒烟）。
* 仓库内所有敏感串均已脱敏（`grep -rn "sk-"` 只会在文档中命中脱敏示例）。

## 免责

仅用于自有 APK 的协议学习与互操作性研究。上游服务与其中数据均属第三方，请勿用于未授权访问、批量滥用或二次分发。使用风险自负。
