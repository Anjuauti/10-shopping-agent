import base64
import json
import os
import re
import sqlite3
from typing import Optional

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain.tools import tool
from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import InMemorySaver

from reviews_api import get_product_rating

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "store.db")

# openai/gpt-oss-120b replaces the deprecated llama-3.3-70b-versatile /
# llama-3.1-8b-instant on Groq and is far more reliable at multi-step
# tool calling. This is the single biggest fix for the "keeps asking
# which one instead of searching" loop you were seeing.
#
# max_tokens caps the completion size too, since Groq's on_demand tier
# counts prompt + completion tokens against the same per-minute limit.
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0, max_tokens=500)

# Current Groq vision-capable model (preview tier).
vision_llm = ChatGroq(model="qwen/qwen3.6-27b", temperature=0, max_tokens=300)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
# Small/fast models are unreliable at turning raw JSON into a clean answer.
# So instead of returning JSON to the LLM and hoping it formats it well,
# the tools below return already-formatted, human-readable text. The model
# only has to relay it (and remember the IDs), which is much more robust.

def _format_product_line(p: dict) -> str:
    organic = "Organic" if p["is_organic"] else "Not organic"
    if p["review_count"] > 0:
        rating = f"{p['average_rating']}★ ({p['review_count']} reviews)"
    else:
        rating = "No reviews yet"
    # Keep descriptions short — this text goes straight into the LLM's
    # context on a tight per-minute token budget, so verbose product
    # copy adds up fast across a list of results.
    description = p["description"] or ""
    if len(description) > 80:
        description = description[:77] + "..."
    return (
        f"ID {p['id']} — {p['name']} — ${p['price']:.2f} — "
        f"{organic} — {rating} — {description}"
    )


@tool
def search_products(
    query: str,
    max_price: Optional[float] = None,
    min_rating: Optional[float] = None,
    is_organic: Optional[bool] = None,
) -> str:
    """Search the store for products. Returns a formatted, numbered list of
    matching products including their database ID, price, organic status,
    and rating. Always call this before asking the user which product they
    want — never ask "which one" without first showing real search results.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    sql = """
        SELECT p.id, p.name, p.category, p.price, p.description,
               p.is_organic,
               COALESCE(AVG(r.rating), 0) AS average_rating,
               COUNT(r.id) AS review_count
        FROM products p
        LEFT JOIN reviews r ON p.id = r.product_id
        WHERE 1=1
    """
    params = []

    if query:
        sql += " AND (p.name LIKE ? OR p.description LIKE ? OR p.category LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like, like])

    if max_price is not None:
        sql += " AND p.price <= ?"
        params.append(max_price)

    if is_organic is not None:
        sql += " AND p.is_organic = ?"
        params.append(1 if is_organic else 0)

    sql += " GROUP BY p.id, p.name, p.category, p.price, p.description, p.is_organic"

    if min_rating is not None:
        sql += " HAVING COALESCE(AVG(r.rating), 0) >= ?"
        params.append(min_rating)

    # LIMIT kept small (was 10) to control token usage per turn on a
    # tight Groq TPM budget — 5 well-chosen results is plenty for a user
    # to pick from, and they can narrow the query for more.
    sql += " ORDER BY average_rating DESC, p.price ASC LIMIT 5"

    cursor.execute(sql, params)
    rows = cursor.fetchall()
    conn.close()

    products = [
        {
            "id": row[0],
            "name": row[1],
            "category": row[2],
            "price": row[3],
            "description": row[4],
            "is_organic": bool(row[5]),
            "average_rating": round(row[6], 2),
            "review_count": row[7],
        }
        for row in rows
    ]

    if not products:
        return (
            "No products found matching that search. Ask the user to try "
            "different keywords or loosen their filters (price/rating/organic)."
        )

    lines = [_format_product_line(p) for p in products]
    return (
        f"Found {len(products)} product(s):\n\n"
        + "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))
        + "\n\nShow this list to the user as-is (you may lightly reformat "
        "for readability) and ask them to pick one by product ID."
    )


@tool
def get_rating(product_id: int) -> str:
    """Get the average customer rating and review count for one product by
    its database ID. Only use this when the user asks specifically about a
    single product's rating/reviews, not for general searches.
    """
    data = get_product_rating(product_id)
    if not data or data.get("review_count", 0) == 0:
        return f"Product ID {product_id} has no reviews yet."
    return (
        f"Product ID {product_id}: {data.get('average_rating')}★ "
        f"based on {data.get('review_count')} review(s)."
    )


@tool
def checkout(product_id: int) -> str:
    """Place an order for a product using its database product ID. The
    product ID MUST come from a previous search_products result or an
    explicit ID the user typed — never invent one. Repeat purchases are
    allowed."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, name, price FROM products WHERE id = ?",
        (product_id,),
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        return (
            f"Product ID {product_id} does not exist in the store. "
            "Please search again and use a valid product ID."
        )

    product_id_db, name, price = row

    cursor.execute(
        """
        INSERT INTO orders (product_id, product_name, price)
        VALUES (?, ?, ?)
        """,
        (product_id_db, name, price),
    )

    order_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return (
        "✅ Order placed successfully!\n\n"
        f"Order ID: {order_id}\n"
        f"Product: {name}\n"
        f"Product ID: {product_id_db}\n"
        f"Price: ${price:.2f}\n"
        "Estimated delivery: 3-5 business days."
    )


