"""Small HTTP API that connects the React client to the shopping agent."""

import os
import shutil
import tempfile
import uuid
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from shopping_agent import process_user_message

PROJECT_DIR = Path(__file__).resolve().parent
DIST_DIR = PROJECT_DIR / "frontend" / "dist"


async def chat(request):
    """Accept a message and optional image attachment from the chat composer."""
    form = await request.form()
    message = (form.get("message") or "").strip()
    thread_id = (form.get("thread_id") or str(uuid.uuid4())).strip()
    upload = form.get("image")
    image_path = None

    try:
        if upload and getattr(upload, "filename", None):
            extension = os.path.splitext(upload.filename)[1].lower() or ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as file:
                image_path = file.name
                shutil.copyfileobj(upload.file, file)

            image_request = (
                "I uploaded a product image. Analyze it and find similar products "
                f"in the store. Image path: {image_path}"
            )
            message = f"{message}\n\n{image_request}".strip()

        if not message:
            return JSONResponse({"detail": "Enter a message or attach an image."}, status_code=400)

        response = process_user_message(message, thread_id)
        return JSONResponse({"response": response, "thread_id": thread_id})
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)


async def frontend(request):
    """Serve the production React UI from the same server as the agent API."""
    index_file = DIST_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(
            {"detail": "Frontend is not built. Run `npm run build` in frontend first."},
            status_code=503,
        )
    return FileResponse(index_file)


app = Starlette(routes=[Route("/api/chat", chat, methods=["POST"]), Route("/", frontend)])
if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://localhost:5176"],
    allow_methods=["POST"],
    allow_headers=["*"],
)
