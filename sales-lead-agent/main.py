import uuid
import re
import os
from typing import Optional, Annotated
from typing_extensions import TypedDict
from fastapi import FastAPI, Request
from gotohuman import GotoHuman
from firecrawl import FirecrawlApp
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt
from dotenv import load_dotenv

load_dotenv(override=True)

app = FastAPI()
gotohuman = GotoHuman()

class State(TypedDict):
    messages: Annotated[list, add_messages]
    email_address: str
    lead_website_url: str
    email_to_send: str

@tool
async def web_scrape_tool(url: str) -> str:
    """Scrape a website"""
    app = FirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY"))
    scrape_result = app.scrape_url(url, params={'formats': ['markdown']})
    print(f"Scraped website {url}: {scrape_result['markdown'][:50]}")
    return scrape_result["markdown"]

@tool
async def summarizer_tool(content: str) -> str:
    """Summarize scraped website content"""
    messages = [
        SystemMessage(content="You are a helpful website content summarizer. You will be passed the content of a scraped company website. Please summarize it in 250-300 words focusing on what kind of company this is, the services they offer and how they operate."),
        HumanMessage(content=content),
    ]
    model = ChatOpenAI(temperature=0.5, model="gpt-4o-mini")
    response = await model.ainvoke(messages)
    print(f"Summarized website: {response.content[:100]}")
    return response.content

@tool
async def draft_tool(email_address: str, company_description: str, previous_draft: Optional[str], retry_comment: Optional[str]) -> str:
    """Write or revise a sales email."""
    no_domain = not bool(company_description)
    
    sender_name = "Jess"
    sender_company_desc = "FreshFruits is a premier subscription-based delivery service..."
    
    messages = [
        SystemMessage(content=f"""You are a helpful sales expert, great at writing enticing emails.
        You will write an email for {sender_name} who wants to reach out to a new prospect who left their email address: {email_address}. {sender_name} works for the following company:
        {sender_company_desc}
        Write no more than 300 words.
        {'It must be tailored as much as possible to the prospect\'s company based on the website information we fetched. Don\'t mention that we got the information from the website. Include no placeholders! Your response should be nothing but the pure email body!' if not no_domain else ''}"""),
        HumanMessage(content="No additional information found about the prospect" if no_domain else f"#Company website summary:\n{company_description}")
    ]
    if previous_draft:
        messages.append(AIMessage(content=previous_draft))
    if retry_comment:
        messages.append(HumanMessage(content=retry_comment))
    
    model = ChatOpenAI(temperature=0.75, model="gpt-4o-mini")
    response = await model.ainvoke(messages)
    print(f"Drafted email: {response.content[:100]}")
    return response.content

def extract_domain(state: State):
    email_address = state["email_address"]
    common_providers = [
        'gmail', 'yahoo', 'ymail', 'rocketmail',
        'outlook', 'hotmail', 'live', 'msn',
        'icloud', 'me', 'mac', 'aol',
        'zoho', 'protonmail', 'mail', 'gmx'
    ]
    
    url = None
    domain = email_address.split('@')[-1] if '@' in email_address else None
    if domain:
        pattern = fr"^({'|'.join(common_providers)})\.(?:com|net|org|edu|.*)"
        if not re.search(pattern, domain):
            url = f"https://{domain}"
    print(f"Extracted domain from email address {email_address}: {url}")
    return {"lead_website_url": url, "messages": [HumanMessage(content=f"We got the email address of a new lead: {state['email_address']}. {f'Scrape the corresponding website: {url}. Then use the summarizer tool to describe it.' if url else ''} Then write an outreach email. Only respond with the email body!")]}

tools = [web_scrape_tool, summarizer_tool, draft_tool]
llm = ChatOpenAI(model="gpt-4o", temperature=0)
llm_with_tools = llm.bind_tools(tools)

def chatbot(state: State):
    message = llm_with_tools.invoke(state["messages"])
    return {"messages": [message]}

def route_tools(
    state: State,
):
    """
    Use in the conditional_edge to route to the ToolNode if the last message
    has tool calls. Otherwise, route to the human approval.
    """
    if isinstance(state, list):
        ai_message = state[-1]
    elif messages := state.get("messages", []):
        ai_message = messages[-1]
    else:
        raise ValueError(f"No messages found in input state to tool_edge: {state}")
    if hasattr(ai_message, "tool_calls") and len(ai_message.tool_calls) > 0:
        return "tools"
    return "ask_human"

