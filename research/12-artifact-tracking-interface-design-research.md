# 开源项目 Artifact Tracking 查询接口设计调研

> 调研目的：为 amta 的 artifact.py 重设计提供参考——如何用原子化的查询原语替代硬编码命令，实现"管线产物追溯"。
> 调研日期：2026-09-11
> 方法：一手来源（官方文档、API reference、源码）

---

## 1. 五个典型项目的设计概览

| 项目 | 核心抽象 | 定位维度 | 查询接口 | 追溯机制 |
|------|---------|---------|---------|---------|
| **MLflow** | Run → Artifact | run_id + artifact_path(可选) | `list_artifacts(run_id, artifact_path?)` | run 关联 + 路径前缀 |
| **Airflow XCom** | DAG Run → Task Instance → XCom | dag_id + dag_run_id + task_id + xcom_key | `xcom_pull(task_ids, key?)` / REST API | task 依赖图 + xcom 键值 |
| **DVC** | Pipeline → Stage → Output | pipeline + stage + path | `dvc.yaml` 声明式 + `dvc.lock` 哈希 | deps→outs DAG 自动血缘 |
| **Pachyderm** | Repo → Branch → Commit → File | repo + branch + commit + path | PFS 文件系统 API | input repo → output repo 自动血缘 |
| **W&B** | Run → Artifact | run + artifact_name + version | `use_artifact()` / `log_artifact()` | use→log 显式声明血缘 |

---

## 2. 共性设计模式（五个项目都遵循的）

### 2.1 多级定位维度（必填 + 可选）

所有系统都有一个**必填的"运行实例"ID**作为第一级定位，然后是**可选的过滤维度**：

- **MLflow**：`run_id`（必填）+ `artifact_path`（可选，路径前缀过滤）["https://www.mlflow.org/docs/latest/api_reference/rest-api.html"]
- **Airflow**：`dag_id` + `dag_run_id`（必填）+ `task_id` + `xcom_key`（可选）["https://github.com/apache/airflow-client-go/blob/main/airflow/docs/XComApi.md"]
- **DVC**：`pipeline`（必填）+ `stage`（可选）+ `path`（可选）["https://doc.dvc.org/user-guide/project-structure/dvcyaml-files"]
- **Pachyderm**：`repo` + `branch`（必填）+ `commit`（可选，默认 latest）+ `path`（可选）["https://support.hpe.com/hpesc/public/docDisplay?docId=a00pachyderm29en_us&page=latest%2Fbuild-dags%2Fpipeline-spec.html"]
- **W&B**：`run`（必填）+ `artifact_name` + `version/alias`（可选）["https://github.com/papapabi/wandb-experiments/blob/main/README.md"]

**关键洞察**：没有一个系统是"必填所有维度才能查"的。都是"必填最粗粒度，可选下钻"。

### 2.2 一个查询原语 + 可选参数，而非多个硬编码命令

- MLflow 只有 `list_artifacts` 一个查询入口，通过 `artifact_path` 控制范围（不填=全部，填前缀=过滤）["https://mlflow.org/docs/latest/api_reference/python_api/mlflow.artifacts.html"]
- Airflow REST API 只有 `GetXcomEntries`（列表）和 `GetXcomEntry`（单个）两个，通过路径参数控制范围["https://github.com/apache/airflow-client-go/blob/main/airflow/docs/XComApi.md"]
- DVC 没有"查询命令"，查询是通过读 `dvc.yaml` + `dvc.lock` 两个声明式文件完成的["https://dvc.org/doc/user-guide/pipelines/defining-pipelines"]

**关键洞察**：没有一个系统设计了 `find_single` / `list_by_stage` / `list_by_page` / `status_summary` 这种按场景硬编码的命令。都是一个查询原语 + 参数组合。

### 2.3 产物携带元数据，而非只返回路径

