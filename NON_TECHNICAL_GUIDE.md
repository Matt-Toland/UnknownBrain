# Client Name Management - Non-Technical Guide

## What Problem Does This Solve?

Sometimes the same client appears with different names in your data:
- "Omnicom" vs "Omnicom / DDB"
- "Leagas Delaney" vs "Legas Delaney" (typo)
- Corrupted names like "Bcb88E78 88E8"

This makes it hard to see all meetings for a single client.

## ✨ How It Works (Automatically!)

**Good news**: The system now **automatically fixes client names** when new transcripts are scored!

### Behind the Scenes

1. **New transcript arrives** → System scores it
2. **Client name extracted** → "Omnicom / DDB"
3. **Auto-normalized** → Changes to "Omnicom"
4. **Saved to database** → Already clean!

You don't need to do anything for new transcripts! 🎉

## When Do You Need to Take Action?

### Scenario 1: New Client Variant Discovered

**Example**: LLM starts extracting "Omnicom Group" instead of "Omnicom"

**What to do**:
1. Ask your technical contact to run:
   ```bash
   python -m src.cli add-client-mapping "Omnicom Group" "Omnicom"
   ```

2. That's it! Future transcripts will auto-normalize.

3. Optional: Fix old records:
   ```bash
   python -m src.cli fix-client-names --execute
   ```

### Scenario 2: Fix Existing Records

Old transcripts in the database still have variant names.

**What to do**:
Ask technical contact to run:
```bash
python -m src.cli fix-client-names --execute
```

This updates all existing records at once.

## Simple Commands Reference

Your technical contact can run these commands:

### See all client names
```bash
python -m src.cli list-clients --counts
```
**Shows**: Every unique client name and how many meetings each has

### See current name mappings
```bash
python -m src.cli list-mappings
```
**Shows**: All the "variant → canonical" name mappings

### Add a new mapping
```bash
python -m src.cli add-client-mapping "Wrong Name" "Correct Name"
```
**Does**: Tells system to auto-fix "Wrong Name" to "Correct Name"

### Fix old records
```bash
python -m src.cli fix-client-names --execute
```
**Does**: Updates all existing records in the database

## Current Mappings (Active)

These client names are **automatically fixed** when found:

| If System Sees This | It Changes To | Why |
|---------------------|---------------|-----|
| `25615A3D E4C9` | `Unknown` | Corrupted data |
| `Bcb88E78 88E8` | `Unknown` | Corrupted data |
| `D185Be63 81B0` | `Unknown` | Corrupted data |
| `Legas Delaney` | `Leagas Delaney` | Typo fix |
| `Omnicom / DDB` | `Omnicom` | Use parent company |
| `Sophia (creative agency...)` | `Sophia` | Remove description |
| `Media Arts Lab (Apple's...)` | `Media Arts Lab` | Remove description |
| `Your Studio (unnamed...)` | `Your Studio` | Remove description |

## FAQ for Non-Technical Users

### Q: Do I need to do anything for new transcripts?
**A**: No! New transcripts are automatically cleaned.

### Q: What about old transcripts already in the database?
**A**: Run `fix-client-names --execute` to update them (ask tech contact).

### Q: How do I add a new name mapping?
**A**: Ask your technical contact to run `add-client-mapping`.

### Q: Where are the mappings stored?
**A**: In BigQuery (cloud database), so they work everywhere automatically.

### Q: Do changes require redeploying the application?
**A**: No! Mappings update instantly without redeployment.

### Q: Can I add mappings from the BigQuery console?
**A**: Yes! Your technical contact can insert directly into the `client_mappings` table.

## When to Contact Technical Support

Contact your technical team if:

1. **New client variant appears regularly**
   - They can add a permanent mapping

2. **Want to bulk update all records**
   - They can run the fix command

3. **Need to remove a mapping**
   - They can use `delete-client-mapping`

4. **Corrupted names still appearing**
   - May need to investigate the source data

## Workflow Summary

```
┌─────────────────────────────────────────┐
│ New Transcript Arrives                  │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ System Extracts Client Name             │
│ Example: "Omnicom / DDB"                │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ Auto-Normalize Using Mappings ✨        │
│ "Omnicom / DDB" → "Omnicom"             │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│ Save to Database                        │
│ Already clean!                          │
└─────────────────────────────────────────┘
```

**Bottom line**: The system is now fully automatic. You only need manual intervention when discovering new variants!
