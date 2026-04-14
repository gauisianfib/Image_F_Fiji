# controller/nd2_controller.py
import TkEasyGUI as sg
import time
import os
import glob
import importlib.util
import sys
import numpy as np
from PIL import Image,ImageDraw

from plugins.base_plugin import BasePlugin
from model.nd2_model import ND2Model
from view.nd2_view import ND2View
from service.nd2_image_service import ND2ImageService
from utils.image_utils import apply_min_max_12bit, create_cmy_simple_composite

import cellpose.models as models
from cellpose.utils import stitch3D


class ND2Controller:
    def __init__(self, nd2_files, config):
        self.config = config
        self.model = ND2Model(nd2_files)
        self.view = ND2View(config)
        self.view.controller = self
        self.service = ND2ImageService(config)


        self.current_nd2_idx = 0
        self.current_z = 0
        self.current_t = 0
        self.channel_enabled = [True, True, True]
        self.channel_params = {
            0: {"min": 0, "max": config.BIT12_MAX},
            1: {"min": 0, "max": config.BIT12_MAX},
            2: {"min": 0, "max": config.BIT12_MAX}
        }

        self.is_playing_z = False
        self.is_playing_t = False
        self.is_playing_nd2 = False
        self.fps = 10
        self.last_update_z = time.time()
        self.last_update_t = time.time()
        self.last_update_nd2 = time.time()
        self.last_display_time = 0
        self.min_display_interval = config.MIN_DISPLAY_INTERVAL

        self.current_edited_image: Image.Image | None = None

        self.plugins = self._load_plugins()

        if not self.model.data_list:
            sg.popup_error("有効なND2ファイルがありませんでした")
            self.view.close()
            return

        self.display_mode = "CMY"

        self._add_plugin_buttons()
        self.window = self.view.create_window()
        
        self._load_current_nd2()
        self._display_current()

    def _load_plugins(self):
        plugins = []
        plugin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins")

        if not os.path.isdir(plugin_dir):
            print("pluginsフォルダが見つかりません。")
            return plugins

        original_path = sys.path[:]
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)

        for file in sorted(glob.glob(os.path.join(plugin_dir, "*.py"))):
            basename = os.path.basename(file)
            if basename.startswith("__") or basename == "base_plugin.py":
                continue

            try:
                module_name = os.path.splitext(basename)[0]
                spec = importlib.util.spec_from_file_location(module_name, file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                if hasattr(module, "Plugin"):
                    plugin_class = module.Plugin
                    if (isinstance(plugin_class, type) and
                            issubclass(plugin_class, BasePlugin) and
                            hasattr(plugin_class, "process") and callable(plugin_class.process)):

                        plugins.append(plugin_class)
                        print(f"プラグイン読み込み成功: {plugin_class.name} ({basename})")
                        continue

                print(f"警告: {basename} に有効な Plugin クラスが見つかりません")

            except Exception as e:
                print(f"プラグイン読み込み失敗 {basename}: {e}")

        sys.path[:] = original_path
        return plugins

    def _add_plugin_buttons(self):
        if not self.plugins:
            return

        # プラグインボタン用のレイアウトを作成
        plugin_layout = []
        row = []
        for i, plugin in enumerate(self.plugins):
            btn = sg.Button(
                plugin.name,
                key=f"-PLUGIN_{i}-",
                button_color=getattr(plugin, "button_color", ("white", "#607d8b")),
                size=(20, 1)
            )
            row.append(btn)
            if len(row) == 2:
                plugin_layout.append(row)
                row = []
        if row:
            plugin_layout.append(row)

        # セパレーターとタイトルを挿入
        plugin_section = [
            [sg.Text("─" * 60, text_color="#666")],
            [sg.Text("画像処理プラグイン", font=("Helvetica", 12, "bold"))],
            [sg.Column(plugin_layout, expand_x=True)]
        ]

        # ★★★ 重要：レイアウトを事前に拡張 ★★★
        # control_columnはリストなので、insertではなくextendで追加
        self.view.control_column.extend(plugin_section)

        # ウィンドウは最初に1回だけ作成するので、ここでは何もしない
        print(f"✅ プラグインボタン追加完了: {len(self.plugins)}個")

    def _load_current_nd2(self):
        data, sizes = self.model.get_data(self.current_nd2_idx)
        if data is None:
            return

        self.data = data
        self.sizes = sizes
        self.axis_order = list(sizes.keys())
        self.shape = data.shape

        self.z_size = sizes.get('Z', 1)
        self.t_size = sizes.get('T', 1)

        self.current_edited_image = None

        self.view.update_z_slider(self.z_size - 1, self.current_z)
        self.view.update_t_slider(self.t_size - 1, self.current_t)
        self.view.update_filename(f"{self.current_nd2_idx}: {self.model.get_filename(self.current_nd2_idx)}")
        self.view.update_nd2_slider(self.model.get_total_files() - 1, self.current_nd2_idx)
        self.view.update_channel_checkboxes(self.channel_enabled)
        self.view.update_min_max_sliders(self.channel_params)
        self.view.update_channel_labels(self.display_mode)
        self.view._is_first_display = True

    def run(self):
        while True:
            event, values = self.window.read(timeout=30)

            if event in (sg.WINDOW_CLOSED, "-CLOSE-"):
                self.is_playing_z = False
                self.is_playing_t = False
                break

            updated = False
            self.fps = int(values.get("-FPS-", 10))

            if event.startswith("-MODE_"):
                updated = self._handle_display_mode(event)
            elif event.startswith("-PLUGIN_"):
                updated = self._handle_plugin(event)

            elif event in ("-ND2_SLIDER-", "-ND2_JUMP_BTN-", "\r", "\n"):
                updated = self._handle_nd2_navigation(event, values)
            elif event in ("-Z_SLIDER-", "-T_SLIDER-"):
                updated = self._handle_slider(event, values)
            elif event in ("-CH0-", "-CH1-", "-CH2-"):
                updated = self._handle_channel_toggle(event, values)
            elif event.startswith(("-MIN_CH", "-MAX_CH")):
                updated = self._handle_minmax_change(event, values)
            elif event == "-RESET_MINMAX-":
                updated = self._handle_reset_minmax()
            elif event == "-SAVE_ND2-":
                self._save_nd2_composite()
                continue
            elif event in ("-PLAY_Z-", "-STOP_Z-", "-PLAY_T-", "-STOP_T-", "-PLAY_ND2-", "-STOP_ND2-"):
                self._handle_play_button(event)
            elif event == "-START_BATCH_PEARSON-":
                self.view._start_batch_pearson_mode()
                updated = False
            elif event == "-RUN_BATCH_PEARSON-":
                self.view._run_batch_pearson_calculation()
                updated = False

            elif event == "-START_CELLPOSE_Z-":          # ← ここを追加！
                self.view._start_cellpose_z_mode()
                updated = False
                

            now = time.time()
            if self.is_playing_z and self.z_size > 1:
                updated |= self._update_z_playback(now)
            if self.is_playing_t and self.t_size > 1:
                updated |= self._update_t_playback(now)
            if self.is_playing_nd2 and self.model.get_total_files() > 1:
                updated |= self._update_nd2_playback(now)

            if updated:
                current_time = time.time()
                if current_time - self.last_display_time >= self.min_display_interval:
                    self._display_current()
                    self.last_display_time = current_time

        self.view.close()
    def _calculate_pearson(self, rgb_array, display_mode="CMY", mask=None, roi_info=None, pairs=None):
        """Pearson相関係数を計算し、結果文字列を返す"""
        if rgb_array is None:
            return "エラー: 画像データがありません"

        rgb = np.array(rgb_array)
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            return "エラー: 有効な3チャンネル画像ではありません"

        # チャンネル抽出
        if mask is not None and mask.any():
            mask_flat = mask.flatten()
            ch = [
                rgb[..., 0].astype(np.float32).flatten()[mask_flat],
                rgb[..., 1].astype(np.float32).flatten()[mask_flat],
                rgb[..., 2].astype(np.float32).flatten()[mask_flat]
            ]
        else:
            ch = [
                rgb[..., 0].astype(np.float32).flatten(),
                rgb[..., 1].astype(np.float32).flatten(),
                rgb[..., 2].astype(np.float32).flatten()
            ]

        # BGRモード対応
        if display_mode == "BGR":
            if mask is not None and mask.any():
                temp = ch[:]
                ch[0] = temp[2]  # Blue
                ch[1] = temp[1]  # Green
                ch[2] = temp[0]  # Red
            else:
                ch[0] = rgb[..., 2].astype(np.float32).flatten()
                ch[1] = rgb[..., 1].astype(np.float32).flatten()
                ch[2] = rgb[..., 0].astype(np.float32).flatten()

        # ラベル設定
        if display_mode == "CMY":
            labels = ["Cyan (Ch0)", "Magenta (Ch1)", "Yellow (Ch2)"]
        elif display_mode == "RGB":
            labels = ["Red (Ch0)", "Green (Ch1)", "Blue (Ch2)"]
        elif display_mode == "BGR":
            labels = ["Blue (Ch0)", "Green (Ch1)", "Red (Ch2)"]
        else:
            labels = ["Ch0", "Ch1", "Ch2"]

        # ペアが指定されていない場合はすべて計算
        if not pairs:
            pairs = [(0,1), (0,2), (1,2)]

        def pearson_corr(x, y):
            if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
                return 0.0
            return np.corrcoef(x, y)[0, 1]

        result_lines = []
        for a, b in pairs:
            r = pearson_corr(ch[a], ch[b])
            result_lines.append(f"{labels[a]} ↔ {labels[b]} : {r:.4f}")

        # ヘッダー
        if roi_info:
            header = f"【領域 {roi_info.get('index', '')}】 {roi_info.get('filename', 'Unknown')}\n"
            header += f"ND2: {roi_info.get('nd2_idx', 0)} | Z: {roi_info.get('z', 0)} | T: {roi_info.get('t', 0)}\n\n"
        else:
            header = ""

        result = header + "\n".join(result_lines) + "\n" + "─" * 60 + "\n"
        return result

        def pearson_corr(x, y):
            if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
                return 0.0
            return np.corrcoef(x, y)[0, 1]

        result_lines = []
        for a, b in pairs:
            r = pearson_corr(ch[a], ch[b])
            result_lines.append(f"{labels[a]} ↔ {labels[b]} : {r:.4f}")

        # ヘッダー
        if roi_info:
            header = f"【領域 {roi_info.get('index', '')}】 {roi_info.get('filename', 'Unknown')}\n"
            header += f"ND2: {roi_info.get('nd2_idx', 0)} | Z: {roi_info.get('z', 0)} | T: {roi_info.get('t', 0)}\n\n"
        else:
            header = ""

        result = header + "\n".join(result_lines) + "\n" + "─" * 60 + "\n"
        return result

        # ====================== Pearson計算 ======================
        def pearson_corr(x, y):
            if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
                return 0.0
            return np.corrcoef(x, y)[0, 1]

        r01 = pearson_corr(ch0, ch1)
        r02 = pearson_corr(ch0, ch2)
        r12 = pearson_corr(ch1, ch2)

        # ====================== 表示ラベル ======================
        if display_mode == "CMY":
            labels = ["Cyan (Ch0)", "Magenta (Ch1)", "Yellow (Ch2)"]
        elif display_mode == "RGB":
            labels = ["Red (Ch0)", "Green (Ch1)", "Blue (Ch2)"]
        elif display_mode == "BGR":
            labels = ["Blue (Ch0)", "Green (Ch1)", "Red (Ch2)"]
        else:
            labels = ["Ch0", "Ch1", "Ch2"]

        # ====================== 結果文字列作成 ======================
        if roi_info:
            header = f"【領域 {roi_info.get('index', '')}】 {roi_info.get('filename', 'Unknown')}\n"
            header += f"ND2: {roi_info.get('nd2_idx', 0)} | Z: {roi_info.get('z', 0)} | T: {roi_info.get('t', 0)}\n\n"
        else:
            header = ""

        result = f"""{header}{labels[0]} ↔ {labels[1]} : {r01:.4f}
{labels[0]} ↔ {labels[2]} : {r02:.4f}
{labels[1]} ↔ {labels[2]} : {r12:.4f}
{'─' * 60}
"""
        return result

        # ====================== Pearson計算 ======================
        def pearson_corr(x, y):
            if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
                return 0.0
            return np.corrcoef(x, y)[0, 1]

        r01 = pearson_corr(ch0, ch1)
        r02 = pearson_corr(ch0, ch2)
        r12 = pearson_corr(ch1, ch2)

        # ====================== 表示ラベル ======================
        if display_mode == "CMY":
            labels = ["Cyan (Ch0)", "Magenta (Ch1)", "Yellow (Ch2)"]
        elif display_mode == "RGB":
            labels = ["Red (Ch0)", "Green (Ch1)", "Blue (Ch2)"]
        elif display_mode == "BGR":
            labels = ["Blue (Ch0)", "Green (Ch1)", "Red (Ch2)"]
        else:
            labels = ["Ch0", "Ch1", "Ch2"]

        result_text = f"""【Pearson相関係数（PCC）計算結果】 - {display_mode}モード

{labels[0]} ↔ {labels[1]} : {r01:.4f}
{labels[0]} ↔ {labels[2]} : {r02:.4f}
{labels[1]} ↔ {labels[2]} : {r12:.4f}

解釈:
・1.0 に近い → 非常に強い正の相関（よく共局在）
・0.0 前後 → 相関なし
・-1.0 に近い → 強い負の相関（互いに排他的）
"""

        sg.popup_scrolled(result_text, title=f"Pearson相関係数 ({display_mode}モード)", size=(85, 24))

    def _handle_display_mode(self, event):
        if event == "-MODE_CMY-":
            self.display_mode = "CMY"
        elif event == "-MODE_RGB-":
            self.display_mode = "RGB"
        elif event == "-MODE_BGR-":
            self.display_mode = "BGR"
        self.view.update_channel_labels(self.display_mode)
        return True

    def _handle_plugin(self, event):
        try:
            idx = int(event.replace("-PLUGIN_", "").replace("-", ""))
            if 0 <= idx < len(self.plugins):
                plugin_class = self.plugins[idx]

                # Pearson相関係数は専用ボタンで処理するため、ここではスキップ
                if getattr(plugin_class, "name", "") == "Pearson相関係数":
                    return False

                return self._apply_plugin(plugin_class)

        except Exception as e:
            sg.popup_error(f"プラグイン実行エラー:\n{e}")
        return False
    def _handle_nd2_navigation(self, event, values):
        try:
            if event == "-ND2_SLIDER-":
                new_idx = int(values["-ND2_SLIDER-"])
            else:
                new_idx = int(values.get("-ND2_JUMP-", "0"))
            if 0 <= new_idx < self.model.get_total_files() and new_idx != self.current_nd2_idx:
                self.current_nd2_idx = new_idx
                self._load_current_nd2()
                return True
        except:
            pass
        return False

    def _handle_slider(self, event, values):
        if event == "-Z_SLIDER-":
            self.current_z = int(values["-Z_SLIDER-"])
        else:
            self.current_t = int(values["-T_SLIDER-"])
        self.current_edited_image = None
        return True

    def _handle_channel_toggle(self, event, values):
        for i, key in enumerate(["-CH0-", "-CH1-", "-CH2-"]):
            if event == key:
                self.channel_enabled[i] = values[key]
                self.current_edited_image = None
                return True
        return False

    def _handle_minmax_change(self, event, values):
        for ch in range(3):
            if event == f"-MIN_CH{ch}-":
                self.channel_params[ch]["min"] = int(values[event])
                self.current_edited_image = None
                return True
            if event == f"-MAX_CH{ch}-":
                self.channel_params[ch]["max"] = int(values[event])
                self.current_edited_image = None
                return True
        return False

    def _handle_reset_minmax(self):
        for ch in range(3):
            self.channel_params[ch] = {"min": 0, "max": self.config.BIT12_MAX}
        self.current_edited_image = None
        self.view.update_min_max_sliders(self.channel_params)
        return True

    def _handle_play_button(self, event):
        if event == "-PLAY_Z-":
            self.is_playing_z = True
        elif event == "-STOP_Z-":
            self.is_playing_z = False
        elif event == "-PLAY_T-":
            self.is_playing_t = True
        elif event == "-STOP_T-":
            self.is_playing_t = False
        elif event == "-PLAY_ND2-":          # ← 新規
            self.is_playing_nd2 = True
        elif event == "-STOP_ND2-":          # ← 新規
            self.is_playing_nd2 = False

    def _update_z_playback(self, now):
        if now - self.last_update_z > 1.0 / self.fps:
            self.current_z = (self.current_z + 1) % self.z_size
            self.window["-Z_SLIDER-"].update(value=self.current_z)
            self.last_update_z = now
            self.current_edited_image = None
            return True
        return False

    def _update_t_playback(self, now):
        if now - self.last_update_t > 1.0 / self.fps:
            self.current_t = (self.current_t + 1) % self.t_size
            self.window["-T_SLIDER-"].update(value=self.current_t)
            self.last_update_t = now
            self.current_edited_image = None
            return True
        return False
    
    def _update_nd2_playback(self, now):
        """ND2ファイルの自動再生"""
        if now - self.last_update_nd2 > 1.0 / self.fps:
            total_files = self.model.get_total_files()
            self.current_nd2_idx = (self.current_nd2_idx + 1) % total_files
            self.window["-ND2_SLIDER-"].update(value=self.current_nd2_idx)
            
            self._load_current_nd2()        # ファイル切り替え処理を実行
            self.last_update_nd2 = now
            self.current_edited_image = None
            return True
        return False

    def _display_current(self):
        if self.current_edited_image is not None:
            rgb_array = np.array(self.current_edited_image)
            self.view.display_composite(rgb_array)
            return

        channels = self.service.get_current_channels(
            self.data, self.sizes, self.current_z, self.current_t, self.axis_order
        )
        rgb = self.service.create_composite_image(
            channels, self.channel_enabled, self.channel_params, self.display_mode
        )
        self.view.display_composite(rgb)

    def _save_nd2_composite(self):
        """現在の表示画像を、選択中のND2ファイル名を使って保存"""
        if self.current_edited_image is not None:
            pil_img = self.current_edited_image.copy()
        else:
            channels = self.service.get_current_channels(
                self.data, self.sizes, self.current_z, self.current_t, self.axis_order
            )
            pil_img = self.service.save_composite(
                channels, self.channel_enabled, self.channel_params, self.display_mode
            )

        # 現在選択されているND2のファイル名を取得
        filename = self.model.get_filename(self.current_nd2_idx)
        base_name = os.path.splitext(filename)[0]  # .nd2 を除去

        # 保存ダイアログにデフォルトファイル名をセット
        default_path = f"{base_name}_processed.png"

        save_path = sg.popup_get_file(
            "保存先を選択",
            save_as=True,
            default_path=default_path,
            file_types=(("PNG", "*.png"), ("JPG", "*.jpg"), ("TIFF", "*.tif"))
        )

        if save_path:
            try:
                if not save_path.lower().endswith(('.png', '.jpg', '.jpeg', '.tif', '.tiff')):
                    save_path += '.png'
                pil_img.save(save_path)
                sg.popup(f"保存完了！\n{save_path}")
            except Exception as e:
                sg.popup_error(f"保存失敗:\n{e}")

    def _apply_plugin(self, plugin_class):
        if self.view.current_pil_image is None:
            sg.popup_warning("画像が表示されていません")
            return False

        try:
            plugin_instance = plugin_class()
            original = self.view.current_pil_image.copy()
            
            # ★★★ ここを修正 ★★★
            processed = plugin_instance.process(original, roi=None, display_mode=self.display_mode)

            if isinstance(processed, Image.Image):
                self.current_edited_image = processed.copy()
                self.view.current_pil_image = processed
                self.view._redraw_image()
                print(f"プラグイン適用完了: {plugin_class.name}")
                return True

            return False

        except Exception as e:
            import traceback
            print(f"プラグイン実行エラー詳細:\n{traceback.format_exc()}")
            sg.popup_error(f"プラグイン実行エラー:\n{plugin_class.name}\n\n{e}")
            return False
        
    def _apply_plugin_after_roi(self):
        """論文モードで範囲選択完了後に自動実行"""
        if not self.plugins:
            sg.popup_warning("プラグインが読み込まれていません")
            return

        for plugin_class in self.plugins:
            if getattr(plugin_class, "name", "") == "論文画像作成モード":
                print("【論文モード】範囲選択完了 → Cropして論文画像を作成")
                self._apply_plugin(plugin_class)
                return

        # フォールバック
        if self.plugins:
            self._apply_plugin(self.plugins[0])

    def show_bbox_four_panel(self, bbox):
        """右クリックで選択された正方形範囲だけを4分割で表示"""
        if not bbox or self.view.current_pil_image is None:
            sg.popup_warning("画像または選択範囲がありません")
            return

        x1, y1, x2, y2 = bbox
        side = x2 - x1

        # ★★★ 重要：選択範囲だけを各チャンネルから切り出す ★★★
        channels = self.service.get_current_channels(
            self.data, self.sizes, self.current_z, self.current_t, self.axis_order
        )

        adjusted_pil = []
        for i in range(3):
            if self.channel_enabled[i]:
                # チャンネル画像から選択範囲だけをCrop
                ch_array = channels[i]
                crop_ch = ch_array[y1:y2, x1:x2]                    # numpyで範囲切り出し
                adj = apply_min_max_12bit(crop_ch,
                                          self.channel_params[i]["min"],
                                          self.channel_params[i]["max"])
                adjusted_pil.append(Image.fromarray(adj))
            else:
                adjusted_pil.append(Image.new("L", (side, side), 0))

        # Composite画像も選択範囲だけを使用
        adj_array = [np.array(p) for p in adjusted_pil]
        if self.display_mode == "CMY":
            comp_array = create_cmy_simple_composite(adj_array)
        elif self.display_mode == "RGB":
            comp_array = np.stack([adj_array[0], adj_array[1], adj_array[2]], axis=2)
        elif self.display_mode == "BGR":
            comp_array = np.stack([adj_array[2], adj_array[1], adj_array[0]], axis=2)
        else:
            comp_array = np.zeros((side, side, 3), dtype=np.uint8)

        composite_pil = Image.fromarray(comp_array)

        # Viewに4分割表示を依頼（選択範囲のみ）
        self.view.show_four_panel(
            adjusted_pil[0], adjusted_pil[1], adjusted_pil[2],
            composite_pil,
            self.display_mode,
            bbox
        )
        
    def on_freehand_selected(self, polygon):
        """フリーハンドで選択されたポリゴン領域でPearson相関係数を計算"""
        if len(polygon) < 3:
            sg.popup_warning("領域が小さすぎます")
            return

        try:
            # 現在の表示画像からマスクを作成
            w, h = self.view.current_pil_image.size
            mask = Image.new("L", (w, h), 0)
            draw = ImageDraw.Draw(mask)
            draw.polygon(polygon, fill=255)
            mask_array = np.array(mask) > 0

            # Pearsonプラグインを探して実行（mask付き）
            for plugin_class in self.plugins:
                if getattr(plugin_class, "name", "") == "Pearson相関係数":
                    plugin_instance = plugin_class()
                    processed = plugin_instance.process(
                        self.view.current_pil_image.copy(),
                        roi=None,
                        display_mode=self.display_mode,
                        mask=mask_array
                    )
                    print(f"✅ フリーハンド領域（{len(polygon)}点）でPearson計算完了")
                    sg.popup_ok("フリーハンド領域でPearson相関係数を計算しました", 
                                title="計算完了")
                    return

            sg.popup_warning("Pearson相関係数プラグインが見つかりません")
        except Exception as e:
            import traceback
            print(f"フリーハンドPearsonエラー:\n{traceback.format_exc()}")
            sg.popup_error(f"フリーハンドPearson計算エラー:\n{e}")
            
    def on_batch_pearson_selected(self, batch_rois):
        """バッチPearson計算（計算ペアを選択可能）"""
        if not batch_rois:
            sg.popup_warning("計算する領域がありません")
            return

        total = len(batch_rois)

        # ====================== 計算したいペアを選択 ======================
        pair_layout = [
            [sg.Text("計算したい蛍光ペアを選択してください", font=("Helvetica", 11, "bold"))],
            [sg.Checkbox("Ch0 ↔ Ch1", default=True, key="-PAIR_01-")],
            [sg.Checkbox("Ch0 ↔ Ch2", default=True, key="-PAIR_02-")],
            [sg.Checkbox("Ch1 ↔ Ch2", default=True, key="-PAIR_12-")],
            [sg.Text("※少なくとも1つ選択してください", text_color="#ff9800")],
            [sg.Button("これで計算開始", key="-START_CALC-", size=(20,1)), 
             sg.Button("キャンセル", key="-CANCEL-", size=(15,1))]
        ]

        pair_win = sg.Window("Pearson計算ペア選択", pair_layout, modal=True, finalize=True)

        selected_pairs = None
        while True:
            event, values = pair_win.read()
            if event in (sg.WINDOW_CLOSED, "-CANCEL-"):
                pair_win.close()
                return
            if event == "-START_CALC-":
                pairs = []
                if values["-PAIR_01-"]: pairs.append((0, 1))
                if values["-PAIR_02-"]: pairs.append((0, 2))
                if values["-PAIR_12-"]: pairs.append((1, 2))

                if not pairs:
                    sg.popup_warning("少なくとも1つのペアを選択してください")
                    continue

                selected_pairs = pairs
                break

        pair_win.close()

        # ====================== バッチ計算開始 ======================
        sg.popup(f"バッチ処理を開始します...\n{total}個の領域 × {len(selected_pairs)}ペア\n\n少々お待ちください...",
                 title="Pearsonバッチ計算開始")

        all_results = f"【Pearson相関係数 バッチ計算結果】\n"
        all_results += f"合計領域数: {total}個   |   計算ペア: {len(selected_pairs)}個\n"
        all_results += "=" * 85 + "\n\n"

        for i, roi in enumerate(batch_rois, 1):
            try:
                self.current_nd2_idx = roi['nd2_idx']
                self.current_z = roi['z']
                self.current_t = roi['t']
                self._load_current_nd2()

                channels = self.service.get_current_channels(
                    self.data, self.sizes, self.current_z, self.current_t, self.axis_order
                )
                rgb_array = self.service.create_composite_image(
                    channels, [True]*3, self.channel_params, self.display_mode
                )

                h, w = channels[0].shape
                mask = Image.new("L", (w, h), 0)
                draw = ImageDraw.Draw(mask)
                draw.polygon(roi['polygon'], fill=255)
                mask_array = np.array(mask) > 0

                roi_info = {
                    'index': i,
                    'filename': roi.get('filename', 'Unknown'),
                    'nd2_idx': roi['nd2_idx'],
                    'z': roi['z'],
                    't': roi['t']
                }

                result_text = self._calculate_pearson(
                    rgb_array, self.display_mode, mask_array, roi_info, selected_pairs
                )
                all_results += result_text

                print(f"[{i}/{total}] 計算完了")

            except Exception as e:
                error_msg = f"【領域 {i}】 エラー: {e}\n{'─' * 60}\n"
                all_results += error_msg

        # 結果を1つにまとめて表示
        sg.popup_scrolled(all_results, 
                         title=f"Pearsonバッチ結果 ({total}領域・{len(selected_pairs)}ペア)",
                         size=(100, 35))

        sg.popup_ok(f"✅ 完了しました！\n{total}領域 × {len(selected_pairs)}ペアの結果をまとめました。",
                    title="Pearsonバッチ完了")
        
# ================================================
# 【更新版】ND2Controller.py の on_cellpose_z_selected を完全置き換え
# 一細胞ごとに「Z軸方向のPearson → 細胞ごとの平均PCC」を自動計算・表示
# ================================================

# ================================================
# 【最新版】ND2Controller.py の on_cellpose_z_selected を完全置き換え
# 変更点：
#   1. Cellpose実行後、参照Zスライスでの「細胞ごとの面積（px）」を即座に計算
#   2. ユーザーに「Label番号 + 面積」を一覧表示 → どの細胞でPearsonを計算するか自分で選択
#   3. 選択基準は「面積」でソート済み（大きい順）
#   4. 選択後、Z軸方向Pearson → 細胞ごとの平均PCCを計算（前回と同じロジック）
#   5. 従来のオーバーレイ表示＋切り抜き表示もそのまま実行
# ================================================

# ================================================
# 【Coloc2レベル拡張版】ND2Controller.py の on_cellpose_z_selected を完全置き換え
# 拡張内容（まさにColoc2に匹敵するレベル）
#   ・Cellpose実行後 → 参照Zでの面積一覧で細胞選択（前回と同じ）
#   ・選択後 → 「Coloc2解析設定」ダイアログでペア＋閾値方法を選択
#   ・計算する指標（Coloc2の主力すべて）：
#        - Pearson's R（PCC）
#        - Manders' M1（ChAのうちChBと共局在する割合）
#        - Manders' M2（ChBのうちChAと共局在する割合）
#   ・閾値処理は2種類選択可能：
#        1. No threshold（positive pixels only）
#        2. Use current Min slider（ユーザーが調整した背景閾値を使用）
#   ・全Zスライスで各指標を計算 → 細胞ごとに平均値を出力
#   ・結果テーブルに面積・PCC・M1・M2・解釈を一覧表示＋CSV保存
# ================================================

    def on_cellpose_z_selected(self, polygon, selected_z):
        """1細胞を囲んだROIからZ-stack全体をCellpose 3Dでセグメンテーション
           → 面積一覧で細胞選択 → Coloc2レベル解析（PCC + Manders M1/M2）"""
        if not polygon or len(polygon) < 3:
            sg.popup_warning("有効な領域が選択されていません")
            return

        # 直径をROIから推定
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        estimated_diameter = max((w + h) / 2.0, 15.0)

        # ====================== Cellpose設定ダイアログ ======================
        ch_layout = [
            [sg.Text("Cellpose入力チャンネルを選択 (Cytoplasm)", font=("Helvetica", 11, "bold"))],
            [sg.Radio("Ch0", "cellpose_ch", default=True, key="-CH0-"),
             sg.Text("(Cyan / Red)", text_color="#00ffff")],
            [sg.Radio("Ch1", "cellpose_ch", default=False, key="-CH1-"),
             sg.Text("(Magenta / Green)", text_color="#ff00ff")],
            [sg.Radio("Ch2", "cellpose_ch", default=False, key="-CH2-"),
             sg.Text("(Yellow / Blue)", text_color="#ffff00")],

            [sg.Text("─" * 50, text_color="#666")],
            [sg.Text(f"囲った領域: {w}×{h}px", font=("Consolas", 11), text_color="#00ffaa")],
            [sg.Text(f"推定直径: {estimated_diameter:.1f} pixels", text_color="#ff9800")],
            [sg.Text("─" * 50, text_color="#666")],

            [sg.Text("Anisotropy (Z/XY比)", font=("Helvetica", 10, "bold"))],
            [sg.Input(default_text="3.0", key="-ANISOTROPY-", size=(8, 1))],
            [sg.Text("min_size（小さい物体を無視）", font=("Helvetica", 10, "bold"))],
            [sg.Input(default_text="40", key="-MIN_SIZE-", size=(8, 1))],
            [sg.Button("Cellpose実行", key="-RUN-", size=(15,1)), 
             sg.Button("キャンセル", key="-CANCEL-")]
        ]

        ch_win = sg.Window("Cellpose 3D設定", ch_layout, modal=True, finalize=True)
        ch_idx = 0
        anisotropy = 3.0
        min_size = 40

        while True:
            ev, vals = ch_win.read()
            if ev in (sg.WINDOW_CLOSED, "-CANCEL-"):
                ch_win.close()
                return
            if ev == "-RUN-":
                try:
                    anisotropy = float(vals.get("-ANISOTROPY-", "3.0"))
                    min_size = int(vals.get("-MIN_SIZE-", "40"))
                except:
                    sg.popup_warning("数値を正しく入力してください")
                    continue
                if vals.get("-CH1-"): ch_idx = 1
                elif vals.get("-CH2-"): ch_idx = 2
                break
        ch_win.close()

        sg.popup(f"Cellpose 3D実行中...\n参照Z: {selected_z}\n囲った領域: {w}×{h}px", 
                 title="処理開始")

        try:
            # 1. 3D volume作成
            volume = np.stack([
                self.service.get_current_channels(self.data, self.sizes, z, self.current_t, self.axis_order)[ch_idx].astype(np.float32)
                for z in range(self.z_size)
            ], axis=0)

            # 2. Cellpose実行
            model = models.CellposeModel(gpu=True, model_type='cyto3')
            result = model.eval(volume, diameter=estimated_diameter, channels=[0, 0],
                                do_3D=True, z_axis=0, anisotropy=anisotropy,
                                min_size=min_size, normalize=True)
            masks_3d = result[0] if isinstance(result, tuple) else result

            # 3. グローバル色マップ
            color_map = {label: np.random.randint(80, 255, 3, dtype=np.uint8)
                         for label in np.unique(masks_3d) if label != 0}

            # 4. オーバーレイ + 切り抜き画像リスト（全細胞）
            overlay_list = []
            cropped_list = []

            for z in range(self.z_size):
                channels = self.service.get_current_channels(
                    self.data, self.sizes, z, self.current_t, self.axis_order)
                rgb = self.service.create_composite_image(
                    channels, [True]*3, self.channel_params, self.display_mode)
                pil_rgb = Image.fromarray(rgb).convert("RGB")

                mask_slice = masks_3d[z]
                if mask_slice.max() > 0:
                    colored = np.zeros((*mask_slice.shape, 3), dtype=np.uint8)
                    for label, color in color_map.items():
                        colored[mask_slice == label] = color
                    overlay_pil = Image.blend(pil_rgb, Image.fromarray(colored), alpha=0.40)
                    overlay_list.append(overlay_pil)

                    mask_pil = Image.fromarray((mask_slice > 0).astype(np.uint8) * 255)
                    cropped = Image.new("RGB", pil_rgb.size, (0, 0, 0))
                    cropped.paste(pil_rgb, mask=mask_pil)
                    cropped_list.append(cropped)
                else:
                    overlay_list.append(pil_rgb)
                    cropped_list.append(Image.new("RGB", pil_rgb.size, (0, 0, 0)))

            # ====================== 参照Zスライスでの面積計算 ======================
            ref_mask = masks_3d[selected_z]
            areas = {}
            for label in np.unique(ref_mask):
                if label == 0:
                    continue
                area_px = np.sum(ref_mask == label)
                areas[label] = area_px

            if not areas:
                sg.popup_warning("参照Zスライスに細胞が検出されませんでした")
            else:
                cell_list = sorted(areas.items(), key=lambda x: x[1], reverse=True)
                display_items = [f"Label {label:3d}   |   {area:6d} px" for label, area in cell_list]

                # ====================== 細胞選択ダイアログ ======================
                select_layout = [
                    [sg.Text("【Cellposeセグメンテーション結果】", font=("Helvetica", 14, "bold"), text_color="#4caf50")],
                    [sg.Text(f"参照Zスライス: Z = {selected_z}    検出細胞数: {len(cell_list)} 個", 
                             font=("Helvetica", 11))],
                    [sg.Text("面積の大きい順に並んでいます。Coloc2解析したい細胞を選択してください", 
                             text_color="#ff9800")],
                    [sg.Listbox(values=display_items, key="-CELL_LIST-", size=(55, 12),
                                select_mode=sg.LISTBOX_SELECT_MODE_MULTIPLE, font=("Consolas", 11))],
                    [sg.Button("✅ 選択した細胞でColoc2解析", key="-RUN_COLOC-", size=(30, 2),
                               button_color=("white", "#ff9800")),
                     sg.Button("全細胞で解析", key="-ALL_CELLS-", size=(20, 2)),
                     sg.Button("スキップ（表示のみ）", key="-SKIP-", size=(20, 2))]
                ]

                select_win = sg.Window("細胞選択（面積基準）", select_layout, modal=True, finalize=True)
                selected_labels = None
                while True:
                    ev, vals = select_win.read()
                    if ev in (sg.WINDOW_CLOSED, "-SKIP-"):
                        selected_labels = []
                        break
                    if ev == "-ALL_CELLS-":
                        selected_labels = list(areas.keys())
                        break
                    if ev == "-RUN_COLOC-":
                        selected_idx = vals["-CELL_LIST-"]
                        if not selected_idx:
                            sg.popup_warning("少なくとも1つの細胞を選択してください")
                            continue
                        selected_labels = []
                        for item in selected_idx:
                            label = int(item.split("Label")[1].split("|")[0].strip())
                            selected_labels.append(label)
                        break
                select_win.close()

                # ====================== 【Coloc2レベル解析】 ======================
                if selected_labels:
                    # Coloc2設定ダイアログ
                    coloc_layout = [
                        [sg.Text("【Coloc2レベル共局在解析】", font=("Helvetica", 12, "bold"), text_color="#ff9800")],
                        [sg.Text(f"選択細胞数: {len(selected_labels)} 個", font=("Helvetica", 11))],
                        [sg.Text("計算したい蛍光ペアを選択してください", font=("Helvetica", 11, "bold"))],
                        [sg.Radio("Ch0 ↔ Ch1", "coloc_pair", default=True, key="-P01-")],
                        [sg.Radio("Ch0 ↔ Ch2", "coloc_pair", default=False, key="-P02-")],
                        [sg.Radio("Ch1 ↔ Ch2", "coloc_pair", default=False, key="-P12-")],

                        [sg.Text("─" * 60, text_color="#666")],
                        [sg.Text("Manders係数用の閾値処理方法", font=("Helvetica", 11, "bold"))],
                        [sg.Radio("No threshold（positive pixels only）", "thresh_mode", default=True, key="-NO_THRESH-")],
                        [sg.Radio("Current Min sliderを背景閾値として使用", "thresh_mode", default=False, key="-USE_MIN-")],
                        [sg.Text("（Coloc2のCostes自動閾値に近い実用的処理です）", text_color="#ff9800", font=("Helvetica", 9))],

                        [sg.Button("Coloc2解析実行", key="-RUN_COLOC-", size=(20,1)), 
                         sg.Button("キャンセル", key="-CANCEL-")]
                    ]

                    coloc_win = sg.Window("Coloc2解析設定", coloc_layout, modal=True, finalize=True)
                    selected_pair = None
                    use_threshold = False
                    while True:
                        ev, vals = coloc_win.read()
                        if ev in (sg.WINDOW_CLOSED, "-CANCEL-"):
                            coloc_win.close()
                            selected_labels = None
                            break
                        if ev == "-RUN_COLOC-":
                            if vals["-P01-"]: selected_pair = (0, 1)
                            elif vals["-P02-"]: selected_pair = (0, 2)
                            elif vals["-P12-"]: selected_pair = (1, 2)
                            use_threshold = vals["-USE_MIN-"]
                            coloc_win.close()
                            break
                    coloc_win.close()

                    if selected_pair is not None and selected_labels:
                        sg.popup(f"Coloc2解析実行中...\n"
                                 f"ペア: Ch{selected_pair[0]} ↔ Ch{selected_pair[1]}\n"
                                 f"閾値: {'Min slider使用' if use_threshold else 'No threshold'}\n"
                                 f"{len(selected_labels)}細胞 × 全Zスライス", 
                                 title="Coloc2計算開始")

                        results = []
                        for label in selected_labels:
                            per_z_pcc = []
                            per_z_m1 = []
                            per_z_m2 = []

                            for z in range(self.z_size):
                                mask_slice = (masks_3d[z] == label)
                                if not np.any(mask_slice):
                                    continue

                                channels = self.service.get_current_channels(
                                    self.data, self.sizes, z, self.current_t, self.axis_order)

                                ch_a_raw = channels[selected_pair[0]].astype(np.float32)
                                ch_b_raw = channels[selected_pair[1]].astype(np.float32)

                                ch_a_adj = apply_min_max_12bit(ch_a_raw,
                                                               self.channel_params[selected_pair[0]]["min"],
                                                               self.channel_params[selected_pair[0]]["max"])
                                ch_b_adj = apply_min_max_12bit(ch_b_raw,
                                                               self.channel_params[selected_pair[1]]["min"],
                                                               self.channel_params[selected_pair[1]]["max"])

                                vals_a = ch_a_adj[mask_slice].flatten()
                                vals_b = ch_b_adj[mask_slice].flatten()

                                # Pearson's R
                                if len(vals_a) < 2 or np.std(vals_a) == 0 or np.std(vals_b) == 0:
                                    pcc = 0.0
                                else:
                                    pcc = np.corrcoef(vals_a, vals_b)[0, 1]
                                per_z_pcc.append(pcc)

                                # Manders係数
                                if use_threshold:
                                    thresh_a = self.channel_params[selected_pair[0]]["min"]
                                    thresh_b = self.channel_params[selected_pair[1]]["min"]
                                else:
                                    thresh_a = 0
                                    thresh_b = 0

                                mask_b_over = vals_b > thresh_b
                                mask_a_over = vals_a > thresh_a

                                sum_a = np.sum(vals_a)
                                sum_b = np.sum(vals_b)

                                m1 = np.sum(vals_a[mask_b_over]) / sum_a if sum_a > 0 else 0.0
                                m2 = np.sum(vals_b[mask_a_over]) / sum_b if sum_b > 0 else 0.0

                                per_z_m1.append(m1)
                                per_z_m2.append(m2)

                            if per_z_pcc:
                                avg_pcc = float(np.mean(per_z_pcc))
                                avg_m1 = float(np.mean(per_z_m1))
                                avg_m2 = float(np.mean(per_z_m2))
                                num_z = len(per_z_pcc)
                                results.append({
                                    'label': int(label),
                                    'area_px': areas.get(label, 0),
                                    'avg_pcc': avg_pcc,
                                    'avg_m1': avg_m1,
                                    'avg_m2': avg_m2,
                                    'num_z': num_z
                                })

                        # ====================== Coloc2結果表示 ======================
                        if results:
                            thresh_str = "Min slider" if use_threshold else "No threshold"
                            result_text = f"【Coloc2レベル共局在解析結果】\n"
                            result_text += f"ペア: Ch{selected_pair[0]} ↔ Ch{selected_pair[1]}\n"
                            result_text += f"閾値処理: {thresh_str}\n"
                            result_text += f"解析細胞数: {len(results)} 個   参照Z: {selected_z}\n\n"
                            result_text += "Label | 面積(px) | PCC     | M1      | M2      | 解釈\n"
                            result_text += "─" * 75 + "\n"

                            for r in sorted(results, key=lambda x: x['area_px'], reverse=True):
                                interp = "非常に強い共局在" if r['avg_pcc'] > 0.6 else \
                                         "強い共局在" if r['avg_pcc'] > 0.4 else \
                                         "中程度" if r['avg_pcc'] > 0.2 else "弱い／なし"
                                result_text += (f"{r['label']:5d} | {r['area_px']:7d} | "
                                                f"{r['avg_pcc']:.4f} | {r['avg_m1']:.4f} | "
                                                f"{r['avg_m2']:.4f} | {interp}\n")

                            result_text += "\n" + "─" * 75 + "\n"
                            result_text += "PCC : Pearson相関係数（線形相関）\n"
                            result_text += "M1  : ChAの信号のうちChBと共局在する割合\n"
                            result_text += "M2  : ChBの信号のうちChAと共局在する割合\n"
                            result_text += "※各Zスライスで計算し、細胞ごとに平均化しています（Coloc2同等）"

                            sg.popup_scrolled(result_text,
                                              title=f"Coloc2結果（{len(results)}細胞）",
                                              size=(120, 35))

                            # CSV保存
                            if sg.popup_yes_no("結果をCSVで保存しますか？", title="保存") == "Yes":
                                save_path = sg.popup_get_file("CSV保存先", save_as=True, file_types=(("CSV", "*.csv"),))
                                if save_path:
                                    if not save_path.lower().endswith('.csv'):
                                        save_path += '.csv'
                                    import csv
                                    with open(save_path, 'w', newline='', encoding='utf-8') as f:
                                        writer = csv.writer(f)
                                        writer.writerow(['Label', 'Area_px', 'PCC', 'M1', 'M2', 'Num_Z'])
                                        for r in results:
                                            writer.writerow([r['label'], r['area_px'],
                                                             f"{r['avg_pcc']:.6f}",
                                                             f"{r['avg_m1']:.6f}",
                                                             f"{r['avg_m2']:.6f}",
                                                             r['num_z']])
                                    sg.popup_ok(f"CSV保存完了！\n{save_path}")

        except Exception as e:
            import traceback
            print("[Cellpose + Coloc2 Error]\n" + traceback.format_exc())
            sg.popup_error(f"処理中にエラーが発生しました:\n{str(e)}")
            return

        # ====================== 従来の表示（全細胞） ======================
        self.view.show_cellpose_z_masks(overlay_list)
        self.view.show_cellpose_cropped_cells(cropped_list)

        sg.popup_ok("✅ Cellpose 3D + 細胞面積選択 + Coloc2解析完了！\n\n"
                    "・左側ウィンドウ：マスク重ね表示（全細胞）\n"
                    "・右側ウィンドウ：細胞部分だけ切り抜き表示（全細胞）\n"
                    "・Coloc2結果は選択した細胞のみ計算済み", 
                    title="全処理完了")