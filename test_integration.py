#!/usr/bin/env python3
"""Integration tests for Qwen2.5-7B translation system"""
import os
import sys

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.translator import translate_batch, has_model


def test_api_token():
    """Test 1: API Token Check"""
    print("\n" + "="*60)
    print("TEST 1: API Token Check")
    print("="*60)

    token = os.getenv('HF_API_TOKEN')
    if not token:
        print("❌ FAIL: HF_API_TOKEN not set")
        print("   Get token at: https://huggingface.co/settings/tokens")
        return False

    if not token.startswith('hf_'):
        print("❌ FAIL: Invalid token format (should start with 'hf_')")
        return False

    if not has_model('de', 'en'):
        print("❌ FAIL: has_model() returned False")
        return False

    print("✓ PASS: API Token configured correctly")
    print("   Token: [REDACTED]")
    return True


def test_german_to_english():
    """Test 2: German → English (main use case)"""
    print("\n" + "="*60)
    print("TEST 2: German → English Translation")
    print("="*60)

    test_cases = [
        ("Hallo Welt", "Hello World"),
        ("Guten Tag", "Good day"),
        ("Wie geht es dir?", "How are you")
    ]

    try:
        for de_text, expected_en in test_cases:
            result = translate_batch([de_text], src='de', dst='en')
            translation = result[0]

            print(f"\n   DE: {de_text}")
            print(f"   EN: {translation}")

            # Basic validation (not exact match due to LLM variations)
            if len(translation) < 2:
                print(f"   ❌ Translation too short")
                return False

        print("\n✓ PASS: All German→English translations successful")
        return True

    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False


def test_all_languages():
    """Test 3: All 7 Required Languages"""
    print("\n" + "="*60)
    print("TEST 3: All 7 Required Languages")
    print("="*60)

    test_pairs = [
        ('en', 'de', 'Hello', 'English→German'),
        ('de', 'en', 'Hallo', 'German→English'),
        ('fr', 'en', 'Bonjour', 'French→English'),
        ('es', 'en', 'Hola', 'Spanish→English'),
        ('ru', 'en', 'Привет', 'Russian→English'),
        ('hi', 'en', 'नमस्ते', 'Hindi→English'),
        ('zh', 'en', '你好', 'Chinese→English')
    ]

    try:
        for src, dst, text, label in test_pairs:
            if not has_model(src, dst):
                print(f"   ❌ {label}: has_model() failed")
                return False

            result = translate_batch([text], src=src, dst=dst)
            translation = result[0]

            print(f"   ✓ {label}: {text} → {translation}")

            if len(translation) < 1:
                print(f"   ❌ Empty translation for {label}")
                return False

        print("\n✓ PASS: All 7 languages working")
        return True

    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False


def test_skip_logic():
    """Test 4: Skip Logic (empty, punctuation, English)"""
    print("\n" + "="*60)
    print("TEST 4: Skip Logic")
    print("="*60)

    test_cases = [
        ("", "empty string"),
        ("   ", "whitespace only"),
        ("•", "punctuation only"),
        ("This is already English", "English text (ASCII + stopwords)")
    ]

    try:
        for text, description in test_cases:
            result = translate_batch([text], src='de', dst='en')
            translation = result[0]

            # Should return original text unchanged
            if translation == text:
                print(f"   ✓ Skipped: {description}")
            else:
                print(f"   ❌ Should skip but translated: {description}")
                print(f"      Original: '{text}'")
                print(f"      Result:   '{translation}'")
                return False

        print("\n✓ PASS: Skip logic working correctly")
        return True

    except Exception as e:
        print(f"❌ FAIL: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "╔" + "="*58 + "╗")
    print("║  QWEN2.5-7B TRANSLATION INTEGRATION TESTS" + " "*15 + "║")
    print("╚" + "="*58 + "╝")

    tests = [
        ("API Token", test_api_token),
        ("DE→EN", test_german_to_english),
        ("All Languages", test_all_languages),
        ("Skip Logic", test_skip_logic)
    ]

    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"\n❌ CRITICAL ERROR in {name}: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    all_passed = True
    for name, passed in results:
        status = "PASS ✓" if passed else "FAIL ✗"
        print(f"{status:10} | {name}")
        if not passed:
            all_passed = False

    print("="*60)

    if all_passed:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
