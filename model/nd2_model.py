# model/nd2_model.py
import nd2
import os


class ND2Model:
    def __init__(self, nd2_files):
        self.nd2_files = nd2_files
        self.data_list = []
        self.sizes_list = []

        for path in nd2_files:
            try:
                data = nd2.imread(path)
                with nd2.ND2File(path) as f:
                    sizes = f.sizes
                self.data_list.append(data)
                self.sizes_list.append(sizes)
            except Exception as e:
                print(f"読み込み失敗: {os.path.basename(path)} - {e}")

    def get_data(self, idx):
        if 0 <= idx < len(self.data_list):
            return self.data_list[idx], self.sizes_list[idx]
        return None, None

    def get_total_files(self):
        return len(self.nd2_files)

    def get_filename(self, idx):
        if 0 <= idx < len(self.nd2_files):
            return os.path.basename(self.nd2_files[idx])
        return ""