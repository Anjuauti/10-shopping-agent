import os
import tempfile
import uuid

import streamlit as st

from shopping_agent import process_user_message


st.set_page_config(
    page_title="AI Shopping Assistant",
    page_icon="🛒",
    layout="wide",
)

st.title("🛒 AI Shopping Assistant")
st.caption(
    "Tell me what you want — I'll search, rate, and order the best match for you."
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "pending_image" not in st.session_state:
    st.session_state.pending_image = None


# ---------------------------------------------------------------------------
# Sidebar — image shopping
# ---------------------------------------------------------------------------

with st.sidebar:

    st.header("🛍️ Shop by Image")
    st.caption(
        "Upload a photo of a product and I'll find similar items in our store."
    )

    uploaded_file = st.file_uploader(
        "Upload product image",
        type=["jpg", "jpeg", "png", "webp"],
    )

    if uploaded_file:
        st.image(uploaded_file, use_container_width=True)

    if uploaded_file and st.button(
        "Find similar products",
        use_container_width=True,
    ):

        suffix = os.path.splitext(uploaded_file.name)[1] or ".jpg"

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as tmp:
            tmp.write(uploaded_file.getvalue())
            image_path = tmp.name

        prompt = (
            "I uploaded a product image. "
            "Analyze it and find similar products in the store. "
            f"Image path: {image_path}"
        )

        st.session_state.messages.append(
            {
                "role": "user",
                "content": prompt,
            }
        )

        st.session_state.pending_image = {
            "filename": uploaded_file.name,
            "path": image_path,
            "prompt": prompt,
        }

        st.rerun()


    st.divider()

    if st.button(
        "🆕 New Chat",
        use_container_width=True,
    ):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.pending_image = None
        st.rerun()


# ---------------------------------------------------------------------------
# Display history
# ---------------------------------------------------------------------------

for msg in st.session_state.messages:

    with st.chat_message(msg["role"]):

        content = msg["content"]

        if (
            msg["role"] == "user"
            and content.startswith("I uploaded a product image")
        ):

            if "Image path:" in content:
                image_path = content.split("Image path:")[-1].strip()
                filename = os.path.basename(image_path)

                st.markdown(
                    f"🔎 Searching by image: **{filename}**"
                )
            else:
                st.markdown("🔎 Searching by image...")

        else:
            st.markdown(content.replace("$", r"\$"))


# ---------------------------------------------------------------------------
# Process image request
# ---------------------------------------------------------------------------

if st.session_state.pending_image is not None:

    image_info = st.session_state.pending_image
    image_path = image_info["path"]
    image_prompt = image_info["prompt"]

    with st.chat_message("assistant"):

        with st.spinner("Analyzing image and searching..."):

            response = process_user_message(
                image_prompt,
                st.session_state.thread_id,
            )

        st.markdown(response.replace("$", r"\$"))

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response,
        }
    )

    try:
        if os.path.exists(image_path):
            os.remove(image_path)
    except Exception:
        pass

    st.session_state.pending_image = None
    st.rerun()


# ---------------------------------------------------------------------------
# Normal chat
# ---------------------------------------------------------------------------

if prompt := st.chat_input(
    "e.g. I want organic honey under $15 with 4+ rating"
):

    st.session_state.messages.append(
        {
            "role": "user",
            "content": prompt,
        }
    )

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):

        with st.spinner("Thinking..."):

            # Only the NEW message is sent.
            # LangGraph uses thread_id to retrieve conversation memory.
            response = process_user_message(
                prompt,
                st.session_state.thread_id,
            )

        st.markdown(response.replace("$", r"\$"))

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response,
        }
    )

    st.rerun()