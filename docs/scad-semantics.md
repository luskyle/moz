# SCAD 语义陷阱（实测清单）

这些都是**运行观测**出来的结论（源码里读不出来），是把 `.scad` 忠实翻成 Python 时必须知道的东西。
每条都给了现象、证据与正确做法。

## 1. 导出字节取决于 CSG 节点结构

**现象**：同样的几何、同样的面数，下面三种写法的 STL 字节互不相同。

```scad
union() { a; b; }              // 显式 union
{ a; b; }                      // 裸块 => group 节点
module m() { a; b; }  m();     // 模块体（比裸块还多一层）
```

**后果**：Python 侧用 API 拼源码时**不可能**与 `.scad` 逐字节对齐；验收不能用字节相等做唯一判据
（见 [verification.md](verification.md) 的三档判据）。
另外 `for` / `if` 在 2021.01 里是 `GroupNode`——它算**一个** union 操作数，不是把子对象展开到父列表里，
所以 `difference(A, for(...))` 与 `difference(A, B1, B2)` 不同构。

## 2. 块作用域的 `$fn` 会泄漏给后续兄弟对象

```scad
union() { { $fn = 8; cylinder(r=2,h=12); } sphere(5); }   // sphere 也变成 8 段
union() { cylinder(r=2,h=12,$fn=8);  sphere(5); }         // sphere 保持默认
```

**正确做法**：只影响单个对象时用**具名参数** `sphere(r=1, fn=8)`；
只有原文件本来就是**文件级/模块级赋值**（`$fn = 40;`）时，才用块作用域包整体
（Python 侧 `moz.settings(model, fn=40)`），并且要注意它会把后面的兄弟一起带上。

## 3. `linear_extrude` 不传 `slices` 时由引擎推导

`linear_extrude(height=10) square(5)` 是 12 面；补一个 `slices = 20` 会变成 164 面。
**不要**给 `scale`/`twist`/`slices` 塞默认值——绑定层曾经硬写 `slices = 20`，
是一处真实的保真度缺陷，已修。

## 4. `offset(N)` 的第一个位置参数是 `r`，不是 `delta`

```scad
linear_extrude(20) offset(10)         square(50, center=true);   // 172 面（圆角外扩）
linear_extrude(20) offset(r=10)       square(50, center=true);   // 172 面
linear_extrude(20) offset(delta=10)   square(50, center=true);   //  12 面（尖角外扩）
```

Python 侧：`moz.offset(obj, 10)` / `moz.offset(obj, r=10)` 都是圆角；`delta=` 才是尖角。

## 5. `cylinder(h, N)` 的第二位置参数是 `r1`

`cylinder(50, 2)` == `cylinder(h=50, r1=2)` == `cylinder(h=50, r1=2, r2=1)`（体积 319.25），
也就是**圆台**；而 `cylinder(h=50, r=2)` 是圆柱（547.28 面体积）。
`Parametric/candleStand.scad` 的 `cylinder(length, width-2)` 就是圆台。

## 6. 三角函数有专用实现，别用 `math.radians`

SCAD 的 `sin/cos/tan/asin/acos/atan/atan2` 以**度**为单位，且 `src/degree_trig.cc` 对
30/45/60/90 直接给精确常量（`0.5`、`M_SQRT1_2`、`M_SQRT3_4`……），反三角还会在结果接近整数时取整。
用 `math.sin(math.radians(x))` 会差最后几位，进而改变网格。

**正确做法**：`moz.sin_deg / cos_deg / tan_deg / asin_deg / acos_deg / atan_deg / atan2_deg`
（已按同一算法复刻；实测 `sin(1e18)`、`cos(123456789)`、`tan(89.9999)`、`acos(-1)`、
`atan2(-0, -1)` 等边界值全部逐比特一致）。

## 7. `echo()` / `str()` 打印数字只有 6 位有效数字

`value.cc` 里 `DC_PRECISION_REQUESTED = 6`：`echo(1/3)` 得到 `0.333333`。
**所以不能拿 echo 文本当取值通道**（参数化模型会被末位误差毁掉）。
本项目的 `moz.value/number/vector` 改用注册进引擎的内置函数取原值，按 17 位有效数字输出。

## 8. `search()` 对字符串是「逐字符」匹配

```scad
search("one", 8bit_polyfont()[2], 1, 1)   // => [111, 110, 101]（o、n、e 三个字形下标）
search("one", 8bit_polyfont()[2], 0, 1)   // => [[111], [110], [101]]
```

`Old/example023.scad` 的钟面就靠这个特性把单词拆成字形。

## 9. 顶层变量是「提升」的；`$t` 默认 0

