"""LLM-based classifier for distinguishing locations from names using Ollama."""

import logging
import json
import os
from typing import Optional, Dict, Any

logger = logging.getLogger("nzz_scraper")


class LLMLocationClassifier:
    """Uses LLM (via Ollama) to classify terms as locations or names."""

    def __init__(
        self,
        model_name: str = "gemma3:270m",
        use_llm: bool = True,
        ollama_base_url: Optional[str] = None,
    ):
        """Initialize the LLM classifier using Ollama.

        Args:
            model_name: Name of the Ollama model to use (default: "gemma3:270m")
                       Can be overridden with OLLAMA_MODEL environment variable
            use_llm: Whether to use LLM (default: True). If False, returns None for all classifications.
            ollama_base_url: Base URL for Ollama API (default: "http://localhost:11434")
                            Can be overridden with OLLAMA_BASE_URL environment variable
        """
        self.use_llm = use_llm
        self.client = None
        self.model_name = model_name or os.getenv("OLLAMA_MODEL", "gemma3:270m")
        self.ollama_base_url = ollama_base_url or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )

        if not use_llm:
            logger.info("LLM classifier disabled")
            return

        try:
            import ollama

            self.client = ollama

            # Test connection and verify model is available
            try:
                # Check if model is available
                models_response = ollama.list()
                # ollama.list() returns a dict with 'models' key containing list of Model objects
                models_list = models_response.get("models", [])
                # Extract model names (Model objects have 'model' attribute, not 'name')
                model_names = []
                for model in models_list:
                    if hasattr(model, "model"):
                        model_names.append(model.model)
                    elif isinstance(model, dict):
                        model_names.append(model.get("model", model.get("name", "")))
                    else:
                        model_names.append(str(model))
                if self.model_name not in model_names:
                    logger.warning(
                        f"Model '{self.model_name}' not found in Ollama. Available models: {model_names}"
                    )
                    logger.warning(
                        f"Please install it with: ollama pull {self.model_name}"
                    )
                    logger.warning("LLM classification will be disabled.")
                    self.use_llm = False
                    return
                logger.info(
                    f"LLM classifier initialized with Ollama model: {self.model_name} (Base URL: {self.ollama_base_url})"
                )
            except Exception as e:
                logger.warning(
                    f"Could not verify Ollama model '{self.model_name}': {str(e)}"
                )
                logger.warning(
                    "Make sure Ollama is running and the model is installed."
                )
                logger.warning("LLM classification will be disabled.")
                self.use_llm = False
        except ImportError:
            logger.warning(
                "ollama library not installed. Install with: pip install ollama"
            )
            logger.warning("LLM classification will be disabled.")
            self.use_llm = False
        except Exception as e:
            logger.error(f"Failed to initialize Ollama client: {str(e)}")
            logger.warning("LLM classification will be disabled.")
            self.use_llm = False

    def classify_term(self, term: str, context: Optional[str] = None) -> Dict[str, Any]:
        """Parse a term and split it into names, locations, and departments.

        Args:
            term: The term to parse (e.g., "Bangkok, Andreas, Babst" or "Daniel Böhm, Tikrit und Mosul")
            context: Optional context (e.g., full author string)

        Returns:
            Dictionary with:
            - 'names': list of person names found
            - 'locations': list of locations found
            - 'departments': list of departments found
        """
        if not self.use_llm or not self.client:
            return {"names": [], "locations": [], "departments": []}

        if not term or len(term.strip()) < 2:
            return {"names": [], "locations": [], "departments": []}

        term_clean = term.strip()

        # Build minimal prompt - avoid example text that might be returned
        prompt = f'Parse: "{term_clean}"\nExtract ONLY names, locations, departments that appear in the input.\nIf format is "Name, Location", split them correctly: name goes to names, location goes to locations.\nFor names with middle initials like "Johannes C. Bockenheimer", keep the full name in names array (middle initial will be parsed separately).\nDo not invent or add anything.\nJSON: {{"names":[],"locations":[],"departments":[]}}'

        try:
            # Generate response using Ollama
            response = self.client.generate(
                model=self.model_name,
                prompt=prompt,
                options={
                    "temperature": 0.1,
                    "num_predict": 100,  # Reduced for speed
                },
                stream=False,
            )

            # Extract text from response
            if hasattr(response, "response"):
                text = response.response.strip()
            elif isinstance(response, dict):
                text = response.get("response", "").strip()
            else:
                text = str(response).strip()

            # Extract JSON
            json_start = text.find("{")
            json_end = text.rfind("}") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = text[json_start:json_end]
                result = json.loads(json_str)

                # Validate and normalize result
                names = result.get("names", [])
                locations = result.get("locations", [])
                departments = result.get("departments", [])

                # Ensure lists and filter empty strings
                return {
                    "names": [
                        n.strip() for n in names if isinstance(n, str) and n.strip()
                    ],
                    "locations": [
                        loc.strip()
                        for loc in locations
                        if isinstance(loc, str) and loc.strip()
                    ],
                    "departments": [
                        d.strip()
                        for d in departments
                        if isinstance(d, str) and d.strip()
                    ],
                }
            else:
                logger.debug(f"Could not extract JSON from LLM response: {text}")
                return {"names": [], "locations": [], "departments": []}

        except json.JSONDecodeError as e:
            logger.debug(f"JSON decode error for term '{term_clean}': {str(e)}")
            return {"names": [], "locations": [], "departments": []}
        except Exception as e:
            logger.debug(f"Error classifying term '{term_clean}': {str(e)}")
            return {"names": [], "locations": [], "departments": []}

    def is_location(
        self, term: str, context: Optional[str] = None, min_confidence: float = 0.6
    ) -> bool:
        """Check if a term contains any locations.

        Args:
            term: Term to check
            context: Optional context
            min_confidence: Ignored (kept for backward compatibility)

        Returns:
            True if term contains at least one location
        """
        result = self.classify_term(term, context)
        return len(result.get("locations", [])) > 0

    def is_name(
        self, term: str, context: Optional[str] = None, min_confidence: float = 0.6
    ) -> bool:
        """Check if a term contains any names.

        Args:
            term: Term to check
            context: Optional context
            min_confidence: Ignored (kept for backward compatibility)

        Returns:
            True if term contains at least one name
        """
        result = self.classify_term(term, context)
        return len(result.get("names", [])) > 0

    def is_department(
        self, term: str, context: Optional[str] = None, min_confidence: float = 0.6
    ) -> bool:
        """Check if a term contains any departments.

        Args:
            term: Term to check
            context: Optional context
            min_confidence: Ignored (kept for backward compatibility)

        Returns:
            True if term contains at least one department
        """
        result = self.classify_term(term, context)
        return len(result.get("departments", [])) > 0
