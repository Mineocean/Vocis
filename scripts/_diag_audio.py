import sys

import sounddevice as sd

all_devs = sd.query_devices()
hostapis = sd.query_hostapis()

# 找 WASAPI hostapi 的索引
wasapi_idx = None
for i, api in enumerate(hostapis):
    if "wasapi" in api["name"].lower():
        wasapi_idx = i
        break

if wasapi_idx is None:
    print("ERROR: no WASAPI hostapi found")
    sys.exit(1)

print(f"WASAPI hostapi index: {wasapi_idx}")
print()

# 列出 WASAPI 下的所有输入设备
print("=== WASAPI INPUT DEVICES ===")
for i, d in enumerate(all_devs):
    if d["hostapi"] == wasapi_idx and d["max_input_channels"] > 0:
        print(f"  [{i:2d}] {d['name']}")
        print(f"        channels: {d['max_input_channels']} in / {d['max_output_channels']} out")
        print(f"        default_sr: {d['default_samplerate']}")
        print()

# 尝试打开每个 WASAPI 输入设备 @ 48000Hz
print("=== TESTING WASAPI INPUTS ===")
for i, d in enumerate(all_devs):
    if d["hostapi"] == wasapi_idx and d["max_input_channels"] > 0:
        sr = int(d["default_samplerate"])
        try:
            s = sd.InputStream(device=i, channels=1, samplerate=sr, dtype="float32", blocksize=0)
            s.start()
            print(f"  [{i:2d}] OK @ {sr}Hz - {d['name'][:40]}")
            s.stop()
            s.close()
        except Exception as e:
            print(f"  [{i:2d}] FAIL @ {sr}Hz - {str(e)[:80]}")
