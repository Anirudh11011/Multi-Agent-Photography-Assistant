
from langchain_chroma import Chroma
from langgraph.graph import StateGraph, MessagesState, START, END

from sentence_transformers import SentenceTransformer
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
vector_store = Chroma(
    collection_name="Multi_agent_collection",
    embedding_function=model.encode,
    persist_directory="./chroma_langchain_db",
)


def mock_llm(state: MessagesState):
    return {"messages": [{"role": "ai", "content": "hello world"}]}

graph = StateGraph(MessagesState)
graph.add_node(mock_llm)
graph.add_edge(START, "mock_llm")
graph.add_edge("mock_llm", END)
graph = graph.compile()

graph.invoke({"messages": [{"role": "user", "content": "hi!"}]})