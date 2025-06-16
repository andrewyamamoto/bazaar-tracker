import importlib
import os
import sys
import types
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def setup_env():
    sys.modules['bcrypt'] = types.ModuleType('bcrypt')
    sys.modules['boto3'] = types.ModuleType('boto3')
    sys.modules['httpx'] = types.ModuleType('httpx')
    sys.modules['uvicorn'] = types.ModuleType('uvicorn')
    sys.modules['dotenv'] = types.SimpleNamespace(load_dotenv=lambda: None)
    sys.modules['fastapi'] = types.SimpleNamespace(Request=object)
    middleware = types.ModuleType('starlette.middleware.sessions')
    middleware.SessionMiddleware = object
    sys.modules['starlette.middleware.sessions'] = middleware

    fields = types.ModuleType('tortoise.fields')
    for name in ['IntField','ForeignKeyField','BooleanField','CharField','TextField','DatetimeField']:
        setattr(fields, name, lambda *a, **kw: None)
    models_mod = types.ModuleType('tortoise.models')
    models_mod.Model = object
    expressions = types.ModuleType('tortoise.expressions')
    expressions.Q = object
    class TortoiseStub:
        _inited = False
        async def init(*a, **kw):
            pass
        async def generate_schemas(*a, **kw):
            pass
        async def close_connections(*a, **kw):
            pass
    tortoise_mod = types.ModuleType('tortoise')
    tortoise_mod.Tortoise = TortoiseStub
    sys.modules['tortoise'] = tortoise_mod
    sys.modules['tortoise.fields'] = fields
    sys.modules['tortoise.models'] = models_mod
    sys.modules['tortoise.expressions'] = expressions

    class DummyElement:
        def __call__(self, *a, **kw):
            return self
        def __getattr__(self, name):
            return lambda *a, **kw: self
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def classes(self, *a, **kw):
            return self
        def props(self, *a, **kw):
            return self
        def style(self, *a, **kw):
            return self
        def bind_visibility_from(self, *a, **kw):
            return self
        def bind_text_from(self, *a, **kw):
            return self
        def on(self, *a, **kw):
            return self
        def reset(self):
            pass
    class DummyUI(DummyElement):
        def page(self, path):
            def decorator(func):
                return func
            return decorator
        def refreshable(self, func):
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)
            wrapper.refresh = lambda *a, **kw: None
            wrapper.__wrapped__ = func
            return wrapper
        def timer(self, *a, **kw):
            pass
        def run(self, *a, **kw):
            pass
    ui = DummyUI()
    class DummyApp:
        def on_startup(self, func):
            pass
        def on_shutdown(self, func):
            pass
        def add_middleware(self, *a, **kw):
            pass
        def post(self, path):
            def decorator(func):
                return func
            return decorator
    app = DummyApp()
    context = types.SimpleNamespace()
    nicegui_mod = types.ModuleType('nicegui')
    nicegui_mod.app = app
    nicegui_mod.ui = ui
    nicegui_mod.context = context
    sys.modules['nicegui'] = nicegui_mod


def test_compute_placement_percentages():
    setup_env()
    main = importlib.import_module('main')

    class DummyGame:
        def __init__(self, wins, finished):
            self.wins = wins
            self.finished = finished

    games = [DummyGame(5, 8) for _ in range(3)] + [DummyGame(0, 0) for _ in range(25)]

    async def fake_filter(*a, **kw):
        return games

    main.models.Game.filter = fake_filter

    cats, percents = asyncio.run(main.compute_placement_percentages(1, 0))
    result = dict(zip(cats, percents))
    assert result['3rd'] == 10.71
    assert result['No Placement'] == 89.29
    assert all(result[c] == 0 for c in ['2nd', '1st', 'Perfect Game'])
