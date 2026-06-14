"""Human-in-the-loop confirmation node.

The graph is compiled with interrupt_before=["hil_confirmation"].
This means execution pauses before this node runs and the current state
(including pending_action) is returned to the caller.

On the next /chat call, the user's response is injected into state as
hil_decision and the graph resumes from this node.
"""

from langchain_core.messages import AIMessage

from app.agents.state import GraphState


async def hil_node(state: GraphState) -> dict:
    """Passthrough node — just acknowledges the decision and passes control back."""
    if state.get("hil_decision") == "cancel":
        return {
            "messages": [AIMessage(content="Cancelled. No changes were made.")],
            "pending_action": None,
            "hil_decision": None,
        }
    # If confirmed, the graph routes back to action_agent_node for execution
    return {}
