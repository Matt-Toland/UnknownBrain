#!/usr/bin/env python3
"""
Script to process all transcript files through the API endpoint
"""
import requests
import json
import time
from typing import List

# API configuration
API_BASE_URL = "https://unknown-brain-728000457978.us-central1.run.app"
BUCKET = "unknown-brain-transcripts"

# List of all transcript files (excluding .gitkeep)
TRANSCRIPT_FILES = [
    "transcripts/Matt_Matt_x_Unknown_Brain_Test_Meet_-_2025-09-16T15_45_00_01_00.txt",
    "transcripts/Matt__-_2025-09-18T13_07_07.566Z.txt",
    "transcripts/Ollie_Alex_Lubar_call___-_2025-08-26T14_00_00_01_00.txt",
    "transcripts/Ollie_Instrument_x_Unknown_Connect_-_2025-06-30T15_00_00_01_00.txt",
    "transcripts/Ollie_Ollie_x_John_-_2025-09-22T14_00_00_01_00.txt",
    "transcripts/Ollie_Ollie_x_Zulum_-_2025-08-26T12_15_00_01_00.txt",
    "transcripts/Ollie_Scott_Laura_x_Carrie___Ollie_-_2025-03-28T13_00_00Z.txt",
    "transcripts/Ollie_Scott_Ollie__Unknown__x_James__CO___-_Intro_chat_-_2025-04-08T10_30_00_01_00.txt",
    "transcripts/Ollie_Scott_Ollie_x_Eric_-_2025-06-27T12_30_00_01_00.txt",
    "transcripts/_Erik_Lehmann_-_Spekk_Vibe_Interview_-_2025-06-11T16_30_00_01_00.txt",
    "transcripts/_Matt__Granola_brain_project_planning_with_Access_Transform_Ventures_team_-_2025-09-18T13_07_07.txt",
    "transcripts/_Matt__Matt_x_Unknown_Brain_Test_Meet_-_2025-09-16T15_45_00_01_00.txt",
    "transcripts/_Molly_-_Atoms_Space_X_Unknown__-_2025-09-23T11_00_00_01_00.txt",
    "transcripts/_Recruiting_-_2025-07-24T17_00_00_01_00.txt",
    "transcripts/_Tom_Philipson_-_VC_-_2025-09-26T15_30_00_01_00.txt",
    "transcripts/_Unkown_-_2025-07-28T12_30_00_01_00.txt",
    "transcripts/_We_are_unknown_-_2025-07-29T14_00_00_01_00.txt"
]

def process_transcript(bucket: str, file_path: str, model: str = "gpt-5-mini") -> dict:
    """Process a single transcript through the API"""
    url = f"{API_BASE_URL}/process-transcript"

    payload = {
        "bucket": bucket,
        "file_path": file_path,
        "model": model
    }

    headers = {
        "Content-Type": "application/json"
    }

    try:
        print(f"Processing: {file_path}")
        response = requests.post(url, json=payload, headers=headers, timeout=300)

        if response.status_code == 200:
            print(f"✅ Successfully processed: {file_path}")
            return {"status": "success", "file": file_path, "response": response.json()}
        else:
            print(f"❌ Failed to process: {file_path} (Status: {response.status_code})")
            print(f"Response: {response.text}")
            return {"status": "failed", "file": file_path, "error": response.text}

    except requests.exceptions.Timeout:
        print(f"⏰ Timeout processing: {file_path}")
        return {"status": "timeout", "file": file_path}
    except Exception as e:
        print(f"💥 Error processing: {file_path} - {str(e)}")
        return {"status": "error", "file": file_path, "error": str(e)}

def main():
    """Process all transcript files"""
    print(f"Starting to process {len(TRANSCRIPT_FILES)} transcript files...")
    print(f"API Endpoint: {API_BASE_URL}/process-transcript")
    print(f"Bucket: {BUCKET}")
    print("-" * 60)

    results = []
    successful = 0
    failed = 0

    for i, file_path in enumerate(TRANSCRIPT_FILES, 1):
        print(f"\n[{i}/{len(TRANSCRIPT_FILES)}] Processing: {file_path}")

        result = process_transcript(BUCKET, file_path)
        results.append(result)

        if result["status"] == "success":
            successful += 1
        else:
            failed += 1

        # Add a small delay between requests to be respectful
        if i < len(TRANSCRIPT_FILES):
            print("Waiting 2 seconds before next request...")
            time.sleep(2)

    # Summary
    print("\n" + "=" * 60)
    print("PROCESSING SUMMARY")
    print("=" * 60)
    print(f"Total files: {len(TRANSCRIPT_FILES)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")

    if failed > 0:
        print("\nFailed files:")
        for result in results:
            if result["status"] != "success":
                print(f"  - {result['file']} ({result['status']})")

    # Save detailed results
    with open("processing_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to: processing_results.json")

if __name__ == "__main__":
    main()