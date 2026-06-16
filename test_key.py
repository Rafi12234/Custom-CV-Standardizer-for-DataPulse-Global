# test_key.py
from dotenv import load_dotenv
import os
import time
load_dotenv()

from google import genai

key = os.getenv("GEMINI_API_KEY", "")
if not key:
    print("ERROR: GEMINI_API_KEY is empty in .env file")
    exit(1)

print(f"Key loaded: {key[:8]}...{key[-4:]}")
print()

client = genai.Client(api_key=key)

MAX_ATTEMPTS = 5
WAIT         = 15

for attempt in range(1, MAX_ATTEMPTS + 1):
    print(f"Attempt {attempt}/{MAX_ATTEMPTS} — calling Gemini...")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say hello in one word.",
        )
        print(f"Response : {response.text.strip()}")
        print("SUCCESS: API key is working correctly!")
        break

    except Exception as exc:
        err = str(exc).lower()
        print(f"Error    : {exc}")

        retryable = any(k in err for k in [
            "429", "500", "503", "504",
            "quota", "rate", "unavailable",
            "high demand", "try again",
            "timeout", "internal",
        ])

        if retryable and attempt < MAX_ATTEMPTS:
            print(f"Temporary error. Waiting {WAIT}s before retry...\n")
            time.sleep(WAIT)
            WAIT = min(WAIT * 2, 120)
        else:
            print("Non-retryable error or max attempts reached.")
            break