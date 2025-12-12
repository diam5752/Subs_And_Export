import os

import stable_whisper


# Minimal reproduction of the transcription call
def debug():
    # 1. Use real file
    files = [f for f in os.listdir("data/uploads") if f.endswith(".mp4")]
    if not files:
        print("No files found in data/uploads")
        return

    video_path = "data/uploads/710b2cfd-3774-4f70-80d2-4937366acf88_input.mp4"
    audio_path = "temp_debug.wav"

    print(f"Extracting 10s audio using ffmpeg from {video_path}...")
    os.system(f"ffmpeg -i {video_path} -t 10 -vn -acodec pcm_s16le -ar 16000 -ac 1 {audio_path} -y -hide_banner -loglevel error")

    print("Loading model...")
    # Using tiny for speed
    model = stable_whisper.load_faster_whisper("tiny", device="cpu", compute_type="int8")

    print("Transcribing...")
    transcribe_kwargs = {
        "language": "en",
        "word_timestamps": True,
        "vad": True,
        "regroup": True,
        "suppress_silence": True,
        "suppress_word_ts": False,
        "vad_threshold": 0.35,
    }

    result = model.transcribe(audio_path, **transcribe_kwargs)

    print(f"Segments found: {len(result.segments)}")
    if result.segments:
        seg = result.segments[0]
        print(f"First Segment: text='{seg.text}'")
        print(f"Has words? {bool(seg.words)}")
        if seg.words:
             print(f"First Word Type: {type(seg.words[0])}")
             print(f"Word content: {seg.words[0]}")
    else:
        print("No segments (expected for silence, let's try a file with speech if possible, but structure check is hard without speech)")

if __name__ == "__main__":
    debug()
