from __future__ import annotations
from pathlib import Path
from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from ..config import Config
from ..db.store import Store
from ..pipeline import runner

_DIR = Path(__file__).parent

def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.load()
    app = FastAPI()
    templates = Jinja2Templates(directory=str(_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(_DIR / "static")), name="static")

    def store() -> Store:
        return Store.open(config)

    def _run_pipeline(sid: int) -> None:
        # Open a fresh Store in the worker thread — sqlite connections are
        # bound to the thread that created them, so the request-thread Store
        # must not cross into the background task.
        runner.run(sid, Store.open(config), config)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        sessions = store().list_sessions()
        cleaned = sorted(p.name for p in config.cleaned_dir.glob("*.MOV")) \
            if config.cleaned_dir.is_dir() else []
        return templates.TemplateResponse(
            request, "index.html", {"sessions": sessions, "cleaned": cleaned})

    @app.post("/upload")
    def upload(background: BackgroundTasks, source: str = Form(...)):
        name = Path(source).name
        candidate = (config.cleaned_dir / name).resolve()
        if name != source or candidate.parent != config.cleaned_dir.resolve() or not candidate.is_file():
            raise HTTPException(status_code=400, detail="invalid source")
        s = store()
        sid = s.create_session(video_path=str(config.cleaned_dir / name))
        background.add_task(_run_pipeline, sid)
        return RedirectResponse(f"/sessions/{sid}", status_code=303)

    @app.get("/sessions/{sid}", response_class=HTMLResponse)
    def session_view(request: Request, sid: int):
        s = store()
        sess = s.get_session(sid)
        speakers = {sp.id: sp for sp in s.get_speakers(sid)}
        return templates.TemplateResponse(request, "session.html", {
            "sess": sess, "speakers": speakers,
            "utterances": s.get_utterances(sid), "summaries": s.get_summaries(sid),
            "tags": s.get_situation_tags(sid), "links": s.get_repeated_links(sid)})

    @app.get("/media/{sid}")
    def media(sid: int):
        sess = store().get_session(sid)
        return FileResponse(sess.video_path)

    @app.post("/sessions/{sid}/tags")
    def add_tag(sid: int, kind: str = Form(...), value: str = Form(""),
                start_s: float = Form(0.0), end_s: float = Form(0.0)):
        store().add_situation_tag(sid, start_s, end_s, kind, value, "manual")
        return RedirectResponse(f"/sessions/{sid}", status_code=303)

    @app.post("/sessions/{sid}/roles")
    def set_role(sid: int, speaker_id: int = Form(...), role: str = Form(...)):
        store().set_speaker_role(speaker_id, role)
        return RedirectResponse(f"/sessions/{sid}", status_code=303)

    @app.get("/players/{name}", response_class=HTMLResponse)
    def player_view(request: Request, name: str):
        advice = store().get_advice(player=name)
        return templates.TemplateResponse(
            request, "player.html", {"name": name, "advice": advice})

    return app

app = create_app  # uvicorn: `uvicorn sailog.web.app:app --factory`