- **MLflow** `list_artifacts` 返回 `list[FileInfo]`，每个 FileInfo 含 `path`、`size`、`is_dir`["https://mlflow.org/docs/latest/api_reference/python_api/mlflow.artifacts.html"]
- **Airflow XCom** 每条记录含 `key`、`value`、`task_id`、`dag_id`、`execution_date`["https://airflow.apache.org/docs/apache-airflow/2.11.0/core-concepts/xcoms.html"]
- **DVC** artifact 含 `path`（必填）、`type`、`desc`、`labels`、`meta`（可选）["https://doc.dvc.org/user-guide/project-structure/dvcyaml-files"]
- **W&B** Artifact 含 `name`、`type`、`description`、`metadata`、`aliases`["https://github.com/vanman2024/ai-dev-marketplace/blob/master/plugins/ml-training/skills/monitoring-dashboard/examples/wandb-integration.md"]

**关键洞察**：没有一个系统的查询返回值是"裸路径字符串"。都是结构化对象，至少包含路径 + 基本元数据。

### 2.4 追溯（lineage）通过依赖声明自动建立

- **DVC**：每个 stage 声明 `deps`（输入）和 `outs`（输出），DAG 自动建立血缘["https://dvc.org/doc/user-guide/pipelines/defining-pipelines"]
- **Pachyderm**：pipeline 的 input repo 变化时自动触发，output repo 自动关联 input commit，完整不可变血缘["https://uplatz.com/blog/an-architectural-analysis-of-data-versioning-and-lineage-in-modern-machine-learning-operations/"]
- **W&B**：`run.use_artifact()` 声明输入依赖，`run.log_artifact()` 声明输出，自动建立 artifact 血缘图["https://github.com/papapabi/wandb-experiments/blob/main/README.md"]
- **Airflow**：task 之间的依赖通过 `>>` 运算符声明，XCom 自动关联上下游 task["https://airflow.apache.org/docs/apache-airflow/3.1.5/core-concepts/taskflow.html"]

**关键洞察**：追溯不是"查询时再去拼"，而是"生产时就声明好依赖关系"。查询时直接读依赖图即可。

### 2.5 内容哈希做不可变版本

- **DVC**：每个 output 的哈希存在 `dvc.lock`，内容变了哈希就变["https://dvc.org/doc/user-guide/pipelines/defining-pipelines"]
- **Pachyderm**：PFS 用 copy-on-write + 内容寻址，每个 file 有 hash["https://academic.oup.com/bioinformatics/advance-article-pdf/doi/10.1093/bioinformatics/bty699/25442459/bty699.pdf"]
- **MLflow**：run_id 本身就是版本，artifact 关联到 run["https://mlflow.org/docs/latest/ml/tracking/tracking-api/"]

---

## 3. 对 amta artifact.py 重设计的启示

### 3.1 定位维度映射

| 开源通用维度 | amta 对应 | 必填？ |
|-------------|----------|--------|
| 运行实例（run_id / dag_run_id） | `work-id` | ✅ 必填 |
| 阶段/任务（stage / task_id） | `stage` | ❌ 可选（不填=所有阶段） |
| 数据分片（datum / partition） | `page` | ❌ 可选（不填=所有页） |
| 产物路径（artifact_path / path） | 自动解析 | ❌ 不需要用户填 |

### 3.2 原子查询原语

**一个命令，三个参数（一个必填，两个可选）：**

```
artifact.py query --work-id <id> [--stage <stage>] [--page <page>]
```

返回值：**结构化产物列表**，每个产物含：
- `path`：文件路径
- `stage`：所属阶段
- `page`：所属页
- `type`：json / image
- `size`：文件大小
- `mtime`：生成时间
- `fingerprint`：内容哈希（如果有）
- `upstream`：上游依赖（如果可追溯）

**参数组合出所有场景：**
- `--work-id ab-no-prefix-b` → 列出该工作区所有产物
- `--work-id ab-no-prefix-b --stage typeset` → 列出该工作区 typeset 阶段所有页
- `--work-id ab-no-prefix-b --page page_11` → 列出该页所有阶段产物（追溯链）
- `--work-id ab-no-prefix-b --stage typeset --page page_11` → 定位单个产物

