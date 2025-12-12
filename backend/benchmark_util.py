import json
from pathlib import Path


def analyze_logs():
    # Path to logs (relative to backend dir where we run this)
    log_path = Path("../logs/pipeline_metrics.jsonl").resolve()

    if not log_path.exists():
        print(f"Log file not found at: {log_path}")
        return

    print(f"Reading logs from: {log_path}")
    print("-" * 80)
    print(f"{'TIMESTAMP':<25} | {'MODEL':<10} | {'BEAM':<4} | {'DUR':<6} | {'COMPUTE':<12} | {'TRANSCRIBE':<10} | {'TOTAL':<10}")
    print("-" * 100)

    entries = []
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    entries.append(data)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    # Show last 5 successful runs
    valid_entries = [e for e in entries if e.get('status') == 'success' or e.get('timings')]

    for entry in valid_entries[-5:]:
        ts = entry.get('ts', 'N/A')[:19]
        model = entry.get('model_size', 'N/A')
        beam = entry.get('beam_size', 'N/A')
        duration = entry.get('duration_s', 0)
        compute = entry.get('compute_type', 'N/A')

        timings = entry.get('timings', {})
        transcribe_s = timings.get('transcribe_s', 0)
        total_s = timings.get('total_s', 0)

        # Shorten model name if needed
        if "large-v3" in str(model):
            model = "large-v3"

        print(f"{ts:<25} | {str(model):<10} | {str(beam):<4} | {duration:<6.1f} | {str(compute):<12} | {transcribe_s:>9.2f}s | {total_s:>9.2f}s")

if __name__ == "__main__":
    analyze_logs()