def human_approval(
        state: State,
):
    # Get the last ToolMessage with name "draft_tool" which is the drafted email
    messages = state.get("messages", [])
    draft_tool_message = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)
    if not draft_tool_message:
        raise ValueError(f"No ToolMessage with name 'draft_tool' found: {state}")
    email_draft_content = draft_tool_message.content
    
    # The interrupt will surface the email draft to our graph run. The returned interrupt will continue here with the response from gotoHuman.
    human_response = interrupt(
        {
            "email_draft": email_draft_content,
        },
    )
    print(f"Interrupt returned human response: {human_response}")
    response = human_response.get("response", "")
    emailContentReviewed = human_response.get("reviewed_email", "")
    retryComment = human_response.get("comment", "")

    if response == "retry":
        return Command(goto="agent", update={"messages": [HumanMessage(content=f"Please revise the previous draft considering the following: {retryComment}.\nAgain, only respond with the email body!")]})
    elif response == "approve":
        return Command(goto="send_email", update={"email_to_send": emailContentReviewed})
    return Command(goto=END)
    
    
def send_email(
    state: State,
):
    email_address = state.get("email_address")
    email = state.get("email_to_send")
    print(f"Sending email to {email_address} with content: {email[:50]}")
    # TODO: Implement sending email
    return {"messages": [AIMessage(content=f"Email sent to {email_address}")]}

@app.post("/")
async def process_request(request: Request):
    req = await request.json()
    thread_id = req.get("meta", {}).get("threadId") or str(uuid.uuid4())

    graph_builder = StateGraph(State)
    graph_builder.add_node("extract_domain", extract_domain)
    graph_builder.add_node("agent", chatbot)

    tool_node = ToolNode(tools=tools)
    graph_builder.add_node("tools", tool_node)
    graph_builder.add_node("ask_human", human_approval, destinations=("agent", "send_email", END))
    graph_builder.add_node("send_email", send_email)

    graph_builder.add_edge(START, "extract_domain")
    graph_builder.add_edge("extract_domain", "agent")
    graph_builder.add_conditional_edges(
        "agent",
        route_tools,
    )
    graph_builder.add_edge("tools", "agent")
    graph_builder.add_edge("send_email", END)

    # Initialize DB to persist state of the conversation thread between graph runs
    async with AsyncPostgresSaver.from_conn_string(os.getenv("POSTGRES_CONN_STRING")) as memory:
        #check if no threadId is provided
        if req.get("meta", {}).get("threadId") is None:
          await memory.setup()
        graph = graph_builder.compile(checkpointer=memory)
        thread_config = { "configurable": { "thread_id": thread_id } }
            
        if req.get("type") == "trigger" or req.get("email"):
            # we were called by the gotoHuman trigger or by another triggering request including an email
            email_address = req.get("email") or req.get("responseValues", {}).get("email", {}).get("value", "")
            print(f"Starting graph with email address: {email_address}")
            await graph.ainvoke({"email_address": email_address}, config=thread_config)
        
        elif req.get("type") == "review":
            # we were called again with the review response from gotoHuman
            approval = req["responseValues"].get("emailApproval", {}).get("value", "")
            email_text = req["responseValues"].get("emailDraft", {}).get("value", "")
            retry_comment = req["responseValues"].get("retryComment", {}).get("value", "")
            
            await graph.ainvoke(Command(resume={ "response": approval, "reviewed_email": email_text, "comment": retry_comment }), config=thread_config)

        # check if the graph reached the interrupt in node "ask_human"
        state = await graph.aget_state(thread_config)
        if state.tasks and state.tasks[0].name == "ask_human":
            email_draft = state.tasks[0].interrupts[0].value["email_draft"] if state.tasks else None
            email_address = state.values.get("email_address", "")
            website_url = state.values.get("lead_website_url", "")
            
            # Create review request with GotoHuman
            review_request = (
                gotohuman.create_review(os.getenv("GOTOHUMAN_FORM_ID"))
                .add_field_data("email", email_address)
                .add_field_data("emailDomain", {"url": website_url, "label": "Website checked"})
                .add_field_data("emailDraft", email_draft)
                .add_meta_data("threadId", thread_id)
            )
            
            gotohuman_response = await review_request.async_send_request()
            print(f"gotoHuman: requested human review: {gotohuman_response}")
            return {"message": "The email draft needs human review.", "link": gotohuman_response["gthLink"]}
    
    print("Graph ended")
    return {"message": "Graph ended"}