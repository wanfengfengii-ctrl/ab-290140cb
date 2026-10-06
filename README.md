# 乐谱提示点 → 音频采样时钟投影服务

把乐谱提示点（cue）从刻度域投影到音频采样时钟：给定速度图（tempo map），
为每个提示点输出纳秒时刻与零基采样帧。累计时长全程以精确有理数
（`fractions.Fraction`）计算，速度自动化跨段不会累积舍入误差；纳秒与
采样帧各自从**未舍入**的累计时长按**半偶（round-half-even）**规则独立取整，
同刻度提示必然得到相同投影。

## 运行

```bash
docker compose up --build app                 # 默认宿主机端口 8080
APP_PORT=9090 docker compose up --build app   # 健康检查/服务端口可配置
curl localhost:9090/health                    # {"status":"ok"}
```

## 一键验证（测试 + 构建 + 冒烟）

`verify` 是一次性服务：待 app 健康检查后，依次执行单元测试、字节码构建、
保持段与渐变段的 API 冒烟，随后自行退出，退出码即结果（0 通过 / 非 0 失败）。

```bash
docker compose up --build --abort-on-container-exit --exit-code-from verify verify
echo $?   # 0 = 全部通过
```

本地无 Docker 时等价执行：`python3 -m unittest discover -s tests -v`，
启动服务后 `APP_URL=http://127.0.0.1:8080 python3 smoke.py`。

## API

### `POST /api/timelines/project`

```json
{
  "ticksPerQuarter": 480,
  "sampleRate": 48000,
  "tempoPoints": [
    {"tick": 0,   "microsPerQuarter": 500000, "mode": "ramp"},
    {"tick": 960, "microsPerQuarter": 250000, "mode": "hold"}
  ],
  "cues": [
    {"id": "verse", "tick": 480},
    {"id": "hook",  "tick": 1440}
  ]
}
```

- `ticksPerQuarter`：每四分音符刻度数，正整数。
- `sampleRate`：采样率 Hz，正整数。
- `tempoPoints`：1–500 个。`tick` 为非负整数，首点必须为 0 且严格递增；
  `microsPerQuarter` 为正整数微秒/四分音符；`mode` 为 `hold`（该点后区间
  速度恒定）或 `ramp`（该点后区间速度随刻度线性变化到下一点）。末点之后
  速度恒定。
- `cues`：1–2000 个，`id` 唯一（非空字符串或整数），`tick` 非负整数。

成功 `200`，按提示点原顺序返回：

```json
{"projections": [{"id": "verse", "tick": 480, "nanoseconds": 437500000, "frame": 21000}]}
```

### 数学定义

- hold 段：`Δt_µs = τ · Δtick / PPQ`
- ramp 段（宽 w，端点 τ₀→τ₁，行进 d）：`Δt_µs = (τ₀·d + (τ₁−τ₀)·d²/(2w)) / PPQ`
- 末点后：`τ_last` 恒定延伸
- `nanoseconds = round_half_even(µs · 1000)`，
  `frame = round_half_even(µs · sampleRate / 10⁶)`

### 错误响应

校验整体失败即返回，不夹带任何部分投影结果。错误体：

```json
{"error": {"code": "DUPLICATE_TICK", "message": "...", "position": {"path": "tempoPoints[2].tick", "index": 2}}}
```

| code | HTTP | 含义 |
|---|---|---|
| `MALFORMED_JSON` | 400 | 请求体不是合法 JSON |
| `INVALID_PAYLOAD` | 400 | 顶层不是 JSON 对象 |
| `MISSING_FIELD` | 400 | 缺少必填字段 |
| `INVALID_FIELD_TYPE` | 400 | 字段类型错误（刻度/速度须为 JSON 整数） |
| `INVALID_FIELD_VALUE` | 422 | `ticksPerQuarter`/`sampleRate` 非正、速度点刻度为负 |
| `INVALID_CUE_ID` | 400 | 提示点编号缺失或类型非法 |
| `TEMPO_POINT_COUNT_OUT_OF_RANGE` | 422 | 速度点数量不在 1–500 |
| `CUE_COUNT_OUT_OF_RANGE` | 422 | 提示点数量不在 1–2000 |
| `TEMPO_MAP_GAP` | 422 | 速度图未从刻度 0 开始（缺口） |
| `DUPLICATE_TICK` | 422 | 速度点刻度重复 |
| `TICKS_NOT_INCREASING` | 422 | 速度点刻度未严格递增 |
| `ILLEGAL_MODE` | 422 | 模式不是 `hold`/`ramp` |
| `NON_POSITIVE_TEMPO` | 422 | 微秒/四分音符非正整数 |
| `CUE_OUT_OF_RANGE` | 422 | 提示点刻度为负（越界） |
| `DUPLICATE_CUE_ID` | 422 | 提示点编号重复 |
| `NOT_FOUND` | 404 | 路径不存在 |

## 结构

```
app/server.py       HTTP 服务（纯标准库，GET /health、POST /api/timelines/project）
app/projection.py   精确有理数累计 + 半偶取整投影
app/validation.py   请求校验，稳定错误码与位置
tests/              单元测试（数学、校验、HTTP）
smoke.py            API 冒烟（保持段、渐变段、半偶取整、错误码）
verify.sh           verify 服务入口：测试 → 构建 → 冒烟
Dockerfile / docker-compose.yml
```
