import uvicorn

from sonakit.core.config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("sonakit.app:app", host=settings.host, port=settings.port, reload=True)
