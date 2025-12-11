import os
import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI

from .schemas import (
    Transcript, Note, ScoreResult, FitResult, NewScoreResult, SectionResult, ClientInfo,
    SalesAssessmentResult, SalesScoreResult, SALES_ASSESSMENT_CRITERIA
)
import re

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
    # FIT service aliases for backward compatibility
    FIT_ALIASES = {
        "talent": "Access",
        "access": "Access",
        "evolve": "Transform",
        "transform": "Transform",
        "ventures": "Ventures",
        "venture": "Ventures"
    }

    # Client taxonomy controlled vocabularies
    TAXONOMY_CHALLENGES = [
        "Diversify product & services",
        "Expand locations",
        "Succession planning",
        "Shrinking margin",
        "Spikes in workload",
        "Losing revenue cos lack of staff",
        "Needing specialists in short notice",
        "Maintaining creative quality without ballooning overheads",
        "Margins eroding as business scales",
        "Misalignment between creating value and delivering value",
        "Unsure how to value their business",
        "Not knowing which businesses are right to buy / acquire",
        "Lacking intros to PE or M&A firms",
        "Missing out on growth opportunities as they can't move fast enough",
        "Don't have networks in specific locations",
        "Diversify product",
        "Consolidating agencies",
        "Elevating creativity"
    ]

    TAXONOMY_RESULTS = [
        "Revenue Growth",
        "Win rate on pitches %",
        "Access to new markets and clients",
        "Ability to take on more complex higher margin work",
        "Lower fixed cost base through flexible talent models",
        "More profit per head",
        "Reduced talent churn",
        "Reduced inefficiencies",
        "Avoiding mishires",
        "Avoiding stagnancy",
        "Smooth succession protecting value and continuity",
        "Built proprietary products that lead to higher valuations",
        "Faster hiring in scarce talent pools",
        "Foresight of costs with flexible talent models",
        "Foresight of resource with always-on talent",
        "Scaled systems that mean we focus on compounding our strengths",
        "Won industry accolades",
        "Increased quality of output meaning more client wins",
        "Stronger brand reputation and client stickiness",
        "Stronger employer brand reputation and talent stickiness",
        "Distinctive talent advantage that competitors can't replicate easily"
    ]

    TAXONOMY_OFFERINGS = [
        "Creative & Design",
        "Branding Consultancy",
        "Product",
        "Content Studio",
        "Production Company",
        "Influencer / Creator agency",
        "Media",
        "Performance Marketing",
        "PR / Comms",
        "Experiential",
        "Social",
        "Innovation",
        "Data",
        "E-Commerce",
        "AI Automation",
        "Brand",
        "Health & Pharma",
        "B2B",
        "Sports & Entertainment",
        "Sustainability agency",
        "Luxury & Fashion",
        "Gaming",
        "Fintech",
        "Other"
    ]

    def __init__(self, model: str = None):
        # Set longer timeout for GPT-5 models which need more time for reasoning
        timeout = 120.0  # 2 minutes for reasoning models
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=timeout)
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

    def _validate_section_response(self, result: Dict[str, Any], prompt: str, context: str, retry_count: int = 0) -> Dict[str, Any]:
        """Validate section response matches expected schema"""
        expected_keys = {"qualified", "reason", "summary", "evidence"}

        # Check if keys match exactly
        actual_keys = set(result.keys())
        if actual_keys != expected_keys:
            if retry_count < 1:
                print(f"Invalid keys in response. Expected: {expected_keys}, Got: {actual_keys}. Retrying...")
                retry_prompt = f"{prompt}\n\nYou returned invalid JSON. Return exactly the schema."
                return self._make_openai_request(retry_prompt, context, retry_count + 1)
            else:
                return {
                    "qualified": False,
                    "reason": "Invalid JSON from model",
                    "summary": "Model returned invalid response format",
                    "evidence": None
                }

        # Check qualified is boolean
        if not isinstance(result.get("qualified"), bool):
            if retry_count < 1:
                print(f"'qualified' must be boolean, got {type(result.get('qualified'))}. Retrying...")
                retry_prompt = f"{prompt}\n\nYou returned invalid JSON. Return exactly the schema."
                return self._make_openai_request(retry_prompt, context, retry_count + 1)
            else:
                return {
                    "qualified": False,
                    "reason": "Invalid JSON from model",
                    "summary": "Model returned non-boolean qualified field",
                    "evidence": None
                }


        return result

    def _normalize_fit_services(self, items):
        """Normalize FIT service names for backward compatibility"""
        norm = []
        if not isinstance(items, list):
            return norm
        for x in items:
            if not isinstance(x, str):
                continue
            key = x.strip().lower()
            mapped = self.FIT_ALIASES.get(key)
            if mapped and mapped not in norm:
                norm.append(mapped)
        return norm

    def _clean_evidence(self, evidence):
        """Clean and validate evidence text"""
        if not evidence or not isinstance(evidence, str):
            return None

        # Strip and check length
        cleaned = evidence.strip()
        if not cleaned:
            return None

        # Enforce 25-word limit for FIT evidence
        words = cleaned.split()
        if len(words) > 25:
            cleaned = ' '.join(words[:25])

        return cleaned

    def _validate_fit_response(self, result: Dict[str, Any], prompt: str, context: str, retry_count: int = 0) -> Dict[str, Any]:
        """Validate FIT response matches expected schema (includes services field)"""
        expected_keys = {"qualified", "reason", "summary", "services", "evidence"}

        # Check if keys match exactly
        actual_keys = set(result.keys())
        if actual_keys != expected_keys:
            if retry_count < 1:
                print(f"Invalid keys in FIT response. Expected: {expected_keys}, Got: {actual_keys}. Retrying...")
                retry_prompt = f"{prompt}\n\nYou returned invalid JSON. Return exactly the schema."
                return self._make_openai_request(retry_prompt, context, retry_count + 1)
            else:
                return {
                    "qualified": False,
                    "reason": "Invalid JSON from model",
                    "summary": "Model returned invalid response format",
                    "services": [],
                    "evidence": None
                }

        # Check qualified is boolean
        if not isinstance(result.get("qualified"), bool):
            if retry_count < 1:
                print(f"'qualified' must be boolean, got {type(result.get('qualified'))}. Retrying...")
                retry_prompt = f"{prompt}\n\nYou returned invalid JSON. Return exactly the schema."
                return self._make_openai_request(retry_prompt, context, retry_count + 1)
            else:
                return {
                    "qualified": False,
                    "reason": "Invalid JSON from model",
                    "summary": "Model returned non-boolean qualified field",
                    "services": [],
                    "evidence": None
                }

        # Check services is list
        if not isinstance(result.get("services"), list):
            if retry_count < 1:
                print(f"'services' must be list, got {type(result.get('services'))}. Retrying...")
                retry_prompt = f"{prompt}\n\nYou returned invalid JSON. Return exactly the schema."
                return self._make_openai_request(retry_prompt, context, retry_count + 1)
            else:
                result["services"] = []

        # Normalize service names for backward compatibility
        result["services"] = self._normalize_fit_services(result.get("services", []))
        result["evidence"] = self._clean_evidence(result.get("evidence"))
        return result

    def _extract_client_info(self, transcript: Transcript) -> ClientInfo:
        """Extract client information using three-tier approach"""
        # Tier 1: Use LLM extraction (most accurate)
        llm_client = self._extract_client_with_llm(transcript)
        if llm_client.client and llm_client.client.strip():
            return llm_client

        # Tier 2: Extract from filename (fallback)
        filename_client = self._extract_client_from_filename(transcript.meeting_id)
        if filename_client and len(filename_client) > 3 and not filename_client.lower().startswith(('auto', 'meeting', 'call')):
            return ClientInfo(
                client=filename_client,
                source="filename"
            )

        # Tier 3: Domain heuristics fallback
        domain_client = self._extract_client_from_domain(transcript)
        return domain_client

    def _extract_client_from_filename(self, meeting_id: str) -> Optional[str]:
        """Extract client name from meeting ID/filename"""
        # Remove common prefixes and suffixes
        clean_id = meeting_id.lower()
        clean_id = re.sub(r'^(auto-|meeting-|call-|transcript-)', '', clean_id)
        clean_id = re.sub(r'-(\d{10,}|transcript|call|meeting).*$', '', clean_id)

        # Split on hyphens and take meaningful parts
        parts = clean_id.split('-')
        if len(parts) >= 2:
            # Take first 1-2 parts as potential company name
            company_parts = parts[:2] if len(parts[1]) > 2 else parts[:1]
            return ' '.join(company_parts).title()

        return None

    def _extract_client_with_llm(self, transcript: Transcript) -> ClientInfo:
        """Extract client information using LLM"""
        context = self._format_transcript(transcript)

        prompt = """
        Extract client/company information from this meeting transcript:

        What to identify:
        1. Primary company/client name being discussed
        2. Industry/domain (fintech, healthcare, e-commerce, etc.)
        3. Company size category (startup, scaleup, enterprise)

        Return JSON:
        {
            "client": "Company Name or null",
            "domain": "industry vertical or null",
            "size": "startup/scaleup/enterprise or null"
        }
        """

        result = self._make_openai_request(prompt, context)

        return ClientInfo(
            client=result.get("client"),
            domain=result.get("domain"),
            size=result.get("size"),
            source="llm"
        )

    def _extract_client_from_domain(self, transcript: Transcript) -> ClientInfo:
        """Extract client using domain heuristics as fallback"""
        # Use existing company field as fallback
        client = transcript.company or "Unknown"

        # Simple domain classification based on keywords
        content = self._format_transcript(transcript).lower()

        domain = None
        if any(word in content for word in ['fintech', 'banking', 'payments', 'crypto']):
            domain = 'fintech'
        elif any(word in content for word in ['healthcare', 'medical', 'pharma', 'biotech']):
            domain = 'healthcare'
        elif any(word in content for word in ['ecommerce', 'retail', 'marketplace', 'shopping']):
            domain = 'e-commerce'
        elif any(word in content for word in ['saas', 'software', 'platform', 'api']):
            domain = 'saas'

        return ClientInfo(
            client=client,
            domain=domain,
            source="domain"
        )
    
    def _format_transcript(self, transcript: Transcript) -> str:
        """Format transcript for LLM analysis, prioritizing enhanced notes"""
        context = f"""CRITICAL SPEAKER CONTEXT:
- "Me:" = Unknown representative (IGNORE for scoring)
- "Them:" = Client company (ANALYZE for scoring)

WARNING: You MUST analyze ONLY the CLIENT company's metrics, needs, and situation.
Do NOT use any statements from "Me:" speakers as evidence about the client.

Company being analyzed: {transcript.company or 'Unknown'}
Date: {transcript.date}
Participants: {', '.join(transcript.participants)}

"""

        # Prioritize enhanced notes for better evidence diversity
        if transcript.enhanced_notes and len(transcript.enhanced_notes.strip()) > 100:
            context += "Enhanced Meeting Notes:\n"
            context += transcript.enhanced_notes.strip() + "\n\n"

            # Optionally add full transcript for additional context if enhanced notes are short
            if len(transcript.enhanced_notes.strip()) < 1000:
                context += "Additional Context (Full Transcript):\n"
                if transcript.full_transcript:
                    # Limit full transcript to avoid token overload
                    full_transcript_text = transcript.full_transcript.strip()
                    if len(full_transcript_text) > 3000:
                        full_transcript_text = full_transcript_text[:3000] + "...\n[Transcript truncated]"
                    context += full_transcript_text + "\n"
                else:
                    # Fallback to notes format
                    for note in transcript.notes[:20]:  # Limit to first 20 notes
                        timestamp = f"[{note.t}] " if note.t else ""
                        speaker = f"{note.speaker}: " if note.speaker else ""
                        context += f"{timestamp}{speaker}{note.text}\n"
        else:
            # Fallback to original format if no enhanced notes
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
                return {"qualified": False, "reason": f"Model {self.model} requires {tier_required} access", "summary": "API access error", "evidence": None}

            return {"qualified": False, "reason": f"API error: {str(e)}", "summary": "API request failed", "evidence": None}
    
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
            return {"qualified": False, "reason": f"Responses API error: {str(e)}", "summary": "API request failed", "evidence": None}
        
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
            return {"qualified": False, "reason": f"o1 Chat API error: {str(e)}", "summary": "API request failed", "evidence": None}
        
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
            return {"qualified": False, "reason": f"Chat Completions API error: {str(e)}", "summary": "API request failed", "evidence": None}
        
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
                return {"qualified": False, "reason": f"Empty response from {self.model}", "summary": "No response received", "evidence": None}
        
        content = content.strip()
        
        # Try to extract JSON from response
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
        
        try:
            result = json.loads(content)

            # Normalize evidence field if it's a list
            if "evidence" in result and isinstance(result["evidence"], list):
                # Join list elements into a single string
                result["evidence"] = " ".join(str(item) for item in result["evidence"] if item)

            return result
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            print(f"Response content: {content}")
            print(f"Model: {self.model}")
            
            # Retry on JSON errors with fallback strategy
            if retry_count < 1 and (self.model.startswith("gpt-5") or "o1" in self.model):
                # First retry: Try same model again
                print(f"Retrying {self.model} due to JSON error... ({retry_count + 1}/2)")
                return self._make_openai_request(prompt, context, retry_count + 1)
            elif retry_count == 1 and self.model.startswith("gpt-5"):
                # Second retry: Fall back to GPT-4o-mini for reliability
                print(f"JSON error persists with {self.model}, falling back to gpt-4o-mini...")
                original_model = self.model
                self.model = "gpt-4o-mini"
                result = self._make_openai_request(prompt, context, retry_count + 1)
                self.model = original_model  # Restore original model
                return result

            return {"qualified": False, "reason": "JSON parse error", "summary": "Invalid response format", "evidence": None}
    
    def _check_now(self, context: str) -> SectionResult:
        """Check for current state and immediate hiring needs"""
        prompt = """
        Analyze this meeting transcript for the CLIENT company's CURRENT STATE and IMMEDIATE talent needs.
        ONLY analyze "Them:" speakers (the client). IGNORE all "Me:" speakers (Unknown representative).

        What to look for (aligned with UNKNOWN Access products):
        1. Current company scale (revenue, headcount, team structure)
        2. Immediate hiring needs - especially for roles that "change where they're going"
        3. Need for flexible talent model without compromising on quality (The Bench)
        4. TA team struggling to access right talent (The Partnership)
        5. Critical roles blocking growth or transformation

        Examples of NOW signals for UNKNOWN Access:
        - "We need someone who can change our trajectory, not just fill a role"
        - "Our TA team can't find the caliber of people we need"
        - "Need exceptional freelance talent on tap"
        - "Looking for people we didn't even know existed"
        - "Critical senior hire blocking our next phase"

        Return JSON with exactly these fields:
        {
            "qualified": true or false,
            "reason": "short explanation linking to UNKNOWN Access products if relevant",
            "summary": "1-3 sentences about the CLIENT's current talent situation",
            "evidence": "verbatim quote from 'Them:' speakers only, NEVER from 'Me:' speakers"
        }
        """

        result = self._make_openai_request(prompt, context)
        validated_result = self._validate_section_response(result, prompt, context)

        return SectionResult(
            qualified=validated_result.get("qualified", False),
            reason=validated_result.get("reason", "No reason provided"),
            summary=validated_result.get("summary", "Not stated."),
            evidence=validated_result.get("evidence")
        )
    
    def _check_next(self, context: str) -> SectionResult:
        """Check for future growth plans and vision"""
        prompt = """
        Analyze this meeting transcript for the CLIENT company's FUTURE VISION and transformation needs.
        ONLY analyze "Them:" speakers (the client). IGNORE all "Me:" speakers (Unknown representative).

        What to look for (aligned with UNKNOWN Transform & Ventures):
        1. Vision of becoming something new (Transform: "what you're becoming")
        2. Need to work ON the business model, not just IN the business
        3. Plans for M&A, partnerships, or exits (Ventures)
        4. Desire to build talent strategy for creative capital growth
        5. Expansion plans requiring new operating models

        Examples of NEXT signals for UNKNOWN Transform/Ventures:
        - "We know what we want to become but not how to get there"
        - "Need to redesign our org for where we're going"
        - "Looking at acquisitions but unsure about valuation"
        - "Want to build conditions for creativity to thrive"
        - "Exploring partnerships to accelerate growth"
        - "Need outside perspective on our talent strategy"
        - "75% of acquisitions fail - we can't afford that"

        Return JSON with exactly these fields:
        {
            "qualified": true or false,
            "reason": "short explanation linking to Transform/Ventures products if relevant",
            "summary": "1-3 sentences about the CLIENT's transformation journey",
            "evidence": "verbatim quote from 'Them:' speakers only, NEVER from 'Me:' speakers"
        }
        """

        result = self._make_openai_request(prompt, context)
        validated_result = self._validate_section_response(result, prompt, context)

        return SectionResult(
            qualified=validated_result.get("qualified", False),
            reason=validated_result.get("reason", "No reason provided"),
            summary=validated_result.get("summary", "Not stated."),
            evidence=validated_result.get("evidence")
        )
    
    def _check_measure(self, context: str) -> SectionResult:
        """Check for success metrics and measurement approach"""
        prompt = """
        Analyze how this CLIENT company measures SUCCESS.
        ONLY analyze "Them:" speakers (the client). IGNORE all "Me:" speakers (Unknown representative).

        What to look for:
        1. Financial: revenue/ARR, margin %, topline targets
        2. Adoption/NPS: usage, adoption, NPS/eNPS
        3. Operational: time-to-hire, cycle time, churn, retention
        4. Timeframes: any target dates (SMART if present)

        Return JSON with exactly these fields:
        {
            "qualified": true or false,
            "reason": "short explanation for decision",
            "summary": "1-3 sentences about the CLIENT (Them: speakers only)",
            "evidence": "verbatim quote from 'Them:' speakers only, NEVER from 'Me:' speakers"
        }
        """

        result = self._make_openai_request(prompt, context)
        validated_result = self._validate_section_response(result, prompt, context)

        return SectionResult(
            qualified=validated_result.get("qualified", False),
            reason=validated_result.get("reason", "No reason provided"),
            summary=validated_result.get("summary", "Not stated."),
            evidence=validated_result.get("evidence")
        )
    
    def _check_blocker(self, context: str) -> SectionResult:
        """Check for blockers preventing growth"""
        prompt = """
        Identify the CLIENT company's biggest BLOCKERS that UNKNOWN can solve.
        ONLY analyze "Them:" speakers (the client). IGNORE all "Me:" speakers (Unknown representative).

        Blockers aligned with UNKNOWN solutions:
        1. ACCESS BLOCKERS:
           - "Can't access talent we didn't know existed"
           - "TA team lacks specialist support to find right people"
           - "Need game-changing hires, not just role-fillers"
           - "Talent compromises due to flexibility needs"

        2. TRANSFORM BLOCKERS:
           - "Working IN the business, can't work ON the business"
           - "Don't know how to build for what we're becoming"
           - "Lack talent strategy for creative capital growth"
           - "No clear blueprint from current state to future state"

        3. VENTURES BLOCKERS:
           - "Don't know how to value creative capital"
           - "Fear of being in the 75% of failed acquisitions"
           - "Need connections but don't want cattle-mart feeling"
           - "Unsure of our worth to potential partners"

        Return JSON with exactly these fields:
        {
            "qualified": true or false,
            "reason": "explain which UNKNOWN products could solve their blockers",
            "summary": "1-3 sentences about blockers UNKNOWN can address",
            "evidence": "verbatim quote from 'Them:' speakers only, NEVER from 'Me:' speakers"
        }
        """

        result = self._make_openai_request(prompt, context)
        validated_result = self._validate_section_response(result, prompt, context)

        return SectionResult(
            qualified=validated_result.get("qualified", False),
            reason=validated_result.get("reason", "No reason provided"),
            summary=validated_result.get("summary", "Not stated."),
            evidence=validated_result.get("evidence")
        )
    
    def _tag_taxonomy(self, context: str) -> Dict[str, Any]:
        """Tag meeting with client's controlled taxonomy vocabularies"""
        challenges_list = "\n".join(f"- {c}" for c in self.TAXONOMY_CHALLENGES)
        results_list = "\n".join(f"- {r}" for r in self.TAXONOMY_RESULTS)
        offerings_list = "\n".join(f"- {o}" for o in self.TAXONOMY_OFFERINGS)

        prompt = f"""
        Tag this meeting transcript using ONLY the predefined taxonomy labels below.
        ONLY analyze "Them:" speakers (the client). IGNORE "Me:" speakers (Unknown representative).

        CHALLENGES (select 0-5 most relevant):
{challenges_list}

        RESULTS (select 0-5 most relevant):
{results_list}

        OFFERINGS (select exactly 1 primary or null):
{offerings_list}

        Instructions:
        1. Only return labels that EXACTLY match the lists above (case-sensitive)
        2. For challenges: identify client's current pain points
        3. For results: identify desired outcomes they're seeking
        4. For offerings: identify their primary business type/sector
        5. Return null for offering if none clearly fit

        Return STRICT JSON:
        {{
            "challenges": ["label1", "label2"],  // 0-5 labels from CHALLENGES list only
            "results": ["label1", "label2"],     // 0-5 labels from RESULTS list only
            "offering": "label or null"          // exactly 1 label from OFFERINGS or null
        }}
        """

        try:
            result = self._make_openai_request(prompt, context)

            # Validate and filter to ensure only valid taxonomy labels
            validated = {
                "challenges": [],
                "results": [],
                "offering": None
            }

            # Validate challenges
            if "challenges" in result and isinstance(result["challenges"], list):
                validated["challenges"] = [
                    c for c in result["challenges"]
                    if c in self.TAXONOMY_CHALLENGES
                ][:5]  # Max 5

            # Validate results
            if "results" in result and isinstance(result["results"], list):
                validated["results"] = [
                    r for r in result["results"]
                    if r in self.TAXONOMY_RESULTS
                ][:5]  # Max 5

            # Validate offering (single value)
            if "offering" in result and result["offering"] in self.TAXONOMY_OFFERINGS:
                validated["offering"] = result["offering"]

            return validated

        except Exception as e:
            print(f"Error in taxonomy tagging: {e}")
            return {
                "challenges": [],
                "results": [],
                "offering": None
            }

    def _check_fit(self, context: str) -> FitResult:
        """Check which UNKNOWN services match the company's needs"""
        prompt = """
        Classify this CLIENT company's needs into UNKNOWN's 3 product categories.
        ONLY analyze "Them:" speakers (the client). IGNORE all "Me:" speakers (Unknown representative).

        ACCESS (When you need the right people to deliver):
        - The Search: Need someone to change trajectory, not just fill a role
        - The Bench: Need exceptional freelance talent without compromising quality
        - The Partnership: TA team needs specialist support to access right talent
        Look for: "People we didn't know existed", "change where we're going", "on tap talent"

        TRANSFORM (When you need the right strategy to become more):
        - Transform Workshop: Know what to become but not how to get there
        - Shape of You: Need to change but can't put finger on what
        - Partnership+: Have transformation goals but lack skills to deliver
        Look for: "Work ON not IN business", "talent success model", "creative capital"

        VENTURES (When you need the right partnerships for step-change):
        - Fake or Fortune (Buy): M&A deal completion and valuation
        - The Closer (Buy): Finding acquisition targets that fit
        - The Intro (Sell): Finding partners who truly get your value
        Look for: "Value creative capital", "75% acquisitions fail", "exit planning"

        Return STRICT JSON with exactly these fields:
        {
            "qualified": true or false,
            "reason": "explain which specific UNKNOWN products match their needs",
            "summary": "1–3 sentences mapping needs to UNKNOWN products",
            "services": ["Access","Transform","Ventures"],   // choose 1–3; Title Case
            "evidence": "verbatim <= 25 words from 'Them:' speakers only"
        }
        """

        result = self._make_openai_request(prompt, context)
        validated_result = self._validate_fit_response(result, prompt, context)

        return FitResult(
            qualified=validated_result.get("qualified", False),
            reason=validated_result.get("reason", "No reason provided"),
            summary=validated_result.get("summary", "Not stated."),
            services=validated_result.get("services", []),
            evidence=validated_result.get("evidence")
        )

    # =========================================================================
    # SALESPERSON ASSESSMENT METHODS
    # =========================================================================

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

    def _format_transcript_for_sales(self, transcript: Transcript) -> str:
        """
        Format transcript for sales assessment, emphasizing "Me:" speaker analysis.
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

        # Prioritize full transcript for sales assessment (need to see conversation flow)
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

    def _check_sales_introduction(self, context: str) -> Dict[str, Any]:
        """Assess introduction and framing"""
        prompt = """
        Assess how well the UNKNOWN representative introduced themselves and framed the meeting.
        ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

        What to look for:
        1. Did they introduce themselves and UNKNOWN succinctly?
        2. Did they frame the purpose of the meeting?
        3. Did they set an agenda (discovery → solutions → next steps)?
        4. Did they ask permission to ask probing/challenging questions?

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
            "evidence": "verbatim quote from 'Me:' speakers, or null",
            "coaching_note": "specific suggestion to improve, or null if score is 3"
        }
        """
        result = self._make_openai_request(prompt, context)
        return self._validate_sales_assessment_response(result, prompt, context)

    def _check_sales_discovery(self, context: str) -> Dict[str, Any]:
        """Assess discovery of problems and pain"""
        prompt = """
        Assess how well the UNKNOWN representative uncovered the client's problems and pain points.
        ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

        What to look for:
        1. Did they uncover high-level business challenges?
        2. Did they identify specific talent/hiring challenges?
        3. Did they explore impact of challenges?
        4. Did they identify emotional drivers?
        5. Did they ask what they've tried before?
        6. Did they ask layered, high-quality questions?

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
            "evidence": "verbatim quote from 'Me:' speakers, or null",
            "coaching_note": "specific suggestion to improve discovery, or null if score is 3"
        }
        """
        result = self._make_openai_request(prompt, context)
        return self._validate_sales_assessment_response(result, prompt, context)

    def _check_sales_scoping(self, context: str) -> Dict[str, Any]:
        """Assess opportunity scoping and qualification"""
        prompt = """
        Assess how well the UNKNOWN representative scoped and qualified the opportunity.
        ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

        What to look for:
        1. Did they discuss budgets?
        2. Did they ask about hiring volumes?
        3. Did they understand current hiring process?
        4. Did they identify stakeholders?
        5. Did they understand buying process and timeline?

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
            "evidence": "verbatim quote from 'Me:' speakers, or null",
            "coaching_note": "specific suggestion to improve scoping, or null if score is 3"
        }
        """
        result = self._make_openai_request(prompt, context)
        return self._validate_sales_assessment_response(result, prompt, context)

    def _check_sales_solution(self, context: str) -> Dict[str, Any]:
        """Assess solution positioning"""
        prompt = """
        Assess how well the UNKNOWN representative positioned UNKNOWN's solution.
        ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

        What to look for:
        1. Did they match client problems to UNKNOWN products (Partnership, Bench, Search, Ventures)?
        2. Did they use business outcomes, not just features?
        3. Did they position UNKNOWN as advisors vs. just recruiters?
        4. Did they tailor positioning to the client's specific situation?

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
            "evidence": "verbatim quote from 'Me:' speakers, or null",
            "coaching_note": "specific suggestion to improve positioning, or null if score is 3"
        }
        """
        result = self._make_openai_request(prompt, context)
        return self._validate_sales_assessment_response(result, prompt, context)

    def _check_sales_commercial(self, context: str) -> Dict[str, Any]:
        """Assess commercial confidence"""
        prompt = """
        Assess how confidently the UNKNOWN representative discussed commercials and fees.
        ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

        What to look for:
        1. Did they mention fees or commercial terms (not apologetically)?
        2. Did they explain the value behind the fees?
        3. Did they discuss payment structure?
        4. Did they check budget alignment before promising a proposal?

        Scoring guide:
        - 0: No commercial discussion or avoided the topic
        - 1: Mentioned fees but apologetically or vaguely
        - 2: Clear fee discussion with some value articulation
        - 3: Confident commercial discussion with value justification and budget alignment

        Return JSON with exactly these fields:
        {
            "qualified": true if score >= 2,
            "score": 0-3 integer,
            "reason": "short explanation for the score",
            "evidence": "verbatim quote from 'Me:' speakers, or null",
            "coaching_note": "specific suggestion to improve commercial confidence, or null if score is 3"
        }
        """
        result = self._make_openai_request(prompt, context)
        return self._validate_sales_assessment_response(result, prompt, context)

    def _check_sales_case_studies(self, context: str) -> Dict[str, Any]:
        """Assess use of case studies and proof points"""
        prompt = """
        Assess whether the UNKNOWN representative shared relevant case studies or proof points.
        ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

        What to look for:
        1. Did they share specific case studies or client examples?
        2. Were the examples relevant to the client's situation?
        3. Did they include specific outcomes or results?
        4. Did they use stories to build credibility?

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
            "evidence": "verbatim quote from 'Me:' speakers, or null",
            "coaching_note": "specific suggestion to improve use of proof points, or null if score is 3"
        }
        """
        result = self._make_openai_request(prompt, context)
        return self._validate_sales_assessment_response(result, prompt, context)

    def _check_sales_next_steps(self, context: str) -> Dict[str, Any]:
        """Assess next steps and stakeholder mapping"""
        prompt = """
        Assess how well the UNKNOWN representative closed the meeting and agreed next steps.
        ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

        What to look for:
        1. Did they summarize what they heard?
        2. Did they agree a specific next step with a date/time?
        3. Did they identify decision-makers and influencers?
        4. Did they confirm the buying process?
        5. Did they create momentum rather than leaving things open-ended?

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
            "evidence": "verbatim quote from 'Me:' speakers, or null",
            "coaching_note": "specific suggestion to improve closing, or null if score is 3"
        }
        """
        result = self._make_openai_request(prompt, context)
        return self._validate_sales_assessment_response(result, prompt, context)

    def _check_sales_strategic_context(self, context: str) -> Dict[str, Any]:
        """Assess strategic context gathering"""
        prompt = """
        Assess how well the UNKNOWN representative gathered strategic context about the client's business.
        ONLY analyze "Me:" speakers (the UNKNOWN rep). IGNORE all "Them:" speakers (the client).

        What to look for:
        1. Did they ask where the business is going?
        2. Did they understand org design challenges or market conditions?
        3. Did they identify talent bottlenecks blocking growth?
        4. Did they ask what success looks like in 12 months?
        5. Did they spot cross-sell opportunities naturally?

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
            "evidence": "verbatim quote from 'Me:' speakers, or null",
            "coaching_note": "specific suggestion to improve strategic questioning, or null if score is 3"
        }
        """
        result = self._make_openai_request(prompt, context)
        return self._validate_sales_assessment_response(result, prompt, context)

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

    def score_salesperson(self, transcript: Transcript) -> SalesScoreResult:
        """
        Score a transcript for salesperson capability assessment.

        Returns a SalesScoreResult with all 8 assessment criteria.
        """
        from datetime import datetime, timezone

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

        return SalesScoreResult(
            meeting_id=transcript.meeting_id,
            salesperson_name=transcript.creator_name,
            salesperson_email=transcript.creator_email,
            date=transcript.date,
            client=client_info.client,
            total_score=total_score,
            total_qualified=total_qualified,
            introduction=SalesAssessmentResult(**introduction),
            discovery=SalesAssessmentResult(**discovery),
            scoping=SalesAssessmentResult(**scoping),
            solution=SalesAssessmentResult(**solution),
            commercial=SalesAssessmentResult(**commercial),
            case_studies=SalesAssessmentResult(**case_studies),
            next_steps=SalesAssessmentResult(**next_steps),
            strategic_context=SalesAssessmentResult(**strategic_context),
            strengths=coaching_summary["strengths"],
            improvements=coaching_summary["improvements"],
            overall_coaching=coaching_summary["overall_coaching"],
            scored_at=datetime.now(timezone.utc),
            llm_model=self.model
        )
    
    def score_transcript_new(self, transcript: Transcript) -> NewScoreResult:
        """Score a transcript using new JSON blob format"""
        from datetime import datetime, timezone

        context = self._format_transcript(transcript)

        # Extract client information first
        client_info = self._extract_client_info(transcript)

        # Run all scoring checks
        now_result = self._check_now(context)
        next_result = self._check_next(context)
        measure_result = self._check_measure(context)
        blocker_result = self._check_blocker(context)
        fit_result = self._check_fit(context)

        # Tag with client taxonomy
        taxonomy_tags = self._tag_taxonomy(context)

        # Calculate total qualified sections
        total_qualified_sections = (
            int(now_result.qualified) +
            int(next_result.qualified) +
            int(measure_result.qualified) +
            int(blocker_result.qualified) +
            int(fit_result.qualified)
        )

        return NewScoreResult(
            meeting_id=transcript.meeting_id,
            client_info=client_info,
            date=transcript.date,
            total_qualified_sections=total_qualified_sections,
            now=now_result,
            next=next_result,
            measure=measure_result,
            blocker=blocker_result,
            fit=fit_result,
            challenges=taxonomy_tags.get("challenges", []),
            results=taxonomy_tags.get("results", []),
            offering=taxonomy_tags.get("offering"),
            scored_at=datetime.now(timezone.utc),
            llm_model=self.model
        )

    def score_transcript(self, transcript: Transcript) -> ScoreResult:
        """Score a transcript using LLM analysis (legacy format)"""
        context = self._format_transcript(transcript)

        # Run all scoring checks
        now_result = self._check_now(context)
        next_result = self._check_next(context)
        measure_result = self._check_measure(context)
        blocker_result = self._check_blocker(context)
        fit_result = self._check_fit(context)

        # Calculate total score (legacy format compatibility)
        total_score = (
            int(now_result.qualified) +
            int(next_result.qualified) +
            int(measure_result.qualified) +
            int(blocker_result.qualified) +
            int(fit_result.qualified)
        )

        return ScoreResult(
            meeting_id=transcript.meeting_id,
            company=transcript.company,
            date=transcript.date,
            total_qualified_sections=total_score,
            checks={
                "now": {
                    "score": int(now_result.qualified),
                    "evidence_line": now_result.evidence,
                    "timestamp": None
                },
                "next": {
                    "score": int(next_result.qualified),
                    "evidence_line": next_result.evidence,
                    "timestamp": None
                },
                "measure": {
                    "score": int(measure_result.qualified),
                    "evidence_line": measure_result.evidence,
                    "timestamp": None
                },
                "blocker": {
                    "score": int(blocker_result.qualified),
                    "evidence_line": blocker_result.evidence,
                    "timestamp": None
                },
                "fit": {
                    "score": int(fit_result.qualified),
                    "fit_labels": fit_result.services,
                    "evidence_line": fit_result.evidence,
                    "timestamp": None
                }
            }
        )