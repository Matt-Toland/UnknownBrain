import os
import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI

from .schemas import Transcript, Note, ScoreResult, CheckResult, FitResult

# Load environment variables
load_dotenv()


# Model configuration profiles
MODEL_CONFIGS = {
    "gpt-5": {
        "token_param": "max_completion_tokens",
        "supports_temperature": False,
        "context_window": 400000,
        "tier_required": "Team/Pro/Enterprise",
        "description": "Latest frontier model with 400k context"
    },
    "gpt-5-mini": {
        "token_param": "max_completion_tokens",
        "supports_temperature": False,
        "context_window": 400000,
        "tier_required": "Team/Pro/Enterprise",
        "description": "Cheaper, faster GPT-5 variant"
    },
    "gpt-5-pro": {
        "token_param": "max_completion_tokens",
        "supports_temperature": False,
        "context_window": 400000,
        "tier_required": "Pro/Enterprise",
        "description": "Extended reasoning GPT-5"
    },
    "gpt-5-nano": {
        "token_param": "max_completion_tokens",
        "supports_temperature": False,
        "context_window": 400000,
        "tier_required": "Team/Pro/Enterprise",
        "description": "Smallest GPT-5 variant"
    },
    "gpt-5-chat-latest": {
        "token_param": "max_completion_tokens",
        "supports_temperature": False,
        "context_window": 400000,
        "tier_required": "Team/Pro/Enterprise",
        "description": "Latest GPT-5 chat model"
    },
    "gpt-4o": {
        "token_param": "max_tokens",
        "supports_temperature": True,
        "context_window": 128000,
        "description": "Standard GPT-4o model"
    },
    "gpt-4o-mini": {
        "token_param": "max_tokens",
        "supports_temperature": True,
        "context_window": 128000,
        "description": "Cost-effective GPT-4o variant"
    },
    "gpt-4o-2024-08-06": {
        "token_param": "max_tokens",
        "supports_temperature": True,
        "context_window": 128000,
        "supports_structured": True,
        "description": "GPT-4o with structured outputs support"
    },
    "o1-preview": {
        "token_param": "max_completion_tokens",
        "supports_temperature": False,
        "context_window": 128000,
        "description": "Advanced reasoning model"
    },
    "o1-mini": {
        "token_param": "max_completion_tokens",
        "supports_temperature": False,
        "context_window": 128000,
        "description": "Cost-effective reasoning model"
    }
}


