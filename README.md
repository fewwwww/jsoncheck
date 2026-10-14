# jsoncheck

本地 JSON 正确性检查器，两个入口，都不联网、不依赖任何第三方包：

- **网页版** `index.html` —— 双击打开，直接往里贴内容，边打边校验。
- **命令行版** `jsoncheck.py` —— 单文件 Python 3.6+，适合批量跑或挂 CI。

---

## 网页版

```bash
open /Users/msfew/claudecode/jsoncheck/index.html
```

纯本地文件，内容不出浏览器；上次贴的内容存在 localStorage，关掉再开还在。

- 贴进去即时校验，错误定位到 **行:列**，附出错处上下三行 + `^` 指针，点行号可跳过去
- 左侧行号栏把出错行标红
- 报错说人话，且给改法：单引号 / 尾随逗号 / 注释 / 全角逗号冒号 / 键名没加引号 /
  `undefined` / `.5` / `+5` / `0x1F` / 字符串里直接换行 / 从网页复制带进来的不换行空格
- **重复的键**给出完整路径（如 `nested.y[2].k`），**大整数精度丢失**给出实际读到的值 ——
  这两类 `JSON.parse` 不会报错，但线上最容易埋雷
- 工具栏：格式化 / 压缩 / 按键排序 / 复制 / 粘贴 / 打开文件（也能直接把文件拖进来）
- 「结构树」标签页可折叠浏览解析结果；「JSON Lines」模式逐行校验；「严格模式」把警告升级成错误
- 跟随系统深浅色，也可手动切

---

## 命令行版

## 用法

```bash
./jsoncheck.py a.json b.json        # 检查若干文件
./jsoncheck.py -r ./config          # 递归检查目录下的 .json / .jsonl / .ndjson / .geojson
cat a.json | ./jsoncheck.py         # 从 stdin 读
./jsoncheck.py --jsonl logs.txt     # 按 JSON Lines 逐行校验
./jsoncheck.py --strict -r .        # 重复键、NaN / Infinity 一律判错
```

装到 PATH 上（可选）：

```bash
ln -s /Users/msfew/claudecode/jsoncheck/jsoncheck.py /usr/local/bin/jsoncheck
```

## 它会查什么

| 检查项 | 级别 | 说明 |
|---|---|---|
| 语法错误 | 错误 | 报 `文件:行:列`，并打印出错处上下三行 + `^` 指针 |
| 空文件 / 空内容 | 错误 | |
| 尾部多余内容 | 错误 | `{"a":1} xxx` 这类 |
| 非 UTF-8 编码 | 错误 | |
| 嵌套过深 | 错误 | 超出解析器递归上限 |
| 重复的键 | 警告 | 给出键路径如 `d.k`，后者会覆盖前者；`--dup-keys error` 判错 |
| `NaN` / `Infinity` | 警告 | Python 能解析但不是标准 JSON，跨语言会炸；`--allow-nan error` 判错 |
| BOM 开头 | 警告 | 部分解析器会报错 |

## 参数

| 参数 | 作用 |
|---|---|
| `-r, --recursive` | 递归进目录（自动跳过隐藏目录与 `node_modules`） |
| `--jsonl` / `--no-jsonl` | 强制 / 禁用逐行模式（默认按扩展名判断） |
| `--dup-keys {ignore,warn,error}` | 重复键处理方式，默认 `warn` |
| `--allow-nan {ignore,warn,error}` | `NaN` / `Infinity` 处理方式，默认 `warn` |
| `--strict` | 等价于 `--dup-keys error --allow-nan error` |
| `--ext .json,.cfg` | 递归时匹配的扩展名 |
| `-q, --quiet` | 不打印，只靠退出码 |
| `-v, --verbose` | 通过的文件也逐个打印 |
| `--no-color` | 关颜色（也认 `NO_COLOR` 环境变量） |

## 退出码

- `0`：全部通过（只有警告也算通过）
- `1`：存在错误
- `2`：用法或 IO 问题（例如目录没加 `-r`、没匹配到任何文件）

适合直接挂进 pre-commit 或 CI：

```bash
jsoncheck --strict -r . || exit 1
```

## 样例

`samples/` 下放了各类正例与反例，跑一遍即可看到全部输出形态：

```bash
./jsoncheck.py -v -r samples
```
