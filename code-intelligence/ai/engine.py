from .prompts import (
    EXPLANATION_PROMPT,
    DOCUMENTATION_PROMPT,
    ARCHITECTURE_PROMPT,
)


class AIEngine:

    def explain(self, code: str, level: str = "developer"):
        prompt = EXPLANATION_PROMPT.format(
            level=level,
            code=code
        )

        return {
            "prompt": prompt,
            "status": "ready"
        }

    def generate_documentation(self, code: str):
        prompt = DOCUMENTATION_PROMPT.format(code=code)

        return {
            "prompt": prompt,
            "status": "ready"
        }

    def generate_architecture(self, project_structure: str):
        prompt = ARCHITECTURE_PROMPT.format(
            project_structure=project_structure
        )

        return {
            "prompt": prompt,
            "status": "ready"
        }