class LLMScorer:
    def __init__(self, model: str = None):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = model or os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "500"))
        
        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY environment variable not set")
        
        # Get model configuration
        self.model_config = self._get_model_config()
    
    def _get_model_config(self) -> Dict[str, Any]:
        """Get configuration for the current model"""
        # Direct match first
        if self.model in MODEL_CONFIGS:
            return MODEL_CONFIGS[self.model]
        
        # Pattern matching for model variants
        for config_model, config in MODEL_CONFIGS.items():
            if self.model.startswith(config_model):
                return config
        
        # Default fallback for unknown models (assume GPT-4 style)
        return {
            "token_param": "max_tokens",
            "supports_temperature": True,
            "context_window": 8000,
            "description": f"Unknown model: {self.model}"
        }
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the current model"""
        return {
            "model": self.model,
            "config": self.model_config.copy(),
            "temperature": self.temperature if self.model_config.get("supports_temperature", True) else 1.0,
            "max_tokens": self.max_tokens
        }
    
    def _extract_evidence(self, result: Dict[str, Any]) -> Optional[str]:
        """Extract evidence string from LLM result, handling list responses"""
        evidence = result.get("evidence")
        if isinstance(evidence, list):
            return evidence[0] if evidence else None
        return evidence
    
    def _format_transcript(self, transcript: Transcript) -> str:
        """Format transcript for LLM analysis"""
        context = f"Company: {transcript.company or 'Unknown'}\n"
        context += f"Date: {transcript.date}\n"
        context += f"Participants: {', '.join(transcript.participants)}\n\n"
        context += "Meeting Notes:\n"
        
        for note in transcript.notes:
            timestamp = f"[{note.t}] " if note.t else ""
            speaker = f"{note.speaker}: " if note.speaker else ""
            context += f"{timestamp}{speaker}{note.text}\n"
        
        return context
    
    def _make_openai_request(self, prompt: str, context: str, retry_count: int = 0) -> Dict[str, Any]:
        """Make request to OpenAI API with error handling"""
        try:
            # Route to appropriate API based on model type
            if self.model.startswith("gpt-5"):
                # Use Responses API for GPT-5 models
                return self._make_responses_api_request(prompt, context, retry_count)
            elif self.model.startswith("o1"):
                # o1 models use Chat Completions but with special handling
                return self._make_o1_chat_request(prompt, context, retry_count)
            else:
                # Use Chat Completions API for GPT-4o models
                return self._make_chat_completions_request(prompt, context, retry_count)
                
        except Exception as e:
            print(f"OpenAI API error: {e}")
            print(f"Model: {self.model}")
            
            # Check for specific model access errors
            if "does not exist" in str(e) or "access" in str(e).lower():
                tier_required = self.model_config.get("tier_required", "Unknown")
                return {"score": 0, "evidence": None, "reasoning": f"Model {self.model} requires {tier_required} access"}
            
            return {"score": 0, "evidence": None, "reasoning": f"API error: {str(e)}"}
    
    def _make_responses_api_request(self, prompt: str, context: str, retry_count: int = 0) -> Dict[str, Any]:
        """Make request using Responses API for GPT-5/o1 models"""
        full_prompt = f"{prompt}\n\nTranscript:\n{context}\n\nPlease respond in JSON format."
        
        # Add system instruction to prompt for reasoning models
        system_instruction = "You are an expert at analyzing business meetings for hiring and organizational needs. Always respond with valid JSON."
        combined_prompt = f"{system_instruction}\n\n{full_prompt}"
        
        # Use higher token limit for reasoning models
        max_out = max(self.max_tokens, 1500)
        
        try:
            response = self.client.responses.create(
                model=self.model,
                input=combined_prompt,
                reasoning={"effort": "minimal"},  # Fast reasoning to avoid timeouts
                text={"verbosity": "low"},       # Concise output
                max_output_tokens=max_out
            )
            
            content = response.output_text
            
        except Exception as e:
            print(f"Responses API error: {e}")
            print(f"Model: {self.model}")
            return {"score": 0, "evidence": None, "reasoning": f"Responses API error: {str(e)}"}
        
        return self._process_response_content(content, retry_count, prompt, context)
    
    def _make_o1_chat_request(self, prompt: str, context: str, retry_count: int = 0) -> Dict[str, Any]:
        """Make request using Chat Completions API for o1 models with special handling"""
        full_prompt = f"{prompt}\n\nTranscript:\n{context}\n\nPlease respond in JSON format."
        
        # Add system instruction to prompt for o1 models (no system message support)
        system_instruction = "You are an expert at analyzing business meetings for hiring and organizational needs. Always respond with valid JSON."
        combined_prompt = f"{system_instruction}\n\n{full_prompt}"
        
        # Use higher token limit for reasoning models
        max_out = max(self.max_tokens, 1500)
        
        try:
            request_params = {
                "model": self.model,
                "messages": [
                    {"role": "user", "content": combined_prompt}
                ],
                "max_completion_tokens": max_out
                # Don't set temperature for o1 models
            }
            
            response = self.client.chat.completions.create(**request_params)
            content = response.choices[0].message.content
            
        except Exception as e:
            print(f"o1 Chat Completions API error: {e}")
            print(f"Model: {self.model}")
            return {"score": 0, "evidence": None, "reasoning": f"o1 Chat API error: {str(e)}"}
        
        return self._process_response_content(content, retry_count, prompt, context)
    
    def _make_chat_completions_request(self, prompt: str, context: str, retry_count: int = 0) -> Dict[str, Any]:
        """Make request using Chat Completions API for GPT-4o models"""
        full_prompt = f"{prompt}\n\nTranscript:\n{context}\n\nPlease respond in JSON format."
        
        try:
            # Build request parameters using model configuration
            request_params = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are an expert at analyzing business meetings for hiring and organizational needs. Always respond with valid JSON."},
                    {"role": "user", "content": full_prompt}
                ]
            }
            
            # Set token parameter based on model config
            token_param = self.model_config.get("token_param", "max_tokens")
            request_params[token_param] = self.max_tokens
            
            # Set temperature only if model supports it
            if self.model_config.get("supports_temperature", True):
                request_params["temperature"] = self.temperature
            
            response = self.client.chat.completions.create(**request_params)
            content = response.choices[0].message.content
            
        except Exception as e:
            print(f"Chat Completions API error: {e}")
            print(f"Model: {self.model}")
            return {"score": 0, "evidence": None, "reasoning": f"Chat Completions API error: {str(e)}"}
        
        return self._process_response_content(content, retry_count, prompt, context)
    
    def _process_response_content(self, content: str, retry_count: int, prompt: str, context: str) -> Dict[str, Any]:
        """Process and parse response content from either API"""
        if not content or content.strip() == "":
            # Handle empty responses
            if retry_count < 2:  # Retry up to 2 times
                print(f"Empty response from {self.model}, retrying... ({retry_count + 1}/3)")
                return self._make_openai_request(prompt, context, retry_count + 1)
            else:
                print(f"Empty response from {self.model} after 3 attempts")
                return {"score": 0, "evidence": None, "reasoning": f"Empty response from {self.model}"}
        
        content = content.strip()
        
        # Try to extract JSON from response
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            print(f"Response content: {content}")
            print(f"Model: {self.model}")
            
            # Retry on JSON errors for reasoning models
            if retry_count < 1 and (self.model.startswith("gpt-5") or "o1" in self.model):
                print(f"Retrying {self.model} due to JSON error... ({retry_count + 1}/2)")
                return self._make_openai_request(prompt, context, retry_count + 1)
            
            return {"score": 0, "evidence": None, "reasoning": "JSON parse error"}
    
    def _check_now(self, context: str) -> CheckResult:
        """Check for current state and immediate hiring needs"""
        prompt = """
        Analyze this meeting transcript for the company's CURRENT STATE and IMMEDIATE hiring needs:

        What to look for:
        1. Current company scale (revenue, headcount, size indicators)
        2. Immediate hiring needs (within 60 days)
        3. Urgent talent requirements or open roles
        4. Current team capacity issues

        Examples of NOW signals:
        - "We have 50 employees and $10M ARR"
        - "Need to hire 3 engineers this month"
        - "Team is overwhelmed, need help ASAP"
        - "Critical roles open, blocking client delivery"

        Return JSON: 
        {
            "score": 1 or 0,
            "evidence": "specific quote from transcript or null",
            "reasoning": "brief explanation"
        }
        """
        
        result = self._make_openai_request(prompt, context)
        
        return CheckResult(
            score=result.get("score", 0),
            evidence_line=self._extract_evidence(result),
            timestamp=None
        )
    
    def _check_next(self, context: str) -> CheckResult:
        """Check for future growth plans and vision"""
        prompt = """
        Analyze this meeting transcript for the company's FUTURE VISION and growth ambitions:

        What to look for:
        1. Growth ambition (scale targets, exit plans, market expansion)
        2. Future hiring plans (60-180 days out)
        3. Vision of where they want to be
        4. Strategic initiatives requiring talent

        Examples of NEXT signals:
        - "Planning to double headcount next year"
        - "After Series B, we'll expand to Europe"
        - "Goal is IPO in 24 months"
        - "Will need 20 more engineers once funding closes"

        Return JSON:
        {
            "score": 1 or 0,
            "evidence": "specific quote from transcript or null",
            "reasoning": "brief explanation"
        }
        """
        
        result = self._make_openai_request(prompt, context)
        
        return CheckResult(
            score=result.get("score", 0),
            evidence_line=self._extract_evidence(result),
            timestamp=None
        )
    
    def _check_measure(self, context: str) -> CheckResult:
        """Check for success metrics and measurement approach"""
        prompt = """
        Analyze how this company measures SUCCESS using the Fun/Fame/Fortune framework:

        What to look for:
        1. FUN: Culture metrics, team satisfaction, work environment quality
        2. FAME: Market recognition, brand building, industry leadership goals
        3. FORTUNE: Revenue targets, profitability, financial metrics
        4. Specific KPIs, measurements, or success criteria mentioned

        Examples of MEASURE signals:
        - "Target 95% employee satisfaction"
        - "Aiming for market leader position"
        - "Goal is $100M ARR by 2026"
        - "Time-to-hire under 30 days"
        - "eNPS score of 70+"

        Return JSON:
        {
            "score": 1 or 0,
            "evidence": "specific quote from transcript or null",
            "reasoning": "brief explanation",
            "category": "Fun, Fame, or Fortune"
        }
        """
        
        result = self._make_openai_request(prompt, context)
        
        return CheckResult(
            score=result.get("score", 0),
            evidence_line=self._extract_evidence(result),
            timestamp=None
        )
    
    def _check_blocker(self, context: str) -> CheckResult:
        """Check for blockers preventing growth"""
        prompt = """
        Identify the company's biggest BLOCKERS preventing them from achieving their goals:

        Categories to look for:
        1. TALENT GAPS: Can't find right people, skills shortages
        2. STRUCTURE: Org design issues, process problems
        3. GROWTH STALLS: Market, product, or sales constraints
        4. INVESTOR PRESSURE: Board demands, funding requirements
        5. EXTERNAL: Regulatory, legal, market conditions

        Examples of BLOCKER signals:
        - "Can't find senior engineers"
        - "Our onboarding process is broken"
        - "Market is saturated"
        - "Board pushing for profitability"
        - "Regulatory approval taking too long"

        Return JSON:
        {
            "score": 1 or 0,
            "evidence": "specific quote from transcript or null",
            "reasoning": "brief explanation",
            "category": "Talent/Structure/Growth/Investor/External"
        }
        """
        
        result = self._make_openai_request(prompt, context)
        
        return CheckResult(
            score=result.get("score", 0),
            evidence_line=self._extract_evidence(result),
            timestamp=None
        )
    
    def _check_fit(self, context: str) -> FitResult:
        """Check which UNKNOWN services match the company's needs"""
        prompt = """
        Classify this company's needs into UNKNOWN service categories:

        TALENT (Recruitment & Hiring):
        - Hiring needs, recruitment challenges
        - Time-to-hire issues, sourcing problems
        - Interview processes, candidate pipelines
        - Offer acceptance, onboarding

        EVOLVE (Organizational Development):
        - Organization design, structure changes
        - Compensation, salary bands, benchmarking
        - Performance management systems
        - Culture, retention, employee experience
        - Team scaling, management development

        VENTURES (Growth & Innovation):
        - New market entry, expansion plans
        - Innovation projects, pilots, MVPs
        - Business model transformation
        - M&A, partnerships, ventures

        Return JSON:
        {
            "score": 1 or 0,
            "fit_labels": ["Talent", "Evolve", "Ventures"] (list of matching categories),
            "evidence": "specific quote from transcript or null",
            "reasoning": "brief explanation of matches"
        }
        """
        
        result = self._make_openai_request(prompt, context)
        
        return FitResult(
            score=result.get("score", 0),
            fit_labels=result.get("fit_labels", []),
            evidence_line=self._extract_evidence(result),
            timestamp=None
        )
    
    def score_transcript(self, transcript: Transcript) -> ScoreResult:
        """Score a transcript using LLM analysis"""
        context = self._format_transcript(transcript)
        
        # Run all scoring checks
        now_result = self._check_now(context)
        next_result = self._check_next(context)
        measure_result = self._check_measure(context)
        blocker_result = self._check_blocker(context)
        fit_result = self._check_fit(context)
        
        # Calculate total score
        total_score = (
            now_result.score +
            next_result.score + 
            measure_result.score +
            blocker_result.score +
            fit_result.score
        )
        
        return ScoreResult(
            meeting_id=transcript.meeting_id,
            company=transcript.company,
            date=transcript.date,
            total_score=total_score,
            checks={
                "now": {
                    "score": now_result.score,
                    "evidence_line": now_result.evidence_line,
                    "timestamp": now_result.timestamp
                },
                "next": {
                    "score": next_result.score,
                    "evidence_line": next_result.evidence_line,
                    "timestamp": next_result.timestamp
                },
                "measure": {
                    "score": measure_result.score,
                    "evidence_line": measure_result.evidence_line,
                    "timestamp": measure_result.timestamp
                },
                "blocker": {
                    "score": blocker_result.score,
                    "evidence_line": blocker_result.evidence_line,
                    "timestamp": blocker_result.timestamp
                },
                "fit": {
                    "score": fit_result.score,
                    "fit_labels": fit_result.fit_labels,
                    "evidence_line": fit_result.evidence_line,
                    "timestamp": fit_result.timestamp
                }
            }
        )