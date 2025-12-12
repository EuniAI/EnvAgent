import functools
from typing import Dict

import neo4j
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.graph.knowledge_graph import KnowledgeGraph
from app.lang_graph.states.testsuite_state import TestsuiteState
from app.lang_graph.testsuite_nodes.testsuite_context_extraction_node import TestsuiteContextExtractionNode
from app.lang_graph.testsuite_nodes.testsuite_context_provider_node import TestsuiteContextProviderNode
from app.lang_graph.testsuite_nodes.testsuite_context_query_message_node import TestsuiteContextQueryMessageNode
from app.lang_graph.testsuite_nodes.testsuite_context_refine_node import TestsuiteContextRefineNode
from app.lang_graph.testsuite_nodes.testsuite_classify_node import TestsuiteClassifyNode
from app.lang_graph.testsuite_nodes.testsuite_sequence_node import TestsuiteSequenceNode
from app.lang_graph.testsuite_nodes.testsuite_cicd_workflow_node import TestsuiteCICDWorkflowNode


class TestsuiteSubgraph:
    """
    A LangGraph-based subgraph for retrieving relevant contextual information
    (e.g., code, documentation, definitions) from a knowledge graph based on a query.

    This subgraph performs an iterative retrieval process:
    1. Constructs a context query message from the user prompt
    2. Uses tool-based retrieval (Neo4j-backed) to gather candidate context snippets
    3. Selects relevant context with LLM assistance
    4. Optionally refines the query and retries if necessary
    5. Outputs the final selected context

    Nodes:
        - ContextQueryMessageNode: Converts user query to internal query prompt
        - ContextProviderNode: Queries knowledge graph using structured tools
        - ToolNode: Dynamically invokes retrieval tools based on tool condition
        - ContextSelectionNode: Uses LLM to select useful context snippets
        - ResetMessagesNode: Clears previous context messages
        - ContextRefineNode: Decides whether to refine the query and retry
    """

    def __init__(
        self,
        model: BaseChatModel,
        test_mode: str,
        kg: KnowledgeGraph,
        local_path: str,
        neo4j_driver: neo4j.Driver,
        max_token_per_neo4j_result: int,
    ):
        """
        Initializes the context retrieval subgraph.

        Args:
            model (BaseChatModel): The LLM used for context selection and refinement.
            local_path (str): Local path to the codebase for context extraction.
            neo4j_driver (neo4j.Driver): Driver for executing Cypher queries in Neo4j.
            max_token_per_neo4j_result (int): Token limit for responses from graph tools.
        """

        self.test_mode = test_mode
        self.local_path = local_path

        if self.test_mode == "CI/CD":
            # CI/CD mode: Find and read workflow files from .github/workflows
            testsuite_cicd_workflow_node = TestsuiteCICDWorkflowNode(local_path)

            # Construct a simple workflow for CI/CD mode
            workflow = StateGraph(TestsuiteState)

            # Add the workflow node
            workflow.add_node("testsuite_cicd_workflow_node", testsuite_cicd_workflow_node)

            # Set the entry point
            workflow.set_entry_point("testsuite_cicd_workflow_node")

            # End after workflow discovery
            workflow.add_edge("testsuite_cicd_workflow_node", END)

            # Compile and store the subgraph
            self.subgraph = workflow.compile()

        else:  # generation 模式下
            # Step 1: Generate an initial query from the user's input
            testsuite_context_query_message_node = TestsuiteContextQueryMessageNode()

            # Step 2: Provide candidate context snippets using knowledge graph tools
            testsuite_context_provider_node = TestsuiteContextProviderNode(
                model, kg, neo4j_driver, max_token_per_neo4j_result
            )

            # Step 3: Add tool node to handle tool-based retrieval invocation dynamically
            # The tool message will be added to the end of the context provider messages
            testsuite_context_provider_tools = ToolNode(
                tools=testsuite_context_provider_node.tools,
                name="context_provider_tools",
                messages_key="testsuite_context_provider_messages",
            )

            # Step 4: Extract the Context
            testsuite_context_extraction_node = TestsuiteContextExtractionNode(model, local_path)

            # Step 5: Reset tool messages to prepare for the next iteration (if needed)
            # reset_testsuite_context_provider_messages_node = ResetMessagesNode("testsuite_context_provider_messages")

            # Step 6: Refine the query if needed and loop back
            testsuite_context_refine_node = TestsuiteContextRefineNode(model, kg)

            testsuite_classify_node = TestsuiteClassifyNode(model)
            testsuite_sequence_node = TestsuiteSequenceNode(model)

            # Construct the LangGraph workflow
            workflow = StateGraph(TestsuiteState)

            # Add all nodes to the graph
            workflow.add_node(
                "testsuite_context_query_message_node", testsuite_context_query_message_node
            )
            workflow.add_node("testsuite_context_provider_node", testsuite_context_provider_node)
            workflow.add_node("testsuite_context_provider_tools", testsuite_context_provider_tools)
            workflow.add_node("testsuite_context_extraction_node", testsuite_context_extraction_node)
            workflow.add_node("testsuite_classify_node", testsuite_classify_node)
            workflow.add_node("testsuite_context_refine_node", testsuite_context_refine_node)
            workflow.add_node("testsuite_sequence_node", testsuite_sequence_node)

            # Set the entry point for the workflow
            workflow.set_entry_point("testsuite_context_query_message_node")
            # Define edges between nodes
            workflow.add_edge("testsuite_context_query_message_node", "testsuite_context_provider_node")

            # Conditional: Use tool node if tools_condition is satisfied
            workflow.add_conditional_edges(
                "testsuite_context_provider_node",
                functools.partial(tools_condition, messages_key="testsuite_context_provider_messages"),
                {"tools": "testsuite_context_provider_tools", END: "testsuite_context_extraction_node"},
            )
            workflow.add_edge("testsuite_context_provider_tools", "testsuite_context_provider_node")
            workflow.add_edge("testsuite_context_extraction_node", "testsuite_classify_node")
            workflow.add_edge("testsuite_classify_node", "testsuite_context_refine_node")

            # If refined_query is non-empty AND no command found yet, loop back to provider; else terminate
            workflow.add_conditional_edges(
                "testsuite_context_refine_node",
                lambda state: bool(state["testsuite_refined_query"])
                and not bool(state.get("testsuite_command", "")),
                {True: "testsuite_context_provider_node", False: testsuite_sequence_node},
            )

            workflow.add_edge("testsuite_sequence_node", END)

            # Compile and store the subgraph
            self.subgraph = workflow.compile()

    def invoke(self, max_refined_query_loop: int) -> Dict[str, str]:
        """
        Executes the context retrieval subgraph given an initial query.

        Args:
            max_refined_query_loop (int): Maximum number of times the system can refine and retry the query.

        Returns:
            Dict with a single key:
                - "context" (Sequence[Context]): A list of selected context snippets relevant to the query.
        """
        # Set the recursion limit based on the maximum number of refined query loops
        config = {"recursion_limit": max_refined_query_loop * 40}

        input_state = {
            "testsuite_max_refined_query_loop": max_refined_query_loop,
        }

        output_state = self.subgraph.invoke(input_state, config)

        return output_state
