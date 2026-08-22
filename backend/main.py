"""
Heimdallv2 Server Entrypoint
FastAPI App + WebSockets + Tactical Command Center Static Host
"""

import os
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .api.routes import router as api_router, ws_manager

app = FastAPI(
    title="Heimdallv2 — Drone Traffic Intelligence Platform",
    description="Autonomous aerial perception, BoT-SORT multi-object tracking, and DiaB command console.",
    version="2.0.0",
)

# Enable CORS for cross-origin local dashboard development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include REST APIs
app.include_router(api_router)


# Real-Time WebSocket Streaming Endpoint
@app.websocket("/ws/tracking")
async def websocket_tracking_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep alive and receive any client-side control commands
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        await ws_manager.disconnect(websocket)


# Serve Static Frontend Dashboard
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    async def serve_index():
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"status": "Heimdallv2 Backend Online. Frontend static files loading..."}

    @app.get("/favicon.ico")
    async def serve_favicon():
        from fastapi.responses import Response
        return Response(status_code=204)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    print(f"=================================================================")
    print(f"  HEIMDALLv2 DRONE TRAFFIC INTELLIGENCE PLATFORM")
    print(f"  Listening on http://{host}:{port}")
    print(f"  Command Center: http://localhost:{port}/")
    print(f"  Swagger Docs:   http://localhost:{port}/docs")
    print(f"  WebSocket:      ws://localhost:{port}/ws/tracking")
    print(f"=================================================================")
    uvicorn.run("backend.main:app", host=host, port=port, reload=False)
