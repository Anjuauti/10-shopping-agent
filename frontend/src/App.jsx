import { useRef, useState } from "react";

const suggestions = [
  "Find organic honey under $15",
  "Show me highly rated coffee",
  "What healthy snacks do you have?",
];

function createMessage(role, content, image) {
  return { id: crypto.randomUUID(), role, content, image };
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [text, setText] = useState("");
  const [image, setImage] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const [threadId, setThreadId] = useState(() => crypto.randomUUID());
  const inputRef = useRef(null);

  const resetChat = () => {
    setMessages([]);
    setText("");
    setImage(null);
    setThreadId(crypto.randomUUID());
    if (inputRef.current) inputRef.current.value = "";
  };

  const submit = async (event, suggestion) => {
    event?.preventDefault();
    const messageText = (suggestion ?? text).trim();
    if ((!messageText && !image) || isSending) return;

    const selectedImage = image;
    setMessages((current) => [
      ...current,
      createMessage("user", messageText || "Find similar products", selectedImage && URL.createObjectURL(selectedImage)),
    ]);
    setText("");
    setImage(null);
    if (inputRef.current) inputRef.current.value = "";
    setIsSending(true);

    try {
      const data = new FormData();
      data.append("message", messageText);
      data.append("thread_id", threadId);
      if (selectedImage) data.append("image", selectedImage);
      const result = await fetch("/api/chat", { method: "POST", body: data });
      const rawBody = await result.text();
      let payload = {};
      if (rawBody) {
        try {
          payload = JSON.parse(rawBody);
        } catch {
          payload = {};
        }
      }
      if (!result.ok) {
        throw new Error(
          payload.detail || "The shopping service is unavailable. Restart the app with npm run dev and try again.",
        );
      }
      setThreadId(payload.thread_id);
      setMessages((current) => [...current, createMessage("assistant", payload.response)]);
    } catch (error) {
      setMessages((current) => [...current, createMessage("assistant", `I couldn't complete that request. ${error.message}`)]);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <main className="app-shell">
      <section className="chat-card" aria-label="Cartly shopping assistant">
        <header className="topbar">
          <div className="brand"><span className="brand-mark">C</span><span>cartly</span></div>
          <div className="agent-status"><i /> Shopping concierge</div>
          <button className="new-chat" onClick={resetChat} type="button">New chat <span>+</span></button>
        </header>

        <div className="conversation">
          {messages.length === 0 ? (
            <section className="welcome">
              <div className="welcome-icon">⌕</div>
              <p className="eyebrow">YOUR PERSONAL SHOPPING CONCIERGE</p>
              <h1>Find exactly what<br />you’re looking for.</h1>
              <p className="intro">Ask for products, compare options, check ratings, or order with a product ID. You can also add a product photo right in the message box.</p>
              <div className="how-it-works">
                <div><b>01</b><span>Describe what you need</span></div>
                <div><b>02</b><span>Choose from real store results</span></div>
                <div><b>03</b><span>Order using its product ID</span></div>
              </div>
              <p className="try-label">Try one of these</p>
              <div className="suggestions">
                {suggestions.map((suggestion) => <button onClick={(event) => submit(event, suggestion)} type="button" key={suggestion}>{suggestion}<span>↗</span></button>)}
              </div>
            </section>
          ) : (
            <section className="messages">
              {messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <div className="avatar">{message.role === "assistant" ? "C" : "You"}</div>
                  <div className="message-body">
                    {message.image && <img src={message.image} alt="Uploaded product" />}
                    {message.content && <p>{message.content}</p>}
                  </div>
                </article>
              ))}
              {isSending && <article className="message assistant"><div className="avatar">C</div><div className="typing"><i /><i /><i /></div></article>}
            </section>
          )}
        </div>

        <form className="composer" onSubmit={submit}>
          {image && <div className="attachment"><img src={URL.createObjectURL(image)} alt="Ready to send" /><span>{image.name}</span><button type="button" onClick={() => setImage(null)} aria-label="Remove image">×</button></div>}
          <div className="input-row">
            <label className="image-button" title="Add a product image"><input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setImage(event.target.files?.[0] || null)} />⌑</label>
            <input value={text} onChange={(event) => setText(event.target.value)} placeholder="Ask about products, or add a product image…" aria-label="Your shopping request" />
            <button className="send" disabled={isSending || (!text.trim() && !image)} aria-label="Send message">↑</button>
          </div>
          <p>Attach a photo to find similar items • Orders require a product ID</p>
        </form>
      </section>
    </main>
  );
}
