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
    "transcripts/Matt__-_2025-09-18T13_07_07.566Z.txt",
    "transcripts/Ollie_Alex_Lubar_call___-_2025-08-26T14_00_00_01_00.txt",
    "transcripts/Ollie_Instrument_x_Unknown_Connect_-_2025-06-30T15_00_00_01_00.txt",
    "transcripts/Ollie_Ollie_x_John_-_2025-09-22T14_00_00_01_00.txt",
    "transcripts/Ollie_Ollie_x_Zulum_-_2025-08-26T12_15_00_01_00.txt",
    "transcripts/Ollie_Scott_Laura_x_Carrie___Ollie_-_2025-03-28T13_00_00Z.txt",
    "transcripts/Ollie_Scott_Ollie__Unknown__x_James__CO___-_Intro_chat_-_2025-04-08T10_30_00_01_00.txt",
    "transcripts/Ollie_Scott_Ollie_x_Eric_-_2025-06-27T12_30_00_01_00.txt",
    "transcripts/_Ellie_Gould__Diverse_candidate_recruitment_and_Taylor_s_potential_project_opportunity_-_2025-0.txt",
    "transcripts/_Ellie__Bolder_studio_talent_and_hiring_strategy_planning_-_2025-08-19T16_32_32.431Z.txt",
    "transcripts/_Ellie__Creative_talent_search_and_agency_strategy_review_for_Weareunknown_-_2025-08-27T14_06_3.txt",
    "transcripts/_Ellie__Ellie_x_Ayo_-_2025-09-18T11_15_00_01_00.txt",
    "transcripts/_Ellie__Ellie_x_Miranda__-_2025-07-21T15_00_00_01_00.txt",
    "transcripts/_Ellie__Virtue_creative_agency_strategy_director_role_exploration_with_candidate_-_2025-08-28T1.txt",
    "transcripts/_Erik_Lehmann_-_Spekk_Vibe_Interview_-_2025-06-11T16_30_00_01_00.txt",
    "transcripts/_Matt__Granola_brain_project_planning_with_Access_Transform_Ventures_team_-_2025-09-18T13_07_07.txt",
    "transcripts/_Matt__Matt_x_Unknown_Brain_Test_Meet_-_2025-09-16T15_45_00_01_00.txt",
    "transcripts/_Molly_-_Atoms_Space_X_Unknown__-_2025-09-23T11_00_00_01_00.txt",
    "transcripts/_Ollie__Sam__Ollie_x_Sam_connect_-_2025-10-01T10_30_00_01_00.txt",
    "transcripts/_Recruiting_-_2025-07-24T17_00_00_01_00.txt",
    "transcripts/_Sam_Winward__Briefing_Unknown__online__-_2025-09-04T11_30_00_01_00.txt",
    "transcripts/_Sam_Winward__Effy__Ellie_x_Sam_connect_IRL._-_2025-09-24T13_00_00_01_00.txt",
    "transcripts/_Sam_Winward__Gladwell_x_Sam_connect_-_2025-09-26T17_00_00_01_00.txt",
    "transcripts/_Sam_Winward__Lorenzo_x_Sam_connect_-_2025-09-29T14_00_00_01_00.txt",
    "transcripts/_Sam_Winward__Lucia_x_Sam_connect_-_2025-09-17T17_00_00_01_00.txt",
    "transcripts/_Sam_Winward__Robin_x_Sam_connect_-_2025-09-19T14_30_00_01_00.txt",
    "transcripts/_Sam_Winward__Stu_x_Sam_call_-_2025-09-23T16_00_00_01_00.txt",
    "transcripts/_Sam_Winward__Toby_x_Sam_call_-_2025-09-18T15_00_00_01_00.txt",
    "transcripts/_Sam_reconnect_-_2025-09-17T14_30_00_01_00.txt",
    "transcripts/_Sean__Sean_x_Mohan_-_Design_connect_-_2025-10-02T14_00_00_01_00.txt",
    "transcripts/_Tom_Philipson_-_VC_-_2025-09-26T15_30_00_01_00.txt",
    "transcripts/_Unkown_-_2025-07-28T12_30_00_01_00.txt",
    "transcripts/_We_are_unknown_-_2025-07-29T14_00_00_01_00.txt",
    "transcripts/_Woody__Astronaut_Monastery_x_UNKNOWN__Design_-_2025-08-19T17_30_00_01_00.txt",
    "transcripts/_Woody__BA_Kick_off_call-_UNKNOWN_-_2025-08-27T16_30_00_01_00.txt",
    "transcripts/_Woody__Mark_Shanley_X_Woody___Joe_Connect_-_2025-09-16T14_00_00_01_00.txt",
    "transcripts/_Woody__WatchHouse_x_UKNOWN_-_2025-09-29T12_30_00_01_00.txt"
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