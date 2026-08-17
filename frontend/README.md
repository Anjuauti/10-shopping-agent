# Cartly React frontend

## Run the app

The Python server now delivers both the API and the built React interface. From
the project folder, run this single command:

```powershell
& "..\.venv\Scripts\python.exe" -m uvicorn api:app --reload --port 8011
```

Open [http://localhost:8011](http://localhost:8011). Product photos are attached from the single chat composer and are sent with the message to the existing shopping agent.

## Frontend development

For local React development, this command starts **both** Vite and the Python
shopping API automatically:

```powershell
cd frontend
npm run dev
```

Wait until the terminal shows both `Uvicorn running on http://127.0.0.1:8011`
and the Vite local URL, then open the Vite URL.
