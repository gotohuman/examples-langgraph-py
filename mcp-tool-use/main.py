import asyncio
import sys
from gotohuman import GotoHuman
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

from dotenv import load_dotenv
load_dotenv(override=True)

model = ChatOpenAI(model="gpt-4o")
gotoHuman = GotoHuman()

python_path = sys.executable

async def main():

  async with MultiServerMCPClient() as client:
    await client.connect_to_server(
        "copywriter",
        command=python_path,
        args=["copywriter_server.py"],
        encoding_error_handler="ignore",
    )
    await client.connect_to_server(
        "image",
        command=python_path,
        args=["image_server.py"],
        encoding_error_handler="ignore",
    )
    await client.connect_to_server(
        "gotoHuman",
        command=python_path,
        args=["gotohuman_server.py"],
        encoding_error_handler="ignore",
    )
    agent = create_react_agent(model, client.get_tools(), debug=True)
    review_requested = await agent.ainvoke(debug=True, input={"messages": "Write a blog post about the weather in NYC, create images for it, and then request approval from a human reviewer"})
    print("Review requested successfully: ", review_requested)

if __name__ == "__main__":
    asyncio.run(main())