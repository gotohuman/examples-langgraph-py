from mcp.server.fastmcp import FastMCP, Context
import openai
from openai import AsyncOpenAI
from typing import List

from dotenv import load_dotenv
load_dotenv(override=True)

client = AsyncOpenAI()
mcp = FastMCP("image")

@mcp.tool()
async def generate_images(topic: str, ctx: Context) -> List[str]:
    """Generate header images for a blog post.
    
    Args:
        topic: The topic of the blog post
        
    Returns:
        The list of image URLs
    """
    image_url_list = []
    try:
        images_response = await client.images.generate(
          prompt= f"Photorealistic image about: {topic}.",
          n= 3,
          style= "natural",
          response_format= "url",
        )
        for image in images_response.data:
          image_url_list.append(image.model_dump()["url"])
        # await ctx.info(f"Images generated {str(image_url_list)}") # will only work after fix by MCP
        return image_url_list
    except openai.APIConnectionError as e:
        # await ctx.error(f"Server connection error: {e.__cause__}")
        raise
    except openai.RateLimitError as e:
        # await ctx.error(f"OpenAI RATE LIMIT error {e.status_code}: (e.response)")
        raise
    except openai.APIStatusError as e:
        # await ctx.error(f"OpenAI STATUS error {e.status_code}: (e.response)")
        raise
    except openai.BadRequestError as e:
        # await ctx.error(f"OpenAI BAD REQUEST error {e.status_code}: (e.response)")
        raise
    except Exception as e:
        # await ctx.error(f"An unexpected error occurred: {e}")
        raise


if __name__ == "__main__":
  mcp.run()