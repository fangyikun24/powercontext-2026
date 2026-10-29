# 脑洞制造机（Idea Engine）— Dify 赛道作品

> **赛道**：Dify —— Just for Fun：好玩的智能应用（20 分）
> **一句话**：输入一个主题，AI 给你 3 个离谱又合理的神奇脑洞；PowerContext 记住你玩过的脑洞，灵感越玩越多。

## 这是什么

一个**可体验的趣味应用**：用户给任意主题（如"会飞的冰箱""周一上班"），Dify 工作流
用大模型生成 3 个"离谱但自洽"的创意方案，并把每次脑洞保存到 PowerContext 记忆。
下次再玩时，工作流先检索历史脑洞（记忆复用），避免重复并"在此基础上续写"——
**创意不断累积，越玩越有料**。

## 技术结合（赛题要求：Dify 必选 + seekdb/PowerContext 至少一种）

| 技术 | 角色 | 是否实际发挥作用 |
|---|---|---|
| **Dify** | 核心流程编排（工作流） | ✅ 承担全部编排：start → 检索 → 生成 → 保存 → 输出 |
| **PowerContext（官方）** | 记忆层（HTTP 节点调用） | ✅ 每次脑洞保存到记忆；每次生成前检索历史脑洞用于续写 |

PowerContext 采用 **OceanBase 官方 PowerContext 1.4.x**（官方 Server + 官方 Python SDK），
经 **Dify HTTP 请求节点**接入（无需插件），端点对齐官方 OpenAPI 合同：
- `memory_retrieve` 节点：POST `/v1/memory/search` 检索历史脑洞（body: `scope_id/query/limit`）
- `memory_save` 节点：POST `/v1/memory/remember` 保存本次创意（body: `scope_id/kind/text`）

## 部署官方 PowerContext Server（真实服务，非自制实现）

```bash
pip install "powercontext[cli,builtin]>=1.4"   # 官方依赖
python server/memory_server.py                 # 启动官方 Server :8000
# （等价于官方命令：powercontext server run --host 127.0.0.1 --port 8000）
```

启动后提供官方端点 `/v1/memory/remember` 与 `/v1/memory/search`。
支持 OceanBase / seekdb / SQLite 持久化后端（PowerContext 官方内置能力，可在 Server 配置中选择）。

## 官方 SDK 验证（真实运行证据）

```bash
python server/verify.py     # 官方 SDK：from powercontext.client import PowerContextClient
```

`verify.py` 通过官方 `PowerContextClient` 真实调用 `remember_memory(RememberMemoryRequest(...))`
与 `search_memory(SearchMemoryRequest(...))`，验证记忆保存与按相关度检索的完整闭环
（输出见 `server/verify_output.txt`）。

## 导入运行（Dify 云端版）

1. 登录 Dify（云端版 / 社区版均可），进入"工作区"；
2. 右上角 **导入 DSL 文件**，选择 `idea_engine.yml`（Dify 原生 DSL：顶层 `kind/version/workflow`）；
3. 打开应用，选择模型（任意可用 LLM 提供商）；
4. （可选）若本地运行了官方 PowerContext Server，HTTP 节点默认指向 `http://127.0.0.1:8000` 即可联通；
5. 保存并运行：输入主题 → 等待 → 得到 3 个脑洞创意（并自动保存到记忆）。

## 验证样例

```
输入主题：会飞的冰箱
输出（示意）：
1. 冷链快递员：冰箱自己飞去你家，把一周生鲜"投递"进厨房，顺带跟邻居拼单。
2. 空中菜市场：楼顶停靠，扫码开柜，冰镇快乐水从天而降。
3. 冰箱地铁：上班高峰把便当挂在冰箱把手，到站自动加热，下车即取。
【记忆】已保存本次脑洞，下次主题相近时会在此基础上续写，不重复。
```

（真实输出取决于所配模型；PowerContext 记忆闭环为官方 Server + 官方 SDK 实测，见 VALIDATION.md。）

## 提交材料（放在 dify/ 目录）

- `idea_engine.yml` —— Dify 工作流 DSL（原生格式，可导入）
- `server/memory_server.py` —— 官方 PowerContext Server 启动入口（`powercontext server run`）
- `server/run_powercontext.py` —— 官方 Server 启动封装（等价命令）
- `server/verify.py` —— 官方 Python SDK 一键验证（`PowerContextClient`）
- `server/requirements.txt` —— 官方依赖 `powercontext[cli,builtin]`
- `server/verify_output.txt` —— 官方 SDK 实测运行日志
- `README.md` —— 本文件（运行说明）
- `VALIDATION.md` —— 验证记录（勾选 + 官方运行说明）

## 评分维度对照

| 维度 | 本作品落点 |
|---|---|
| 创意 | 脑洞生成 + 记忆续写机制，天然有趣 |
| 趣味与互动 | 任意主题即时反馈，玩法门槛为零 |
| 体验与完成度 | 原生 DSL 导入即用 + 官方服务可复现 |
| 技术结合 | Dify 编排 + 官方 PowerContext 记忆复用双路生效 |
| 工程质量与可复现 | 结构清晰、节点职责单一、失败可降级、官方命令可复现 |
