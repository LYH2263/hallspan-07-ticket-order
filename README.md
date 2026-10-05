# HallSpan 考场间距排座

在考室网格上按最小曼哈顿距离排座，同试卷套不得四邻相邻，并输出违规与统计。

排座采用**种子打乱**（不按准考证号顺序占座），并落一条**只追加（append-only）的占座流水账**：每次成功排座按准考证号升序追加流水行（准考证号、格子、次序 `seq`），当前排座图必须能由该段流水重放还原，对不上即整段失败。**同一排不得出现两个相同准考证尾号**，后到者只能另排他格或进未排，绝不为给后号腾格而改写先号已提交的流水（流水只追加 ⇄ 回头挤位互斥）。

- 准考证号为空或重复：整场拒绝（不写图、不写流水）。
- `GET /api/seating/journal`：查看最新流水段及重放校验；`POST /api/seating/replay`：重放当前图。
- `PUT /api/candidates/{id}`：改正准考证号。号段、最新流水段、排座图同成功或同失败；失败整段回到保存前，历史流水永不被本次改号 UPDATE，只新增一段。


技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4900 |
| API | http://localhost:9900 |
| API 文档 | http://localhost:9900/docs |
| Postgres | localhost:5450 |

健康检查：`GET http://localhost:9900/api/health`

## 使用说明

1. 在「考室」「考生」「试卷套」确认基础数据。
2. 打开「排座图」执行间距排座。
3. 在「违规」查看间距或同卷相邻问题。
4. 在「统计」查看占用与违规汇总。

## 开发与测试

```bash
docker compose exec api pytest -q
```
