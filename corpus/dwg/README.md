# DWG 回归语料

`py/verify_cadio.py` 的输入之一。**只用于开发期回归**（不进 wheel、不进运行时数据）。

仓库原本一个 DWG 都没有，而 DWG 通路（libdxfrw）**必须**有真实 DWG 才能验收——
这批样本就是为它抓的（`scripts/fetch_dwg_samples.py`）。

| 子目录 | 来源 | 许可 | 为什么收集它 |
| --- | --- | --- | --- |
| `acadsharp/` | [DomCR/ACadSharp](https://github.com/DomCR/ACadSharp) 的 `samples/` | MIT | **同一张图的版本阶梯**：`sample_AC1014/1015/1018/1021/1024/1027.dwg`（R14/2000/2004/2007/2010/2013-2017），正好一次盯住 `dwgReader15/18/21/24/27` 五个读取器；另加动态块与地理定位两个专项（都是 AC1032） |
| `libdxfrw/` | [LibreCAD/libdxfrw](https://github.com/LibreCAD/libdxfrw) 的 `tests/fixtures/dwg/` | GPLv2-or-later | 解析库**自己的**测试样本：按版本命名（AC1015/1018/1021/1027）+ ANSI932 编码页 + 多边形实体/径向标注/富文本弧文本等专项；其中 3 个是 AC1032 |

## 实测覆盖面（2026-09-28，`libmozcadio.so` + 上游 libdxfrw 2.0.0）

16 个样本**全部读得出来**，模型空间实体数如下（`owner == ""` 的那些）：

| 样本 | 版本 | 模型空间 | 备注 |
| --- | --- | --- | --- |
| `sample_AC1014` / `sample_AC1015` | AC1014 / AC1015 | 145 / 145 | 同一张图在 R14 与 2000 下一致 |
| `sample_AC1018` / `sample_AC1021` | AC1018 / AC1021 | 133 / 139 | 2004 / 2007 |
| `sample_AC1024` / `sample_AC1027` | AC1024 / AC1027 | 140 / 140 | 2010 / 2013–2017 |
| `BLOCKVISIBILITYPARAMETER` / `geoloc` | AC1032 | 4 / 0 | 动态块 4 个块参照；地理定位样例模型空间本身是空的 |
| `ordinary_enc_AC1015/1018/1021/1027`、`..._ansi932` | 各自版本 | 3 / 3 / 3 / 3 | 简单三线图 + 编码页 |
| `large_radial` / `mpolygon_solid` / `rtext_arctext` | AC1032 | 1 / 1 / 2 | 径向标注 / 多边形填充 / 富文本 |

**反面证据（为什么要上游 2.0.0 而不是 LibreCAD 树里那份）**：同一批文件用树里 vendored 的
libdxfrw（0.5.11 时代）读，`AC1018/AC1021/AC1024/AC1027` 全部失败
（`BAD_READ_BLOCKS`/`BAD_READ_TABLES`/`BAD_READ_FILE_HEADER`），AC1032 直接拒绝，
而且 `sample_AC1014` 只读出 **104** 个实体（上游 2.0.0 读 145）——**老那份还在静默丢实体**。

## 怎么更新

```bash
python3 scripts/fetch_dwg_samples.py            # 抓（已存在的不覆盖；默认 4 路并发）
python3 scripts/fetch_dwg_samples.py --dry-run  # 只看会抓什么
PYTHONPATH=py python3 py/verify_cadio.py        # 连 DXF 语料一起扫一遍
```

## 已知边界

- 三个样本其实是 **AC1032（2018+）**：上游 2.0.0 有 `dwgReader32` 能读；树里那份 0.5.11 不行；
- **R2.5 及更早的几个古董版本**（`MC0.0`/`AC1.2`/`AC1.50`/`AC1002`）上游没有解析器，
  会明确报"没有可用的读取器"；
- 上游自带的 `screw2012binary.dxf`（在 `3rd/librecad/libraries/libdxfrw/`）**对象段读不了**，
  两个版本的 libdxfrw 都读不了它（`BAD_READ_SECTION` / `BAD_READ_OBJECTS`），ezdxf 读它没问题；
  我们的态度是整体报错，不静默给半个图——已在 `py/verify_cadio.py` 的预期清单里记名。