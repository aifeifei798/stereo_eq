# stereo_eq.py (兼容性强化版)
import numpy as np
import soundfile as sf
from scipy.signal import lfilter

# --- 核心：参数化立体声EQ滤波器 (重写以提高兼容性) ---
# 这个版本手动计算biquad滤波器系数，不依赖特定版本的iirfilter
class StereoParametricEQ:
    def __init__(self, center_freq, q, gain_db, sample_rate):
        """
        初始化一个EQ节点。
        """
        self.sample_rate = sample_rate
        
        # --- 这是重写的核心部分 ---
        # 基于 "Audio EQ Cookbook" 的经典公式手动计算滤波器系数
        A = 10**(gain_db / 40.0)
        w0 = 2 * np.pi * center_freq / self.sample_rate
        alpha = np.sin(w0) / (2.0 * q)
        
        # Peaking EQ 的系数公式
        b0 = 1 + alpha * A
        b1 = -2 * np.cos(w0)
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * np.cos(w0)
        a2 = 1 - alpha / A
        
        # 归一化 (让 a0 = 1)
        self.b = np.array([b0 / a0, b1 / a0, b2 / a0])
        self.a = np.array([a0 / a0, a1 / a0, a2 / a0])

    def apply(self, audio_data):
        """
        将滤波器应用到音频数据上。
        """
        return lfilter(self.b, self.a, audio_data)

# --- 主函数：应用多段立体声EQ (与之前版本相同) ---
def apply_stereo_eq(input_path, output_path, eq_settings):
    print(f"正在读取文件: {input_path}")
    audio_data, sr = sf.read(input_path, always_2d=True)

    left_channel = audio_data[:, 0]
    right_channel = audio_data[:, 1]
    
    print("开始应用EQ效果...")
    for i, band in enumerate(eq_settings):
        freq = band['freq']
        q = band['q']
        gain_l_db = band['gain_l_db']
        gain_r_db = band['gain_r_db']
        
        print(f"  频段 {i+1}/{len(eq_settings)}: {freq} Hz")
        print(f"    左声道增益: {gain_l_db} dB | 右声道增益: {gain_r_db} dB")
        
        if gain_l_db != 0:
            eq_left = StereoParametricEQ(freq, q, gain_l_db, sr)
            left_channel = eq_left.apply(left_channel)
            
        if gain_r_db != 0:
            eq_right = StereoParametricEQ(freq, q, gain_r_db, sr)
            right_channel = eq_right.apply(right_channel)

    processed_audio = np.stack([left_channel, right_channel], axis=1)

    max_val = np.max(np.abs(processed_audio))
    if max_val > 1.0:
        processed_audio /= max_val
        print("\n警告: 音频增益过高，已进行自动压限以防止失真。")

    print(f"\n处理完成！正在保存到: {output_path}")
    sf.write(output_path, processed_audio, sr)
    print("搞定！去听听效果吧！")

# --- 如何使用它：一个示例 ---
if __name__ == "__main__":
    input_file = 'your_song.wav'
    output_file = 'your_song_STADIUM_VOCAL_FIX.wav'

    # 2. **“杭州奥体中心” V2修正版 - “人声追光”EQ**
    #    目标：在保持宏大空间感的同时，让人声更清晰。
    my_eq_settings = [
        # --- 保持宏大的“广场感”背景 ---
        # 我们依然需要削减高频来模拟距离
        { 'freq': 5000, 'q': 0.7, 'gain_l_db': -5.0, 'gain_r_db': -5.0 }, # 削减力度比之前轻一点
        { 'freq': 10000, 'q': 1.0, 'gain_l_db': -7.0, 'gain_r_db': -7.0 },
        
        # --- 保持“空洞”的混响感 ---
        { 'freq': 300, 'q': 1.2, 'gain_l_db': 2.0, 'gain_r_db': 2.0 },
        # { 'freq': 1000, 'q': 1.5, 'gain_l_db': -2.0, 'gain_r_db': -2.0 }, # 暂时拿掉这个，避免过度削弱人声

        # --- 保持“散漫”的低音 ---
        { 'freq': 70, 'q': 1.4, 'gain_l_db': -3.0, 'gain_r_db': -3.0 },
        
        # --- 关键修正：为人声打开一扇“窗户” ---
        # 3000Hz (3kHz) 是人声清晰度的核心频段。
        # 我们用一个很窄的Q值(2.5)，像手术刀一样把它精准地提起来。
        { 'freq': 3000, 'q': 2.5, 'gain_l_db': 3.0, 'gain_r_db': 3.0 }, # <--- 就是这句！
    ]

    try:
        apply_stereo_eq(input_file, output_file, my_eq_settings)
    except FileNotFoundError:
        print(f"\n错误！找不到输入文件 '{input_file}'")
    except Exception as e:
        print(f"\n发生了一个意料之外的错误: {e}")