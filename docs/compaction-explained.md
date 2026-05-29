# 压缩与 firstKeptEntryId 详解

## 一、先回答你的核心问题

> `firstKeptEntryId=51` 是干嘛的？

一句话：**它是一个指针，告诉 `buildSessionContext` 函数"从这条 entry 开始，保留原文"。**

`firstKept` = first kept = "第一条要保留的"。

所以 `firstKeptEntryId=51` 的意思是：

> 压缩发生时，把 51 之前的消息都用摘要顶替；从 51 开始（包含 51）保留原文。

它本质上是**一个分界线**。

---

## 二、为什么需要这个分界线？

因为压缩不是"全部压缩"，而是**保留最近一段原文 + 把更老的部分摘要掉**。

### 为什么要保留最近一段？

如果全部压缩成一句话摘要，LLM 会丢掉细节：
- 用户刚才说的具体要求
- 刚跑过的工具结果
- 当前正在进行的任务状态

所以业界通用做法是：**保留最近 N 个 tokens 的原文，更早的内容才摘要**。

pi 的默认设置是 `keepRecentTokens = 20000`，意思是"保留最近 ~20k tokens 的完整对话，再往前的才压缩"。

### 这条分界线在哪？

就是 `firstKeptEntryId`。它指向"保留区"的第一条 entry。

```
[已摘要区]                    [保留区]
msg 20  msg 21  ... msg 50  | msg 51  msg 52  msg 53
                            ^
                  firstKeptEntryId = 51
```

---

## 三、CompactionEntry 长什么样

压缩触发后，pi 在 jsonl 文件**末尾追加一行**：

```json
{
  "type": "compaction",
  "id": "cmp1",
  "parentId": "53",
  "firstKeptEntryId": "51",
  "summary": "用户在做 X 任务，已完成 A、B，正在尝试 C...",
  "tokensBefore": 50000,
  "timestamp": "..."
}
```

字段含义：

| 字段 | 含义 |
|---|---|
| `id` | 这条 compaction entry 自己的 id |
| `parentId` | 挂在当前 leaf 后面（这里是 53） |
| `firstKeptEntryId` | **关键**：从这条 entry id 开始保留原文 |
| `summary` | LLM 写的摘要文本 |
| `tokensBefore` | 压缩前的总 token 数（用于显示） |

**注意**：原来的 msg 20~50 **一个字没改**，只是多了 `cmp1` 这一行。

---

## 四、走一遍完整流程

### 步骤 1：压缩前的 jsonl 文件

```jsonl
{"id":"19","parentId":"18","role":"user",...}
{"id":"20","parentId":"19","role":"assistant",...}
...
{"id":"50","parentId":"49","role":"user",...}
{"id":"51","parentId":"50","role":"assistant",...}
{"id":"52","parentId":"51","role":"user",...}
{"id":"53","parentId":"52","role":"assistant",...}
```

当前 leaf = `53`，上下文总共 50000 tokens，超过阈值，触发压缩。

### 步骤 2：找切点（决定 firstKeptEntryId）

pi 的逻辑：
1. 从最新消息（53）往前数
2. 累加每条消息的 token 数
3. 累加到 20000 tokens 时，停在某个**合法切点**
4. 这个切点的 id 就是 `firstKeptEntryId`

假设算下来停在 `51`，那 `firstKeptEntryId = 51`。

- **51, 52, 53 是"保留区"**（约 20000 tokens 的最近原文）
- **19~50 是"摘要区"**（约 30000 tokens 会被摘要掉）

#### 什么是"合法切点"？

不是哪里都能切。规则：

- 可以切在 user message
- 可以切在 assistant message
- **绝对不能切在 tool_result**

为什么？因为 LLM API 要求 `tool_call` 和 `tool_result` 必须成对出现。如果摘要区里有一个 tool_call，但 tool_result 留在保留区，LLM 会报错。

### 步骤 3：摘要 19~50

pi 把 19~50 的消息序列化成文本，发给 LLM 写摘要。

### 步骤 4：在 jsonl 末尾 append CompactionEntry

```jsonl
{"id":"19",...}
...
{"id":"53",...}
{"id":"cmp1","parentId":"53","type":"compaction","firstKeptEntryId":"51","summary":"...","tokensBefore":50000}
```

新的 leaf 自动变成 `cmp1`。

### 步骤 5：下一轮 LLM 调用，构建上下文

`buildSessionContext` 算法：

