from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

import os
from dotenv import load_dotenv

load_dotenv()
groq_api_key = os.getenv("GROQ_API_KEY")

# Initialize embeddings with HuggingFace
embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

# Initialize Chroma vector store
vector_store = Chroma(
    collection_name="multi_agent_collection",
    embedding_function=embeddings,
    persist_directory="./chroma_langchain_db",
)


# Initialize Groq
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=groq_api_key
)


class AgentState(TypedDict):
    user_input: str
    context: str
    analysis_1: str
    analysis_2: str
    final_response: str


def supervisor_agent(state: AgentState) -> AgentState:
    """Supervisor retrieves related documents, then stores the user input"""
    docs = vector_store.similarity_search(
        state["user_input"],
        k=4,
        filter={"type": "ingested_document"}
    )
    state["context"] = "\n\n".join(d.page_content for d in docs)

    vector_store.add_texts(
        texts=[state["user_input"]],
        metadatas=[{"type": "user_input"}]
    )
    return state


def agent_1(state: AgentState) -> AgentState:
    """Agent 1 performs analysis"""
    prompt = f"You are a helpful Cameramen assistant. When asked to analyze something, analyze scenic nature so that another agent could write a proper camera settings for it.\n\nReference documents:\n{state['context']}\n\nAnalyze this: {state['user_input']}"
    response = llm.invoke([HumanMessage(content=prompt)])
    state["analysis_1"] = response.content

    # Store in vector store
    vector_store.add_texts(
        texts=[response.content],
        metadatas=[{"type": "agent1_analysis"}]
    )
    return state


def agent_2(state: AgentState) -> AgentState:
    """Agent 2 performs analysis"""
    prompt = f"You are a helpful assistant. Provide detailed camera settings of that camera model using the information you got from agent 1.\n\nReference documents:\n{state['context']}\n\nAgent 1 analysis:\n{state['analysis_1']}\n\nGive the settings for: {state['user_input']}"
    response = llm.invoke([HumanMessage(content=prompt)])
    state["analysis_2"] = response.content

    # Store in vector store
    vector_store.add_texts(
        texts=[response.content],
        metadatas=[{"type": "agent2_analysis"}]
    )
    return state


def response_generator(state: AgentState) -> AgentState:
    """Generate final response"""
    prompt = f"""Based on these analyses, generate a response:

Analysis 1: {state["analysis_1"]}
Analysis 2: {state["analysis_2"]}

Provide a final answer."""

    response = llm.invoke([HumanMessage(content=prompt)])
    state["final_response"] = response.content
    return state


# Build graph
graph_builder = StateGraph(AgentState)
graph_builder.add_node("supervisor", supervisor_agent)
graph_builder.add_node("agent_1", agent_1)
graph_builder.add_node("agent_2", agent_2)
graph_builder.add_node("response_generator", response_generator)

# Add edges
graph_builder.add_edge(START, "supervisor")
graph_builder.add_edge("supervisor", "agent_1")
graph_builder.add_edge("agent_1", "agent_2")
graph_builder.add_edge("agent_2", "response_generator")
graph_builder.add_edge("response_generator", END)

# Compile
graph = graph_builder.compile()


def chat(user_input: str) -> str:
    """Run the chatbot"""
    initial_state = {
        "user_input": user_input,
        "context": "",
        "analysis_1": "",
        "analysis_2": "",
        "final_response": ""
    }
    result = graph.invoke(initial_state)
    return result["final_response"]


# Main loop
if __name__ == "__main__":
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == "exit":
            break
        response = chat(user_input)
        print(f"Bot: {response}\n")