`cube([size,1,1]); size = 20;` 用的是 **20**（不是 undef）。
无动画场景下 `$t` 为 **0**，所以 `Advanced/animation.scad` 直接求值得到的就是第 0 帧
（想取别的帧就 `moz.eval_file(..., **{"$t": 0.25})`）。

**顺序陷阱**：`-D` 变量（`moz.eval_*` 的关键字参数、`eval_animation` 逐帧注入的 `$t`）是拼接在
源码**之后**的，因此**顶层赋值看不到它们**：

```scad
tz = 6 * sin(360 * $t);              // 求值时 $t 还是默认 0，后面的 $t=... 还没生效
translate([0, 0, tz]) sphere(2);     // 逐帧几何完全相同（错误）
```

把 `$t` 直接放进几何表达式就对了（实测逐帧几何才随 `$t` 变化）：

```scad
translate([0, 0, 6 * sin(360 * $t)]) sphere(2);
```

这是 `py/examples/moz/animation.py` 落地时踩到的坑。

## 10. `%` / `#` / `render()` 的语义

- `%对象`：**背景**修饰符，预览可见，**不进入 F6/导出**。翻译时不要放进 `build()` 返回值。
- `#对象`：**高亮**，只影响预览，几何上等同普通对象。
- `render(convexity=N)`：F6 下只透传几何（去掉它几何不变，实测字节也常常不变），
  但它会在 CSG 树里产生节点、影响导出顺序，所以忠实时**照原样保留**。

## 11. 外部文件的相对名依赖「文档目录」

`.scad` 里的 `import(file = "x.dxf")` 相对**它自己所在目录**解析；
而我们 Python 侧是通过 `eval_text` 拼源码求值的，没有文档目录 → 写相对名会**静默返回空几何**。
一律写绝对路径（`PYTHONPATH=py` 下用 `moz.data_path("examples", "<分类>", "x.dxf")` 取——那就是
从上游示例目录复制到 `py/moz_data/examples/` 的同一份数据）。

顺带：C ABI 早期版本在 `moz_eval_file("相对路径")` 时 chdir 到文档目录却又用相对文档名解析兄弟文件，
也会静默变空——已修（路径先绝对化）。记住原理即可。

## 12. 浮点循环与求和顺序

- `for (i = [a : step : b])` 是按 `i += step` **累加**的，Python 侧必须用 `while` 复刻
  （`range`/`arange` 会得到不同的浮点值）。示例：`Old/example020`(spring 的 `stepsize` 循环)、
  `example019` 的 `[-100:5:+100]`。
- `Functions/polygon_areas.scad` 的递归 `sum()` 是**右结合**累加
  （`v[0] + (v[1] + (v[2] + ...))`），Python 的 `sum()` 是左结合，末位会不同——面积取整后可能变。

## 13. 空几何的维度仍然是 3

`CGAL_Nef_polyhedron::getDimension()` 恒为 3，所以 `Functions/echo.scad` 这种没有几何的模型
`dimension == 3`、`is_empty == 1`。判断「有没有东西」要用 `is_empty`，
Python 侧预览器也据此判断（否则会去建一个空网格）。

## 14. 配色方案来自 JSON，共享库需要资源目录

非默认配色（`Tomorrow`、`Starnight`…）不是写死在 C++ 里，而是从
`<资源目录>/color-schemes/render/*.json` 枚举出来的。共享库没有「应用路径」，
默认只能拿到内置的 `Cornfield`。本项目用 `MOZ_OPENSCAD_RESOURCE_DIR` 指到 `3rd/openscad`
（`moz_openscad.py` 会自动填，见 [build.md](build.md)）。

## 15. 上游本身就有「有颜色 / 无颜色」两条渲染路径

`openscad --render=cgal -o x.png` 是**无颜色**的（`CGALRenderer` 只用配色方案的材质色）；
有颜色的是 preview 路径（`CsgInfo` + `OpenCSGRenderer`/`ThrownTogetherRenderer`，即 GUI F5）。
本项目默认走 preview 路径，并保留 `renderer="cgal"` 复现上游行为。

## 16. MCAD 之类的子模块不在 OpenSCAD 源码包里

`3rd/openscad/libraries/MCAD/` 在源码包里是**空目录**（上游用 submodule 管理），
`tests/` 目录也依赖它。本项目把自研的 drop-in 放在随包数据目录
（`py/moz_data/libraries/MCAD/fonts.scad`，只实现 `8bit_polyfont()`，见 [third-party.md](third-party.md)），
因此 `Old/example023.scad` 能直接跑出几何（引擎会把 `<资源>/libraries` 加进库搜索路径）；
上游那份 MCAD 文件里的 `polytext()` / `braille_*` 等模块没有实现。