@tool
def describe_product_image(image_path: str) -> str:
    """Analyze an uploaded product image and return a short search query
    describing the product. After calling this, immediately call
    search_products with the returned search_query."""
    if not os.path.exists(image_path):
        return "The uploaded image could not be found on disk."

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    mime = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")

    message = HumanMessage(
        content=[
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_data}"},
            },
            {
                "type": "text",
                "text": (
                    "Analyze this product image for shopping. "
                    "Return ONLY valid JSON with exactly these fields: "
                    "product_type, search_query, is_organic, description. "
                    "The search_query must describe the actual product "
                    "visible in the image and be suitable for a store "
                    "database search. If the image shows oats, use 'oats' "
                    "as search_query."
                ),
            },
        ]
    )

    response = vision_llm.invoke([message])
    content = response.content
    if not isinstance(content, str):
        content = str(content)
    content = content.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = {"search_query": content, "product_type": content}

    search_query = data.get("search_query") or data.get("product_type") or ""
    description = data.get("description", "")
    is_organic = data.get("is_organic")

    return (
        f"Image identified as: {data.get('product_type', 'unknown product')}\n"
        f"Suggested search query: {search_query}\n"
        f"Organic: {is_organic}\n"
        f"Notes: {description}\n\n"
        f"Now call search_products with query='{search_query}'"
        + (" and is_organic=true" if is_organic else "")
        + " to find matching items."
    )


# ---------------------------------------------------------------------------
# Deterministic product-ID ordering (bypasses the LLM entirely for
# unambiguous "order id N" style commands)
# ---------------------------------------------------------------------------

ORDER_ID_PATTERNS = [
    r"\border\s+product\s+id\s*[:#]?\s*(\d+)\s*$",
    r"\border\s+id\s*[:#]?\s*(\d+)\s*$",
    r"\border\s+product\s*[:#]?\s*(\d+)\s*$",
    r"\bbuy\s+product\s+id\s*[:#]?\s*(\d+)\s*$",
    r"\bbuy\s+id\s*[:#]?\s*(\d+)\s*$",
    r"\bbuy\s+product\s*[:#]?\s*(\d+)\s*$",
    r"\bplace\s+order\s+for\s+product\s+id\s*[:#]?\s*(\d+)\s*$",
    r"\bplace\s+order\s+for\s+id\s*[:#]?\s*(\d+)\s*$",
]