```
1. 从 leaf (cmp1) 沿 parentId 上溯到根
   得到路径 pathEntries = [19, 20, ..., 53, cmp1]

2. 扫一遍 pathEntries，找最新的 compaction
   compaction = cmp1

3. 因为有 compaction，触发"压缩模式"：

   a. 第一条消息：放 cmp1.summary

   b. 遍历 cmp1 之前的 entries（19 到 53）：
      foundFirstKept = False
      for entry in [19, 20, ..., 53]:
          if entry.id == "51":
              foundFirstKept = True
          if foundFirstKept:
              输出 entry    # 51, 52, 53 输出
          else:
              跳过 entry    # 19~50 跳过

4. 返回 messages = [summary, msg51, msg52, msg53]
```

**LLM 最终看到的**：

```
[system prompt]
[compaction summary: "用户在做 X..."]
[msg 51 原文]
[msg 52 原文]
[msg 53 原文]
```

---

## 五、用图理解

### 物理存储（jsonl 文件）

```
entry 19   parentId=18
entry 20   parentId=19
...
entry 50   parentId=49                       <- 压缩区（还在！没删！）
entry 51   parentId=50    <- firstKeptEntryId
entry 52   parentId=51                       <- 保留区
entry 53   parentId=52
entry cmp1 parentId=53                       <- 末尾新增
           firstKeptEntryId=51
           summary="..."
```

### LLM 看到的（buildSessionContext 输出）

```
[system prompt]
[summary of 19~50]    <- 来自 cmp1.summary
msg 51 原文           <- firstKeptEntryId 之后保留
msg 52 原文
msg 53 原文
```

对比：
- 文件里有几十条 entry
- LLM 只看到 4 条（summary + 51 + 52 + 53）

---

## 六、为什么这个设计很巧妙

### 1. 老消息不删，可逆

如果你 `/tree` 跳回 msg 30：
- 新 leaf = msg 29
- 路径 = [..., 19, 20, ..., 29]
- **路径上没有 cmp1**（cmp1 挂在 53 后面，53 不在新路径上）
- `buildSessionContext` 走"无压缩"分支
- LLM 看到 msg 1 ~ msg 29 的完整原文

**压缩只影响"路径经过 cmp1 的那条分支"。跳到其他分支，原文重新可见。**

### 2. 多次压缩可叠加

第一次压缩后，对话继续，又满了：
- jsonl 末尾再 append 一条 `cmp2`
- `cmp2.firstKeptEntryId` 指向第二次压缩的切点
- `buildSessionContext` 扫路径时，只用**最新的** compaction（cmp2）

### 3. 不需要"记忆"系统

整个机制只用了：
- jsonl 文件（事实存储）
- 一个 `buildSessionContext` 函数（视图算法）

---

## 七、firstKeptEntryId 的本质

把它想成 git 的 commit hash：

| git | pi compaction |
|---|---|
| HEAD 指向某个 commit | leaf 指向某个 entry |
| git log 显示所有 commit | jsonl 存所有 entry |
| git rebase 截掉一段 | compaction 用 summary 顶替一段 |
| HEAD~5 表示"往前数 5 个 commit" | firstKeptEntryId 表示"保留区从这里开始" |

它就是一个**指针/书签**，标记"保留区的起点"。

---

## 八、回到你的项目

旧版 `memory_pythonic/compress.py` 干过的事：

```
取出旧短期记忆待压缩列表里的老消息
   ↓
LLM 摘要
   ↓
把摘要回注到旧短期记忆               <- 替换老消息
   ↓
老消息从此消失
```

当前主线已经删掉短期 memory/压缩链路，压缩应直接落到追加式 `CompactionEntry`，不要再做 `summary.md` sidecar。关键变化是：

```
session 里找一个合法切点，记下 first_kept_entry_id
   ↓
切点之前的消息 → LLM 摘要
   ↓
session.append(CompactionEntry(
    summary=...,
    first_kept_entry_id=切点 id
))
   ↓
老消息一条不删，留在 jsonl 里
   ↓
build_llm_context 时跳过摘要区，从 first_kept_entry_id 开始保留原文
```

---

## 九、一句话总结

**`firstKeptEntryId` 是"压缩边界"：它指向保留区的第一条 entry。`buildSessionContext` 用它决定"哪些原文要给 LLM 看，哪些用摘要顶替"。**

整个机制的精髓是：

> **不删数据，只追加标记，用视图算法决定 LLM 看什么。**
