一款纯本地的 Windows 英文自动补全工具。A pure local Windows English auto-completion tool
模仿拼音输入法的交互体验，仅支持 Windows 10 / 11
使用了AI工具并经人工调试

<img width="923" height="214" alt="Desktop 2026 11 06 - 16 15 37 01 - frame at 0m2s" src="https://github.com/user-attachments/assets/f3ba8d58-c9e7-4f18-9eb9-a31aa1c9b872" />

##  核心特性

- **丝滑补全**：输入字母即刻弹出候选框，支持 `Tab`、`Enter`、`空格` 或数字键快速上屏。
- **现代UI**：提供 6 种候选框皮肤（Win11、Mac、暗黑、极简等），支持自适应屏幕边缘防溢出。
- **智能学习**：常用词动态排序
- **模糊匹配**：拼写错误也能智能猜测（如 `recieve` -> `receive`）。
- **智能撤销**：上屏后如果不满意，按一下退格键即可瞬间恢复，继续选择。
- **隐私安全**：纯离线运行，不收集任何数据；自动在密码框/敏感输入框禁用。
- **可定制**：支持自定义词库导入导出、触发延迟、最大候选词数量。

<img width="662" height="732" alt="屏幕截图 2026-11-06 161827" src="https://github.com/user-attachments/assets/aceb9dd5-d4fb-4a09-ae44-59ffea64d4eb" />

## 普通用户：如何使用？

1. 点击本页面右侧的 **[Releases](https://github.com/2023829782/EnglishAutoComplete/releases)** 
2. 下载最新版本的 `EnglishAutoComplete.zip` 压缩包。
3. 解压到任意文件夹，**双击 `EnglishAutoComplete.exe` 即可运行**。
4. 词库可选择

>  **重要提示**：使用了全局键盘监听，部分杀毒软件可能会误报


##  二次开发

如果你想修改代码或自己编译，有以下要求：

1. **环境要求**：仅支持 Windows 10 / 11，需安装 Python 3.8+。
2. **安装依赖**：
   ```bash
   pip install -r requirements.txt
