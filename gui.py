"""微信 AI 自动回复 — 弹窗 GUI（默认启动方式）。"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import config
from logger import log, subscribe, unsubscribe
from main import Monitor
from personas import (
    get_style_label,
    list_styles,
    resolve_persona,
    resolve_style,
)


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("微信 AI 自动回复")
        self.root.geometry("620x780")
        self.root.minsize(560, 640)

        self._monitor: Monitor | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._log_handler = self._append_log
        self._style_busy = False
        self._config_busy = False
        self._pending_style: tuple[str, str, bool] | None = None
        self._style_apply_after_id: str | None = None
        self._style_trace_guard = False

        self._listen_mode_labels = {
            "selected": "指定联系人",
            "all": "全部联系人",
        }
        self._listen_mode_keys = {v: k for k, v in self._listen_mode_labels.items()}

        self._build_ui()
        subscribe(self._log_handler)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}

        top = ttk.LabelFrame(self.root, text="角色风格（监听中可随时切换）")
        top.pack(fill=tk.X, **pad)

        style_row = ttk.Frame(top)
        style_row.pack(fill=tk.X, padx=8, pady=(8, 4))

        self._styles = list_styles()
        self._styles_map = {label: key for key, label in self._styles}
        ttk.Label(style_row, text="风格").pack(side=tk.LEFT)
        default_style = resolve_style(config.DEFAULT_PERSONA)
        self.style_var = tk.StringVar(value=get_style_label(default_style))
        self.style_cb = ttk.Combobox(
            style_row,
            textvariable=self.style_var,
            values=[label for _, label in self._styles],
            state="readonly",
            width=14,
        )
        self.style_cb.pack(side=tk.LEFT, padx=(6, 16))
        self.style_cb.bind("<<ComboboxSelected>>", self._on_style_change)
        self.style_var.trace_add("write", self._on_style_var_change)

        self.apply_style_btn = ttk.Button(
            style_row, text="应用风格", command=self._apply_style, width=10
        )
        self.apply_style_btn.pack(side=tk.LEFT)

        self.style_hint_var = tk.StringVar(value="")
        ttk.Label(
            top,
            textvariable=self.style_hint_var,
            foreground="#666",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=8, pady=(4, 10))

        self.style_hint_var.set(
            f"当前选择：{self._current_style_label()}（启动后生效）"
        )

        info = ttk.LabelFrame(self.root, text="监听配置（.env，可修改后保存）")
        info.pack(fill=tk.X, **pad)

        ttk.Label(info, text="模式").grid(row=0, column=0, sticky=tk.W, padx=8, pady=6)
        mode_label = self._listen_mode_labels.get(config.LISTEN_MODE, "指定联系人")
        self.listen_mode_var = tk.StringVar(value=mode_label)
        self.listen_mode_cb = ttk.Combobox(
            info,
            textvariable=self.listen_mode_var,
            values=list(self._listen_mode_labels.values()),
            state="readonly",
            width=14,
        )
        self.listen_mode_cb.grid(row=0, column=1, sticky=tk.W, pady=6)

        ttk.Label(info, text="白名单").grid(row=1, column=0, sticky=tk.NW, padx=8, pady=4)
        self.targets_var = tk.StringVar(
            value=config.join_names(config.TARGET_NICKNAMES)
        )
        self.targets_entry = ttk.Entry(info, textvariable=self.targets_var, width=46)
        self.targets_entry.grid(
            row=1, column=1, columnspan=2, sticky=tk.EW, padx=(0, 8), pady=4
        )

        cfg_btn_row = ttk.Frame(info)
        cfg_btn_row.grid(row=2, column=0, columnspan=3, sticky=tk.EW, padx=8, pady=(4, 0))
        self.save_cfg_btn = ttk.Button(
            cfg_btn_row, text="保存配置", command=self._save_listen_config, width=10
        )
        self.save_cfg_btn.pack(side=tk.LEFT)

        self.config_hint_var = tk.StringVar(value="多人/群名用顿号（、）分隔，保存后写入 .env")
        ttk.Label(
            info,
            textvariable=self.config_hint_var,
            foreground="#666",
            wraplength=560,
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=3, sticky=tk.EW, padx=8, pady=(4, 10))

        info.columnconfigure(1, weight=1)
        self.listen_mode_cb.bind("<<ComboboxSelected>>", self._on_listen_mode_change)
        self._on_listen_mode_change()

        btn_row = ttk.Frame(self.root)
        btn_row.pack(fill=tk.X, **pad)
        btn_inner = ttk.Frame(btn_row)
        btn_inner.pack(fill=tk.X, padx=10)
        self.start_btn = ttk.Button(btn_inner, text="开始监听", command=self._start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.stop_btn = ttk.Button(
            btn_inner, text="停止", command=self._stop, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(
            btn_row,
            textvariable=self.status_var,
            foreground="#333",
            wraplength=580,
            justify=tk.RIGHT,
        ).pack(fill=tk.X, padx=10, pady=(4, 0))

        log_frame = ttk.LabelFrame(self.root, text="运行日志")
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, height=22, state=tk.DISABLED, font=("Consolas", 10)
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    def _listen_mode_key(self) -> str:
        label = self.listen_mode_var.get()
        return self._listen_mode_keys.get(label, "selected")

    def _on_listen_mode_change(self, _event=None) -> None:
        selected = self._listen_mode_key() == "selected"
        state = tk.NORMAL if selected else tk.DISABLED
        self.targets_entry.configure(state=state)
        if selected:
            self.config_hint_var.set("多人/群名用顿号（、）分隔，保存后写入 .env")
        else:
            self.config_hint_var.set("全部联系人模式：白名单无效，可用 IGNORE_NICKNAMES 排除")

    def _save_listen_config(self) -> None:
        if self._config_busy:
            return
        mode = self._listen_mode_key()
        targets_raw = self.targets_var.get().strip()
        if mode == "selected" and not targets_raw:
            messagebox.showwarning("配置无效", "指定联系人模式下，白名单不能为空。")
            return

        updates = {
            "LISTEN_MODE": mode,
            "TARGET_NICKNAMES": config.normalize_names_input(targets_raw),
            "REPLY_GROUP_CHATS": "true",
            "USE_CHAT_HISTORY": "true",
        }

        self._config_busy = True
        self.save_cfg_btn.configure(state=tk.DISABLED)

        def work() -> None:
            try:
                config.update_env_vars(updates)
                config.reload_listen_config()
                need_restart = False
                msg = "配置已保存"
                if self._running and self._monitor:
                    need_restart, msg = self._monitor.apply_listen_config()
                self.root.after(
                    0,
                    lambda: self._on_config_saved(msg, need_restart),
                )
            except Exception as e:
                self.root.after(
                    0,
                    lambda: self._on_config_failed(str(e)),
                )

        threading.Thread(target=work, daemon=True).start()

    def _on_config_saved(self, msg: str, need_restart: bool) -> None:
        self._config_busy = False
        self.save_cfg_btn.configure(state=tk.NORMAL)
        self.config_hint_var.set(msg)
        log(f"监听配置：{msg}")
        if need_restart:
            messagebox.showinfo(
                "需重启监听",
                "监听模式已变更，请先点「停止」，再点「开始监听」使新模式生效。",
            )

    def _on_config_failed(self, err: str) -> None:
        self._config_busy = False
        self.save_cfg_btn.configure(state=tk.NORMAL)
        messagebox.showerror("保存失败", err)

    def _style_key(self) -> str:
        label = self.style_var.get()
        return self._styles_map.get(label, resolve_style(config.DEFAULT_PERSONA))

    def _gender_key(self) -> str:
        g, _ = resolve_persona("", self._style_key())
        return g

    def _persona_key(self) -> str:
        return self._style_key()

    def _current_style_label(self) -> str:
        return get_style_label(self._style_key())

    def _set_style_var(self, value: str) -> None:
        self._style_trace_guard = True
        self.style_var.set(value)
        self._style_trace_guard = False

    def _on_style_var_change(self, *_args) -> None:
        if self._style_trace_guard:
            return
        self._schedule_style_apply(from_combobox=True, debounce=True)

    def _on_style_change(self, _event=None) -> None:
        self._schedule_style_apply(from_combobox=True)

    def _persist_style_choice(self, persona: str) -> None:
        try:
            config.update_env_vars({"PERSONA": persona})
        except Exception as e:
            log(f"风格未写入 .env：{e}")

    def _schedule_style_apply(
        self, from_combobox: bool = False, debounce: bool = False
    ) -> None:
        label = self._current_style_label()
        persona = self._persona_key()

        if not self._running or self._monitor is None:
            self.style_hint_var.set(f"当前选择：{label}（未监听，下次启动生效）")
            self._persist_style_choice(persona)
            if from_combobox:
                log(f"已选择风格：{label}（点「开始监听」后生效）")
            return

        gender = self._gender_key()
        self.style_hint_var.set(f"切换中：{label}…")
        self._pending_style = (gender, persona, from_combobox)
        if debounce:
            if self._style_apply_after_id:
                self.root.after_cancel(self._style_apply_after_id)
            self._style_apply_after_id = self.root.after(
                120, self._run_style_apply
            )
            return
        self._run_style_apply()

    def _apply_style(self, auto: bool = False) -> None:
        if not self._running or self._monitor is None:
            label = self._current_style_label()
            persona = self._persona_key()
            self._persist_style_choice(persona)
            self.style_hint_var.set(f"当前选择：{label}（未监听，下次启动生效）")
            log(f"已选择风格：{label}（点「开始监听」后生效）")
            return
        self._schedule_style_apply(from_combobox=auto)

    def _run_style_apply(self) -> None:
        self._style_apply_after_id = None
        if not self._pending_style or not self._running or self._monitor is None:
            self._pending_style = None
            return
        gender, persona, auto = self._pending_style
        self._pending_style = None
        if self._style_busy:
            self._pending_style = (gender, persona, auto)
            return
        self._style_busy = True
        try:
            display = self._monitor.apply_style(gender, persona)
            self._on_style_applied(display, auto)
        except Exception as e:
            self._on_style_failed(str(e))

    def _on_style_applied(self, display: str, auto: bool) -> None:
        self._style_busy = False
        if self._running:
            self.style_hint_var.set(f"当前风格：{display}")
            self.status_var.set(f"监听中 · {display}")
            log(f"风格已切换 → {display}")
        else:
            self.style_hint_var.set(f"当前选择：{display}（未监听，下次启动生效）")
        if self._running and self._pending_style:
            self.root.after(50, self._run_style_apply)

    def _on_style_failed(self, err: str) -> None:
        self._style_busy = False
        self._pending_style = None
        self.style_hint_var.set(f"切换失败：{self._current_style_label()}")
        if self._running:
            messagebox.showerror("切换失败", err)

    def _append_log(self, line: str) -> None:
        def do() -> None:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, line + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        try:
            self.root.after(0, do)
        except tk.TclError:
            pass

    def _start(self) -> None:
        if self._running:
            return
        gender = self._gender_key()
        persona = self._persona_key()
        gender, persona = resolve_persona(gender, persona)
        label = get_style_label(persona)

        try:
            self._monitor = Monitor(persona_key=persona, gender_key=gender)
        except SystemExit as e:
            messagebox.showerror("启动失败", str(e))
            return
        except Exception as e:
            messagebox.showerror("启动失败", str(e))
            return

        self._running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.status_var.set(f"监听中 · {label}")
        self.style_hint_var.set(f"当前风格：{label}")
        log(f"已启动 · {label}")

        def run_loop() -> None:
            try:
                if self._monitor:
                    self._monitor.run()
            except Exception as e:
                log(f"监听异常：{e}")
            finally:
                self.root.after(0, self._on_stopped)

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

    def _stop(self) -> None:
        if self._monitor:
            self._monitor.stop()
        self._on_stopped()

    def _on_stopped(self) -> None:
        if not self._running and self.stop_btn.cget("state") == tk.DISABLED:
            return
        if self._style_apply_after_id:
            try:
                self.root.after_cancel(self._style_apply_after_id)
            except Exception:
                pass
            self._style_apply_after_id = None
        self._running = False
        self._pending_style = None
        self._style_busy = False
        self.apply_style_btn.configure(state=tk.NORMAL)
        self.style_cb.configure(state="readonly")
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self.status_var.set("已停止")
        self.style_hint_var.set(
            f"当前选择：{self._current_style_label()}（未监听，下次启动生效）"
        )
        log("已停止监听")

    def _on_close(self) -> None:
        unsubscribe(self._log_handler)
        if self._monitor:
            self._monitor.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
