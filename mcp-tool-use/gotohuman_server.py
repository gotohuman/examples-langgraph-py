import os
from mcp.server.fastmcp import FastMCP
from typing import List
from gotohuman import GotoHuman

from dotenv import load_dotenv
load_dotenv(override=True)

mcp = FastMCP("gotoHuman")
gotoHuman = GotoHuman()

@mcp.tool()
async def request_approval(ai_text: str, ai_image_urls: List[str]) -> str:
    """Request approval from a human reviewer for a blog post written in markdown with images to choose from.
    
    Args:
        ai_text: The text of the blog post
        ai_image_urls: The URLs of the suggested images
        
    Returns:
        The link to the review request
    """
    form_id = os.getenv("GOTOHUMAN_FORM_ID")
    review = gotoHuman.create_review(form_id)

    review.add_field_data("ai_markdown", ai_text)
    review.add_field_data("ai_image", [{"url": url, "label": f"AI image suggestion {i+1}"} for i, url in enumerate(ai_image_urls)])

    # Send the review request
    try:
        response = await review.async_send_request()
        return response.get('gthLink', 'no_link')

        # TODO: Handle the webhook with the review response from GotoHuman separately

    except Exception as e:
        return f"An error occurred while sending the review request: {e}"

if __name__ == "__main__":
  mcp.run()