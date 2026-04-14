# main.py
import TkEasyGUI as sg
import os
import glob
from config.default import *
from controller.nd2_controller import ND2Controller


class Config:
    pass


def main_loader():
    layout = [
        [sg.Button("ND2ファイルを選択", key="-SELECT_FILE-", size=(28, 1), button_color=("white", "#4caf50"))],
        [sg.Button("ND2を含むフォルダを選択", key="-SELECT_FOLDER-", size=(28, 1), button_color=("white", "#2196f3"))],
    ]

    window = sg.Window(MAIN_WINDOW_TITLE, layout, size=MAIN_WINDOW_SIZE,
                       finalize=True, element_justification="center", resizable=False)

    while True:
        event, _ = window.read()
        if event in (sg.WINDOW_CLOSED, "-EXIT-"):
            break

        nd2_files = []

        if event == "-SELECT_FILE-":
            file_path = sg.popup_get_file("ND2ファイルを選択", file_types=(("ND2ファイル", "*.nd2"),))
            if file_path and os.path.isfile(file_path):
                nd2_files = [file_path]

        elif event == "-SELECT_FOLDER-":
            folder_path = sg.popup_get_folder("ND2ファイルを含むフォルダを選択")
            if folder_path and os.path.isdir(folder_path):
                pattern = os.path.join(folder_path, "**", "*.nd2")
                nd2_files = sorted(glob.glob(pattern, recursive=True))
                if nd2_files:
                    sg.popup(f"{len(nd2_files)}個のND2ファイルを検出しました")
                else:
                    sg.popup_error("ND2ファイルが見つかりませんでした")

        if nd2_files:
            # ====================== ここが重要 ======================
            # ND2ファイル/フォルダーが選択されたら、最初の選択画面を即座に完全に閉じる
            window.close()

            # Config作成（あなたの元の処理をそのまま保持）
            cfg = Config()
            for key, value in globals().items():
                if key.isupper() and not key.startswith("__"):
                    setattr(cfg, key, value)

            # ND2ビューアーを起動
            controller = ND2Controller(nd2_files, cfg)
            controller.run()

            # ビューアーが閉じられたらプログラム全体を終了（選択画面には戻らない）
            print("ND2ビューアーが閉じられました。プログラムを終了します。")
            break   # ← これでループを抜けて二度と選択画面を表示しない

    # 念のためウィンドウを閉じる（すでに閉じている場合は無害）
    if window:
        window.close()


if __name__ == "__main__":
    print("ND2エディタ起動中...（MVC完全分離版 + 正方形BBox 4分割機能 + 論文プラグイン）")
    main_loader()