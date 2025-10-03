import json
from src.llm_scorer import LLMScorer
from src.schemas import Transcript, Note
from datetime import date

# Create a simple test transcript
transcript = Transcript(
    meeting_id="test-taxonomy",
    date=date(2025, 9, 1),
    company="Test Corp",
    notes=[
        Note(text="Them: We're struggling with shrinking margins as we scale."),
        Note(text="Them: We need to achieve revenue growth and better profit per head."),
        Note(text="Them: We're a creative and design agency focused on brand work.")
    ],
    source="test"
)

# Initialize scorer
scorer = LLMScorer(model="gpt-4o-mini")

# Build context
context = "\n\n".join([note.text for note in transcript.notes])
print("Context:")
print(context)
print("\n" + "="*80 + "\n")

# Test taxonomy tagging
taxonomy_result = scorer._tag_taxonomy(context)
print("Taxonomy Result:")
print(json.dumps(taxonomy_result, indent=2))
