import sys
import os
import json
import re
import time
import keyboard
import ctypes
import winreg
from ctypes import wintypes
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton, QComboBox, QCheckBox,
                               QSystemTrayIcon, QMenu, QFileDialog, QSlider,
                               QTabWidget, QGroupBox, QTextEdit, QListWidget,
                               QLineEdit, QSizePolicy, QScrollArea,
                               QMessageBox)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QPoint, QRect
from PySide6.QtGui import QIcon, QFont, QAction, QPixmap, QPainter, QColor

# ================== 底层 SendInput API ==================
PUL = ctypes.POINTER(ctypes.c_ulong)
class KeyBdInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]
class HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_short), ("wParamH", ctypes.c_ushort)]
class MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]
class Input_I(ctypes.Union):
    _fields_ = [("ki", KeyBdInput), ("mi", MouseInput), ("hi", HardwareInput)]
class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", Input_I)]

def make_input(vk, scan, flags):
    inp = Input()
    inp.type = 1
    inp.ii.ki.wVk = vk
    inp.ii.ki.wScan = scan
    inp.ii.ki.dwFlags = flags
    return inp

def send_replace_input(backspace_count, text):
    inputs = []
    for _ in range(backspace_count):
        inputs.append(make_input(0x08, 0, 0))
        inputs.append(make_input(0x08, 0, 2))
    for char in text:
        inputs.append(make_input(0, ord(char), 4))
        inputs.append(make_input(0, ord(char), 4 | 2))
    n_inputs = len(inputs)
    p_inputs = (Input * n_inputs)(*inputs)
    ctypes.windll.user32.SendInput(n_inputs, p_inputs, ctypes.sizeof(Input))

# ================== 系统状态获取 ==================
class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT)
    ]

def get_caret_pos():
    try:
        gui_info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
        if ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui_info)):
            if gui_info.hwndCaret:
                pt = wintypes.POINT(gui_info.rcCaret.left, gui_info.rcCaret.bottom)
                ctypes.windll.user32.ClientToScreen(gui_info.hwndCaret, ctypes.byref(pt))
                if pt.x > 0 and pt.y > 0:
                    return pt.x, pt.y
    except Exception: pass
    return None

def get_active_window_info():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buff = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
    return hwnd, buff.value

def get_foreground_hwnd():
    return ctypes.windll.user32.GetForegroundWindow()

def is_password_field():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd: return False
        thread_id = ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)
        gui_info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
        if not ctypes.windll.user32.GetGUIThreadInfo(thread_id, ctypes.byref(gui_info)):
            return False
        focus = gui_info.hwndFocus
        if not focus: return False
        GWL_STYLE = -16
        ES_PASSWORD = 0x0020
        style = ctypes.windll.user32.GetWindowLongW(focus, GWL_STYLE)
        return bool(style & ES_PASSWORD)
    except Exception:
        return False

def is_ime_active():
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd: return False
        ime_wnd = ctypes.windll.imm32.ImmGetDefaultIMEWnd(hwnd)
        if not ime_wnd: return False

        WM_IME_CONTROL = 0x0283
        IMC_GETOPENSTATUS = 0x0005
        IMC_GETCONVERSIONMODE = 0x0001
        IME_CMODE_NATIVE = 0x0001
        SMTO_ABORTIFHUNG = 0x0002

        def _send_ime(ime_wnd_, msg, wp, lp):
            res = ctypes.c_size_t()
            ok = ctypes.windll.user32.SendMessageTimeoutW(ime_wnd_, msg, wp, lp, SMTO_ABORTIFHUNG, 50, ctypes.byref(res))
            return res.value if ok else 0

        open_status = _send_ime(ime_wnd, WM_IME_CONTROL, IMC_GETOPENSTATUS, 0)
        if not open_status: return False

        himc = ctypes.windll.imm32.ImmGetContext(hwnd)
        if himc:
            comp_len = ctypes.windll.imm32.ImmGetCompositionStringW(himc, 0x0008, None, 0)
            ctypes.windll.imm32.ImmReleaseContext(hwnd, himc)
            if comp_len > 0: return True

        conv = _send_ime(ime_wnd, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0)
        return bool(conv & IME_CMODE_NATIVE)
    except Exception:
        return False

def bounded_levenshtein(s1, s2, max_dist):
    if s1 == s2: return 0
    if abs(len(s1) - len(s2)) > max_dist: return max_dist + 1
    if len(s1) > len(s2): s1, s2 = s2, s1
    prev = list(range(len(s1) + 1))
    for i, c2 in enumerate(s2, 1):
        curr = [i]
        row_min = i
        for j, c1 in enumerate(s1, 1):
            cost = 0 if c1 == c2 else 1
            val = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            curr.append(val)
            if val < row_min: row_min = val
        if row_min > max_dist: return max_dist + 1
        prev = curr
    return prev[-1]

# ================== 多语言字典 ==================
LANG_DICT = {
    "zh": {
        "title": "EnglishAutoComplete - 设置", "tab_gen": "常规与行为", "tab_ui": "外观与皮肤",
        "tab_dict": "词库与配置", "tab_priv": "隐私与排除", "lang": "界面语言:",
        "autostart": "开机自动启动", "delay": "触发延迟(ms):", "min_len": "最小触发长度:",
        "max_res": "最大候选数:", "add_space": "补全后自动加空格", "fuzzy": "开启模糊匹配 (拼写纠错)",
        "undo_cap": "智能撤销 (上屏后按退格，可撤销并恢复之前的拼写)",
        "skip_ime": "中文输入法激活时暂停补全 (避免与输入法候选框冲突)",
        "ui_style": "候选框皮肤:", "font_size": "字体大小:", "preview": "预览效果:",
        "dict_path": "当前主词库:", "change_dict": "更改", "import_prof": "导入配置与词频",
        "export_prof": "导出配置与词频", "enable_learn": "记录使用频率 (越常用越靠前)",
        "learn_tip": "注：学习数据保存在独立文件中，不会修改原 txt",
        "disable_pwd": "密码框/敏感输入框禁用补全",
        "save_btn": "保存并应用", "reset_btn": "还原默认设置",
        "menu_set": "设置", "menu_quit": "退出"
    },
    "en": {
        "title": "EnglishAutoComplete - Settings", "tab_gen": "General", "tab_ui": "Appearance",
        "tab_dict": "Dictionary & Profile", "tab_priv": "Privacy", "lang": "Language:",
        "autostart": "Start with Windows", "delay": "Trigger Delay(ms):", "min_len": "Min Word Length:",
        "max_res": "Max Candidates:", "add_space": "Add Space after completion", "fuzzy": "Enable Fuzzy Match (Typo correction)",
        "undo_cap": "Smart Undo (Press Backspace after completion to restore)",
        "skip_ime": "Pause when IME is active (avoid IME popup conflict)",
        "ui_style": "UI Style:", "font_size": "Font Size:", "preview": "Preview:",
        "dict_path": "Current Dict:", "change_dict": "Change", "import_prof": "Import Profile",
        "export_prof": "Export Profile", "enable_learn": "Learn Frequency",
        "learn_tip": "Note: Saved in a separate file, original txt untouched",
        "disable_pwd": "Disable in password fields",
        "save_btn": "Save & Apply", "reset_btn": "Restore Defaults",
        "menu_set": "Settings", "menu_quit": "Quit"
    }
}

