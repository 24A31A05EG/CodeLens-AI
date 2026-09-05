EXPLANATION_PROMPT = """
You are an expert software engineer.

Analyze the following source code.

Provide:
1. Purpose of the code
2. Main functions/classes
3. Inputs and outputs
4. Dependencies
5. Important logic
6. Potential issues

Explain it clearly for the requested technical level.

Technical level: {level}

Source code:
{code}
"""


DOCUMENTATION_PROMPT = """
You are a technical documentation expert.

Generate developer documentation for the following source code.

Include:
- Overview
- Functions/classes
- Parameters
- Return values
- Dependencies
- Usage example

Source code:
{code}
"""


ARCHITECTURE_PROMPT = """
Analyze the following project structure.

Identify:
- Major components
- Modules
- Dependencies
- Data flow
- Relationships between components

Generate a valid Mermaid architecture diagram.

Return Mermaid syntax.
"""