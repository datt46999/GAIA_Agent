import os 
from dotenv import load_dotenv


from langgraph.graph import START, StateGraph, MessagesState
from langchain_groq import ChatGroq 
from langchain_huggingface import (
    ChatHuggingFace,
    HuggingFaceEndpoint,
    HuggingFaceEmbeddings
)
from langchain_core.messages import SystemMessage, HumanMessage
from langchain.vectorstores import SupabaseVectorStore
from langgraph.prebuilt import ToolNode, tools_condition
from langchain.tools.retriever import create_retriever_tool
from supabase.client import Client, create_client

from tools import TOOL_RESEARCH

load_dotenv()
# load the system prompt from the file
with open("system_prompt.txt", "r", encoding="utf-8") as f:
    system_prompt = f.read()
print(system_prompt)



sys_msg = SystemMessage(content = system_prompt)

# build retriever
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-mpnet-base-v2"
)  #  dim=768

supabase :Client = create_client(
    os.environ.get("SUPABASE_URL"), 
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
)
vector_store = SupabaseVectorStore(
    client = supabase,
    embedding = embeddings,
    table_name="documents2",
    query_name="match_documents_2",
)


create_retriever_tool = create_retriever_tool(
    retriever=vector_store.as_retriever(),
    name="Question Search",
    description="A tool to retrieve similar questions from a vector store.",
)

tools = TOOL_RESEARCH

def build_graph(provider: str = "huggingface"):
    if provider == "groq":
        # Groq https://console.groq.com/docs/models
        llm = ChatGroq(model="qwen/qwen3-32b", temperature=0)
    
    elif provider == "huggingface":
        llm = ChatHuggingFace(
            llm=HuggingFaceEndpoint(
                repo_id = "qwen/qwen3-32b"
            ),
        )
    else:
        raise ValueError("Invalid provider. Choose 'groq' or 'huggingface'.")
    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(tools)
    def assistant(state: MessagesState):
        """ Assistant node"""
        return {"messages": [llm_with_tools.invoke(state["messages"])]}
    def retriever(state: MessagesState):
        similar_question = vector_store.similarity_search(state["messages"][0].content)

        if similar_question:
            example_msg = HumanMessage(
                content = f"Here I provide a similar question and answer for reference: \n\n{similar_question[0].page_content}"
            )
            return {"messages": [sys_msg] + state["messages"] + [example_msg]}
        else:
            # Handle the case when no similar questions are found
            return {"messages": [sys_msg] + state["messages"]}

    """
    START → Retriever → Assistant → Tools → Assistant
                     ↑              ↓
                     └──────────────┘
    """
    # build graph
    builder = StateGraph(MessagesState)
    builder.add_node("retriever", retriever)
    builder.add_node("assistant", assistant)
    builder.add_node("tools", ToolNode(tools))

    builder.add_edge(START, "retriever")
    builder.add_edge("retriever", "assistant")
    builder.add_conditional_edges(
        "assistant",
        tools_condition
    )
    builder.add_edge("tools", "assistant")
    return builder.compile()

# test
if __name__ == "__main__":
    question = "When was a picture of St. Thomas Aquinas first added to the Wikipedia page on the Principle of double effect?"
    graph = build_graph(provider="groq")
    messages = [HumanMessage(content=question)]
    messages = graph.invoke({"messages": messages})
    for m in messages["messages"]:
        m.pretty_print()