# ================== 配置管理 ==================
def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LEARN_FILE = os.path.join(DATA_DIR, "learn.json")

def resolve_path(p):
    if not p: return p
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(BASE_DIR, p))

def make_portable_path(p):
    if not p: return p
    abs_p = os.path.abspath(p)
    try:
        rel = os.path.relpath(abs_p, BASE_DIR)
        if not rel.startswith(".."):
            return rel
    except ValueError:
        pass
    return abs_p

DEFAULT_CONFIG = {
    "dict_path": "data/20k.txt",
    "max_results": 5, "block_short_words": True, "show_length": 2,
    "font_size": 12, "ui_style": "microsoft", "lang": "zh",
    "trigger_delay": 50, "add_space": True, "enable_learn": True,
    "fuzzy_match": True, "undo_cap": True, "autostart": False,
    "disable_password": True, "skip_ime": True,
}

def load_json(file, default):
    if os.path.exists(file):
        try:
            with open(file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[警告] 读取 {file} 失败: {e}，使用默认值")
    return default

def save_json(file, data):
    tmp = file + ".tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, file)
    finally:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except OSError: pass

def find_local_dict(original_path=None):
    candidates = []
    if original_path:
        basename = os.path.basename(original_path)
        candidates.extend([
            os.path.join(BASE_DIR, "data", basename),
            os.path.join(BASE_DIR, basename),
        ])
    candidates.extend([
        os.path.join(BASE_DIR, "data", "20k.txt"),
        os.path.join(BASE_DIR, "20k.txt"),
        os.path.join(DATA_DIR, "20k.txt"),
    ])
    
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

# ================== 词库核心引擎 ==================
class WordEngine:
    RECENT_WINDOW = 7 * 24 * 3600
    RECENT_BONUS = 3000

    def __init__(self):
        if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
        self.config = DEFAULT_CONFIG.copy()
        self.config.update(load_json(CONFIG_FILE, {}))
        if self.config.get("dict_path"):
            self.config["dict_path"] = make_portable_path(self.config["dict_path"])
        self.learn_data = self._normalize_learn(load_json(LEARN_FILE, {}))
        self.words = []
        self._learn_dirty = False
        self.dict_error = None
        self.reload_dictionary()

    def _normalize_learn(self, raw):
        normalized = {}
        for k, v in (raw or {}).items():
            if isinstance(v, dict):
                normalized[k] = {
                    "count": int(v.get("count", 0)),
                    "last": float(v.get("last", 0)),
                }
            else:
                normalized[k] = {"count": int(v), "last": 0.0}
        return normalized

    def _learn_score(self, word):
        entry = self.learn_data.get(word)
        if not entry: return 0
        if isinstance(entry, dict):
            count = entry.get("count", 0)
            last = entry.get("last", 0)
            score = count * 1000
            if last and (time.time() - last) <= self.RECENT_WINDOW:
                score += self.RECENT_BONUS
            return score
        return int(entry) * 1000

    def reload_dictionary(self):
        self.words = []
        self.dict_error = None
        path = resolve_path(self.config["dict_path"])

        if not os.path.exists(path):
            local = find_local_dict(path)
            if local:
                self.config["dict_path"] = make_portable_path(local)
                try:
                    save_json(CONFIG_FILE, self.config)
                except Exception:
                    pass
                path = local
                print(f"[提示] 已自动回退词库: {local}")

        if not os.path.exists(path):
            self.dict_error = f"词库文件不存在: {path}（dict_path={self.config['dict_path']}）"
            print(f"[警告] {self.dict_error}")
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for index, line in enumerate(f):
                    parts = line.strip().split()
                    if not parts: continue
                    word = parts[0].lower()
                    if not re.match(r'^[a-zA-Z]+$', word): continue
                    if self.config["block_short_words"] and len(word) <= 2: continue
                    freq = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else (100000 - index)
                    self.words.append((word, freq))
        except Exception as e:
            self.dict_error = f"读取主词库失败: {e}"
            print(self.dict_error)

    def save_learn(self): save_json(LEARN_FILE, self.learn_data)

    def record_selection(self, word):
        if self.config["enable_learn"]:
            entry = self.learn_data.get(word)
            if isinstance(entry, dict):
                entry["count"] = entry.get("count", 0) + 1
                entry["last"] = time.time()
            else:
                self.learn_data[word] = {"count": 1, "last": time.time()}
            self._learn_dirty = True

    def flush_learn(self):
        if getattr(self, "_learn_dirty", False):
            self.save_learn()
            self._learn_dirty = False

    def search(self, prefix):
        if not prefix: return []
        matched = []
        prefix_lower = prefix.lower()
        enable_learn = self.config["enable_learn"]
        max_results = self.config["max_results"]

        for word, freq in self.words:
            if word.startswith(prefix_lower):
                score = freq + 1000000
                if enable_learn:
                    score += self._learn_score(word)
                matched.append((score, len(word), word))

        fuzzy_trigger_threshold = max_results * 2
        if self.config.get("fuzzy_match") and len(prefix_lower) >= 3 and len(matched) < fuzzy_trigger_threshold:
            max_dist = 2 if len(prefix_lower) <= 5 else 3
            first_char = prefix_lower[0]
            for word, freq in self.words:
                if word[0] != first_char: continue
                if word.startswith(prefix_lower): continue
                w_prefix = word[:len(prefix_lower)] if len(word) >= len(prefix_lower) else word
                dist = bounded_levenshtein(prefix_lower, w_prefix, max_dist)
                if dist <= max_dist:
                    ratio = 1.0 - dist / max(len(prefix_lower), 1)
                    score = freq * ratio
                    if enable_learn:
                        score += self._learn_score(word)
                    matched.append((score, len(word), word))

        seen = set()
        unique_matched = []
        matched.sort(key=lambda x: (-x[0], x[1]))
        for item in matched:
            if item[2] not in seen:
                seen.add(item[2])
                unique_matched.append(item)

        return [w for _, _, w in unique_matched[:50]]

# ================== 键盘监听 ==================
class KeyboardListener(QThread):
    key_pressed = Signal(str, str, str, str)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.current_word = ""
        self.is_running = True
        self.hook_id = None
        self.is_sending = False
        self.current_results = []
        self.visible = False
        self.current_page = 0
        self.highlight_index = 0
        self.last_hwnd = 0
        self.last_autocorrect = None
        self.pending_echoes = 0
        self.echo_deadline = 0.0

    def run(self):
        try:
            self.hook_id = keyboard.hook(self.on_key_event, suppress=True)
        except Exception as e:
            print(f"[警告] suppress=True 挂载失败，回退为不拦截模式: {e}")
            self.hook_id = keyboard.hook(self.on_key_event, suppress=False)

    def stop(self):
        self.is_running = False
        if self.hook_id: keyboard.unhook(self.hook_id)

    def on_key_event(self, event):
        if not self.is_running: return True
        if self.pending_echoes > 0 and time.time() > self.echo_deadline:
            self.pending_echoes = 0
        if self.pending_echoes > 0:
            if event.event_type == keyboard.KEY_DOWN:
                self.pending_echoes -= 1
            return True

        if self.is_sending: return True
        if event.event_type != keyboard.KEY_DOWN: return True

        curr_hwnd = get_foreground_hwnd()
        if curr_hwnd != self.last_hwnd:
            self.current_word = ""
            self.visible = False
            self.last_hwnd = curr_hwnd
            self.last_autocorrect = None
            self.key_pressed.emit("reset", "", "", "")

        key = event.name
        config = self.engine.config

        if config.get("undo_cap", True) and key == 'backspace' and self.last_autocorrect:
            if time.time() - self.last_autocorrect["timestamp"] < 3.0:
                info = self.last_autocorrect
                self.last_autocorrect = None
                self.current_word = info["prefix"]
                self.key_pressed.emit("undo_autocorrect", info["word"], info["append"], info["prefix"])
                self.key_pressed.emit("update", "", self.current_word, "")
                return False
            else:
                self.last_autocorrect = None

        if key != 'backspace':
            self.last_autocorrect = None

        if self.visible and key in ['-', '=', '[', ']']:
            max_res = config["max_results"]
            total_pages = (len(self.current_results) + max_res - 1) // max_res
            if key in ['=', ']']:
                if self.current_page < total_pages - 1:
                    self.current_page += 1
                    self.key_pressed.emit("page", "", "", "")
            else:
                if self.current_page > 0:
                    self.current_page -= 1
                    self.key_pressed.emit("page", "", "", "")
            return False

        if self.visible:
            if key.isdigit() and key != '0':
                key_num = int(key)
                if key_num <= config["max_results"]:
                    idx = key_num - 1 + (self.current_page * config["max_results"])
                    if idx < len(self.current_results):
                        self.trigger_select(idx, append_char="", is_digit=True)
                        return True
                self.visible = False
                self.key_pressed.emit("reset", key, "", "")
                return True
            elif key == 'tab':
                base = self.current_page * config["max_results"]
                self.trigger_select(base + self.highlight_index, append_char='')
                return False
            elif key == 'enter':
                base = self.current_page * config["max_results"]
                self.trigger_select(base + self.highlight_index, append_char='')
                return False
            elif key == 'space':
                base = self.current_page * config["max_results"]
                self.trigger_select(base + self.highlight_index, append_char=' ')
                return True
            elif key == 'esc':
                self.current_word = ""
                self.visible = False
                self.key_pressed.emit("reset", key, "", "")
                return False
            elif key in [',', '.', '?', '!']:
                base = self.current_page * config["max_results"]
                self.trigger_select(base + self.highlight_index, append_char=key)
                return True
            elif key != 'backspace' and not (len(key) == 1 and key.isalpha()):
                self.visible = False
                self.key_pressed.emit("reset", key, "", "")

        if key == 'backspace':
            self.current_word = self.current_word[:-1]
            self.key_pressed.emit("update", key, self.current_word, "")
            return True

        if key in ['left', 'right', 'up', 'down', 'home', 'end'] or len(key) > 1:
            self.current_word = ""
            self.visible = False
            self.key_pressed.emit("reset", key, "", "")
            return True

        if len(key) == 1 and key.isalpha():
            self.current_word += key
            self.key_pressed.emit("update", key, self.current_word, "")
            return True

        return True

    def trigger_select(self, index, append_char="", is_digit=False):
        if index >= len(self.current_results): return
        selected_word = self.current_results[index]
        extra_info = f"__DIGIT__{append_char}" if is_digit else f"__KEY__{append_char}"

        cfg = self.engine.config
        final_append = append_char
        if not final_append:
            final_append = ' ' if cfg["add_space"] else ''

        self.last_autocorrect = {
            "word": selected_word,
            "append": final_append,
            "prefix": self.current_word,
            "timestamp": time.time()
        }

        self.key_pressed.emit("select", selected_word, self.current_word, extra_info)
        self.current_word = ""
        self.visible = False
        self.current_results = []

# ================== 可点击/可悬浮的候选标签 ==================
class ClickableLabel(QLabel):
    clicked = Signal()
    entered = Signal()
    left = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.left.emit()
        super().leaveEvent(event)

# ================== 候选框 UI ==================
class CandidateWindow(QWidget):
    word_selected = Signal(str, str)
    highlight_changed = Signal(int)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.layout = QHBoxLayout(self)

        self.labels = []
        self.display_list = []
        self.highlight_index = 0

        for i in range(9):
            label = ClickableLabel()
            label.clicked.connect(lambda idx=i: self.on_mouse_click(idx))
            label.entered.connect(lambda idx=i: self.on_hover(idx))
            self.layout.addWidget(label)
            label.hide()
            self.labels.append(label)

        self.apply_style()
        self.hide()

    def on_mouse_click(self, index):
        if index < len(self.display_list):
            word = self.display_list[index]
            self.word_selected.emit(word, "__MOUSE__")

    def on_hover(self, index):
        if not self.isVisible() or index >= len(self.display_list):
            return
        if self.highlight_index != index:
            self.highlight_index = index
            self.refresh_labels_style()
            self.highlight_changed.emit(index)

    def leaveEvent(self, event):
        if self.isVisible() and self.highlight_index != 0:
            self.highlight_index = 0
            self.refresh_labels_style()
            self.highlight_changed.emit(0)
        super().leaveEvent(event)

    def apply_style(self):
        style = self.engine.config.get("ui_style", "microsoft")
        font_size = self.engine.config.get("font_size", 12)

        base_css = ""
        if style == "microsoft":
            base_css = "QWidget { background-color: #FFFFFF; border: 1px solid #CCCCCC; border-radius: 4px; } QLabel { color: #333; padding: 4px 8px; }"
            self.layout.setContentsMargins(4, 4, 4, 4); self.layout.setSpacing(10)
        elif style == "win11":
            base_css = "QWidget { background-color: #F3F3F3; border: 1px solid #E5E5E5; border-radius: 8px; } QLabel { color: #1A1A1A; padding: 4px 10px; }"
            self.layout.setContentsMargins(6, 4, 6, 4); self.layout.setSpacing(10)
        elif style == "macos":
            base_css = "QWidget { background-color: #F8F8F8; border: 1px solid #E0E0E0; border-radius: 12px; } QLabel { color: #222; padding: 4px 10px; }"
            self.layout.setContentsMargins(8, 4, 8, 4); self.layout.setSpacing(12)
        elif style == "flat":
            base_css = "QWidget { background-color: #FFFFFF; border: 1px solid #D4D4D4; border-radius: 0px; } QLabel { color: #333; padding: 4px 8px; }"
            self.layout.setContentsMargins(0, 0, 0, 0); self.layout.setSpacing(10)
        elif style == "dark":
            base_css = "QWidget { background-color: #2D2D2D; border: 1px solid #4D4D4D; border-radius: 8px; } QLabel { color: #EEE; padding: 4px 8px; }"
            self.layout.setContentsMargins(6, 4, 6, 4); self.layout.setSpacing(10)
        elif style == "blue":
            base_css = "QWidget { background-color: #E6F2FF; border: 1px solid #99C2FF; border-radius: 6px; } QLabel { color: #003366; padding: 4px 8px; }"
            self.layout.setContentsMargins(4, 4, 4, 4); self.layout.setSpacing(10)

        self.setStyleSheet(base_css)

        f = QFont()
        f.setFamilies(["Microsoft YaHei", "Segoe UI", "Arial"])
        f.setPointSize(font_size)
        for label in self.labels:
            label.setFont(f)

    def refresh_labels_style(self):
        style = self.engine.config.get("ui_style", "microsoft")
        for i in range(len(self.display_list)):
            if i == self.highlight_index:
                if style in ["microsoft", "flat"]:
                    color, text_c, b_rad = "#0067C0", "white", ("2px" if style == "microsoft" else "0px")
                elif style in ["macos", "win11"]:
                    color, text_c, b_rad = "#D3E3FD", "#111", ("6px" if style == "win11" else "8px")
                elif style == "dark":
                    color, text_c, b_rad = "#0078D7", "white", "4px"
                else:
                    color, text_c, b_rad = "#3399FF", "white", "4px"

                self.labels[i].setStyleSheet(f"background-color: {color}; color: {text_c}; border-radius: {b_rad}; padding: 4px 8px;")
            else:
                text_c = "#EEE" if style == "dark" else ("#222" if style in ["macos", "win11"] else "#333")
                self.labels[i].setStyleSheet(f"background-color: transparent; border: none; color: {text_c}; padding: 4px 8px;")

    def update_candidates(self, results, page=0, max_res=5):
        if not results:
            self.hide(); return

        self.current_results = results
        start_idx = page * max_res
        self.display_list = results[start_idx : start_idx + max_res]
        self.highlight_index = 0
        self.highlight_changed.emit(0)

        for i in range(9):
            if i < len(self.display_list):
                self.labels[i].setText(f"{i+1}. {self.display_list[i]}")
                self.labels[i].show()
            else:
                self.labels[i].hide()

        self.refresh_labels_style()

        self.adjustSize()
        if not self.isVisible(): self.show()
        self.move_to_caret()

    def move_to_caret(self):
        pos = get_caret_pos()
        if pos:
            x, y = pos
            screen = QApplication.screenAt(QPoint(x, y))
            if not screen: screen = QApplication.primaryScreen()
            geo = screen.availableGeometry()

            if x + self.width() > geo.right(): x = geo.right() - self.width() + 1
            if x < geo.left(): x = geo.left()

            if y + self.height() > geo.bottom():
                y = y - self.height() - 20
                if y < geo.top(): y = geo.bottom() - self.height() + 1
            else:
                y += 8

            if abs(self.pos().x() - x) > 2 or abs(self.pos().y() - y) > 2:
                self.move(x, y)
        else:
            try:
                pt = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                x, y = pt.x, pt.y
                screen = QApplication.screenAt(QPoint(x, y))
                if not screen: screen = QApplication.primaryScreen()
                geo = screen.availableGeometry()

                px = x + 10
                py = y + 20

                if px + self.width() > geo.right(): px = geo.right() - self.width() + 1
                if py + self.height() > geo.bottom(): py = geo.bottom() - self.height() + 1

                if abs(self.pos().x() - px) > 2 or abs(self.pos().y() - py) > 2:
                    self.move(px, py)
            except Exception:
                pass

# ================== 设置界面 UI ==================
class SettingsWindow(QWidget):
    def __init__(self, engine, candidate_ui):
        super().__init__()
        self.engine = engine
        self.candidate_ui = candidate_ui
        self.setMinimumSize(620, 620)
        self.resize(660, 700)
        self.init_ui()
        self.apply_language()

        self.setStyleSheet("""
            QWidget { font-family: "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 13px; color: #333333; background-color: #F9F9F9; }
            QTabWidget::pane { border: 1px solid #E5E5E5; border-radius: 6px; background-color: #FFFFFF; top: -1px; }
            QTabBar::tab { background-color: #F0F0F0; border: 1px solid #E5E5E5; padding: 8px 18px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
            QTabBar::tab:selected { background-color: #FFFFFF; border-bottom-color: #FFFFFF; color: #0078D4; font-weight: bold; }
            QTabBar::tab:hover:!selected { background-color: #E5F1FB; }
            QPushButton { background-color: #FFFFFF; border: 1px solid #CCCCCC; border-radius: 4px; padding: 6px 16px; min-width: 60px; }
            QPushButton:hover { background-color: #F0F8FF; border-color: #0078D4; }
            QPushButton:pressed { background-color: #E0F0FF; }
            QComboBox, QLineEdit, QTextEdit { border: 1px solid #CCCCCC; border-radius: 4px; padding: 4px; background-color: #FFFFFF; }
            QComboBox:hover, QTextEdit:hover { border-color: #0078D4; }
            QCheckBox { spacing: 8px; }
            QSlider::groove:horizontal { height: 4px; background: #CCCCCC; border-radius: 2px; }
            QSlider::handle:horizontal { background: #0078D4; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }
            QSlider::handle:horizontal:hover { background: #005A9E; }
        """)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        self.tabs = QTabWidget()

        self.w_gen = QWidget(); l_gen = QVBoxLayout(self.w_gen)
        l_gen.setSpacing(12); l_gen.setContentsMargins(20, 20, 20, 20)

        self.hl_lang = QHBoxLayout()
        self.lbl_lang = QLabel()
        self.combo_lang = QComboBox(); self.combo_lang.addItems(["中文", "English"])
        self.combo_lang.setCurrentIndex(0 if self.engine.config["lang"] == "zh" else 1)
        self.combo_lang.currentIndexChanged.connect(self.change_lang_preview)
        self.hl_lang.addWidget(self.lbl_lang); self.hl_lang.addWidget(self.combo_lang); self.hl_lang.addStretch()
        l_gen.addLayout(self.hl_lang)

        self.check_autostart = QCheckBox(); self.check_autostart.setChecked(self.engine.config["autostart"]); l_gen.addWidget(self.check_autostart)

        self.hl_delay = QHBoxLayout(); self.lbl_delay = QLabel()
        self.slider_delay = QSlider(Qt.Horizontal); self.slider_delay.setRange(0, 500); self.slider_delay.setValue(self.engine.config["trigger_delay"])
        self.hl_delay.addWidget(self.lbl_delay); self.hl_delay.addWidget(self.slider_delay); l_gen.addLayout(self.hl_delay)

        self.hl_len = QHBoxLayout(); self.lbl_min_len = QLabel()
        self.combo_min_len = QComboBox(); self.combo_min_len.addItems([str(i) for i in range(1, 6)]); self.combo_min_len.setCurrentText(str(self.engine.config["show_length"]))
        self.lbl_max_res = QLabel()
        self.combo_max_res = QComboBox()
        self.combo_max_res.addItems([str(i) for i in range(1, 10)])
        self.combo_max_res.setCurrentText(str(self.engine.config["max_results"]))
        self.hl_len.addWidget(self.lbl_min_len); self.hl_len.addWidget(self.combo_min_len)
        self.hl_len.addWidget(self.lbl_max_res); self.hl_len.addWidget(self.combo_max_res); l_gen.addLayout(self.hl_len)

        self.check_space = QCheckBox(); self.check_space.setChecked(self.engine.config["add_space"]); l_gen.addWidget(self.check_space)
        self.check_fuzzy = QCheckBox(); self.check_fuzzy.setChecked(self.engine.config["fuzzy_match"]); l_gen.addWidget(self.check_fuzzy)
        self.check_undo = QCheckBox(); self.check_undo.setChecked(self.engine.config["undo_cap"]); l_gen.addWidget(self.check_undo)
        self.check_ime = QCheckBox(); self.check_ime.setChecked(self.engine.config.get("skip_ime", True)); l_gen.addWidget(self.check_ime)
        l_gen.addStretch()

        self.w_ui = QWidget(); l_ui = QVBoxLayout(self.w_ui)
        l_ui.setSpacing(12); l_ui.setContentsMargins(20, 20, 20, 20)

        self.hl_style = QHBoxLayout(); self.lbl_style = QLabel()
        self.combo_style = QComboBox()
        self.combo_style.addItem("微软拼音", "microsoft")
        self.combo_style.addItem("Win11 风格", "win11")
        self.combo_style.addItem("Mac 浅灰", "macos")
        self.combo_style.addItem("极简直角", "flat")
        self.combo_style.addItem("暗黑模式", "dark")
        self.combo_style.addItem("清新浅蓝", "blue")

        for i in range(self.combo_style.count()):
            if self.combo_style.itemData(i) == self.engine.config["ui_style"]: self.combo_style.setCurrentIndex(i)
        self.hl_style.addWidget(self.lbl_style); self.hl_style.addWidget(self.combo_style); l_ui.addLayout(self.hl_style)

        self.lbl_preview = QLabel()
        l_ui.addWidget(self.lbl_preview)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setFixedHeight(100)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.preview_box = QWidget()
        self.preview_layout = QHBoxLayout(self.preview_box)
        self.preview_layout.setContentsMargins(10, 10, 10, 10)
        self.preview_layout.setSpacing(15)

        self.preview_labels = [QLabel(f"{i+1}. exam") for i in range(5)]
        for lab in self.preview_labels:
            lab.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
            self.preview_layout.addWidget(lab)

        self.preview_scroll.setWidget(self.preview_box)
        l_ui.addWidget(self.preview_scroll)

        self.hl_font = QHBoxLayout(); self.lbl_font = QLabel()
        self.slider_font = QSlider(Qt.Horizontal); self.slider_font.setRange(8, 24); self.slider_font.setValue(self.engine.config["font_size"])
        self.slider_font.valueChanged.connect(self.update_preview)
        self.hl_font.addWidget(self.lbl_font); self.hl_font.addWidget(self.slider_font); l_ui.addLayout(self.hl_font)
        l_ui.addStretch()
        self.combo_style.currentIndexChanged.connect(self.update_preview)

        self.w_dict = QWidget(); l_dict = QVBoxLayout(self.w_dict)
        l_dict.setSpacing(12); l_dict.setContentsMargins(20, 20, 20, 20)

        self.hl_dict1 = QHBoxLayout()
        self.lbl_dict = QLabel()
        self.btn_change_dict = QPushButton()
        self.btn_change_dict.clicked.connect(self.change_dict)
        self.hl_dict1.addWidget(self.lbl_dict); self.hl_dict1.addWidget(self.btn_change_dict); l_dict.addLayout(self.hl_dict1)

        self.hl_dict2 = QHBoxLayout()
        self.btn_import = QPushButton(); self.btn_import.clicked.connect(self.import_profile)
        self.btn_export = QPushButton(); self.btn_export.clicked.connect(self.export_profile)
        self.hl_dict2.addWidget(self.btn_import); self.hl_dict2.addWidget(self.btn_export); l_dict.addLayout(self.hl_dict2)

        self.check_learn = QCheckBox(); self.check_learn.setChecked(self.engine.config["enable_learn"]); l_dict.addWidget(self.check_learn)
        self.lbl_learn_tip = QLabel(); self.lbl_learn_tip.setStyleSheet("color: #888888; font-size: 12px;"); l_dict.addWidget(self.lbl_learn_tip)
        l_dict.addStretch()

        self.w_priv = QWidget(); l_priv = QVBoxLayout(self.w_priv)
        l_priv.setSpacing(12); l_priv.setContentsMargins(20, 20, 20, 20)

        self.check_pwd = QCheckBox(); self.check_pwd.setChecked(self.engine.config["disable_password"]); l_priv.addWidget(self.check_pwd)
        l_priv.addStretch()

        self.tabs.addTab(self.w_gen, "")
        self.tabs.addTab(self.w_ui, "")
        self.tabs.addTab(self.w_dict, "")
        self.tabs.addTab(self.w_priv, "")
        layout.addWidget(self.tabs)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 10, 0, 0)
        self.btn_reset = QPushButton()
        self.btn_reset.clicked.connect(self.restore_defaults)
        self.btn_reset.setStyleSheet("QPushButton { color: #D83B01; border-color: #FFB900; } QPushButton:hover { background-color: #FFF4CE; }")
        self.btn_save = QPushButton()
        self.btn_save.setStyleSheet("QPushButton { background-color: #0078D4; color: white; border: none; font-weight: bold; } QPushButton:hover { background-color: #106EBE; } QPushButton:pressed { background-color: #005A9E; }")
        self.btn_save.clicked.connect(self.save_all)

        btn_layout.addWidget(self.btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

        self.update_preview()

    def apply_language(self):
        lang = self.engine.config.get("lang", "zh")
        t = LANG_DICT.get(lang, LANG_DICT["zh"])

        self.setWindowTitle(t["title"])
        self.tabs.setTabText(0, t["tab_gen"]); self.tabs.setTabText(1, t["tab_ui"])
        self.tabs.setTabText(2, t["tab_dict"]); self.tabs.setTabText(3, t["tab_priv"])

        self.lbl_lang.setText(t["lang"])
        self.check_autostart.setText(t["autostart"])
        self.lbl_delay.setText(t["delay"])
        self.lbl_min_len.setText(t["min_len"])
        self.lbl_max_res.setText(t["max_res"])
        self.check_space.setText(t["add_space"])
        self.check_fuzzy.setText(t["fuzzy"])
        self.check_undo.setText(t["undo_cap"])
        self.check_ime.setText(t["skip_ime"])

        self.lbl_style.setText(t["ui_style"])
        self.lbl_font.setText(t["font_size"])
        self.lbl_preview.setText(t["preview"])

        self.lbl_dict.setText(f"{t['dict_path']} {os.path.basename(resolve_path(self.engine.config['dict_path']))}")
        self.btn_change_dict.setText(t["change_dict"])
        self.btn_import.setText(t["import_prof"])
        self.btn_export.setText(t["export_prof"])
        self.check_learn.setText(t["enable_learn"])
        self.lbl_learn_tip.setText(t["learn_tip"])

        self.check_pwd.setText(t["disable_pwd"])

        self.btn_save.setText(t["save_btn"])
        self.btn_reset.setText(t["reset_btn"])

    def change_lang_preview(self):
        self.engine.config["lang"] = "zh" if self.combo_lang.currentIndex() == 0 else "en"
        try:
            save_json(CONFIG_FILE, self.engine.config)
        except Exception as e:
            print(f"[警告] 保存语言设置失败: {e}")
        self.apply_language()

    def update_preview(self):
        style = self.combo_style.currentData()
        size = self.slider_font.value()

        base = ""; h_color = ""; h_text = ""; h_rad = ""
        if style == "microsoft":
            base = "QWidget { background: #FFF; border: 1px solid #CCC; border-radius: 4px; }"
            h_color, h_text, h_rad = "#0067C0", "white", "2px"
        elif style == "win11":
            base = "QWidget { background: #F3F3F3; border: 1px solid #E5E5E5; border-radius: 8px; }"
            h_color, h_text, h_rad = "#D3E3FD", "#111", "6px"
        elif style == "macos":
            base = "QWidget { background: #F8F8F8; border: 1px solid #E0E0E0; border-radius: 12px; }"
            h_color, h_text, h_rad = "#D3E3FD", "#111", "8px"
        elif style == "flat":
            base = "QWidget { background: #FFF; border: 1px solid #D4D4D4; border-radius: 0px; }"
            h_color, h_text, h_rad = "#0067C0", "white", "0px"
        elif style == "dark":
            base = "QWidget { background: #2D2D2D; border: 1px solid #4D4D4D; border-radius: 8px; }"
            h_color, h_text, h_rad = "#0078D7", "white", "4px"
        elif style == "blue":
            base = "QWidget { background: #E6F2FF; border: 1px solid #99C2FF; border-radius: 6px; }"
            h_color, h_text, h_rad = "#3399FF", "white", "4px"

        self.preview_box.setStyleSheet(base)

        for i, lab in enumerate(self.preview_labels):
            if i == 0:
                lab.setStyleSheet(f"font-size: {size}px; font-weight: normal; background-color: {h_color}; color: {h_text}; border-radius: {h_rad}; padding: 4px 8px;")
            else:
                lab.setStyleSheet(f"font-size: {size}px; font-weight: normal; background-color: transparent; border: none; color: #333; padding: 4px 8px;")

        self.preview_box.adjustSize()
        self.preview_layout.invalidate()

    def restore_defaults(self):
        self.engine.config = DEFAULT_CONFIG.copy()
        save_json(CONFIG_FILE, self.engine.config)
        self.refresh_ui_from_config()
        self.engine.reload_dictionary()
        self.candidate_ui.apply_style()
        self.set_autostart(self.engine.config["autostart"])

    def change_dict(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Dict", DATA_DIR, "Text (*.txt)")
        if path:
            self.engine.config["dict_path"] = make_portable_path(path)
            self.lbl_dict.setText(f"{LANG_DICT[self.engine.config['lang']]['dict_path']} {os.path.basename(path)}")

    def export_profile(self):
        default_file = os.path.join(DATA_DIR, "my_autocomplete_profile.json")
        path, _ = QFileDialog.getSaveFileName(self, "Export Profile", default_file, "JSON (*.json)")
        if path:
            cfg = dict(self.engine.config)
            if cfg.get("dict_path"):
                cfg["dict_path"] = make_portable_path(resolve_path(cfg["dict_path"]))
            profile = {"config": cfg, "learn": self.engine.learn_data}
            save_json(path, profile)
            self.btn_export.setText("导出成功!")
            QTimer.singleShot(2000, lambda: self.btn_export.setText(LANG_DICT[self.engine.config['lang']]["export_prof"]))

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profile", DATA_DIR, "JSON (*.json)")
        if path:
            try:
                profile = load_json(path, {})
                if "config" in profile and "learn" in profile:
                    imported_cfg = profile["config"]
                    raw_dict = imported_cfg.get("dict_path", "")
                    imported_portable = make_portable_path(resolve_path(raw_dict)) if raw_dict else DEFAULT_CONFIG["dict_path"]
                    if imported_portable and not os.path.exists(resolve_path(imported_portable)):
                        print(f"[警告] 导入的词典路径在本机不可用: {imported_portable}，回退默认词库")
                        imported_portable = DEFAULT_CONFIG["dict_path"]
                    imported_cfg["dict_path"] = imported_portable

                    self.engine.config.update(imported_cfg)
                    self.engine.learn_data = self.engine._normalize_learn(profile["learn"])
                    save_json(CONFIG_FILE, self.engine.config)
                    save_json(LEARN_FILE, self.engine.learn_data)
                    self.engine.reload_dictionary()
                    self.btn_import.setText("导入成功，即将刷新...")
                    QTimer.singleShot(1500, self.refresh_ui_from_config)
            except Exception as e:
                print(e)

    def refresh_ui_from_config(self):
        self.combo_lang.setCurrentIndex(0 if self.engine.config["lang"] == "zh" else 1)
        self.check_autostart.setChecked(self.engine.config["autostart"])
        self.slider_delay.setValue(self.engine.config["trigger_delay"])
        self.combo_min_len.setCurrentText(str(self.engine.config["show_length"]))
        self.combo_max_res.setCurrentText(str(self.engine.config["max_results"]))
        self.check_space.setChecked(self.engine.config["add_space"])
        self.check_fuzzy.setChecked(self.engine.config["fuzzy_match"])
        self.check_undo.setChecked(self.engine.config["undo_cap"])
        self.check_ime.setChecked(self.engine.config.get("skip_ime", True))
        self.check_learn.setChecked(self.engine.config["enable_learn"])
        self.check_pwd.setChecked(self.engine.config["disable_password"])
        self.btn_import.setText(LANG_DICT[self.engine.config['lang']]["import_prof"])

        for i in range(self.combo_style.count()):
            if self.combo_style.itemData(i) == self.engine.config["ui_style"]:
                self.combo_style.setCurrentIndex(i)
                break
        self.slider_font.setValue(self.engine.config["font_size"])

        self.apply_language()
        self.update_preview()

    def save_all(self):
        c = self.engine.config
        c["lang"] = "zh" if self.combo_lang.currentIndex() == 0 else "en"
        c["autostart"] = self.check_autostart.isChecked()
        c["trigger_delay"] = self.slider_delay.value()
        c["show_length"] = int(self.combo_min_len.currentText())
        c["max_results"] = int(self.combo_max_res.currentText())
        c["add_space"] = self.check_space.isChecked()
        c["fuzzy_match"] = self.check_fuzzy.isChecked()
        c["undo_cap"] = self.check_undo.isChecked()
        c["skip_ime"] = self.check_ime.isChecked()
        c["ui_style"] = self.combo_style.currentData()
        c["font_size"] = self.slider_font.value()
        c["enable_learn"] = self.check_learn.isChecked()
        c["disable_password"] = self.check_pwd.isChecked()

        save_json(CONFIG_FILE, c)
        self.set_autostart(c["autostart"])

        self.engine.reload_dictionary()
        self.candidate_ui.apply_style()
        self.close()

    def set_autostart(self, enable):
        key = winreg.HKEY_CURRENT_USER
        sub_key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "EnglishAutoComplete"
        try:
            with winreg.OpenKey(key, sub_key, 0, winreg.KEY_ALL_ACCESS) as reg_key:
                if enable:
                    if getattr(sys, 'frozen', False):
                        cmd = f'"{sys.executable}"'
                    else:
                        cmd = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
                    winreg.SetValueEx(reg_key, app_name, 0, winreg.REG_SZ, cmd)
                else:
                    try: winreg.DeleteValue(reg_key, app_name)
                    except FileNotFoundError: pass
        except: pass

# ================== 核心控制器 ==================
class AppController:
    def __init__(self, app):
        self.app = app
        self.engine = WordEngine()
        self.candidate_ui = CandidateWindow(self.engine)
        self.candidate_ui.word_selected.connect(self.handle_mouse_select)
        self.candidate_ui.highlight_changed.connect(self._on_highlight_changed)

        self.listener = KeyboardListener(self.engine)
        self.listener.key_pressed.connect(self.handle_key)
        self.listener.start()

        self.settings_ui = SettingsWindow(self.engine, self.candidate_ui)
        self.tray = QSystemTrayIcon(self.app)

        # 读取托盘图标
        tray_icon_path = os.path.join(BASE_DIR, "assets", "tray_icon.png")
        if os.path.exists(tray_icon_path):
            self.tray.setIcon(QIcon(tray_icon_path))
        else:
            # 兜底：图片没找到就用代码画一个
            pixmap = QPixmap(32, 32); pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap); painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor("#0067C0")); painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(0, 0, 32, 32, 8, 8)
            painter.setPen(QColor("white")); painter.setFont(QFont("Arial", 16, QFont.Bold))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "A"); painter.end()
            self.tray.setIcon(QIcon(pixmap))

        self.tray.setToolTip("EnglishAutoComplete")
        self.tray.activated.connect(self.tray_activated)

        self.menu = QMenu()
        self.act_set = QAction("", self.app)
        self.act_set.triggered.connect(self.settings_ui.show)
        self.act_quit = QAction("", self.app)
        self.act_quit.triggered.connect(self.quit_app)
        self.menu.addAction(self.act_set); self.menu.addSeparator(); self.menu.addAction(self.act_quit)
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.update_tray_language()

        self.delay_timer = QTimer()
        self.delay_timer.setSingleShot(True)
        self.delay_timer.timeout.connect(self.trigger_search)
        self.pending_word = ""

        self.mouse_timer = QTimer()
        self.mouse_timer.timeout.connect(self.check_mouse_click)
        self.mouse_timer.start(50)
        self.last_mouse_state = 0

        self.learn_timer = QTimer()
        self.learn_timer.setInterval(3000)
        self.learn_timer.timeout.connect(self.engine.flush_learn)
        self.learn_timer.start()

        if getattr(self.engine, "dict_error", None):
            QTimer.singleShot(800, self._show_dict_missing_warning)

    def _show_dict_missing_warning(self):
        lang = self.engine.config.get("lang", "zh")
        if lang == "en":
            title = "Dictionary Missing"
            msg = (f"Dictionary file not found. Auto-completion will be disabled.\n\n"
                   f"{self.engine.dict_error}\n\n"
                   f"Please put '20k.txt' (or 'data/20k.txt') next to the program, "
                   f"or select a dictionary in Settings.")
        else:
            title = "词库缺失"
            msg = (f"未找到词库文件，自动补全功能将不可用。\n\n"
                   f"{self.engine.dict_error}\n\n"
                   f"请把 20k.txt（或 data/20k.txt）放到程序所在目录下，"
                   f"或在设置中重新选择词库。")
        QMessageBox.warning(None, title, msg)

    def _on_highlight_changed(self, idx):
        self.listener.highlight_index = idx

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.settings_ui.show()
            self.settings_ui.activateWindow()

    def check_mouse_click(self):
        state = ctypes.windll.user32.GetAsyncKeyState(0x01)
        if (state & 0x8000) and not (self.last_mouse_state & 0x8000):
            pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            # 【重要修复】：扩大判定范围，防止 DPI 缩放或边缘误差导致点击悬浮窗被误判为点击外部
            if self.candidate_ui.isVisible():
                rect = self.candidate_ui.geometry().adjusted(-20, -20, 20, 20)
                if rect.contains(pt.x, pt.y):
                    self.last_mouse_state = state
                    return
                
            self.listener.current_word = ""
            self.candidate_ui.hide()
            self.listener.visible = False
            self.delay_timer.stop()
            self.listener.last_autocorrect = None
        self.last_mouse_state = state

    def handle_mouse_select(self, word, extra_info):
        self.candidate_ui.hide()

        curr_hwnd = get_foreground_hwnd()
        # 【重要修复】：不强行因窗口切换而 return，因为点击候选框本身可能引起焦点波动
        # 更新 last_hwnd，防止下一次按键误判
        self.listener.last_hwnd = curr_hwnd
        
        self.listener.is_sending = True
        current_word = self.listener.current_word

        delete_count = len(current_word)
        append_str = ' ' if self.engine.config["add_space"] else ''

        self.listener.pending_echoes = delete_count + len(word + append_str)
        self.listener.echo_deadline = time.time() + 0.5

        send_replace_input(delete_count, word + append_str)
        self.listener.is_sending = False
        self.engine.record_selection(word.lower())

        self.listener.current_word = ""
        self.listener.visible = False
        self.listener.last_autocorrect = {
            "word": word,
            "append": append_str,
            "prefix": current_word,
            "timestamp": time.time()
        }

    def update_tray_language(self):
        lang = self.engine.config.get("lang", "zh")
        if getattr(self, "_last_tray_lang", None) == lang:
            return
        self._last_tray_lang = lang
        t = LANG_DICT.get(lang, LANG_DICT["zh"])
        self.act_set.setText(t["menu_set"])
        self.act_quit.setText(t["menu_quit"])

    def handle_key(self, event_type, key, current_word, extra_info):
        if event_type == "select":
            self.candidate_ui.hide()

            curr_hwnd = get_foreground_hwnd()
            if curr_hwnd != self.listener.last_hwnd:
                self.listener.is_sending = False
                return

            self.listener.is_sending = True

            delete_count = len(current_word)
            append_str = ""

            if extra_info.startswith("__DIGIT__"):
                delete_count += 1
            elif extra_info.startswith("__KEY__"):
                append_str = extra_info.replace("__KEY__", "")
                if append_str in [' ', ',', '.', '?', '!']:
                    delete_count += 1

            if self.engine.config["add_space"] and append_str == "":
                append_str = ' '

            text_to_send = key + append_str
            self.listener.pending_echoes = delete_count + len(text_to_send)
            self.listener.echo_deadline = time.time() + 0.5

            send_replace_input(delete_count, text_to_send)
            self.listener.is_sending = False
            self.engine.record_selection(key.lower())

        elif event_type == "undo_autocorrect":
            word = key
            append = current_word
            prefix = extra_info

            self.listener.is_sending = True
            delete_count = len(word) + len(append)
            self.listener.pending_echoes = delete_count + len(prefix)
            self.listener.echo_deadline = time.time() + 0.5
            send_replace_input(delete_count, prefix)
            self.listener.is_sending = False

        elif event_type == "page":
            self.candidate_ui.update_candidates(self.listener.current_results, self.listener.current_page, self.engine.config["max_results"])
        elif event_type == "reset":
            self.candidate_ui.hide()
            self.listener.visible = False
            self.delay_timer.stop()
        elif event_type == "update":
            self.pending_word = current_word
            self.delay_timer.start(self.engine.config["trigger_delay"])

        self.update_tray_language()

    def trigger_search(self):
        word = self.pending_word

        if self.is_excluded(): return

        if self.engine.config.get("skip_ime", True) and is_ime_active():
            self.candidate_ui.hide()
            self.listener.visible = False
            return

        if len(word) >= self.engine.config["show_length"]:
            results = self.engine.search(word)
            if results:
                self.listener.current_results = results
                self.listener.current_page = 0
                self.listener.visible = True
                self.candidate_ui.update_candidates(results, 0, self.engine.config["max_results"])
            else:
                self.candidate_ui.hide(); self.listener.visible = False
        else:
            self.candidate_ui.hide(); self.listener.visible = False

    def is_excluded(self):
        if self.engine.config["disable_password"]:
            if is_password_field():
                return True
            _, title = get_active_window_info()
            title_lower = title.lower().strip()
            if len(title_lower) <= 30 and any(w in title_lower for w in ["password", "登录", "密码"]):
                return True
        return False

    def quit_app(self):
        self.learn_timer.stop()
        self.engine.flush_learn()
        self.listener.stop()
        self.listener.wait()
        self.app.quit()

# ================== 程序入口 ==================
if __name__ == "__main__":
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "EnglishAutoComplete_Mutex_v1")
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(0, "EnglishAutoComplete 已在运行中。", "EnglishAutoComplete", 0x40)
        sys.exit(0)

    try:
        if ctypes.windll.shell32.IsUserAnAdmin() == 0:
            print("[提示] 当前为普通权限运行。如需覆盖管理员程序窗口，请『以管理员身份运行』。")
    except Exception:
        pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    
    # 读取应用主窗口图标 (左上角和任务栏)
    app_icon_path = os.path.join(BASE_DIR, "assets", "app_icon.png")
    if os.path.exists(app_icon_path):
        app.setWindowIcon(QIcon(app_icon_path))
        
    app.setQuitOnLastWindowClosed(False)
    controller = AppController(app)
    sys.exit(app.exec())
