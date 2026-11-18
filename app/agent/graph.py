"""LangGraph 工作流编排。"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    classify_node,
    confirm_node,
    rag_node,
    review_node,
    route_node,
    safety_node,
    ticket_node,
    tools_node,
)
from app.agent.state import TicketState


def build_graph(checkpointer=None):
    builder = StateGraph(TicketState)

    builder.add_node("classify", classify_node)
    builder.add_node("safety", safety_node)
    builder.add_node("rag", rag_node)
    builder.add_node("tools", tools_node)
    builder.add_node("ticket", ticket_node)
    builder.add_node("confirm", confirm_node)
    builder.add_node("review", review_node)

    builder.add_edge(START, "classify")
    builder.add_edge("classify", "safety")
    builder.add_conditional_edges(
        "safety",
        route_node,
        {
            "rag": "rag",
            "tools": "tools",
            "ticket": "ticket",
            "confirm": "confirm",
            "review": "review",
        },
    )
    builder.add_edge("rag", "review")
    builder.add_edge("tools", "review")
    builder.add_edge("ticket", "review")
    builder.add_edge("confirm", "review")
    builder.add_edge("review", END)

    return builder.compile(checkpointer=checkpointer)
