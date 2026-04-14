import TkEasyGUI as sg
from PIL import Image, ImageTk, ImageDraw


class ND2View:
    """ND2画像ビューワーのUIと描画を担当
    （右クリック4分割 + Pearson単一フリーハンド + バッチPearson複数ROI + Cellpose 1細胞モード）"""

    def __init__(self, config):
        self.config = config
        self.controller = None
        self.window = None
        self.canvas_widget = None
        self.current_pil_image = None
        self.photo_ref = None

        self.zoom_factor = 1.0
        self.image_x = 0
        self.image_y = 0
        self._is_first_display = True

        # 右クリックBBox（4分割表示用）
        self.bbox_mode = False
        self.bbox_start = None
        self.current_bbox = None
        self.bbox_rect_id = None

        # ====================== フリーハンド（Pearson単一用） ======================
        self.freehand_mode = False
        self.freehand_for_pearson = False
        self.freehand_points = []
        self.freehand_line_ids = []

        # ====================== バッチPearson（複数ROI） ======================
        self.batch_pearson_mode = False
        self.batch_rois = []       

        # ====================== Cellpose 1細胞モード ======================
        self.cellpose_z_mode = False
        
        # レイアウト構築
        self.canvas_area = self._create_canvas_area()
        self.control_column = self._create_control_column()

        self.layout = [
            [sg.Column(self.canvas_area, pad=(15, 15), expand_y=True),
             sg.VSeparator(pad=(10, 0)),
             sg.Column(self.control_column, pad=(15, 15), expand_y=True)]
        ]

    def _create_canvas_area(self):
        return [
            [sg.Canvas(key="-CANVAS-", size=self.config.ND2_CANVAS_SIZE, background_color="#1e1e1e")],
            [sg.Text("ND2ファイル:", size=(12, 1), font=("Helvetica", 10, "bold")),
             sg.Text("", key="-ND2_FILENAME-", size=(70, 1))],
            
            [sg.Text("ND2番号:", size=(10, 1)),
             sg.Slider(range=(0, 0), default_value=0, key="-ND2_SLIDER-", orientation="h", size=(35, 2), enable_events=True),
             sg.Input(key="-ND2_JUMP-", size=(6, 1), default_text="0"),
             sg.Button("ジャンプ", key="-ND2_JUMP_BTN-", size=(8, 1)),
             sg.Button("▶ ND2再生", key="-PLAY_ND2-", size=(10, 1)),
             sg.Button("■ ND2停止", key="-STOP_ND2-", size=(10, 1))],

            [sg.Text("Z stack:", size=(8, 1)),
             sg.Slider(range=(0, 0), default_value=0, key="-Z_SLIDER-", orientation="h", size=(40, 2), enable_events=True),
             sg.Button("▶ Z再生", key="-PLAY_Z-", size=(8, 1)),
             sg.Button("■ Z停止", key="-STOP_Z-", size=(8, 1))],
            [sg.Text("Time (T):", size=(8, 1)),
             sg.Slider(range=(0, 0), default_value=0, key="-T_SLIDER-", orientation="h", size=(40, 2), enable_events=True),
             sg.Button("▶ T再生", key="-PLAY_T-", size=(8, 1)),
             sg.Button("■ T停止", key="-STOP_T-", size=(8, 1))],
            [sg.Text("FPS:"), 
             sg.Slider(range=(1, 30), default_value=10, key="-FPS-", orientation="h", size=(30, 2), enable_events=True)],
        ]

    def _create_control_column(self):
        return [
            [sg.Text("Image E Fiji Viewer", font=("Helvetica", 14, "bold"))],
            [sg.Text("─" * 60, text_color="#666")],
            *self._create_display_mode_section(),
            [sg.Text("─" * 60, text_color="#666")],
            *self._create_channel_section(),
            [sg.Text("─" * 60, text_color="#666")],
            *self._create_zoom_help_section(),
            [sg.Button("Reset All Min/Max", key="-RESET_MINMAX-", size=(25, 1))],
            [sg.Button("現在の画像を保存", key="-SAVE_ND2-", size=(25, 1), button_color=("white", "#1976d2"))],
            
            # ====================== Pearson相関係数（バッチ専用） ======================
            [sg.Text("─" * 60, text_color="#666")],
            [sg.Text("Pearson相関係数（複数領域バッチ）", font=("Helvetica", 12, "bold"), text_color="#ff9800")],
            [sg.Button("① 領域選択開始", key="-START_BATCH_PEARSON-", size=(25, 1), 
                       button_color=("white", "#ff9800"))],
            [sg.Button("② 選択領域で計算実行", key="-RUN_BATCH_PEARSON-", size=(25, 1), 
                       button_color=("white", "#d84315"), disabled=True)],
            
            [sg.Button("閉じる", key="-CLOSE-", size=(15, 1), button_color=("white", "#d32f2f"))],
            
            # ====================== Cellpose Z-stack (1細胞モードのみ) ======================
            [sg.Text("─" * 60, text_color="#666")],
            [sg.Text("Cellpose Z-stackセグメンテーション", font=("Helvetica", 12, "bold"), text_color="#4caf50")],
            [sg.Button("Cellpose Z-stack (1細胞から)", key="-START_CELLPOSE_Z-", size=(28, 1), 
                       button_color=("white", "#4caf50"))],
        ]

    def _create_display_mode_section(self):
        return [
            [sg.Text("表示モード", font=("Helvetica", 12, "bold"))],
            [sg.Radio("CMYモード (Cyan/Magenta/Yellow)", "display_mode", default=True, key="-MODE_CMY-", enable_events=True)],
            [sg.Radio("RGBモード", "display_mode", default=False, key="-MODE_RGB-", enable_events=True)],
            [sg.Radio("BGRモード", "display_mode", default=False, key="-MODE_BGR-", enable_events=True)],
        ]

    def _create_channel_section(self):
        return [
            [sg.Text("Cyan / Red (Ch0)", text_color="#00ffff", font=("Helvetica", 10, "bold"), key="-CH0_LABEL-")],
            [sg.Checkbox("表示", default=True, key="-CH0-", enable_events=True)],
            [sg.Text("Min:"), 
             sg.Slider(range=(0, self.config.BIT12_MAX), default_value=0, key="-MIN_CH0-", orientation="h", 
                       size=self.config.SLIDER_SIZE, enable_events=True),
             sg.Text(" Max:"), 
             sg.Slider(range=(0, self.config.BIT12_MAX), default_value=self.config.BIT12_MAX, key="-MAX_CH0-", 
                       orientation="h", size=self.config.SLIDER_SIZE, enable_events=True)],

            [sg.Text("Magenta / Green (Ch1)", text_color="#ff00ff", font=("Helvetica", 10, "bold"), key="-CH1_LABEL-")],
            [sg.Checkbox("表示", default=True, key="-CH1-", enable_events=True)],
            [sg.Text("Min:"), 
             sg.Slider(range=(0, self.config.BIT12_MAX), default_value=0, key="-MIN_CH1-", orientation="h", 
                       size=self.config.SLIDER_SIZE, enable_events=True),
             sg.Text(" Max:"), 
             sg.Slider(range=(0, self.config.BIT12_MAX), default_value=self.config.BIT12_MAX, key="-MAX_CH1-", 
                       orientation="h", size=self.config.SLIDER_SIZE, enable_events=True)],

            [sg.Text("Yellow / Blue (Ch2)", text_color="#ffff00", font=("Helvetica", 10, "bold"), key="-CH2_LABEL-")],
            [sg.Checkbox("表示", default=True, key="-CH2-", enable_events=True)],
            [sg.Text("Min:"), 
             sg.Slider(range=(0, self.config.BIT12_MAX), default_value=0, key="-MIN_CH2-", orientation="h", 
                       size=self.config.SLIDER_SIZE, enable_events=True),
             sg.Text(" Max:"), 
             sg.Slider(range=(0, self.config.BIT12_MAX), default_value=self.config.BIT12_MAX, key="-MAX_CH2-", 
                       orientation="h", size=self.config.SLIDER_SIZE, enable_events=True)],
        ]

    def _create_zoom_help_section(self):
        return [
            [sg.Text("操作方法:", font=("Helvetica", 10, "bold"))],
            [sg.Text("・マウスホイール：ズームイン/アウト", font=("Helvetica", 9))],
            [sg.Text("・左ドラッグ：パン移動", font=("Helvetica", 9))],
            [sg.Text("・ダブルクリック：表示をリセット", font=("Helvetica", 9))],
            [sg.Text("・右クリックドラッグ：正方形選択 → 4分割表示", font=("Helvetica", 9, "bold"), text_color="#ff0000")],
        ]
        
    # ====================== UI更新メソッド ======================
    def update_channel_checkboxes(self, enabled_list):
        """チャンネル表示/非表示チェックボックスを更新"""
        for i in range(3):
            self.window[f"-CH{i}-"].update(enabled_list[i])

    def update_min_max_sliders(self, channel_params):
        """Min/Maxスライダーの値を更新"""
        for ch in range(3):
            self.window[f"-MIN_CH{ch}-"].update(channel_params[ch]["min"])
            self.window[f"-MAX_CH{ch}-"].update(channel_params[ch]["max"])

    def update_channel_labels(self, display_mode):
        """チャンネルラベル（Cyan/Magentaなど）を表示モードに応じて更新"""
        if display_mode == "CMY":
            self.window["-CH0_LABEL-"].update("Cyan (Ch0)", text_color="#00ffff")
            self.window["-CH1_LABEL-"].update("Magenta (Ch1)", text_color="#ff00ff")
            self.window["-CH2_LABEL-"].update("Yellow (Ch2)", text_color="#ffff00")
        elif display_mode == "RGB":
            self.window["-CH0_LABEL-"].update("Red (Ch0)", text_color="#ff0000")
            self.window["-CH1_LABEL-"].update("Green (Ch1)", text_color="#00ff00")
            self.window["-CH2_LABEL-"].update("Blue (Ch2)", text_color="#0000ff")
        elif display_mode == "BGR":
            self.window["-CH0_LABEL-"].update("Blue (Ch0)", text_color="#0000ff")
            self.window["-CH1_LABEL-"].update("Green (Ch1)", text_color="#00ff00")
            self.window["-CH2_LABEL-"].update("Red (Ch2)", text_color="#ff0000")

    def update_nd2_slider(self, max_val, current_val):
        """ND2ファイル選択スライダーを更新"""
        if self.window:
            self.window["-ND2_SLIDER-"].update(range=(0, max_val), value=current_val)

    def update_z_slider(self, max_val, value=0):
        """Zスライダーを更新"""
        if self.window and max_val >= 0:
            self.window["-Z_SLIDER-"].update(range=(0, max_val), value=value)

    def update_t_slider(self, max_val, value=0):
        """Tスライダーを更新"""
        if self.window and max_val >= 0:
            self.window["-T_SLIDER-"].update(range=(0, max_val), value=value)

    def update_filename(self, filename):
        """ND2ファイル名を表示"""
        if self.window:
            self.window["-ND2_FILENAME-"].update(filename)

    # ====================== ウィンドウ作成 ======================
    def create_window(self):
        self.window = sg.Window(
            self.config.ND2_WINDOW_TITLE,
            self.layout,
            size=self.config.ND2_WINDOW_SIZE,
            finalize=True,
            resizable=True,
            element_justification="left"
        )

        self.canvas_widget = self.window["-CANVAS-"].Widget

        # マウスイベントバインド
        self.canvas_widget.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas_widget.bind("<Button-4>", self._on_mouse_wheel)
        self.canvas_widget.bind("<Button-5>", self._on_mouse_wheel)

        self.canvas_widget.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas_widget.bind("<B1-Motion>", self._on_drag_move)
        self.canvas_widget.bind("<Double-Button-1>", self._on_double_click)
        self.canvas_widget.bind("<ButtonRelease-1>", self._on_button_release)

        self.canvas_widget.bind("<Button-3>", self._start_bbox_mode)
        self.canvas_widget.bind("<B3-Motion>", self._on_bbox_drag)
        self.canvas_widget.bind("<ButtonRelease-3>", self._on_bbox_release)

        print("[DEBUG] Canvas events bound: 左クリック=パン/フリーハンド / 右クリック=4分割/Pearson確定")
        return self.window

    # ====================== バッチPearsonモード ======================
    def _start_batch_pearson_mode(self):
        if self.current_pil_image is None:
            sg.popup_warning("画像が表示されていません")
            return

        self.batch_pearson_mode = True
        self.batch_rois = []
        self.freehand_mode = True
        self.freehand_for_pearson = True
        self.freehand_points = []
        self.freehand_line_ids = []

        if self.window:
            self.window["-RUN_BATCH_PEARSON-"].update(disabled=False)

        sg.popup_ok(
            "【Pearson領域選択モード】開始\n\n"
            "1. ND2番号 / Z / T を切り替える\n"
            "2. 左ドラッグで領域を囲む\n"
            "3. 右クリックで登録\n\n"
            "複数の領域を選択後、「② 選択領域で計算実行」を押してください。",
            title="Pearson領域選択開始"
        )
        print("[DEBUG] Pearson領域選択モード開始")

    def _finish_batch_pearson(self):
        if not self.batch_rois:
            sg.popup_warning("領域が1つも選択されていません")
            self._cleanup_batch()
            return

        if self.controller:
            self.controller.on_batch_pearson_selected(self.batch_rois)

        self._cleanup_batch()

    def _cleanup_batch(self):
        self.batch_pearson_mode = False
        self.batch_rois = []
        self.freehand_mode = False
        self.freehand_for_pearson = False
        self._cleanup_freehand_lines_only()
        print("[DEBUG] バッチPearsonモード完全終了")

    # ====================== フリーハンドモード ======================
    def _start_freehand_mode(self):
        if self.current_pil_image is None:
            sg.popup_warning("画像が表示されていません")
            return

        self.freehand_mode = True
        self.freehand_for_pearson = True
        self.freehand_points = []
        self.freehand_line_ids = []

        sg.popup_ok(
            "【Pearson相関係数 用 フリーハンド選択モード】\n\n"
            "・左ドラッグ：領域を囲む\n"
            "・右クリック：確定して計算実行",
            title="Pearsonフリーハンド選択"
        )

    def _on_freehand_press(self, event):
        if not self.freehand_mode:
            self._on_drag_start(event)
            return
        self.freehand_points = [(event.x, event.y)]

    def _on_freehand_drag(self, event):
        if not self.freehand_mode or not self.freehand_points:
            if not self.freehand_mode:
                self._on_drag_move(event)
            return

        x, y = event.x, event.y
        last_x, last_y = self.freehand_points[-1]
        line_id = self.canvas_widget.create_line(
            last_x, last_y, x, y, fill="#00ff88", width=3, smooth=True
        )
        self.freehand_line_ids.append(line_id)
        self.freehand_points.append((x, y))

    def _on_freehand_release(self, event):
        pass

    def _on_freehand_confirm(self, event):
        """右クリック確定（1細胞Cellpose + Pearson対応）"""
        if not self.freehand_mode or len(self.freehand_points) < 3:
            self._cleanup_freehand()
            return

        # ====================== 座標変換 ======================
        canvas_w, canvas_h = self.config.ND2_CANVAS_SIZE
        img_w, img_h = self.current_pil_image.width, self.current_pil_image.height
        scale = self.zoom_factor
        offset_x = (canvas_w - img_w * scale) // 2 + self.image_x
        offset_y = (canvas_h - img_h * scale) // 2 + self.image_y

        polygon = []
        for cx, cy in self.freehand_points:
            ox = max(0, int((cx - offset_x) / scale))
            oy = max(0, int((cy - offset_y) / scale))
            if ox < img_w and oy < img_h:
                polygon.append((ox, oy))

        if len(polygon) < 3:
            self._cleanup_freehand()
            return

        # ====================== モード分岐 ======================
        if self.batch_pearson_mode:
            # バッチPearsonモード
            current_filename = self.window["-ND2_FILENAME-"].get() if self.window else "Unknown"
            self.batch_rois.append({
                'polygon': polygon,
                'nd2_idx': getattr(self.controller, 'current_nd2_idx', 0),
                'z': getattr(self.controller, 'current_z', 0),
                't': getattr(self.controller, 'current_t', 0),
                'filename': current_filename
            })
            count = len(self.batch_rois)
            sg.popup(f"✅ 領域を登録しました！（現在 {count} 個）", title=f"領域登録 ({count}個)")
            self._cleanup_freehand_lines_only()

        elif self.cellpose_z_mode:
            # Cellpose 1細胞モード（これだけ残す）
            if self.controller:
                self.controller.on_cellpose_z_selected(polygon, getattr(self.controller, 'current_z', 0))
            self._cleanup_freehand()

        else:
            # 単一Pearsonモード
            if self.controller:
                self.controller.on_freehand_selected(polygon)
            self._cleanup_freehand()

    def _cleanup_freehand_lines_only(self):
        for line_id in self.freehand_line_ids:
            try:
                self.canvas_widget.delete(line_id)
            except:
                pass
        self.freehand_points = []
        self.freehand_line_ids = []
        print("[DEBUG] フリーハンド線のみクリア")

    def _cleanup_freehand(self):
        """フリーハンドモードを完全に終了"""
        self.freehand_mode = False
        self.freehand_for_pearson = False
        self.cellpose_z_mode = False

        self._cleanup_freehand_lines_only()
        print("[DEBUG] フリーハンドモード完全終了 → 通常操作に戻りました")

    # ====================== Cellpose 1細胞モード ======================
    def _start_cellpose_z_mode(self):
        """「Cellpose Z-stack (1細胞から)」ボタン押下時の処理"""
        if self.current_pil_image is None:
            sg.popup_warning("画像が表示されていません")
            return

        self.cellpose_z_mode = True
        self.freehand_mode = True
        self.freehand_for_pearson = False
        self.freehand_points = []
        self.freehand_line_ids = []

        sg.popup_ok(
            "【Cellpose Z-stack 1細胞モード】開始\n\n"
            "操作手順:\n"
            "1. 任意のZスライスに移動\n"
            "2. 1細胞だけを左ドラッグで丁寧に囲む\n"
            "3. 右クリックで確定 → チャンネル選択画面が表示されます\n\n"
            "※必ず1細胞だけを囲んでください。精度が大幅に向上します。",
            title="Cellpose Z-stack モード開始"
        )
        print("[DEBUG] Cellpose Z-stack (1細胞) モード開始")

    # ====================== マウス操作 ======================
    def _on_mouse_wheel(self, event):
        if self.current_pil_image is None:
            return
        if event.num == 4 or event.delta > 0:
            self.zoom_factor *= 1.1
        elif event.num == 5 or event.delta < 0:
            self.zoom_factor /= 1.1

        self.zoom_factor = max(0.2, min(self.zoom_factor, 10.0))
        self._redraw_image()

    def _on_drag_start(self, event):
        if self.freehand_mode:
            self._on_freehand_press(event)
            return
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def _on_drag_move(self, event):
        if self.freehand_mode:
            self._on_freehand_drag(event)
            return
        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y
        self.image_x += dx
        self.image_y += dy
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self._redraw_image()

    def _on_button_release(self, event):
        if self.freehand_mode:
            self._on_freehand_release(event)
            return

    def _on_double_click(self, event):
        if self.current_pil_image is None:
            return
        self.zoom_factor = self._get_fit_zoom_factor()
        self.image_x = 0
        self.image_y = 0
        self._redraw_image()

    # ====================== 右クリック処理 ======================
    def _start_bbox_mode(self, event):
        if self.freehand_mode or self.batch_pearson_mode:
            return
        if self.current_pil_image is None:
            sg.popup_warning("画像が表示されていません")
            return

        canvas_x = event.x - self.canvas_widget.winfo_x()
        canvas_y = event.y - self.canvas_widget.winfo_y()

        self.bbox_mode = True
        self.bbox_start = (canvas_x, canvas_y)
        self.current_bbox = None

        if self.bbox_rect_id:
            self.canvas_widget.delete(self.bbox_rect_id)
            self.bbox_rect_id = None

    def _on_bbox_drag(self, event):
        if self.freehand_mode or self.batch_pearson_mode:
            return
        if not self.bbox_mode or self.bbox_start is None:
            return

        canvas_x = event.x - self.canvas_widget.winfo_x()
        canvas_y = event.y - self.canvas_widget.winfo_y()

        x1, y1 = self.bbox_start
        x2, y2 = canvas_x, canvas_y

        if self.bbox_rect_id:
            self.canvas_widget.delete(self.bbox_rect_id)

        self.bbox_rect_id = self.canvas_widget.create_rectangle(
            x1, y1, x2, y2, outline="#ff0000", width=3, dash=(6, 4)
        )

    def _on_bbox_release(self, event):
        """右クリックリリース処理"""
        if self.freehand_mode or self.batch_pearson_mode or self.cellpose_z_mode:
            self._on_freehand_confirm(event)
            self.bbox_mode = False
            return

        # 4分割処理
        if not self.bbox_mode or self.bbox_start is None or self.current_pil_image is None:
            self.bbox_mode = False
            return

        # ... (4分割の既存コードはそのまま) ...
        canvas_x = event.x - self.canvas_widget.winfo_x()
        canvas_y = event.y - self.canvas_widget.winfo_y()

        x1, y1 = self.bbox_start
        x2, y2 = canvas_x, canvas_y

        canvas_w, canvas_h = self.config.ND2_CANVAS_SIZE
        img_w, img_h = self.current_pil_image.width, self.current_pil_image.height
        scale = self.zoom_factor
        offset_x = (canvas_w - img_w * scale) // 2 + self.image_x
        offset_y = (canvas_h - img_h * scale) // 2 + self.image_y

        orig_x1 = max(0, int((x1 - offset_x) / scale))
        orig_y1 = max(0, int((y1 - offset_y) / scale))
        orig_x2 = min(img_w, int((x2 - offset_x) / scale))
        orig_y2 = min(img_h, int((y2 - offset_y) / scale))

        if orig_x2 - orig_x1 < 30:
            sg.popup_warning("選択範囲が小さすぎます（30px以上）")
            self.bbox_mode = False
            return

        self.current_bbox = (orig_x1, orig_y1, orig_x2, orig_y2)
        self.bbox_mode = False

        if self.controller:
            self.controller.show_bbox_four_panel(self.current_bbox)

    # ====================== 画像表示 ======================
    def display_composite(self, rgb_array):
        """合成画像を表示（controllerから呼ばれるメイン関数）"""
        if rgb_array is None:
            return
        self.current_pil_image = Image.fromarray(rgb_array)

        if self._is_first_display:
            self.zoom_factor = self._get_fit_zoom_factor()
            self.image_x = 0
            self.image_y = 0
            self._is_first_display = False

        self._redraw_image()

    def _redraw_image(self):
        """キャンバスに現在のPIL画像をズーム・パン状態で再描画"""
        if self.current_pil_image is None or not self.canvas_widget:
            return

        canvas = self.canvas_widget
        canvas.delete("all")

        zoomed_size = (int(self.current_pil_image.width * self.zoom_factor),
                       int(self.current_pil_image.height * self.zoom_factor))

        resized = self.current_pil_image.resize(zoomed_size, Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(resized)
        self.photo_ref = photo  # 参照保持（ガベージコレクション防止）

        cx = (self.config.ND2_CANVAS_SIZE[0] - zoomed_size[0]) // 2 + self.image_x
        cy = (self.config.ND2_CANVAS_SIZE[1] - zoomed_size[1]) // 2 + self.image_y

        canvas.create_image(cx, cy, image=photo, anchor="nw")

    def _get_fit_zoom_factor(self):
        """画像をキャンバスにフィットさせるズーム倍率を計算"""
        if self.current_pil_image is None:
            return 1.0
        ratio_w = self.config.ND2_CANVAS_SIZE[0] / self.current_pil_image.width
        ratio_h = self.config.ND2_CANVAS_SIZE[1] / self.current_pil_image.height
        return min(ratio_w, ratio_h) * 0.98
    
        # ====================== UI更新メソッド ======================
    def update_channel_checkboxes(self, enabled_list):
        for i in range(3):
            self.window[f"-CH{i}-"].update(enabled_list[i])

    def update_min_max_sliders(self, channel_params):
        for ch in range(3):
            self.window[f"-MIN_CH{ch}-"].update(channel_params[ch]["min"])
            self.window[f"-MAX_CH{ch}-"].update(channel_params[ch]["max"])

    def update_channel_labels(self, display_mode):
        if display_mode == "CMY":
            self.window["-CH0_LABEL-"].update("Cyan (Ch0)", text_color="#00ffff")
            self.window["-CH1_LABEL-"].update("Magenta (Ch1)", text_color="#ff00ff")
            self.window["-CH2_LABEL-"].update("Yellow (Ch2)", text_color="#ffff00")
        elif display_mode == "RGB":
            self.window["-CH0_LABEL-"].update("Red (Ch0)", text_color="#ff0000")
            self.window["-CH1_LABEL-"].update("Green (Ch1)", text_color="#00ff00")
            self.window["-CH2_LABEL-"].update("Blue (Ch2)", text_color="#0000ff")
        elif display_mode == "BGR":
            self.window["-CH0_LABEL-"].update("Blue (Ch0)", text_color="#0000ff")
            self.window["-CH1_LABEL-"].update("Green (Ch1)", text_color="#00ff00")
            self.window["-CH2_LABEL-"].update("Red (Ch2)", text_color="#ff0000")

    def update_nd2_slider(self, max_val, current_val):
        if self.window:
            self.window["-ND2_SLIDER-"].update(range=(0, max_val), value=current_val)

    def update_z_slider(self, max_val, value=0):
        if self.window and max_val >= 0:
            self.window["-Z_SLIDER-"].update(range=(0, max_val), value=value)

    def update_t_slider(self, max_val, value=0):
        if self.window and max_val >= 0:
            self.window["-T_SLIDER-"].update(range=(0, max_val), value=value)

    def update_filename(self, filename):
        if self.window:
            self.window["-ND2_FILENAME-"].update(filename)

    def show_four_panel(self, ch0_pil, ch1_pil, ch2_pil, composite_pil, mode, bbox):
        """選択範囲を4分割表示（変更なし）"""
        x1, y1, x2, y2 = bbox
        size = x2 - x1

        if mode == "BGR":
            labels = ["Blue (Ch0)", "Green (Ch1)", "Red (Ch2)"]
        elif mode == "RGB":
            labels = ["Red (Ch0)", "Green (Ch1)", "Blue (Ch2)"]
        else:
            labels = ["Cyan (Ch0)", "Magenta (Ch1)", "Yellow (Ch2)"]

        layout = [
            [sg.Text(f"選択範囲: ({x1},{y1})〜({x2},{y2})   サイズ: {size}×{size}px   モード: {mode}",
                     font=("Helvetica", 11, "bold"))],
            [sg.Canvas(key="-FOUR_CANVAS-", size=(860, 860), background_color="#1e1e1e")],
            [sg.Button("この4分割画像を保存", key="-SAVE_FOUR-", size=(25, 1), button_color=("white", "#1976d2")),
             sg.Button("閉じる", key="-CLOSE_FOUR-", size=(15, 1), button_color=("white", "#d32f2f"))]
        ]

        win = sg.Window(f"4分割ビュー - {mode}モード", layout, size=(900, 950),
                        finalize=True, resizable=True, element_justification="center")

        canvas = win["-FOUR_CANVAS-"].Widget
        panel = 400
        gap = 20
        total_size = panel * 2 + gap

        canvas.create_rectangle(0, 0, total_size, total_size, fill="#1e1e1e", outline="")

        imgs = [img.resize((panel, panel), Image.Resampling.LANCZOS) 
                for img in (ch0_pil, ch1_pil, ch2_pil, composite_pil)]

        positions = [(0, 0), (panel + gap, 0), (0, panel + gap), (panel + gap, panel + gap)]

        photo_refs = []
        for i, (img, (px, py)) in enumerate(zip(imgs, positions)):
            photo = ImageTk.PhotoImage(img)
            photo_refs.append(photo)
            canvas.create_image(px, py, image=photo, anchor="nw")

            label = labels[i] if i < 3 else f"Composite ({mode})"
            canvas.create_text(px + 10, py + 10, text=label, fill="white",
                               font=("Helvetica", 10, "bold"), anchor="nw")

        line_color = "#ffffff"
        line_width = 4
        canvas.create_line(panel + gap//2, 0, panel + gap//2, total_size, fill=line_color, width=line_width)
        canvas.create_line(0, panel + gap//2, total_size, panel + gap//2, fill=line_color, width=line_width)
        canvas.create_rectangle(2, 2, total_size-2, total_size-2, outline=line_color, width=line_width)

        win.photo_refs = photo_refs

        while True:
            event, _ = win.read()
            if event in (sg.WINDOW_CLOSED, "-CLOSE_FOUR-"):
                break
            elif event == "-SAVE_FOUR-":
                save_path = sg.popup_get_file("保存先を選択", save_as=True,
                                              file_types=(("PNG", "*.png"), ("JPG", "*.jpg")))
                if save_path:
                    if not save_path.lower().endswith(('.png', '.jpg', '.jpeg')):
                        save_path += '.png'
                    full = Image.new("RGB", (total_size, total_size), color="#1e1e1e")
                    full.paste(imgs[0], (0, 0))
                    full.paste(imgs[1], (panel + gap, 0))
                    full.paste(imgs[2], (0, panel + gap))
                    full.paste(imgs[3], (panel + gap, panel + gap))
                    
                    draw = ImageDraw.Draw(full)
                    draw.line([(panel + gap//2, 0), (panel + gap//2, total_size)], fill=line_color, width=line_width)
                    draw.line([(0, panel + gap//2), (total_size, panel + gap//2)], fill=line_color, width=line_width)
                    draw.rectangle([2, 2, total_size-2, total_size-2], outline=line_color, width=line_width)
                    
                    full.save(save_path)
                    sg.popup("4分割画像を保存しました！")

        win.close()
        
    def _run_batch_pearson_calculation(self):
        """② 選択領域で計算実行 ボタン押下"""
        if not self.batch_pearson_mode:
            sg.popup_warning("まず「① 領域選択開始」ボタンを押してください")
            return

        if not self.batch_rois:
            sg.popup_warning("登録された領域がありません。\n先に①で領域を登録してください")
            return

        if self.controller:
            self.controller.on_batch_pearson_selected(self.batch_rois)

        # モード終了処理
        self._cleanup_batch()

        # 計算実行ボタンを再度無効化
        if self.window:
            self.window["-RUN_BATCH_PEARSON-"].update(disabled=True)

        print("[DEBUG] バッチPearson計算を実行しました")

    def show_cellpose_z_masks(self, overlaid_list):
        """Cellpose 3D結果を表示（アスペクト比保持 + 完全安定版）
           画像が表示され、ウィンドウを閉じてもエラーが出ない最終版"""
        if not overlaid_list:
            return

        z_size = len(overlaid_list)
        layout = [
            [sg.Text(f"Cellpose Z-stack マスク結果 (全 {z_size} 枚)", font=("Helvetica", 12, "bold"))],
            [sg.Canvas(key="-Z_MASK_CANVAS-", size=(800, 600), background_color="#1e1e1e")],
            [sg.Text("Z:"),
             sg.Slider(range=(0, z_size-1), default_value=0, key="-Z_MASK_SLIDER-", 
                       orientation="h", size=(50, 20), enable_events=True)],
            [sg.Button("閉じる", key="-CLOSE_Z_MASK-", size=(15, 1))]
        ]

        win = sg.Window(
            "Cellpose Z-stack マスク結果",
            layout,
            finalize=True,
            modal=True,
            resizable=True,
            element_justification="center"
        )

        # Canvasを確実に初期化
        win.read(timeout=0)

        canvas = win["-Z_MASK_CANVAS-"].Widget
        current_photo = None

        def redraw(z_idx):
            nonlocal current_photo
            canvas.delete("all")
            pil = overlaid_list[z_idx]

            # アスペクト比を保持してリサイズ（画像が曲がらない）
            canvas_w, canvas_h = 800, 600
            scale_w = canvas_w / pil.width
            scale_h = canvas_h / pil.height
            scale = min(scale_w, scale_h) * 0.98
            new_w = int(pil.width * scale)
            new_h = int(pil.height * scale)

            resized = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(resized)
            current_photo = photo

            # 中央配置
            pos_x = (canvas_w - new_w) // 2
            pos_y = (canvas_h - new_h) // 2
            canvas.create_image(pos_x, pos_y, image=photo, anchor="nw")

            canvas.create_text(10, 10, text=f"Z = {z_idx}", 
                               fill="white", font=("Helvetica", 14, "bold"))

        # 初回描画
        redraw(0)

        # イベントループ
        while True:
            event, values = win.read()
            if event in (sg.WINDOW_CLOSED, "-CLOSE_Z_MASK-"):
                break
            if event == "-Z_MASK_SLIDER-":
                redraw(int(values["-Z_MASK_SLIDER-"]))

        win.close()
        
    def show_cellpose_cropped_cells(self, cropped_list):
        """Cellposeで検出した細胞部分だけを切り抜いた画像を表示（背景黒）"""
        if not cropped_list:
            return

        z_size = len(cropped_list)
        layout = [
            [sg.Text(f"Cellpose 切り抜き細胞画像 (全 {z_size} 枚)", font=("Helvetica", 12, "bold"))],
            [sg.Canvas(key="-CROPPED_CANVAS-", size=(800, 600), background_color="#1e1e1e")],
            [sg.Text("Z:"),
             sg.Slider(range=(0, z_size-1), default_value=0, key="-CROPPED_SLIDER-", 
                       orientation="h", size=(50, 20), enable_events=True)],
            [sg.Button("閉じる", key="-CLOSE_CROPPED-", size=(15, 1))]
        ]

        win = sg.Window("Cellpose 切り抜き細胞画像", layout, finalize=True, modal=True, resizable=True)

        win.read(timeout=0)   # Canvas初期化
        canvas = win["-CROPPED_CANVAS-"].Widget
        current_photo = None

        def redraw(z_idx):
            nonlocal current_photo
            canvas.delete("all")
            pil = cropped_list[z_idx]

            # アスペクト比保持
            cw, ch = 800, 600
            scale = min(cw / pil.width, ch / pil.height) * 0.98
            new_size = (int(pil.width * scale), int(pil.height * scale))
            resized = pil.resize(new_size, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(resized)
            current_photo = photo

            pos_x = (cw - new_size[0]) // 2
            pos_y = (ch - new_size[1]) // 2
            canvas.create_image(pos_x, pos_y, image=photo, anchor="nw")
            canvas.create_text(10, 10, text=f"Z = {z_idx}  (切り抜き)", 
                               fill="white", font=("Helvetica", 14, "bold"))

        redraw(0)

        while True:
            event, values = win.read()
            if event in (sg.WINDOW_CLOSED, "-CLOSE_CROPPED-"):
                break
            if event == "-CROPPED_SLIDER-":
                redraw(int(values["-CROPPED_SLIDER-"]))

        win.close()

    def close(self):
        if self.window:
            self.window.close()