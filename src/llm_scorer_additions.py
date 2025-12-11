"""
SALESPERSON ASSESSMENT LLM SCORER ADDITIONS
Add these methods to src/llm_scorer.py in the upstream scoring project

These methods assess the UNKNOWN salesperson's capability (analyzing "Me:" speakers)
as opposed to the existing criteria which assess opportunity quality (analyzing "Them:" speakers)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# Import from schemas (after adding the new models)
# from .schemas import SalesAssessmentResult, SalesScoreResult


# =============================================================================
# ADD TO LLMScorer CLASS
# =============================================================================

class LLMScorerSalesAdditions:
    """
    Methods to add to the existing LLMScorer class.
    Copy these methods into src/llm_scorer.py
    """

    # =========================================================================
    # SALESPERSON ASSESSMENT PROMPTS
    # =========================================================================

    SALES_INTRODUCTION_PROMPT = """
    Assess how well the UNKNOWN representative introduced themselves and framed the meeting.
    ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

    What to look for:
    1. Did they introduce themselves and UNKNOWN succinctly?
    2. Did they frame the purpose of the meeting ("Why we're here / what you'll get out of today")?
    3. Did they set an agenda (discovery → solutions → next steps)?
    4. Did they ask permission to ask probing/challenging questions?

    Strong examples:
    - "I'm [Name] from UNKNOWN. Today I'd like to understand your challenges, share how we might help, and agree on next steps."
    - "Before we dive in, is it okay if I ask some direct questions to really understand your situation?"
    - "Let me quickly set the agenda - I'll ask about your current challenges, then share relevant examples, then we'll agree on next steps."

    Scoring guide:
    - 0: No introduction or framing attempted
    - 1: Basic intro but no agenda or framing
    - 2: Good intro with some agenda setting
    - 3: Strong intro with clear agenda, permission to probe, and meeting control

    Return JSON with exactly these fields:
    {
        "qualified": true if score >= 2,
        "score": 0-3 integer,
        "reason": "short explanation for the score",
        "evidence": "verbatim quote from 'Me:' speakers demonstrating this behavior, or null",
        "coaching_note": "specific suggestion to improve this skill, or null if score is 3"
    }
    """

    SALES_DISCOVERY_PROMPT = """
    Assess how well the UNKNOWN representative uncovered the client's problems and pain points.
    ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

    What to look for:
    1. Did they uncover high-level business challenges?
    2. Did they identify specific talent/hiring challenges?
    3. Did they explore impact of challenges (cost, time, burnout, quality, opportunity loss)?
    4. Did they identify emotional drivers (frustration, urgency, risk, ambition)?
    5. Did they ask what they've tried before and what didn't work?
    6. Did they ask layered, high-quality questions (peeled the onion)?

    Strong discovery questions:
    - "What's the biggest challenge that's keeping you up at night?"
    - "How is that impacting the business commercially?"
    - "What have you tried before to solve this?"
    - "Why do you think that didn't work?"
    - "If you don't solve this in the next 6 months, what happens?"

    Scoring guide:
    - 0: No meaningful discovery questions asked
    - 1: Surface-level questions only
    - 2: Good discovery with some depth
    - 3: Excellent layered discovery uncovering business impact and emotional drivers

    Return JSON with exactly these fields:
    {
        "qualified": true if score >= 2,
        "score": 0-3 integer,
        "reason": "short explanation for the score",
        "evidence": "verbatim quote from 'Me:' speakers showing discovery questions, or null",
        "coaching_note": "specific suggestion to improve discovery skills, or null if score is 3"
    }
    """

    SALES_SCOPING_PROMPT = """
    Assess how well the UNKNOWN representative scoped and qualified the opportunity.
    ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

    What to look for:
    1. Did they discuss budgets (perm, freelance, project, embedded)?
    2. Did they ask about hiring volumes for next 3-6-12 months?
    3. Did they understand how the client currently hires?
    4. Did they define what 'good' looks like for the client?
    5. Did they identify stakeholders involved in the decision?
    6. Did they understand the buying process and timeline?
    7. Did they ask about competing priorities?

    Strong scoping questions:
    - "What's your budget for this hire / these hires?"
    - "How many people do you expect to hire in the next 6 months, perm and freelance?"
    - "How do you currently source candidates for these roles?"
    - "Who else is involved in making this decision?"
    - "What's your timeline for getting someone in place?"
    - "Where does this sit on your leadership's priority list?"

    Scoring guide:
    - 0: No scoping or qualification attempted
    - 1: Basic scoping (1-2 elements)
    - 2: Good scoping covering budget and timeline
    - 3: Comprehensive scoping with budget, volumes, stakeholders, and process

    Return JSON with exactly these fields:
    {
        "qualified": true if score >= 2,
        "score": 0-3 integer,
        "reason": "short explanation for the score",
        "evidence": "verbatim quote from 'Me:' speakers showing scoping questions, or null",
        "coaching_note": "specific suggestion to improve scoping skills, or null if score is 3"
    }
    """

    SALES_SOLUTION_PROMPT = """
    Assess how well the UNKNOWN representative positioned UNKNOWN's solution.
    ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

    What to look for:
    1. Did they match client problems to UNKNOWN products (Partnership, Bench, Search, Ventures)?
    2. Did they use business outcomes, not just features?
    3. Did they position UNKNOWN as advisors/partners vs. just recruiters?
    4. Did they tailor the positioning to the client's specific situation?

    UNKNOWN Products:
    - The Partnership: Embedded talent advisory, extension of their TA team
    - The Bench: On-demand freelance creative talent
    - The Search: Executive/senior search for transformational hires
    - Ventures: M&A advisory, valuations, partnerships

    Strong positioning:
    - "Based on what you've told me about needing flexible capacity, The Bench could give you access to senior freelancers without the fixed overhead."
    - "This sounds like a transformation hire that will change your trajectory - that's exactly what our Search practice specializes in."
    - "We're not a typical recruiter - we work as an extension of your team to build long-term talent strategy."

    Scoring guide:
    - 0: No solution positioning attempted
    - 1: Generic pitch without matching to client needs
    - 2: Good positioning with some product matching
    - 3: Strong positioning with clear problem-to-product mapping and outcome focus

    Return JSON with exactly these fields:
    {
        "qualified": true if score >= 2,
        "score": 0-3 integer,
        "reason": "short explanation for the score",
        "evidence": "verbatim quote from 'Me:' speakers showing solution positioning, or null",
        "coaching_note": "specific suggestion to improve positioning skills, or null if score is 3"
    }
    """

    SALES_COMMERCIAL_PROMPT = """
    Assess how confidently the UNKNOWN representative discussed commercials and fees.
    ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

    What to look for:
    1. Did they mention fees or commercial terms (not apologetically)?
    2. Did they explain the value behind the fees?
    3. Did they discuss payment structure (retainers, deposits)?
    4. Did they check budget alignment before promising a proposal?
    5. Did they handle any pushback confidently without immediately discounting?

    Strong commercial confidence:
    - "Our typical fee for this type of search is X% of first-year salary. That reflects the depth of our network and the advisory support we provide."
    - "Before I put together a proposal, can you give me a sense of the budget you're working with?"
    - "We work on a retained basis because it allows us to dedicate senior resource to your search."
    - "I understand budget is tight, but let me explain why our approach delivers better ROI than a contingent recruiter."

    Weak commercial confidence:
    - Avoiding fee discussion entirely
    - "I'll send you our rates..." without context
    - Immediately offering discounts when challenged

    Scoring guide:
    - 0: No commercial discussion or actively avoided the topic
    - 1: Mentioned fees but apologetically or vaguely
    - 2: Clear fee discussion with some value articulation
    - 3: Confident commercial discussion with value justification and budget alignment

    Return JSON with exactly these fields:
    {
        "qualified": true if score >= 2,
        "score": 0-3 integer,
        "reason": "short explanation for the score",
        "evidence": "verbatim quote from 'Me:' speakers showing commercial discussion, or null",
        "coaching_note": "specific suggestion to improve commercial confidence, or null if score is 3"
    }
    """

    SALES_CASE_STUDIES_PROMPT = """
    Assess whether the UNKNOWN representative shared relevant case studies or proof points.
    ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

    What to look for:
    1. Did they share specific case studies or client examples?
    2. Were the examples relevant to the client's situation?
    3. Did they include specific outcomes or results?
    4. Did they use stories to build credibility?

    Strong case study sharing:
    - "We worked with a similar agency last year who had the same challenge. We placed their Creative Director in 6 weeks and they've since promoted them to ECD."
    - "One of our Bench clients reduced their freelance spend by 30% while improving quality - I can share that case study if helpful."
    - "We helped [Company] build out their entire product design team during their Series B growth. Happy to connect you with them as a reference."

    Weak examples:
    - "We work with lots of agencies" (no specifics)
    - Case studies that don't match the client's situation
    - No proof points at all

    Scoring guide:
    - 0: No case studies or proof points shared
    - 1: Generic or irrelevant examples mentioned
    - 2: Relevant case study but limited detail
    - 3: Strong, relevant case studies with specific outcomes matched to client needs

    Return JSON with exactly these fields:
    {
        "qualified": true if score >= 2,
        "score": 0-3 integer,
        "reason": "short explanation for the score",
        "evidence": "verbatim quote from 'Me:' speakers sharing case studies, or null",
        "coaching_note": "specific suggestion to improve use of proof points, or null if score is 3"
    }
    """

    SALES_NEXT_STEPS_PROMPT = """
    Assess how well the UNKNOWN representative closed the meeting and agreed next steps.
    ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

    What to look for:
    1. Did they summarize what they heard?
    2. Did they agree a specific next step with a date/time?
    3. Did they identify decision-makers and influencers?
    4. Did they confirm the buying process?
    5. Did they clarify what's needed from the client (brief, org chart, etc.)?
    6. Did they create momentum rather than leaving things open-ended?

    Strong closing:
    - "Let me summarize what I've heard... Does that capture it?"
    - "For next steps, I'll send over a proposal by Friday. Can we schedule a call next Tuesday to walk through it?"
    - "Who else needs to be involved in the decision? Should we include them in the next call?"
    - "What do you need from your side to move this forward?"
    - "I'll send you three candidate profiles by end of week. Can you commit to reviewing them by Monday?"

    Weak closing:
    - "I'll send you some information" (vague)
    - "Let me know when you're ready to move forward" (no commitment)
    - Ending without any clear next action

    Scoring guide:
    - 0: No clear next steps agreed
    - 1: Vague next steps without dates or owners
    - 2: Clear next step but limited stakeholder mapping
    - 3: Strong close with clear next step, stakeholder map, and momentum created

    Return JSON with exactly these fields:
    {
        "qualified": true if score >= 2,
        "score": 0-3 integer,
        "reason": "short explanation for the score",
        "evidence": "verbatim quote from 'Me:' speakers agreeing next steps, or null",
        "coaching_note": "specific suggestion to improve closing skills, or null if score is 3"
    }
    """

    SALES_STRATEGIC_CONTEXT_PROMPT = """
    Assess how well the UNKNOWN representative gathered strategic context about the client's business.
    ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

    What to look for:
    1. Did they ask where the business is going (ambition, growth plans, GTM)?
    2. Did they understand org design challenges or market conditions?
    3. Did they identify talent bottlenecks blocking growth?
    4. Did they ask what success looks like in 12 months?
    5. Did they spot cross-sell opportunities naturally?

    Strong strategic context questions:
    - "Where do you see the business in 12-18 months?"
    - "What's your growth target and what needs to happen to get there?"
    - "What's the biggest talent gap that's blocking your strategy?"
    - "If we nail this hire, what does success look like in a year?"
    - "Are there other areas of the business facing similar challenges?"
    - "How is your market evolving and how does that affect your talent needs?"

    This differs from Discovery (which focuses on current pain) - Strategic Context is about future direction and the bigger picture.

    Scoring guide:
    - 0: No strategic context gathered
    - 1: Basic understanding of current state only
    - 2: Good understanding of direction but limited depth
    - 3: Comprehensive strategic picture with future vision and cross-sell awareness

    Return JSON with exactly these fields:
    {
        "qualified": true if score >= 2,
        "score": 0-3 integer,
        "reason": "short explanation for the score",
        "evidence": "verbatim quote from 'Me:' speakers gathering strategic context, or null",
        "coaching_note": "specific suggestion to improve strategic questioning, or null if score is 3"
    }
    """

    # =========================================================================
    # ASSESSMENT METHODS
    # =========================================================================

    def _check_sales_introduction(self, context: str) -> Dict[str, Any]:
        """Assess introduction and framing"""
        result = self._make_openai_request(self.SALES_INTRODUCTION_PROMPT, context)
        return self._validate_sales_assessment_response(result, self.SALES_INTRODUCTION_PROMPT, context)

    def _check_sales_discovery(self, context: str) -> Dict[str, Any]:
        """Assess discovery of problems and pain"""
        result = self._make_openai_request(self.SALES_DISCOVERY_PROMPT, context)
        return self._validate_sales_assessment_response(result, self.SALES_DISCOVERY_PROMPT, context)

    def _check_sales_scoping(self, context: str) -> Dict[str, Any]:
        """Assess opportunity scoping and qualification"""
        result = self._make_openai_request(self.SALES_SCOPING_PROMPT, context)
        return self._validate_sales_assessment_response(result, self.SALES_SCOPING_PROMPT, context)

    def _check_sales_solution(self, context: str) -> Dict[str, Any]:
        """Assess solution positioning"""
        result = self._make_openai_request(self.SALES_SOLUTION_PROMPT, context)
        return self._validate_sales_assessment_response(result, self.SALES_SOLUTION_PROMPT, context)

    def _check_sales_commercial(self, context: str) -> Dict[str, Any]:
        """Assess commercial confidence"""
        result = self._make_openai_request(self.SALES_COMMERCIAL_PROMPT, context)
        return self._validate_sales_assessment_response(result, self.SALES_COMMERCIAL_PROMPT, context)

    def _check_sales_case_studies(self, context: str) -> Dict[str, Any]:
        """Assess use of case studies and proof points"""
        result = self._make_openai_request(self.SALES_CASE_STUDIES_PROMPT, context)
        return self._validate_sales_assessment_response(result, self.SALES_CASE_STUDIES_PROMPT, context)

    def _check_sales_next_steps(self, context: str) -> Dict[str, Any]:
        """Assess next steps and stakeholder mapping"""
        result = self._make_openai_request(self.SALES_NEXT_STEPS_PROMPT, context)
        return self._validate_sales_assessment_response(result, self.SALES_NEXT_STEPS_PROMPT, context)

    def _check_sales_strategic_context(self, context: str) -> Dict[str, Any]:
        """Assess strategic context gathering"""
        result = self._make_openai_request(self.SALES_STRATEGIC_CONTEXT_PROMPT, context)
        return self._validate_sales_assessment_response(result, self.SALES_STRATEGIC_CONTEXT_PROMPT, context)

    def _validate_sales_assessment_response(self, result: Dict[str, Any], prompt: str, context: str, retry_count: int = 0) -> Dict[str, Any]:
        """Validate sales assessment response matches expected schema"""
        expected_keys = {"qualified", "score", "reason", "evidence", "coaching_note"}

        # Check if keys match
        actual_keys = set(result.keys())
        if not expected_keys.issubset(actual_keys):
            if retry_count < 1:
                print(f"Invalid keys in sales assessment response. Expected: {expected_keys}, Got: {actual_keys}. Retrying...")
                retry_prompt = f"{prompt}\n\nYou returned invalid JSON. Return exactly the schema with: qualified, score, reason, evidence, coaching_note"
                return self._make_openai_request(retry_prompt, context, retry_count + 1)
            else:
                return {
                    "qualified": False,
                    "score": 0,
                    "reason": "Invalid JSON from model",
                    "evidence": None,
                    "coaching_note": "Unable to assess - model returned invalid response"
                }

        # Validate score is 0-3
        score = result.get("score")
        if not isinstance(score, int) or score < 0 or score > 3:
            result["score"] = max(0, min(3, int(score) if isinstance(score, (int, float)) else 0))

        # Ensure qualified matches score
        result["qualified"] = result.get("score", 0) >= 2

        return result

    def _generate_sales_coaching_summary(self, assessments: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Generate overall coaching summary from individual assessments"""
        strengths = []
        improvements = []

        # Map criteria names for readability
        criteria_names = {
            "introduction": "Introduction & Framing",
            "discovery": "Discovery",
            "scoping": "Opportunity Scoping",
            "solution": "Solution Positioning",
            "commercial": "Commercial Confidence",
            "case_studies": "Case Studies",
            "next_steps": "Next Steps",
            "strategic_context": "Strategic Context"
        }

        # Identify strengths (score 3) and improvements (score 0-1)
        for key, assessment in assessments.items():
            score = assessment.get("score", 0)
            name = criteria_names.get(key, key.title())

            if score == 3:
                strengths.append(f"{name}: {assessment.get('reason', 'Strong performance')}")
            elif score <= 1:
                coaching = assessment.get("coaching_note") or assessment.get("reason", "Needs improvement")
                improvements.append(f"{name}: {coaching}")

        # Generate overall coaching note
        total_score = sum(a.get("score", 0) for a in assessments.values())
        total_qualified = sum(1 for a in assessments.values() if a.get("qualified", False))

        if total_score >= 20:
            overall = "Excellent meeting performance. Focus on maintaining consistency and mentoring others."
        elif total_score >= 16:
            overall = "Good meeting performance. A few areas to refine for excellence."
        elif total_score >= 12:
            overall = "Developing skills. Focus on the improvement areas below for your next meeting."
        else:
            overall = "Significant coaching opportunity. Review the fundamentals and consider shadowing a senior colleague."

        return {
            "strengths": strengths[:3],  # Top 3
            "improvements": improvements[:3],  # Top 3
            "overall_coaching": overall
        }

    # =========================================================================
    # MAIN SCORING METHOD
    # =========================================================================

    def score_salesperson(self, transcript) -> Dict[str, Any]:
        """
        Score a transcript for salesperson capability assessment.

        Returns a SalesScoreResult-compatible dictionary.

        Args:
            transcript: Transcript object with meeting data

        Returns:
            Dictionary with all sales assessment scores and coaching
        """
        context = self._format_transcript_for_sales(transcript)

        # Run all 8 sales assessments
        introduction = self._check_sales_introduction(context)
        discovery = self._check_sales_discovery(context)
        scoping = self._check_sales_scoping(context)
        solution = self._check_sales_solution(context)
        commercial = self._check_sales_commercial(context)
        case_studies = self._check_sales_case_studies(context)
        next_steps = self._check_sales_next_steps(context)
        strategic_context = self._check_sales_strategic_context(context)

        # Collect all assessments
        assessments = {
            "introduction": introduction,
            "discovery": discovery,
            "scoping": scoping,
            "solution": solution,
            "commercial": commercial,
            "case_studies": case_studies,
            "next_steps": next_steps,
            "strategic_context": strategic_context
        }

        # Calculate totals
        total_score = sum(a.get("score", 0) for a in assessments.values())
        total_qualified = sum(1 for a in assessments.values() if a.get("qualified", False))

        # Generate coaching summary
        coaching_summary = self._generate_sales_coaching_summary(assessments)

        # Extract client info
        client_info = self._extract_client_info(transcript)

        return {
            "meeting_id": transcript.meeting_id,
            "salesperson_name": transcript.creator_name,
            "salesperson_email": transcript.creator_email,
            "date": transcript.date,
            "client": client_info.client if hasattr(client_info, 'client') else None,

            # Totals
            "total_score": total_score,
            "total_qualified": total_qualified,
            "qualified": total_qualified >= 5,  # Threshold: 5/8 criteria

            # Individual assessments
            "introduction": introduction,
            "discovery": discovery,
            "scoping": scoping,
            "solution": solution,
            "commercial": commercial,
            "case_studies": case_studies,
            "next_steps": next_steps,
            "strategic_context": strategic_context,

            # Coaching
            "strengths": coaching_summary["strengths"],
            "improvements": coaching_summary["improvements"],
            "overall_coaching": coaching_summary["overall_coaching"],

            # Metadata
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "llm_model": self.model
        }

    def _format_transcript_for_sales(self, transcript) -> str:
        """
        Format transcript for sales assessment, emphasizing "Me:" speaker analysis.

        Similar to _format_transcript but with reversed speaker focus.
        """
        context = f"""CRITICAL SPEAKER CONTEXT FOR SALES ASSESSMENT:
- "Me:" = UNKNOWN representative (ANALYZE for sales capability)
- "Them:" = Client company (context only - do not assess)

You are assessing the UNKNOWN salesperson's capability in this meeting.
Focus on what the "Me:" speaker says and does.

Salesperson: {transcript.creator_name or 'Unknown'}
Client Company: {transcript.company or 'Unknown'}
Date: {transcript.date}
Meeting Title: {transcript.title or transcript.calendar_event_title or 'Unknown'}

"""

        # Prioritize full transcript for sales assessment (need to see the conversation flow)
        if transcript.full_transcript and len(transcript.full_transcript.strip()) > 100:
            context += "Meeting Transcript:\n"
            full_text = transcript.full_transcript.strip()
            # Limit to avoid token overload but keep more than opportunity scoring
            if len(full_text) > 8000:
                full_text = full_text[:8000] + "\n...\n[Transcript truncated]"
            context += full_text + "\n"
        elif transcript.enhanced_notes and len(transcript.enhanced_notes.strip()) > 100:
            context += "Enhanced Meeting Notes:\n"
            context += transcript.enhanced_notes.strip() + "\n"
        else:
            # Fallback to notes format
            context += "Meeting Notes:\n"
            for note in transcript.notes:
                timestamp = f"[{note.t}] " if note.t else ""
                speaker = f"{note.speaker}: " if note.speaker else ""
                context += f"{timestamp}{speaker}{note.text}\n"

        return context

    # =========================================================================
    # COMBINED SCORING METHOD (both opportunity and sales)
    # =========================================================================

    def score_transcript_full(self, transcript) -> Dict[str, Any]:
        """
        Score a transcript for BOTH opportunity quality AND salesperson capability.

        This combines:
        - Existing: score_transcript_new() for opportunity scoring (NOW/NEXT/MEASURE/BLOCKER/FIT)
        - New: score_salesperson() for sales capability assessment

        Returns a combined result suitable for the updated BigQuery schema.
        """
        # Run opportunity scoring (existing)
        opportunity_result = self.score_transcript_new(transcript)

        # Run sales assessment (new)
        sales_result = self.score_salesperson(transcript)

        # Combine into single result
        combined = opportunity_result.model_dump() if hasattr(opportunity_result, 'model_dump') else dict(opportunity_result)

        # Add sales assessment fields
        combined["salesperson_name"] = sales_result["salesperson_name"]
        combined["salesperson_email"] = sales_result["salesperson_email"]
        combined["sales_total_score"] = sales_result["total_score"]
        combined["sales_total_qualified"] = sales_result["total_qualified"]
        combined["sales_qualified"] = sales_result["qualified"]

        # Add individual sales assessments
        combined["sales_introduction"] = sales_result["introduction"]
        combined["sales_discovery"] = sales_result["discovery"]
        combined["sales_scoping"] = sales_result["scoping"]
        combined["sales_solution"] = sales_result["solution"]
        combined["sales_commercial"] = sales_result["commercial"]
        combined["sales_case_studies"] = sales_result["case_studies"]
        combined["sales_next_steps"] = sales_result["next_steps"]
        combined["sales_strategic_context"] = sales_result["strategic_context"]

        # Add coaching summaries
        combined["sales_strengths"] = sales_result["strengths"]
        combined["sales_improvements"] = sales_result["improvements"]
        combined["sales_overall_coaching"] = sales_result["overall_coaching"]

        return combined