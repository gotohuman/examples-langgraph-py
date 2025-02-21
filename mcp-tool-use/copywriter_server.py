from mcp.server.fastmcp import FastMCP, Context
from langchain_openai import ChatOpenAI

from dotenv import load_dotenv
load_dotenv(override=True)

model = ChatOpenAI(model="gpt-4o-mini", verbose=True)
mcp = FastMCP("copywriter")

@mcp.tool()
async def write_blog_post(topic: str, ctx: Context) -> str:
    """Write a blog post.
    
    Args:
        topic: The topic of the blog post
        
    Returns:
        The written blog post
    """
    try:
        # await ctx.info(f"Processing {topic}")
        messages = [
            (
                "system",
                "You are a senior copywriter. Write an engaging blog post about the given topic. Maximum 300 words. Output only markdown format.",
            ),
            ("human", f"The topic is: {topic}"),
        ]
        ai_msg = await model.ainvoke(messages)
        return ai_msg.content
    except Exception as e:
        return f"An error occurred while writing the blog post: {e}"

if __name__ == "__main__":
  mcp.run()