def extract_product_id_from_order(text: str):
    """Extract a product ID from an explicit, unambiguous order/buy command.
    Deliberately conservative (anchored to end of string) so it doesn't
    misfire on things like "order 3 jars of honey".
    """
    text = text.lower().strip()
    for pattern in ORDER_ID_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def handle_explicit_product_order(user_message: str):
    """Handle explicit product-ID orders without sending them to the LLM."""
    product_id = extract_product_id_from_order(user_message)
    if product_id is None:
        return None

    print(f"[ORDER ROUTER] Explicit product order detected: product_id={product_id}")
    return checkout.invoke({"product_id": product_id})


SYSTEM_PROMPT = """
You are a STRICT shopping assistant for an online store. You ONLY help with:
- Finding/searching products
- Product prices and descriptions
- Product ratings and reviews
- Finding similar products from an uploaded image
- Placing product orders

For anything unrelated to shopping, reply EXACTLY with:
"Sorry, I can only help with shopping-related requests such as finding products, product prices, ratings/reviews, shopping by image, and placing orders."

WORKFLOW RULES (follow strictly):
1. If the user wants to find/browse/compare products, or mentions any product
   by name, you MUST call search_products before saying anything else.
   NEVER ask "which one would you like?" unless you have just shown the user
   real results from search_products in this conversation.
2. When search_products returns results, present them to the user clearly
   (product ID, name, price, organic status, rating) and ask them to choose
   by product ID.
3. If the user uploaded an image, call describe_product_image first, then
   immediately call search_products using the search_query it returns.
4. Use get_rating only when the user asks specifically about one product's
   rating/reviews.
5. To place an order you MUST have a numeric product ID. Get it from:
   - an explicit ID the user typed ("order id 12"), or
   - conversation memory, by mapping references like "the first one",
     "the second one", "the cheaper one", "that one", "yes" to the ID from
     the most recent search_products results shown in this conversation.
   NEVER invent or guess a product ID. If you cannot determine one with
   confidence, ask the user to specify which product ID to order.
6. After checkout succeeds, relay its confirmation message (order ID,
   product, price, delivery estimate) back to the user as-is.
7. The database is the single source of truth. Never invent products,
   prices, ratings, review counts, product IDs, or order confirmations
   yourself — only report what the tools return.
8. Repeat purchases of the same product are allowed.

You are a SHOPPING ASSISTANT, not a general-purpose assistant.
"""

checkpointer = InMemorySaver()

# Without this, every turn resends the ENTIRE conversation (every search
# result, every order confirmation, the image description...) to the
# model. On Groq's on_demand tier (8,000 tokens/minute for gpt-oss-120b)
# that overflows after a handful of turns — which is exactly the 413
# "Request too large" error you hit. This middleware condenses older
# messages into a running summary once the history gets big, while
# keeping the most recent messages verbatim so ordinal references like
# "the second one" still resolve correctly against the last search.
summarization = SummarizationMiddleware(
    model=llm,
    max_tokens_before_summary=3000,
    messages_to_keep=6,
)

agent = create_agent(
    model=llm,
    tools=[
        search_products,
        get_rating,
        checkout,
        describe_product_image,
    ],
    system_prompt=SYSTEM_PROMPT,
    middleware=[summarization],
    checkpointer=checkpointer,
)


def process_user_message(user_message: str, thread_id: str):
    """
    Main entry point for Streamlit.

    Explicit product-ID orders are handled deterministically.
    Everything else goes through the LangGraph agent, which has
    conversation memory keyed by thread_id.
    """
    direct_order_result = handle_explicit_product_order(user_message)
    if direct_order_result is not None:
        return direct_order_result

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": user_message,
                }
            ]
        },
        {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 25,
        },
    )

    response = result["messages"][-1].content
    if not isinstance(response, str):
        response = str(response)

    return response.replace("`", "")