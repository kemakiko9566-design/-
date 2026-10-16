# 配置 JSON

脚本入口：`douyin-chat-bubble/scripts/bubble_check.py`。配置使用 UTF-8 JSON，所有坐标均为源图像素。

## 最小示例

```json
{
  "source_size": [198, 162],
  "cuts": {"left": 72, "top": 84, "right": 144, "bottom": 108},
  "text_box": [37, 54, 155, 126],
  "protected_box": [60, 54, 132, 126],
  "font_size": 51,
  "artworks": [
    {
      "id": "red",
      "file": "red.png",
      "text_color": "#FFFFFF",
      "panel_box": [7, 30, 183, 150],
      "border_width": 3
    }
  ]
}
```

这些数值用于随包示例；其他图应重新规划。

## 字段

| 字段 | 含义 |
|---|---|
| `source_size` | 可选 `[宽,高]`，提供时须与 PNG 一致 |
| `cuts` | 必需；`left < right`、`top < bottom`，均在图内 |
| `text_box` | 必需 `[左,上,右,下]`；右下不包含，供检查与预览使用 |
| `protected_box` | 可选，位于文字框内的参考保护区 |
| `font_size` | 默认 51；当前官方固定字号。修改本地参数不代表平台支持改字号 |
| `panel_bounds` | 可选，所有素材共用的实体底板范围；被单项 `panel_box` 覆盖 |
| `artworks` | 至少一张素材的配置列表 |
| `artworks[].id` | 预览文件名标识，建议用简短英文字母/数字/连字符 |
| `artworks[].file` | 相对于配置 JSON 目录的图片路径 |
| `artworks[].text_color` | 正文色，例如 `#FFFFFF` |
| `artworks[].text_box` | 可选，覆盖共同文字框 |
| `artworks[].panel_box` | 可选，底板主体范围，不包括外伸装饰；供内部留白预检 |
| `artworks[].border_width` | 默认 0；计算声明内边距时扣除的描边宽度 |

额外说明性字段会被忽略。`panel_box` 是设计者声明的范围，不是脚本自动识别的底板；声明错误可能产生错误判断，需对照实际图像。

## 结果解释

- `local_pass`：硬检查是否通过。
- `errors` / `warnings`：错误与仍需人工查看的问题。
- `contrast_min` / `contrast_p01`：文字框内最低及第 1 百分位对比度，硬检查使用最低值。
- `declared_inside_padding_LTRB`：扣除描边后的声明内边距，顺序为左/上/右/下。
- `alpha_scans`：alpha≥128、alpha=255 的保守三分位置及邻近像素检查，不是抖音内部算法。
- `fixed_corners_preserved`：模拟伸缩时四角像素保持；不证明其他区域没有放错装饰。
- `preview`：提供字体且硬检查通过时生成的预览文件。

对比度覆盖声明的整个文字框，而非只检查当前样例的字形下方。原始图片与配置要一同交付，避免检查结果脱离其对象。
