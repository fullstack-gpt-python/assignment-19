import streamlit as st
from langchain.utilities.duckduckgo_search import DuckDuckGoSearchAPIWrapper
import json
from langchain.document_loaders import WebBaseLoader
from langchain.tools import DuckDuckGoSearchResults
from langchain.tools import WikipediaQueryRun
from openai import OpenAI
from datetime import datetime, timedelta, timezone


def get_assistant():
    if "assistant" in st.session_state:
        return st.session_state["assistant"]

    functions = [
        {
            "type": "function",
            "function": {
                "name": "get_ddg_results",
                "description": "Use this tool to perform web searches using the DuckDuckGo search engine. It takes a query as an argument.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The query you will search for",
                        }
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_wiki_results",
                "description": "Use this tool to perform searches on Wikipedia.It takes a query as an argument.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The query you will search for",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_web_content",
                "description": "If you found the website link in DuckDuckGo, Use this to get the content of the link for my research.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL of the website you want to scrape",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
    ]

    assistant = client.beta.assistants.create(
        name="Research Assistant",
        instructions="""
        You are a research expert.

        Your task is to use Wikipedia or DuckDuckGo to gather comprehensive and accurate information about the query provided. 

        When you find a relevant website through DuckDuckGo, you must scrape the content from that website. Use this scraped content to thoroughly research and formulate a detailed answer to the question. 

        Combine information from Wikipedia, DuckDuckGo searches, and any relevant websites you find. Ensure that the final answer is well-organized and detailed, and include citations with links (URLs) for all sources used.

        Your research should be saved to a .txt file, and the content should match the detailed findings provided. Make sure to include all sources and relevant information.

        The information from Wikipedia must be included.
        """,
        model="gpt-4o-mini",
        tools=functions,
    )

    st.session_state["assistant"] = assistant

    return st.session_state["assistant"]


def get_ddg_results(inputs):
    query = inputs["query"]
    search = DuckDuckGoSearchResults()
    return search.run(query)


def get_wiki_results(inputs):
    query = inputs["query"]
    wrapper = DuckDuckGoSearchAPIWrapper(max_results=3)
    wiki = WikipediaQueryRun(api_wrapper=wrapper)
    return wiki.run(query)


def get_web_content(inputs):
    url = inputs["url"]
    try:
        loader = WebBaseLoader([url])
        docs = loader.load()
        text = "\n\n".join([doc.page_content for doc in docs])
        return text
    except:
        print("ERROR on get_web_content")
        return f"Error getting content from {url}. You need to try again or use another url."


functions_map = {
    "get_ddg_results": get_ddg_results,
    "get_web_content": get_web_content,
    "get_wiki_results": get_wiki_results,
}


def get_thread_id():
    if "thread_id" not in st.session_state:

        thread = client.beta.threads.create(
            messages=[
                {
                    "role": "assistant",
                    "content": "Hi, How can I help you?",
                }
            ]
        )
        st.session_state["thread_id"] = thread.id
    return st.session_state["thread_id"]


def get_run(run_id, thread_id):

    return client.beta.threads.runs.retrieve(
        run_id=run_id,
        thread_id=thread_id,
    )


def start_run(thread_id, assistant_id, content):
    if "run" not in st.session_state or get_run(
        st.session_state["run"].id, get_thread_id()
    ).status in (
        "expired",
        "completed",
    ):

        client.beta.threads.messages.create(
            thread_id=thread_id, role="user", content=content
        )

        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread_id,
            assistant_id=assistant_id,
        )

        st.session_state["run"] = run
    else:
        print("already running")

    run = st.session_state["run"]

    with st.status("Processing..."):
        while get_run(run.id, get_thread_id()).status == "requires_action":
            submit_tool_outputs(run.id, get_thread_id())

    print(f"done, {get_run(run.id, get_thread_id()).status}")
    final_message = get_messages(get_thread_id())[-1]
    if get_run(run.id, get_thread_id()).status == "completed":
        with st.chat_message(final_message.role):
            st.markdown(final_message.content[0].text.value)

        paint_download_btn(
            final_message.content[0].text.value, createdAt=final_message.created_at
        )
        print(final_message)
    elif get_run(run.id, get_thread_id()).status == "failed":
        with st.chat_message("assistant"):
            st.markdown("Sorry. I failed researching. Try Again later :()")


def get_messages(thread_id):
    messages = list(
        client.beta.threads.messages.list(
            thread_id=thread_id,
        )
    )
    return list(reversed(messages))


def get_tool_outputs(run_id, thread_id):
    run = get_run(run_id, thread_id)
    outputs = []
    for action in run.required_action.submit_tool_outputs.tool_calls:
        action_id = action.id
        function = action.function
        st.write(f"Calling function: {function.name} with arg {function.arguments}")
        print(f"Calling function: {function.name} with arg {function.arguments}")
        output = functions_map[function.name](json.loads(function.arguments))
        outputs.append(
            {
                "output": output,
                "tool_call_id": action_id,
            }
        )
    return outputs


def submit_tool_outputs(run_id, thread_id):

    outputs = get_tool_outputs(run_id, thread_id)
    return client.beta.threads.runs.submit_tool_outputs_and_poll(
        run_id=run_id, thread_id=thread_id, tool_outputs=outputs
    )


def send_message(_content: str):
    thread_id = get_thread_id()

    start_run(thread_id, assistant_id, _content)


def paint_download_btn(content, createdAt):
    file_bytes = content.encode("utf-8")

    created_at_utc = datetime.fromtimestamp(createdAt, tz=timezone.utc)
    kst_timezone = timezone(timedelta(hours=9))
    created_at_kst = created_at_utc.astimezone(kst_timezone)
    formatted_date = created_at_kst.strftime("%y_%m_%d_%H%M_Answer")

    st.download_button(
        label="Download this answer.",
        data=file_bytes,
        file_name=f"{formatted_date}_{createdAt}.txt",
        mime="text/plain",
        key=createdAt,
    )


st.set_page_config(
    page_title="OpenAI Agent",
    page_icon="🤖",
)

st.markdown(
    """
    # OpenAI Agent

    ### Agent to help you search
    """
)

# ? Sidebar
with st.sidebar:
    openai_api_key = st.text_input(
        "Input your OpenAI API Key",
    )
    if not openai_api_key:
        st.error("OpenAI API Key is required.")

    st.markdown("---")
    st.write("https://github.com/fullstack-gpt-python/assignment-19")

# ? Main Screen
if not openai_api_key:
    st.error("Please input your OpenAI API Key on the sidebar")
else:
    query = st.chat_input("Ask a question to the website.")
    client = OpenAI(api_key=openai_api_key)
    assistant_id = get_assistant().id

    # 메시지 기록 출력
    for idx, message in enumerate(get_messages(get_thread_id())):
        with st.chat_message(message.role):
            st.markdown(message.content[0].text.value)
        if message.role == "assistant" and idx > 0:
            paint_download_btn(
                message.content[0].text.value, createdAt=message.created_at
            )

    if query:
        with st.chat_message("user"):
            st.markdown(query)
        send_message(query)
