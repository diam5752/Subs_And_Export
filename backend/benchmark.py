import json
import subprocess
import time
from pathlib import Path

from backend.app.core import config
from backend.app.services import subtitles


def generate_sample_audio(path: Path):
    """Generate a sample audio file using macOS 'say' command."""
    text = " ".join(["This is a benchmark test sentence number {}.".format(i) for i in range(20)])
    # macOS 'say' can output to aiff, then we convert to wav
    aiff_path = path.with_suffix(".aiff")
    print(f"Generating sample audio at {aiff_path}...")
    subprocess.run(["say", "-o", str(aiff_path), text], check=True)

    # Convert to standard wav for ML tools
    print(f"Converting to {path}...")
    subprocess.run(["ffmpeg", "-y", "-i", str(aiff_path), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(path)], check=True, capture_output=True)

    # Clean up aiff
    aiff_path.unlink()

def benchmark_model(name: str, provider: str, model_size: str, audio_path: Path):
    print(f"Benchmarking {name} ({provider}/{model_size})...")
    start = time.perf_counter()
    try:
        subtitles.generate_subtitles_from_audio(
            audio_path,
            model_size=model_size,
            provider=provider,
            language="en"
        )
        duration = time.perf_counter() - start
        print(f"  -> {duration:.2f}s")
        return duration
    except Exception as e:
        print(f"  -> Failed: {e}")
        return None

def main():
    sample_path = Path("benchmark_sample.wav")
    try:
        generate_sample_audio(sample_path)

        # Audio length (approximate)
        # 20 sentences * ~2.5s = ~50s? say is fast.
        # let's measure file duration
        duration_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(sample_path)]
        audio_duration = float(subprocess.check_output(duration_cmd).strip())
        print(f"Audio Duration: {audio_duration:.2f}s")

        results = {}

        # 1. Standard (whisper.cpp) - assumes 'base' or config default. UI uses 'turbo' mode but that maps to model.
        # ProcessView uses: provider='whispercpp', mode='turbo' (which is just a UI flag, backend uses config.WHISPERCPP_MODEL)
        # config.WHISPERCPP_MODEL usually defaults to 'base' or 'small' if not set.
        # I'll rely on the default config import.
        t_std = benchmark_model("Standard", "whispercpp", config.WHISPERCPP_MODEL, sample_path)
        if t_std:
            results["standard"] = {"time": t_std, "speed_factor": audio_duration / t_std}

        # 2. Enhanced (Local Turbo)
        t_enh = benchmark_model("Enhanced", "local", config.WHISPER_MODEL, sample_path)
        if t_enh:
             results["enhanced"] = {"time": t_enh, "speed_factor": audio_duration / t_enh}

        # 3. Ultimate (Groq)
        # Note: Needs API Key. If missing, it will fail gracefully.
        t_ult = benchmark_model("Ultimate", "groq", config.GROQ_TRANSCRIBE_MODEL, sample_path)
        if t_ult:
             results["ultimate"] = {"time": t_ult, "speed_factor": audio_duration / t_ult}

        print("\nBenchmark Results:")
        print(json.dumps(results, indent=2))

        # Cleanup
        sample_path.unlink()

    except Exception as e:
        print(f"Benchmark failed: {e}")
        if sample_path.exists():
            sample_path.unlink()

if __name__ == "__main__":
    main()
