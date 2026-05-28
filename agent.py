"""
Compatibility facade for agent functions.

Core implementations now live in the agents/ package:
- agents/langgraph.py
- agents/crew.py
- agents/prompts.py
- agents/service.py
"""

from agents.service import (
    ASSISTANT_INITIALS,
    ASSISTANT_NAME,
    chat,
    create_session,
    get_session,
    list_frameworks,
    list_integrations,
)
