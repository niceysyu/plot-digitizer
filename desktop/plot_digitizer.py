#!/usr/bin/env python3
"""
Plot Digitizer — 그래프 이미지에서 데이터 포인트를 추출하는 데스크톱 도구
Dependencies: Python 3.8+ (tkinter 포함), Pillow
Run:   python plot_digitizer.py [image]
"""
import base64
import copy
import io
import json
import math
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

from PIL import Image, ImageDraw, ImageFont, ImageTk

try:
    from PIL import ImageGrab
except Exception:  # pragma: no cover
    ImageGrab = None

APP = "Plot Digitizer"
VERSION = "1.0"
COLORS = ["#e11d48", "#2563eb", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#4b5563"]
LAB = ["X1", "X2", "Y1", "Y2"]
CAL_COL = ["#0f766e", "#0f766e", "#9333ea", "#9333ea"]
IS_MAC = sys.platform == "darwin"
NEAREST = getattr(Image, "Resampling", Image).NEAREST
BILINEAR = getattr(Image, "Resampling", Image).BILINEAR


def fmt(v):
    if v is None or not math.isfinite(v):
        return ""
    a = abs(v)
    if a != 0 and (a < 1e-3 or a >= 1e5):
        return f"{v:.5e}"
    return f"{v:.6g}"


def proj(P, A, B):
    dx, dy = B[0] - A[0], B[1] - A[1]
    return ((P[0] - A[0]) * dx + (P[1] - A[1]) * dy) / (dx * dx + dy * dy)


def get_font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def make_demo_image():
    """Id–Vgs (log Y) 예제 그래프. returns (image, calib_points, values)."""
    W, H, L, T, PW, PH = 640, 440, 90, 24, 520, 350
    im = Image.new("RGB", (W, H), "white")
    g = ImageDraw.Draw(im)
    f13, f14 = get_font(13), get_font(14)
    px = lambda v: L + v / 1.5 * PW
    py = lambda y: T + PH - (math.log10(y) + 12) / 9 * PH
    for d in range(-12, -2):
        g.line([(L, py(10 ** d)), (L + PW, py(10 ** d))], fill="#e5e7eb")
    for i in range(7):
        v = i * 0.25
        g.line([(px(v), T), (px(v), T + PH)], fill="#e5e7eb")
    g.rectangle([L, T, L + PW, T + PH], outline="#111", width=2)
    for i in range(7):
        v = i * 0.25
        g.line([(px(v), T + PH), (px(v), T + PH - 6)], fill="#111", width=2)
        g.text((px(v), T + PH + 10), f"{v:.2f}", fill="#111", font=f13, anchor="mt")
    for d in range(-12, -2):
        g.line([(L, py(10 ** d)), (L + 6, py(10 ** d))], fill="#111", width=2)
        g.text((L - 8, py(10 ** d)), f"1E{d}", fill="#111", font=f13, anchor="rm")
    g.text((L + PW / 2, T + PH + 34), "Vgs (V)", fill="#111", font=f14, anchor="mt")
    lab = Image.new("RGBA", (80, 24), (255, 255, 255, 0))
    ImageDraw.Draw(lab).text((40, 12), "Id (A)", fill="#111", font=f14, anchor="mm")
    lab = lab.rotate(90, expand=True)
    im.paste(lab, (10, int(T + PH / 2 - 40)), lab)

    def Id(V, vt, k):
        f = math.log(1 + math.exp((V - vt) / 0.07))
        return 3e-12 + k * f * f

    for col, vt, k in (("#dc2626", 0.45, 3e-6), ("#2563eb", 0.62, 1.5e-6)):
        pts = [(px(1.5 * i / 300), py(Id(1.5 * i / 300, vt, k))) for i in range(301)]
        g.line(pts, fill=col, width=3, joint="curve")
    cal = [[px(0), T + PH], [px(1.5), T + PH], [L, py(1e-12)], [L, py(1e-3)]]
    vals = {"x1": "0", "x2": "1.5", "y1": "1e-12", "y2": "1e-3", "logx": False, "logy": True}
    return im, cal, vals


class Digitizer:
    def __init__(self, root):
        self.root = root
        root.title(f"{APP} {VERSION}")
        root.geometry("1360x860")
        root.minsize(900, 600)

        self.img = None          # PIL RGB image
        self.px = None           # pixel access
        self.img_path = None
        self.W = self.H = 0
        self.s, self.ox, self.oy = 1.0, 0.0, 0.0
        self.mode = tk.StringVar(value="calib")
        self.calib = [None, None, None, None]
        self.datasets = []
        self.act = 0
        self.hist = []
        self.pick_color = None
        self.drag = None
        self.hover = None
        self.mouse = None
        self.space = False
        self._tkimg = None
        self._ltkimg = None
        self._render_job = None

        self.cal_vars = {k: tk.StringVar(value=v) for k, v in
                         (("x1", "0"), ("x2", "1"), ("y1", "0"), ("y2", "1"))}
        self.logx = tk.BooleanVar(value=False)
        self.logy = tk.BooleanVar(value=False)
        self.tol = tk.IntVar(value=60)
        self.step = tk.IntVar(value=5)
        self.clip = tk.BooleanVar(value=True)
        self.sortx = tk.BooleanVar(value=True)
        self.scope = tk.StringVar(value="현재 시리즈")
        self.delim = tk.StringVar(value="Comma (CSV)")
        self.act_var = tk.IntVar(value=0)

        self._new_ds()
        self._build_ui()
        self._bind()
        self.set_mode("calib")

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        st = ttk.Style()
        try:
            st.theme_use("vista" if sys.platform.startswith("win") else "clam")
        except tk.TclError:
            pass
        st.configure("Hint.TLabel", foreground="#6b7280")
        st.configure("Ok.TLabel", foreground="#15803d")
        st.configure("Wait.TLabel", foreground="#b45309")
        st.configure("Head.TLabel", foreground="#6b7280", font=("TkDefaultFont", 9, "bold"))

        # menu
        mb = tk.Menu(self.root)
        mod = "Command" if IS_MAC else "Ctrl"
        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="이미지 열기…", accelerator=f"{mod}+O", command=self.open_image)
        fm.add_command(label="클립보드 이미지 붙여넣기", accelerator=f"{mod}+V", command=self.paste_image)
        fm.add_command(label="예제 그래프", command=self.load_demo)
        fm.add_separator()
        fm.add_command(label="프로젝트 열기…", command=self.load_project)
        fm.add_command(label="프로젝트 저장…", accelerator=f"{mod}+S", command=self.save_project)
        fm.add_separator()
        fm.add_command(label="CSV로 저장…", accelerator=f"{mod}+E", command=self.save_csv)
        fm.add_separator()
        fm.add_command(label="종료", command=self.root.destroy)
        mb.add_cascade(label="파일", menu=fm)
        em = tk.Menu(mb, tearoff=0)
        em.add_command(label="되돌리기", accelerator=f"{mod}+Z", command=self.undo)
        em.add_command(label="현재 시리즈 점 모두 삭제", command=self.clear_points)
        mb.add_cascade(label="편집", menu=em)
        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="사용법", command=self.show_help)
        mb.add_cascade(label="도움말", menu=hm)
        self.root.config(menu=mb)

        # toolbar
        tb = ttk.Frame(self.root, padding=(8, 6))
        tb.pack(side="top", fill="x")
        ttk.Button(tb, text="이미지 열기", command=self.open_image).pack(side="left")
        ttk.Button(tb, text="붙여넣기", command=self.paste_image).pack(side="left", padx=(4, 0))
        ttk.Button(tb, text="예제 그래프", command=self.load_demo).pack(side="left", padx=(4, 14))
        for val, txt in (("calib", "① Axis 보정 (C)"), ("add", "② 점 추가/편집 (A)"), ("pick", "③ Color pick (P)")):
            ttk.Radiobutton(tb, text=txt, value=val, variable=self.mode, style="Toolbutton",
                            command=lambda v=val: self.set_mode(v)).pack(side="left", padx=1)
        ttk.Button(tb, text="화면 맞춤 (F)", command=self.fit).pack(side="right")
        ttk.Button(tb, text="되돌리기", command=self.undo).pack(side="right", padx=4)
        ttk.Separator(self.root).pack(fill="x")

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True)

        # sidebar (scrollable)
        side_wrap = ttk.Frame(body, width=360)
        side_wrap.pack(side="right", fill="y")
        side_wrap.pack_propagate(False)
        sc = tk.Canvas(side_wrap, highlightthickness=0, width=340)
        vs = ttk.Scrollbar(side_wrap, orient="vertical", command=sc.yview)
        side = ttk.Frame(sc, padding=(10, 8))
        side.bind("<Configure>", lambda e: sc.configure(scrollregion=sc.bbox("all")))
        sc.create_window((0, 0), window=side, anchor="nw", width=340)
        sc.configure(yscrollcommand=vs.set)
        sc.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.side_canvas = sc

        # stage
        stage = ttk.Frame(body)
        stage.pack(side="left", fill="both", expand=True)
        self.cv = tk.Canvas(stage, bg="#eceef2", highlightthickness=0, cursor="crosshair")
        self.cv.pack(fill="both", expand=True)
        sb = ttk.Frame(stage, padding=(8, 3))
        sb.pack(fill="x")
        self.hint = ttk.Label(sb, text="", style="Hint.TLabel")
        self.hint.pack(side="left")
        self.readout = ttk.Label(sb, text="", font=("Courier", 10))
        self.readout.pack(side="right")

        def head(t):
            ttk.Label(side, text=t, style="Head.TLabel").pack(anchor="w", pady=(10, 4))

        # calibration
        head("AXIS CALIBRATION")
        cg = ttk.Frame(side)
        cg.pack(fill="x")
        self.cal_status = []
        for i, l in enumerate(LAB):
            tk.Label(cg, text=l, fg=CAL_COL[i], font=("TkDefaultFont", 10, "bold")).grid(row=i, column=0, sticky="w")
            e = ttk.Entry(cg, textvariable=self.cal_vars[l.lower()], width=16)
            e.grid(row=i, column=1, sticky="ew", padx=4, pady=1)
            if i == 0:
                self.first_entry = e
            s = ttk.Label(cg, text="미설정", width=8)
            s.grid(row=i, column=2)
            self.cal_status.append(s)
            ttk.Button(cg, text="↺", width=3, command=lambda k=i: self.reset_cal(k)).grid(row=i, column=3)
        cg.columnconfigure(1, weight=1)
        r = ttk.Frame(side)
        r.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(r, text="X log scale", variable=self.logx, command=self.refresh).pack(side="left")
        ttk.Checkbutton(r, text="Y log scale", variable=self.logy, command=self.refresh).pack(side="left", padx=10)
        self.cal_msg = ttk.Label(side, text="", style="Wait.TLabel", wraplength=320)
        self.cal_msg.pack(anchor="w")
        for v in self.cal_vars.values():
            v.trace_add("write", lambda *a: self.refresh())

        head("MAGNIFIER")
        self.lp = tk.Canvas(side, width=320, height=130, bg="#fafafa", highlightthickness=1,
                            highlightbackground="#e3e6eb")
        self.lp.pack(fill="x")

        # datasets
        hf = ttk.Frame(side)
        hf.pack(fill="x", pady=(10, 4))
        ttk.Label(hf, text="DATASETS", style="Head.TLabel").pack(side="left")
        ttk.Button(hf, text="+ 시리즈", command=self.add_ds).pack(side="right")
        self.ds_frame = ttk.Frame(side)
        self.ds_frame.pack(fill="x")

        # auto extract
        head("AUTO EXTRACT (COLOR)")
        pf = ttk.Frame(side)
        pf.pack(fill="x")
        self.swatch = tk.Label(pf, width=3, bg="#dddddd", relief="solid", bd=1)
        self.swatch.pack(side="left")
        self.pick_lbl = ttk.Label(pf, text="색상 미선택 — ③ Color pick 모드에서 곡선 클릭",
                                  style="Hint.TLabel", wraplength=280)
        self.pick_lbl.pack(side="left", padx=6)
        af = ttk.Frame(side)
        af.pack(fill="x", pady=4)
        ttk.Label(af, text="Tolerance (RGB 거리)").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(af, from_=1, to=441, textvariable=self.tol, width=7).grid(row=0, column=1, padx=4)
        ttk.Label(af, text="X step (px)").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(af, from_=1, to=200, textvariable=self.step, width=7).grid(row=1, column=1, padx=4)
        ttk.Checkbutton(side, text="보정점 범위(X1–X2, Y1–Y2) 안에서만 탐색", variable=self.clip).pack(anchor="w")
        xf = ttk.Frame(side)
        xf.pack(fill="x", pady=4)
        ttk.Button(xf, text="현재 시리즈에 추출", command=self.auto_extract).pack(side="left")
        self.auto_msg = ttk.Label(xf, text="", style="Wait.TLabel")
        self.auto_msg.pack(side="left", padx=6)

        # data table
        hf2 = ttk.Frame(side)
        hf2.pack(fill="x", pady=(10, 4))
        ttk.Label(hf2, text="DATA", style="Head.TLabel").pack(side="left")
        ttk.Checkbutton(hf2, text="X 정렬", variable=self.sortx, command=self.refresh).pack(side="right")
        tf = ttk.Frame(side)
        tf.pack(fill="x")
        self.tree = ttk.Treeview(tf, columns=("i", "x", "y"), show="headings", height=8)
        for c, t, w in (("i", "#", 40), ("x", "X", 135), ("y", "Y", 135)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="e" if c != "i" else "w")
        ts = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ts.set)
        self.tree.pack(side="left", fill="x", expand=True)
        ts.pack(side="right", fill="y")

        # export
        head("EXPORT")
        ef = ttk.Frame(side)
        ef.pack(fill="x")
        ttk.Label(ef, text="범위").grid(row=0, column=0, sticky="w")
        ttk.Combobox(ef, textvariable=self.scope, state="readonly", width=26,
                     values=["현재 시리즈", "전체 (long: series,x,y)", "전체 (wide: x1,y1,x2,y2…)"]
                     ).grid(row=0, column=1, sticky="ew", padx=4, pady=1)
        ttk.Label(ef, text="구분자").grid(row=1, column=0, sticky="w")
        ttk.Combobox(ef, textvariable=self.delim, state="readonly", width=26,
                     values=["Comma (CSV)", "Tab (Excel 붙여넣기)"]).grid(row=1, column=1, sticky="ew", padx=4, pady=1)
        bf = ttk.Frame(side)
        bf.pack(fill="x", pady=6)
        ttk.Button(bf, text="클립보드 복사", command=self.copy_out).pack(side="left")
        ttk.Button(bf, text="CSV 저장…", command=self.save_csv).pack(side="left", padx=4)
        self.copy_msg = ttk.Label(bf, text="", style="Ok.TLabel")
        self.copy_msg.pack(side="left", padx=4)

        ttk.Label(side, style="Hint.TLabel", wraplength=320, justify="left", text=(
            "클릭: 점 추가 · 드래그: 점/보정점 이동 · 우클릭: 삭제\n"
            "휠: 확대/축소 · Space+드래그 / 휠버튼 드래그: 화면 이동\n"
            "C 보정 · A 추가 · P 색상 · F 맞춤 · Backspace 마지막 점 삭제")).pack(anchor="w", pady=(12, 0))

    def _bind(self):
        cv = self.cv
        cv.bind("<Configure>", lambda e: (self.fit() if self.img and self.s == 1.0 and not self._fitted else self.render()))
        self._fitted = False
        cv.bind("<ButtonPress-1>", self.on_down)
        cv.bind("<B1-Motion>", self.on_drag)
        cv.bind("<ButtonRelease-1>", self.on_up)
        mid, right = ("<Button-3>", "<Button-2>") if IS_MAC else ("<Button-2>", "<Button-3>")
        cv.bind(mid, self.on_pan_start)
        cv.bind("<B3-Motion>" if IS_MAC else "<B2-Motion>", self.on_pan)
        cv.bind(right, self.on_right)
        if IS_MAC:
            cv.bind("<Control-Button-1>", self.on_right)
        cv.bind("<Motion>", self.on_move)
        cv.bind("<Leave>", lambda e: self.readout.config(text=""))
        cv.bind("<MouseWheel>", self.on_wheel)
        cv.bind("<Button-4>", lambda e: self.zoom_at(e.x, e.y, 1.15))
        cv.bind("<Button-5>", lambda e: self.zoom_at(e.x, e.y, 1 / 1.15))
        self.side_canvas.bind_all("<MouseWheel>", self._side_wheel, add="+")

        r = self.root
        mod = "Command" if IS_MAC else "Control"
        r.bind(f"<{mod}-o>", lambda e: self.open_image())
        r.bind(f"<{mod}-s>", lambda e: self.save_project())
        r.bind(f"<{mod}-e>", lambda e: self.save_csv())
        r.bind(f"<{mod}-z>", lambda e: None if self._typing(e) else self.undo())
        r.bind(f"<{mod}-v>", lambda e: None if self._typing(e) else self.paste_image())
        r.bind("<KeyPress-space>", self._space_down)
        r.bind("<KeyRelease-space>", self._space_up)
        r.bind("<Key>", self.on_key)

    def _side_wheel(self, e):
        w = e.widget
        if w is self.cv or str(w).startswith(str(self.tree)):
            return
        if str(w).startswith(str(self.side_canvas)):
            self.side_canvas.yview_scroll(int(-e.delta / (1 if IS_MAC else 120)), "units")

    @staticmethod
    def _typing(e):
        return isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox, tk.Text))

    # ------------------------------------------------------------ datasets
    def _new_ds(self, name=None):
        i = len(self.datasets)
        self.datasets.append({"name": name or f"Series {i + 1}", "color": COLORS[i % len(COLORS)], "pts": []})
        self.act = i

    def add_ds(self):
        self.snapshot()
        self._new_ds()
        self.refresh()

    def render_ds(self):
        for w in self.ds_frame.winfo_children():
            w.destroy()
        self.act_var.set(self.act)
        for k, ds in enumerate(self.datasets):
            row = ttk.Frame(self.ds_frame)
            row.pack(fill="x", pady=1)
            ttk.Radiobutton(row, variable=self.act_var, value=k, command=lambda k=k: self.select_ds(k)).pack(side="left")
            sw = tk.Label(row, width=2, bg=ds["color"], relief="solid", bd=1, cursor="hand2")
            sw.pack(side="left", padx=3)
            sw.bind("<Button-1>", lambda e, k=k: self.choose_color(k))
            var = tk.StringVar(value=ds["name"])
            ent = ttk.Entry(row, textvariable=var, width=18)
            ent.pack(side="left", fill="x", expand=True, padx=3)
            var.trace_add("write", lambda *a, k=k, v=var: self._rename(k, v.get()))
            ent.bind("<FocusIn>", lambda e, k=k: self.select_ds(k, rebuild=False))
            ttk.Label(row, text=f"{len(ds['pts'])} pts", width=7, style="Hint.TLabel").pack(side="left")
            ttk.Button(row, text="×", width=2, command=lambda k=k: self.del_ds(k)).pack(side="left")

    def _rename(self, k, name):
        if k < len(self.datasets):
            self.datasets[k]["name"] = name

    def select_ds(self, k, rebuild=True):
        if k == self.act:
            return
        self.act = k
        self.act_var.set(k)
        self.refresh(rebuild_ds=rebuild)

    def choose_color(self, k):
        c = colorchooser.askcolor(self.datasets[k]["color"], parent=self.root)
        if c and c[1]:
            self.datasets[k]["color"] = c[1]
            self.refresh()

    def del_ds(self, k):
        self.snapshot()
        if len(self.datasets) == 1:
            self.datasets[0]["pts"] = []
        else:
            self.datasets.pop(k)
            self.act = max(0, min(self.act, len(self.datasets) - 1))
        self.refresh()

    def clear_points(self):
        self.snapshot()
        self.datasets[self.act]["pts"] = []
        self.refresh()

    # --------------------------------------------------------- calibration
    def reset_cal(self, k):
        self.snapshot()
        self.calib[k] = None
        self.set_mode("calib")

    def _num(self, key):
        try:
            return float(self.cal_vars[key].get().strip())
        except ValueError:
            return float("nan")

    def cal(self):
        if any(p is None for p in self.calib):
            return None
        x1, x2, y1, y2 = (self._num(k) for k in ("x1", "x2", "y1", "y2"))
        lx, ly = self.logx.get(), self.logy.get()
        if not all(math.isfinite(v) for v in (x1, x2, y1, y2)) or x1 == x2 or y1 == y2:
            return None
        if (lx and (x1 <= 0 or x2 <= 0)) or (ly and (y1 <= 0 or y2 <= 0)):
            return None
        X1, X2, Y1, Y2 = self.calib
        if math.dist(X1, X2) < 1 or math.dist(Y1, Y2) < 1:
            return None
        t = math.log10
        return dict(lx=lx, ly=ly, X1=X1, X2=X2, Y1=Y1, Y2=Y2,
                    a=t(x1) if lx else x1, b=t(x2) if lx else x2,
                    c=t(y1) if ly else y1, d=t(y2) if ly else y2)

    def to_data(self, px, py, C):
        if not C:
            return None
        x = C["a"] + proj((px, py), C["X1"], C["X2"]) * (C["b"] - C["a"])
        y = C["c"] + proj((px, py), C["Y1"], C["Y2"]) * (C["d"] - C["c"])
        try:
            return (10 ** x if C["lx"] else x, 10 ** y if C["ly"] else y)
        except OverflowError:
            return (float("inf"), float("inf"))

    def cal_message(self):
        if any(p is None for p in self.calib):
            return ""
        v = [self._num(k) for k in ("x1", "x2", "y1", "y2")]
        if not all(math.isfinite(x) for x in v):
            return "축 값 4개를 숫자로 입력하세요 (예: 1e-12)."
        if v[0] == v[1] or v[2] == v[3]:
            return "X1≠X2, Y1≠Y2 이어야 합니다."
        if (self.logx.get() and min(v[0], v[1]) <= 0) or (self.logy.get() and min(v[2], v[3]) <= 0):
            return "Log scale 축의 값은 양수여야 합니다."
        return ""

    # --------------------------------------------------------------- modes
    def set_mode(self, m):
        self.mode.set(m)
        self.refresh()

    def hint_text(self):
        if not self.img:
            return "이미지를 여세요 — 파일 › 이미지 열기 (Ctrl+O), 클립보드 붙여넣기 (Ctrl+V), 또는 exe 아이콘에 이미지를 끌어다 놓기"
        m = self.mode.get()
        if m == "calib":
            n = next((i for i, p in enumerate(self.calib) if p is None), -1)
            if n >= 0:
                which = "X축 위 값을 아는 두 지점 (X1, X2)" if n < 2 else "Y축 위 값을 아는 두 지점 (Y1, Y2)"
                return f"{LAB[n]} 위치를 클릭 — {which}. 휠로 확대 후 tick 교차점을 찍으세요."
            return "보정점은 드래그로 미세 조정 가능. 오른쪽에 축 값을 입력한 뒤 ② 점 추가 모드로."
        if m == "pick":
            return "추출할 곡선의 색을 클릭하세요."
        return ("클릭: 점 추가 · 드래그: 이동 · 우클릭: 삭제 · Space+드래그: 화면 이동" if self.cal()
                else "점은 찍을 수 있지만, 좌표 변환을 위해 축 보정을 완료하세요.")

    # ------------------------------------------------------------- history
    def snapshot(self):
        self.hist.append(json.dumps({"calib": self.calib, "datasets": self.datasets, "act": self.act}))
        if len(self.hist) > 200:
            self.hist.pop(0)

    def undo(self):
        if not self.hist:
            return
        s = json.loads(self.hist.pop())
        self.calib, self.datasets = s["calib"], s["datasets"]
        self.act = min(s["act"], len(self.datasets) - 1)
        self.refresh()

    # ---------------------------------------------------------------- view
    def i2s(self, x, y):
        return x * self.s + self.ox, y * self.s + self.oy

    def s2i(self, x, y):
        return (x - self.ox) / self.s, (y - self.oy) / self.s

    def fit(self):
        if not self.img:
            return
        w, h = max(self.cv.winfo_width(), 50), max(self.cv.winfo_height(), 50)
        s = min(w / self.W, h / self.H) * 0.94
        self.s, self.ox, self.oy = s, (w - self.W * s) / 2, (h - self.H * s) / 2
        self._fitted = True
        self.render()

    def zoom_at(self, mx, my, f):
        if not self.img:
            return
        ns = min(60.0, max(0.03, self.s * f))
        k = ns / self.s
        self.ox = mx - (mx - self.ox) * k
        self.oy = my - (my - self.oy) * k
        self.s = ns
        self.render()

    def on_wheel(self, e):
        d = e.delta if IS_MAC else e.delta / 120
        self.zoom_at(e.x, e.y, 1.15 ** d)

    # -------------------------------------------------------------- render
    def render(self):
        """Full redraw (image + overlay)."""
        cv = self.cv
        cv.delete("img")
        if not self.img:
            self.draw_overlay()
            return
        w, h = cv.winfo_width(), cv.winfo_height()
        s, ox, oy = self.s, self.ox, self.oy
        x0, y0 = max(0, int(math.floor(-ox / s))), max(0, int(math.floor(-oy / s)))
        x1, y1 = min(self.W, int(math.ceil((w - ox) / s))), min(self.H, int(math.ceil((h - oy) / s)))
        if x1 > x0 and y1 > y0:
            crop = self.img.crop((x0, y0, x1, y1))
            dw, dh = max(1, int(round(x1 * s + ox)) - int(round(x0 * s + ox))), \
                max(1, int(round(y1 * s + oy)) - int(round(y0 * s + oy)))
            crop = crop.resize((dw, dh), NEAREST if s > 2.5 else BILINEAR)
            self._tkimg = ImageTk.PhotoImage(crop)
            cv.create_image(int(round(x0 * s + ox)), int(round(y0 * s + oy)), image=self._tkimg, anchor="nw", tags="img")
            cv.tag_lower("img")
        self.draw_overlay()

    def draw_overlay(self):
        cv = self.cv
        cv.delete("ov")
        if not self.img:
            cv.delete("ph")
            w, h = cv.winfo_width(), cv.winfo_height()
            cv.create_text(w / 2, h / 2 - 12, text="그래프 이미지를 여세요 (Ctrl+O) 또는 붙여넣기 (Ctrl+V)",
                           font=("TkDefaultFont", 13, "bold"), fill="#374151", tags="ph")
            cv.create_text(w / 2, h / 2 + 14, text="PNG · JPG · BMP · 스크린샷 · 또는 상단 ‘예제 그래프’",
                           fill="#6b7280", tags="ph")
            return
        cv.delete("ph")
        for i, j, c in ((0, 1, "#0f766e"), (2, 3, "#9333ea")):
            A, B = self.calib[i], self.calib[j]
            if A and B:
                cv.create_line(*self.i2s(*A), *self.i2s(*B), fill=c, dash=(5, 4), tags="ov")
        order = [k for k in range(len(self.datasets)) if k != self.act] + [self.act]
        for k in order:
            ds, on = self.datasets[k], k == self.act
            r = 4.5 if on else 3
            for i, p in enumerate(ds["pts"]):
                sx, sy = self.i2s(*p)
                cv.create_oval(sx - r, sy - r, sx + r, sy + r, fill=ds["color"],
                               outline="white" if on else "", width=1, tags="ov")
                if on and self.hover and self.hover[0] == "pt" and self.hover[1] == i:
                    cv.create_oval(sx - 8, sy - 8, sx + 8, sy + 8, outline=ds["color"], width=2, tags="ov")
        for i, p in enumerate(self.calib):
            if not p:
                continue
            sx, sy = self.i2s(*p)
            c = CAL_COL[i]
            wd = 2.5 if (self.hover and self.hover[0] == "cal" and self.hover[1] == i) else 1.6
            cv.create_line(sx - 11, sy, sx + 11, sy, fill=c, width=wd, tags="ov")
            cv.create_line(sx, sy - 11, sx, sy + 11, fill=c, width=wd, tags="ov")
            cv.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, outline=c, width=wd, tags="ov")
            cv.create_rectangle(sx + 8, sy - 22, sx + 30, sy - 7, fill=c, outline=c, tags="ov")
            cv.create_text(sx + 19, sy - 14, text=LAB[i], fill="white", font=("TkDefaultFont", 8, "bold"), tags="ov")

    def draw_loupe(self):
        lp = self.lp
        lp.delete("all")
        if not self.img or not self.mouse:
            return
        w, h = lp.winfo_width() or 320, lp.winfo_height() or 130
        Z = 7
        ix, iy = self.s2i(*self.mouse)
        sw, sh = w / Z, h / Z
        bx0, by0 = int(math.floor(ix - sw / 2)), int(math.floor(iy - sh / 2))
        bw, bh = int(math.ceil(sw)) + 2, int(math.ceil(sh)) + 2
        tile = Image.new("RGB", (bw, bh), (240, 240, 240))
        cx0, cy0 = max(0, bx0), max(0, by0)
        cx1, cy1 = min(self.W, bx0 + bw), min(self.H, by0 + bh)
        if cx1 > cx0 and cy1 > cy0:
            tile.paste(self.img.crop((cx0, cy0, cx1, cy1)), (cx0 - bx0, cy0 - by0))
        tile = tile.resize((bw * Z, bh * Z), NEAREST)
        self._ltkimg = ImageTk.PhotoImage(tile)
        tr = lambda x, y: ((x - bx0) * Z, (y - by0) * Z)
        cx, cy = tr(ix, iy)
        # shift so that cursor is centered
        dx, dy = w / 2 - cx, h / 2 - cy
        lp.create_image(dx, dy, image=self._ltkimg, anchor="nw")
        for k, ds in enumerate(self.datasets):
            for p in ds["pts"]:
                a, b = tr(*p)
                a, b = a + dx, b + dy
                if -10 < a < w + 10 and -10 < b < h + 10:
                    lp.create_oval(a - 4, b - 4, a + 4, b + 4, fill=ds["color"], outline="")
        for i, p in enumerate(self.calib):
            if p:
                a, b = tr(*p)
                a, b = a + dx, b + dy
                lp.create_oval(a - 6, b - 6, a + 6, b + 6, outline=CAL_COL[i], width=1.5)
        red = "#dc2626"
        lp.create_line(w / 2, 0, w / 2, h / 2 - 6, fill=red)
        lp.create_line(w / 2, h / 2 + 6, w / 2, h, fill=red)
        lp.create_line(0, h / 2, w / 2 - 6, h / 2, fill=red)
        lp.create_line(w / 2 + 6, h / 2, w, h / 2, fill=red)

    # --------------------------------------------------------------- mouse
    def hit_test(self, mx, my):
        m = self.mode.get()
        best, bd = None, None
        if m == "calib":
            bd = 12
            for i, p in enumerate(self.calib):
                if p:
                    d = math.dist(self.i2s(*p), (mx, my))
                    if d < bd:
                        best, bd = ("cal", i), d
        elif m == "add":
            bd = 9
            for i, p in enumerate(self.datasets[self.act]["pts"]):
                d = math.dist(self.i2s(*p), (mx, my))
                if d < bd:
                    best, bd = ("pt", i), d
        return best

    def on_down(self, e):
        self.cv.focus_set()
        if not self.img:
            return
        if self.space:
            return self.on_pan_start(e)
        ix, iy = self.s2i(e.x, e.y)
        h = self.hit_test(e.x, e.y)
        if h:
            self.snapshot()
            self.drag = h
            return
        m = self.mode.get()
        if m == "calib":
            n = next((i for i, p in enumerate(self.calib) if p is None), -1)
            if n < 0:
                return
            self.snapshot()
            self.calib[n] = [ix, iy]
            if all(self.calib):
                self.set_mode("add")
                self.first_entry.focus_set()
                self.first_entry.select_range(0, "end")
            else:
                self.refresh()
        elif m == "pick":
            self.pick_at(ix, iy)
        else:
            self.snapshot()
            pts = self.datasets[self.act]["pts"]
            pts.append([ix, iy])
            self.hover = ("pt", len(pts) - 1)
            self.drag = self.hover
            self.refresh()

    def on_drag(self, e):
        if self.drag and self.drag[0] == "pan":
            return self.on_pan(e)
        if not self.drag:
            return
        ix, iy = self.s2i(e.x, e.y)
        if self.drag[0] == "cal":
            self.calib[self.drag[1]] = [ix, iy]
        else:
            self.datasets[self.act]["pts"][self.drag[1]] = [ix, iy]
        self.mouse = (e.x, e.y)
        self._readout(ix, iy)
        self.draw_overlay()
        self.draw_loupe()

    def on_up(self, e):
        if self.drag:
            was = self.drag[0]
            self.drag = None
            self.cv.config(cursor="fleur" if self.space else "crosshair")
            if was != "pan":
                self.refresh()

    def on_pan_start(self, e):
        if not self.img:
            return
        self.drag = ("pan", e.x, e.y, self.ox, self.oy)
        self.cv.config(cursor="fleur")

    def on_pan(self, e):
        if not self.drag or self.drag[0] != "pan":
            return
        _, sx, sy, ox, oy = self.drag
        self.ox, self.oy = ox + e.x - sx, oy + e.y - sy
        self._schedule_render()

    def _schedule_render(self):
        if self._render_job is None:
            self._render_job = self.root.after(12, self._do_render)

    def _do_render(self):
        self._render_job = None
        self.render()

    def on_right(self, e):
        if not self.img:
            return
        best, bd = -1, 12
        for i, p in enumerate(self.datasets[self.act]["pts"]):
            d = math.dist(self.i2s(*p), (e.x, e.y))
            if d < bd:
                best, bd = i, d
        if best >= 0:
            self.snapshot()
            self.datasets[self.act]["pts"].pop(best)
            self.hover = None
            self.refresh()

    def on_move(self, e):
        if not self.img:
            return
        self.mouse = (e.x, e.y)
        ix, iy = self.s2i(e.x, e.y)
        h = self.hit_test(e.x, e.y)
        if h != self.hover:
            self.hover = h
        if not self.space:
            self.cv.config(cursor="fleur" if h else ("tcross" if self.mode.get() == "pick" else "crosshair"))
        self._readout(ix, iy)
        self.draw_overlay()
        self.draw_loupe()

    def _readout(self, ix, iy):
        d = self.to_data(ix, iy, self.cal())
        t = f"px ({ix:.1f}, {iy:.1f})"
        if d:
            t += f"    X = {fmt(d[0])}    Y = {fmt(d[1])}"
        self.readout.config(text=t)

    # ---------------------------------------------------------------- keys
    def _space_down(self, e):
        if self._typing(e):
            return
        self.space = True
        self.cv.config(cursor="fleur")
        return "break"

    def _space_up(self, e):
        self.space = False
        self.cv.config(cursor="crosshair")

    def on_key(self, e):
        if self._typing(e) or (e.state & 0x4) or (e.state & 0x8 and IS_MAC):
            return
        k = e.keysym.lower()
        if k == "c":
            self.set_mode("calib")
        elif k == "a":
            self.set_mode("add")
        elif k == "p":
            self.set_mode("pick")
        elif k == "f":
            self.fit()
        elif k in ("backspace", "delete"):
            pts = self.datasets[self.act]["pts"]
            if pts:
                self.snapshot()
                pts.pop()
                self.refresh()

    # ------------------------------------------------------- image loading
    def set_image(self, im, path=None, keep=False):
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, "white")
            bg.alpha_composite(im)
            im = bg
        self.img = im.convert("RGB")
        self.px = self.img.load()
        self.W, self.H = self.img.size
        self.img_path = path
        if not keep:
            self.calib = [None, None, None, None]
            for d in self.datasets:
                d["pts"] = []
            self.hist = []
            self.pick_color = None
        self.root.title(f"{APP} — {os.path.basename(path) if path else '(이미지)'}")
        self.root.update_idletasks()
        self.fit()

    def open_image(self, path=None):
        path = path or filedialog.askopenfilename(
            parent=self.root, title="그래프 이미지 열기",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"), ("All files", "*.*")])
        if not path:
            return
        try:
            im = Image.open(path)
            im.load()
        except Exception as ex:
            messagebox.showerror(APP, f"이미지를 열 수 없습니다:\n{ex}", parent=self.root)
            return
        self.set_image(im, path)
        self.set_mode("calib")

    def paste_image(self):
        if ImageGrab is None:
            messagebox.showinfo(APP, "이 플랫폼에서는 클립보드 이미지 붙여넣기를 지원하지 않습니다.", parent=self.root)
            return
        try:
            data = ImageGrab.grabclipboard()
        except Exception as ex:
            messagebox.showinfo(APP, f"클립보드를 읽을 수 없습니다:\n{ex}", parent=self.root)
            return
        if isinstance(data, Image.Image):
            self.set_image(data, None)
            self.set_mode("calib")
        elif isinstance(data, list) and data:
            self.open_image(data[0])
        else:
            messagebox.showinfo(APP, "클립보드에 이미지가 없습니다.", parent=self.root)

    def load_demo(self):
        im, cal, vals = make_demo_image()
        self.datasets = []
        self._new_ds("Device A")
        self._new_ds("Device B")
        self.act = 0
        self.set_image(im, None)
        self.root.title(f"{APP} — 예제 그래프")
        self.calib = cal
        for k in ("x1", "x2", "y1", "y2"):
            self.cal_vars[k].set(vals[k])
        self.logx.set(vals["logx"])
        self.logy.set(vals["logy"])
        self.set_mode("pick")

    # ------------------------------------------------- color pick / extract
    def pick_at(self, ix, iy):
        x, y = int(ix), int(iy)
        if not (0 <= x < self.W and 0 <= y < self.H):
            return
        self.pick_color = tuple(self.px[x, y][:3])
        self.datasets[self.act]["color"] = "#%02x%02x%02x" % self.pick_color
        self.set_mode("add")

    def auto_extract(self):
        C = self.cal()
        msg = self.auto_msg
        msg.config(text="")
        if not self.img:
            return msg.config(text="이미지를 먼저 여세요.")
        if not self.pick_color:
            return msg.config(text="먼저 곡선 색을 선택하세요.")
        try:
            tol, step = max(1, int(self.tol.get())), max(1, int(self.step.get()))
        except (tk.TclError, ValueError):
            return msg.config(text="Tolerance/step 값을 확인하세요.")
        x0, x1, y0, y1 = 0, self.W - 1, 0, self.H - 1
        if self.clip.get():
            if not C:
                return msg.config(text="보정을 먼저 완료하세요 (또는 범위 제한 해제).")
            xs, ys = (C["X1"][0], C["X2"][0]), (C["Y1"][1], C["Y2"][1])
            x0, x1 = max(0, math.ceil(min(xs))), min(self.W - 1, math.floor(max(xs)))
            y0, y1 = max(0, math.ceil(min(ys))), min(self.H - 1, math.floor(max(ys)))
        R, G, B = self.pick_color
        tol2 = tol * tol
        px = self.px
        out, prev = [], None
        for x in range(x0, x1 + 1, step):
            runs, s = [], -1
            for y in range(y0, y1 + 1):
                r, g, b = px[x, y][:3]
                m = (r - R) ** 2 + (g - G) ** 2 + (b - B) ** 2 <= tol2
                if m and s < 0:
                    s = y
                elif not m and s >= 0:
                    runs.append((s, y - 1))
                    s = -1
            if s >= 0:
                runs.append((s, y1))
            if not runs:
                continue
            if prev is None:
                r = max(runs, key=lambda q: q[1] - q[0])
            else:
                r = min(runs, key=lambda q: abs((q[0] + q[1]) / 2 - prev))
            yc = (r[0] + r[1]) / 2
            prev = yc
            out.append([x + 0.5, yc + 0.5])
        if not out:
            return msg.config(text="일치하는 픽셀 없음 — Tolerance↑")
        self.snapshot()
        self.datasets[self.act]["pts"] = out
        msg.config(text=f"{len(out)}개 점 추출")
        self.refresh()

    # ------------------------------------------------------ table / export
    def rows_of(self, ds, C):
        if not C:
            return []
        r = [self.to_data(p[0], p[1], C) for p in ds["pts"]]
        if self.sortx.get():
            r.sort(key=lambda t: t[0])
        return r

    def render_table(self):
        t = self.tree
        t.delete(*t.get_children())
        C = self.cal()
        if not C:
            t.insert("", "end", values=("", "축 보정 필요", f"{len(self.datasets[self.act]['pts'])} pts"))
            return
        for i, r in enumerate(self.rows_of(self.datasets[self.act], C), 1):
            t.insert("", "end", values=(i, fmt(r[0]), fmt(r[1])))

    def export_text(self):
        C = self.cal()
        if not C:
            return ""
        D = "\t" if self.delim.get().startswith("Tab") else ","

        def q(s):
            return '"' + s.replace('"', '""') + '"' if D == "," and any(c in s for c in '",') else s

        sc = self.scope.get()
        lines = []
        if sc.startswith("현재"):
            lines.append(D.join(["x", "y"]))
            lines += [fmt(a) + D + fmt(b) for a, b in self.rows_of(self.datasets[self.act], C)]
        elif "long" in sc:
            lines.append(D.join(["series", "x", "y"]))
            for ds in self.datasets:
                lines += [D.join([q(ds["name"]), fmt(a), fmt(b)]) for a, b in self.rows_of(ds, C)]
        else:
            allr = [self.rows_of(ds, C) for ds in self.datasets]
            n = max([len(a) for a in allr] + [0])
            lines.append(D.join(q(ds["name"] + " x") + D + q(ds["name"] + " y") for ds in self.datasets))
            for i in range(n):
                lines.append(D.join((fmt(a[i][0]) + D + fmt(a[i][1])) if i < len(a) else D for a in allr))
        return "\n".join(lines)

    def copy_out(self):
        t = self.export_text()
        if not t:
            self.copy_msg.config(text="데이터 없음 (보정 확인)")
        else:
            self.root.clipboard_clear()
            self.root.clipboard_append(t)
            self.copy_msg.config(text="복사됨 ✓")
        self.root.after(2000, lambda: self.copy_msg.config(text=""))

    def save_csv(self):
        t = self.export_text()
        if not t:
            messagebox.showinfo(APP, "내보낼 데이터가 없습니다. 축 보정과 점을 확인하세요.", parent=self.root)
            return
        tab = self.delim.get().startswith("Tab")
        base = os.path.splitext(os.path.basename(self.img_path))[0] if self.img_path else "digitized"
        path = filedialog.asksaveasfilename(
            parent=self.root, initialfile=base + (".txt" if tab else ".csv"),
            defaultextension=".txt" if tab else ".csv",
            filetypes=[("CSV", "*.csv"), ("Text", "*.txt"), ("All files", "*.*")])
        if path:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(t.replace("\n", "\r\n") if sys.platform.startswith("win") else t)
            self.copy_msg.config(text="저장됨 ✓")
            self.root.after(2000, lambda: self.copy_msg.config(text=""))

    # ------------------------------------------------------------ project
    def save_project(self):
        if not self.img:
            return
        base = os.path.splitext(os.path.basename(self.img_path))[0] if self.img_path else "digitizer"
        path = filedialog.asksaveasfilename(parent=self.root, initialfile=base + ".pdig.json",
                                            defaultextension=".json", filetypes=[("Digitizer project", "*.json")])
        if not path:
            return
        buf = io.BytesIO()
        self.img.save(buf, "PNG")
        data = {
            "app": APP, "version": VERSION,
            "image_png_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "image_name": os.path.basename(self.img_path) if self.img_path else None,
            "calib": self.calib, "values": {k: v.get() for k, v in self.cal_vars.items()},
            "logx": self.logx.get(), "logy": self.logy.get(),
            "datasets": self.datasets, "act": self.act,
            "pick_color": self.pick_color,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def load_project(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[("Digitizer project", "*.json"), ("All", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            im = Image.open(io.BytesIO(base64.b64decode(d["image_png_base64"])))
            im.load()
        except Exception as ex:
            messagebox.showerror(APP, f"프로젝트를 열 수 없습니다:\n{ex}", parent=self.root)
            return
        self.set_image(im, d.get("image_name"), keep=True)
        self.calib = d["calib"]
        for k, v in d["values"].items():
            self.cal_vars[k].set(v)
        self.logx.set(d["logx"])
        self.logy.set(d["logy"])
        self.datasets = d["datasets"] or []
        if not self.datasets:
            self._new_ds()
        self.act = min(d.get("act", 0), len(self.datasets) - 1)
        self.pick_color = tuple(d["pick_color"]) if d.get("pick_color") else None
        self.hist = []
        self.set_mode("add")

    def show_help(self):
        messagebox.showinfo(APP, (
            "1) 이미지 열기 (Ctrl+O) / 붙여넣기 (Ctrl+V)\n"
            "2) ① Axis 보정: X축 위 두 점(X1,X2), Y축 위 두 점(Y1,Y2)을 클릭하고 값을 입력. "
            "Log 축은 체크.\n"
            "3) ② 점 추가: 클릭으로 추가, 드래그로 이동, 우클릭으로 삭제\n"
            "   또는 ③ Color pick으로 곡선 색 선택 → '현재 시리즈에 추출'\n"
            "4) 클립보드 복사 또는 CSV 저장 (Ctrl+E)\n\n"
            "휠: 확대/축소 · Space+드래그 / 휠버튼 드래그: 이동 · F: 화면 맞춤\n"
            "프로젝트 저장(Ctrl+S)은 이미지·보정·점을 하나의 .json에 저장합니다."), parent=self.root)

    # ------------------------------------------------------------- refresh
    def refresh(self, rebuild_ds=True):
        m = self.mode.get()
        nxt = next((i for i, p in enumerate(self.calib) if p is None), -1)
        for i, s in enumerate(self.cal_status):
            if self.calib[i]:
                s.config(text="설정됨", style="Ok.TLabel")
            elif m == "calib" and i == nxt and self.img:
                s.config(text="클릭 대기", style="Wait.TLabel")
            else:
                s.config(text="미설정", style="TLabel")
        self.cal_msg.config(text=self.cal_message())
        if self.pick_color:
            self.swatch.config(bg="#%02x%02x%02x" % self.pick_color)
            self.pick_lbl.config(text="RGB(%d, %d, %d)" % self.pick_color)
        else:
            self.swatch.config(bg="#dddddd")
            self.pick_lbl.config(text="색상 미선택 — ③ Color pick 모드에서 곡선 클릭")
        self.hint.config(text=self.hint_text())
        if rebuild_ds:
            self.render_ds()
        self.render_table()
        self.draw_overlay()
        self.draw_loupe()


def main():
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    app = Digitizer(root)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args and os.path.isfile(args[0]):
        root.after(100, lambda: app.open_image(args[0]))
    root.mainloop()


if __name__ == "__main__":
    main()