**这就替代了现在的 find + list + status 三个硬编码命令。**

### 3.3 全局搜索模式（不指定 work-id）

开源项目都要求必填 run_id，但 amta 的场景是"AI 想知道有哪些工作区、哪些成品图"——这需要一个**全局发现模式**。

建议加一个 `--all-workspaces` 标志：
```
artifact.py query --all-workspaces --stage final
```
返回所有工作区的 final 阶段产物，按工作区分组。

这是 amta 特有的需求（开源项目通常有中心化的 run 注册表，不需要全局扫），但 amta 是纯本地文件系统，workspace/ 目录就是注册表。

### 3.4 追溯（lineage）怎么建

amta 现在的产物契约（`src/amta/stores/artifacts.py`）已经规定了页键和 region_id 规则，这就是追溯的基础。但还需要：

1. **每个 JSON 产物记录上游依赖**：比如 translate 产物记录它用了哪个 detect 框、哪个 OCR 结果
2. **查询时按 page 聚合**：`--page page_11` 返回该页所有阶段产物，按阶段顺序排列，就是追溯链
3. **不需要额外的血缘数据库**：因为 amta 是线性 pipeline（detect→ocr→translate→inpaint→typeset），不是任意 DAG，按阶段排序就是血缘

### 3.5 invalidate 怎么办

现在的 `invalidate --page` 是缓存操作，不是查询操作。它应该保留为独立命令，但属于"写操作"而非"读操作"。重设计后：
- `query`：读操作（原 find + list + status）
- `invalidate`：写操作（删指纹）

两个命令，职责清晰。

---

## 4. 总结：五个项目教给我们的设计原则

1. **一个查询原语 + 可选参数**，不要按场景硬编码多个命令
2. **必填最粗粒度，可选下钻**，不要要求用户填所有维度才能查
3. **返回结构化对象**（路径+元数据），不要返回裸路径字符串
4. **追溯靠生产时的依赖声明**，不要靠查询时临时拼
5. **内容哈希做版本**，不要靠文件名猜新旧

---

## 参考来源

- MLflow Tracking API: https://mlflow.org/docs/latest/ml/tracking/tracking-api/
- MLflow REST API (List Artifacts): https://www.mlflow.org/docs/latest/api_reference/rest-api.html
- MLflow Python API (mlflow.artifacts): https://mlflow.org/docs/latest/api_reference/python_api/mlflow.artifacts.html
- Airflow XComs: https://airflow.apache.org/docs/apache-airflow/2.11.0/core-concepts/xcoms.html
- Airflow TaskFlow API: https://airflow.apache.org/docs/apache-airflow/3.1.5/core-concepts/taskflow.html
- Airflow XCom API (Go client): https://github.com/apache/airflow-client-go/blob/main/airflow/docs/XComApi.md
- DVC dvc.yaml files: https://doc.dvc.org/user-guide/project-structure/dvcyaml-files
- DVC Defining Pipelines: https://dvc.org/doc/user-guide/pipelines/defining-pipelines
- Pachyderm Pipeline Specification: https://support.hpe.com/hpesc/public/docDisplay?docId=a00pachyderm29en_us&page=latest%2Fbuild-dags%2Fpipeline-spec.html
- Pachyderm Data Lineage Analysis: https://uplatz.com/blog/an-architectural-analysis-of-data-versioning-and-lineage-in-modern-machine-learning-operations/
- Pachyderm Bioinformatics Paper: https://academic.oup.com/bioinformatics/advance-article-pdf/doi/10.1093/bioinformatics/bty699/25442459/bty699.pdf
- W&B Artifacts Example: https://github.com/papapabi/wandb-experiments/blob/main/README.md
- W&B Integration Guide: https://github.com/vanman2024/ai-dev-marketplace/blob/master/plugins/ml-training/skills/monitoring-dashboard/examples/wandb-integration.md
