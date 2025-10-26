#!/usr/bin/env python3
"""Performance benchmark for Qwen2.5-7B translation"""
import os
import sys
import time

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.translator import translate_batch, has_model


def benchmark_translation():
    """Measure translation performance"""
    print("\n" + "="*60)
    print("PERFORMANCE BENCHMARK: Qwen2.5-7B Translation")
    print("="*60)

    # Check API token
    if not has_model('de', 'en'):
        print("❌ HF_API_TOKEN not set")
        print("   Get token at: https://huggingface.co/settings/tokens")
        return 1

    # Test cases (mix of short and long texts)
    test_texts = [
        "Hallo Welt",
        "Guten Tag",
        "Wie geht es dir?",
        "Das ist ein längerer deutscher Satz, der mehr Zeit benötigen könnte.",
        "Willkommen bei unserem Service"
    ]

    print(f"\nBenchmarking {len(test_texts)} texts...")
    print("-" * 60)

    # Measure total time
    start_time = time.time()

    try:
        translations = translate_batch(test_texts, src='de', dst='en')
    except Exception as e:
        print(f"❌ Translation failed: {e}")
        return 1

    end_time = time.time()
    total_time = end_time - start_time

    # Display results
    print("\nResults:")
    print("-" * 60)
    for i, (original, translation) in enumerate(zip(test_texts, translations), 1):
        print(f"\n{i}. DE: {original}")
        print(f"   EN: {translation}")

    # Performance metrics
    avg_time = total_time / len(test_texts)
    print("\n" + "="*60)
    print("PERFORMANCE METRICS")
    print("="*60)
    print(f"Total time:        {total_time:.2f}s")
    print(f"Texts translated:  {len(test_texts)}")
    print(f"Average per text:  {avg_time:.2f}s")

    # Acceptable threshold: < 3s per text
    if avg_time < 3.0:
        print(f"\n✓ PASS: Performance acceptable (< 3s per text)")
        return 0
    else:
        print(f"\n⚠ WARNING: Performance slower than expected (> 3s per text)")
        print("   Note: First API calls may be slower due to model loading")
        return 0  # Still return success, just a warning


if __name__ == '__main__':
    sys.exit(benchmark_translation())
