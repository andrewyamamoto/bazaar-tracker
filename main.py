#!/usr/bin/env python3
import bcrypt
import boto3
import hashlib
import httpx
import json
import models
import os
import re
import time
import uvicorn

from dotenv import load_dotenv
from nicegui import app, ui, context
from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware
from tortoise import Tortoise
from tortoise.expressions import Q
from types import SimpleNamespace

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

load_dotenv()

DATABASE_HOST = os.getenv("DB_HOST")
DATABASE_PORT = os.getenv("DB_PORT", "5432")
DATABASE_NAME = os.getenv("DB_NAME")
DATABASE_USER = os.getenv('DB_USER')
DATABASE_PASSWORD = os.getenv('DB_PASSWORD')
BUCKET_UPLOAD_URL = os.getenv('BUCKET_UPLOAD_URL')
BUCKET_KEY = os.getenv('BUCKET_KEY')
BUCKET_SECRET = os.getenv('BUCKET_SECRET')
DEV_MODE = os.getenv('DEV_MODE', 'false').lower() == 'true'
SESSION_SECRET = os.getenv('SESSION_SECRET')

# per-user version counters for game data; increment whenever a run is added or deleted
game_data_version = {}

def mark_games_changed(user_id: int) -> None:
    """Increase the game data version for the specified user."""
    game_data_version[user_id] = game_data_version.get(user_id, 0) + 1


def categorize_game(game):
    """Return the placement category for a game."""
    if game.wins == 10 and game.finished == 10:
        return 'Perfect Game'
    if game.wins == 10:
        return '1st'
    if game.wins >= 7:
        return '2nd'
    if game.wins >= 4:
        return '3rd'
    return 'No Placement'


async def compute_placement_percentages(user_id: int, season: int):
    """Compute percentage placement statistics for a user's season."""
    categories = ["No Placement", "3rd", "2nd", "1st", "Perfect Game"]
    totals = {c: 0 for c in categories}
    games = await models.Game.filter(player_id=user_id, season=season)
    for g in games:
        cat = categorize_game(g)
        totals[cat] += 1
    total_games = sum(totals.values())
    percentages = [round((totals[c] / total_games) * 100, 2) if total_games else 0.0 for c in categories]
    return categories, percentages


async def delete_game_by_id(game_id: int) -> bool:
    """Delete a game for the current user by id.

    Returns ``True`` on success and ``False`` if the user is not
    authenticated or the game does not belong to them.
    """
    user = await get_current_user()
    if not user:
        ui.notify('Unauthorized', color='negative')
        return False
    # Use `player_id` to ensure we filter by the foreign key column
    game = await models.Game.get_or_none(id=game_id, player_id=user.id)
    if not game:
        ui.notify('Unauthorized', color='negative')
        return False
    await game.delete()
    return True


async def init_db():
    # db_url = f"postgres://{DATABASE_USER}:{DATABASE_PASSWORD}@db-postgresql-sfo2-10284-do-user-282100-0.m.db.ondigitalocean.com:25060/bazaar"
    db_url = f"postgres://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"
    await Tortoise.init(
        db_url=db_url,
        modules={"models": ["models"]}
    )
    await Tortoise.generate_schemas(safe=True)

async def close_db():
    if Tortoise._inited:
        await Tortoise.close_connections()

app.on_startup(init_db)
app.on_shutdown(close_db)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=60 * 60 * 24 * 7,  # one week
    same_site="lax",
    https_only=not DEV_MODE,
)


async def generate_presigned_post(filename):
    session = boto3.session.Session()
    client = session.client('s3',
        region_name='nyc3',
        endpoint_url=BUCKET_UPLOAD_URL,
        aws_access_key_id=BUCKET_KEY,
        aws_secret_access_key=BUCKET_SECRET)

    return client.generate_presigned_post(
        Bucket='bazaar-files',
        Key=f'screenshots/{filename}',
        Fields={"acl": "public-read"},
        Conditions=[
            {"acl": "public-read"},
            ["starts-with", "$Content-Type", ""]
        ],
        ExpiresIn=3600
    )

async def create_user(username, password):
    existing = await models.Users.get_or_none(Q(username=username))
    if existing:
        return False, "User already exists."
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    await models.Users.create(username=username, password=hashed)
    return True, "User created successfully."

async def get_current_user():
    session = getattr(context, 'session', None)
    if not session:
        return None
    user_id = session.get('user_id')
    if not user_id:
        return None
    user = await models.Users.get_or_none(id=user_id)
    return user

async def authenticate(username, password):
    user = await models.Users.get_or_none(Q(username=username))
    if user and bcrypt.checkpw(password.encode(), user.password.encode()):
        return user
    return None

@app.post('/api/login')
async def api_login(request: Request):
    data = await request.json()
    username = data.get('username')
    password = data.get('password')
    user = await authenticate(username, password)
    if user:
        request.session['user_id'] = user.id
        latest_game = await models.Game.filter(player_id=user.id).order_by('-season').first()
        latest_season = latest_game.season if latest_game else 3
        return {'success': True, 'redirect': f'/dashboard/{latest_season}'}
    return {'success': False, 'error': 'Invalid email or password.'}

@app.post('/api/signup')
async def api_signup(request: Request):
    data = await request.json()
    username = data.get('username')
    password = data.get('password')
    success, msg = await create_user(username, password)
    return {'success': success, 'message': msg}

@app.post('/api/logout')
async def api_logout(request: Request):
    request.session.clear()
    return {'success': True}

@ui.page('/')
def login_page(request: Request):
    context.session = request.session
    ui.page_title("Bazaar Tracker")
    ui.label('Login').classes('text-3xl font-bold mb-4')
    email = ui.input('Username').props('type=text').classes('w-full max-w-sm')
    password = ui.input('Password').props('type=password').classes('w-full max-w-sm')
    message = ui.label('').classes('text-red-500 mt-2')

    async def handle_login():
        if not email.value or not password.value:
            message.text = 'Username and password cannot be blank.'
            return
        payload = {"username": email.value, "password": password.value}
        result = await ui.run_javascript(
            f"return fetch('/api/login', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({json.dumps(payload)})}}).then(r => r.json())"
        )
        if result.get('success'):
            message.text = ''
            ui.navigate.to(result.get('redirect', '/dashboard/0'))
        else:
            message.text = 'Invalid email or password.'

    async def handle_signup():
        if not email.value or not password.value:
            message.text = 'Username and password cannot be blank.'
            return
        payload = {"username": email.value, "password": password.value}
        result = await ui.run_javascript(
            f"return fetch('/api/signup', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({json.dumps(payload)})}}).then(r => r.json())"
        )
        message.text = result.get('message', '')
        if result.get('success'):
            ui.notify('Account created! Please log in.', color='positive')

    with ui.row().classes('mt-4 gap-2'):
        ui.button('Login', on_click=handle_login).classes('bg-blue-600 text-white px-4 py-2 rounded')
        ui.button('Sign Up', on_click=handle_signup).classes('bg-green-600 text-white px-4 py-2 rounded')

@ui.page('/logout')
async def logout_page(request: Request):
    context.session = request.session
    context.session.clear()
    ui.navigate.to('/')

@ui.page('/dashboard/{season_id}')
async def index(request: Request, season_id: str = None):

    context.session = request.session
    
    ui.page_title("Bazaar Tracker")
    season_source = season_id or context.query.get('season', '0')
    
    try:
        default_season = int(season_source)
    except ValueError:
        default_season = 0

    class SeasonValue:
        def __init__(self, default):
            self._value = default

        @property
        def value(self):
            return self._value

        @value.setter
        def value(self, v):
            self._value = v

    season = SeasonValue(default_season)
    context.season = season.value

    user = await get_current_user()
    if DEV_MODE and not user:
        user, _ = await models.Users.get_or_create(id=1, defaults={'username': 'devuser', 'password': 'placeholder'})
        context.session['user_id'] = user.id
    if not user:
        ui.navigate.to('/')
        return
    ui.label(f'Logged in as: {user.username}').classes('text-sm text-gray-500 mb-2')
        
    ui.button('Log Out', on_click=lambda: ui.navigate.to('/logout')).classes('absolute top-4 right-4 bg-red-600 text-white px-4 py-2 rounded')
    state = SimpleNamespace(uploaded_url='')
    HERO_OPTIONS = ['Dooley', 'Mak', 'Pygmalien', 'Vanessa']

    current_page = 1
    page_size = 8
    game_rows = {}
    games_container = None
    stats_container = None
    pagination_row = None
    page_label = None
    prev_button = None
    next_button = None
    
    async def handle_upload(e):

        if not e or not getattr(e, 'content', None):
            ui.notify('No file uploaded (optional)', color='warning')
            return

        try:
            folder = 'screenshots'
            original_name = e.name or "upload"
            hash_digest = hashlib.sha256((original_name + str(time.time())).encode()).hexdigest()[:16]
            _, ext = os.path.splitext(original_name)
            name = f"{hash_digest}{ext.lower()}"
            key = f"{folder}/{name}"
            
            presigned = await generate_presigned_post(name)
            fields = presigned['fields']
            data = fields.copy()
            files = {'file': (name, e.content, e.type or 'application/octet-stream')}

            async with httpx.AsyncClient() as client:
                resp = await client.post(presigned['url'], data=data, files=files)

            if resp.status_code in (200, 204):
                CUSTOM_CDN_BASE_URL = "https://bazaar-files.misterdroo.com"

                state.uploaded_url = f"{CUSTOM_CDN_BASE_URL}/{fields['key']}"
                ui.notify('Upload successful!')
            else:
                ui.notify('Upload failed!', color='negative')

        except Exception as ex:
            print('Upload exception:', ex)
            ui.notify('Unexpected error during upload', color='negative')

    grid_style = (
        'display: grid; '
        'grid-template-columns: repeat(9, minmax(100px, 1fr)); '
        'gap: 0.5rem; align-items: center; width: 100%;'
    )

    async def add_row(game) -> None:
        username = game.player.username
        placement_color = (
            "text-white" if game.wins == 10 and game.finished == 10 else
            "text-yellow-400" if game.wins == 10 and game.finished > 10 else
            "text-gray-400" if game.wins >= 7 else
            "text-[#cd7f32]" if game.wins >= 4 else
            "text-gray-500"
        )
        hero_colors = {
            'Dooley': 'bg-[#397d83] text-white',
            'Mak': 'bg-[#2da337] text-white',
            'Pygmalien': 'bg-[#f56a1f] text-white',
            'Vanessa': 'bg-[#6312de] text-white',
        }
        hero_class = hero_colors.get(game.hero.lower().capitalize(), 'bg-gray-200 text-gray-900')

        with games_container:
            with ui.element('div').style(grid_style) as row:
                ui.label(username).classes('truncate text-center')
                ui.label(game.hero).classes(
                    f'truncate rounded-full px-3 py-1 {hero_class} text-sm font-semibold shadow text-center'
                )
                ui.label("Ranked" if game.ranked else "Non-Ranked").classes('truncate text-center')
                ui.label("Perfect Game" if game.wins == 10 and game.finished == 10 else f"{game.wins}/{game.finished}").classes(
                    f'truncate {placement_color} text-center')
                ui.link('View', target=game.media, new_tab=True).classes('text-blue-600 underline text-center') if game.media else ui.label('-').classes('truncate text-center text-gray-500')

                with ui.dialog().props('maximized') as dialog, ui.card().classes('w-full h-full'):
                    ui.image(game.upload).props('fit=none').classes('mb-4')
                    ui.button('Close', on_click=dialog.close).classes('mt-2')

                ui.link('View').on('click', lambda d=dialog: d.open()).classes('text-blue-600 underline text-center') if game.upload else ui.label('No Upload').classes('truncate text-gray-500 text-center')

                ui.label(game.notes or '').classes('truncate text-center')
                played_str = game.played.strftime('%Y-%m-%d %I:%M %p') if game.played else ''
                ui.label(played_str).classes('truncate text-center')
                ui.button(icon="delete", on_click=lambda g=game.id: delete_game(g)).props('color=negative flat')
            ui.separator().classes('col-span-9 my-1')
        game_rows[game.id] = row

    async def load_page(page_number=1):
        nonlocal current_page, page_label
        context.session = request.session
        context.season = season.value
        user_local = await get_current_user()
        if not user_local:
            ui.notify('Not logged in', color='negative')
            ui.navigate.to('/')
            return

        current_page = page_number
        current_season = context.season

        total_games = await models.Game.filter(player_id=user_local.id, season=current_season).count()
        total_pages = max((total_games + page_size - 1) // page_size, 1)
        if current_page > total_pages:
            current_page = total_pages

        games = await models.Game.filter(player_id=user_local.id, season=current_season)\
            .order_by('-played')\
            .offset((current_page - 1) * page_size)\
            .limit(page_size)\
            .prefetch_related('player')

        games_container.clear()
        game_rows.clear()

        if games:
            with games_container:
                with ui.element('div').style(grid_style).classes('font-bold'):
                    for header in ['Player', 'Hero', 'Mode', 'Win/Day', 'Media', 'Upload', 'Notes', 'Played', 'Actions']:
                        ui.label(header).classes('truncate text-center')
        for game in games:
            await add_row(game)

        pagination_row.clear()
        if games:
            with pagination_row:
                if current_page > 1:
                    ui.button('Previous', on_click=lambda: list_of_games.refresh(page_number=current_page - 1))
                page_label = ui.label(f'Page {current_page} of {total_pages}').classes('mt-2')
                if current_page < total_pages:
                    ui.button('Next', on_click=lambda: list_of_games.refresh(page_number=current_page + 1))

    async def delete_game(game_id: int) -> None:
        success = await delete_game_by_id(game_id)
        if not success:
            return
        row = game_rows.pop(game_id, None)
        if row:
            row.delete()
        await load_page(current_page)
        await stats_tables.refresh()
        nonlocal session_version
        mark_games_changed(user.id)
        session_version = game_data_version.get(user.id, 0)

    @ui.refreshable
    async def list_of_games(page_number=1, page_size=page_size) -> None:
        await load_page(page_number)


    async def create() -> None:
        """Create a game entry and refresh without flicker."""
        add_run_btn.props('disable')
        try:
            await models.Game.create(
                player=player.value,
                season=season.value or 0,
                ranked=ranked.value,
                hero=hero.value,
                wins=wins.value,
                finished=finished.value,
                media=media.value,
                upload=state.uploaded_url,
                notes=notes.value,
            )

            nonlocal session_version
            await load_page(current_page)
            await stats_tables.refresh()
            mark_games_changed(user.id)
            session_version = game_data_version.get(user.id, 0)

            ranked.value = False
            hero.value = None
            wins.value = 0
            finished.value = 0
            media.value = ''
            notes.value = ''
            state.uploaded_url = ''
            upload_component.reset()
            ui.notify('Run added!')
        finally:
            add_run_btn.props(remove='disable')

    
    with ui.column().classes('w-full'):
        ui.label('Bazaar Tracker').classes('text-3xl font-bold')
        ui.label(f'Current Season: {season.value}').classes('text-lg')

        async def get_heroes():
            heroes = await models.Game.filter(player_id=user.id, season=season.value).distinct().values_list("hero", flat=True)

            all_heroes = {h.lower().capitalize() for h in heroes}
            all_heroes.update(HERO_OPTIONS)
            return sorted(all_heroes)

        def categorize(game):
            return categorize_game(game)

        async def collect_stats(rank_value: bool):
            heroes = await get_heroes()
            stats = {h: {'No Placement': 0, '3rd': 0, '2nd': 0, '1st': 0, 'Perfect Game': 0} for h in heroes}
            games = await models.Game.filter(player_id=user.id, season=season.value, ranked=rank_value)
            for g in games:
                hero = g.hero.lower().capitalize()
                category = categorize(g)
                if hero not in stats:
                    stats[hero] = {'No Placement': 0, '3rd': 0, '2nd': 0, '1st': 0, 'Perfect Game': 0}
                stats[hero][category] += 1
            return heroes, stats

        @ui.refreshable
        async def stats_tables():

            stats_container.clear()
            has_data = await models.Game.filter(player_id=user.id, season=season.value).exists()
            if not has_data:
                return

            ranked_heroes, ranked_stats = await collect_stats(True)
            unranked_heroes, unranked_stats = await collect_stats(False)

            columns = [
                {"name": "hero", "label": "Hero", "field": "hero"},
                {"name": "No Placement", "label": "No Placement", "field": "No Placement"},
                {"name": "3rd", "label": "3rd", "field": "3rd"},
                {"name": "2nd", "label": "2nd", "field": "2nd"},
                {"name": "1st", "label": "1st", "field": "1st"},
                {"name": "Perfect Game", "label": "Perfect Game", "field": "Perfect Game"},
            ]

            ranked_rows = [
                {"hero": h,
                 "No Placement": ranked_stats[h]['No Placement'],
                 "3rd": ranked_stats[h]['3rd'],
                 "2nd": ranked_stats[h]['2nd'],
                 "1st": ranked_stats[h]['1st'],
                 "Perfect Game": ranked_stats[h]['Perfect Game']} for h in ranked_heroes
            ]

            unranked_rows = [
                {"hero": h,
                 "No Placement": unranked_stats[h]['No Placement'],
                 "3rd": unranked_stats[h]['3rd'],
                 "2nd": unranked_stats[h]['2nd'],
                 "1st": unranked_stats[h]['1st'],
                 "Perfect Game": unranked_stats[h]['Perfect Game']} for h in unranked_heroes
            ]

            categories = ["No Placement", "3rd", "2nd", "1st", "Perfect Game"]

            if ranked_rows:
                totals = {"hero": "Total"}
                for cat in categories:
                    totals[cat] = sum(r[cat] for r in ranked_rows)
                ranked_rows.append(totals)

            if unranked_rows:
                totals = {"hero": "Total"}
                for cat in categories:
                    totals[cat] = sum(r[cat] for r in unranked_rows)
                unranked_rows.append(totals)
            categories_p, percentages = await compute_placement_percentages(user.id, season.value)
            chart_options = {
                "tooltip": {"trigger": "item"},
                "legend": {"top": "center", "left": "left", "orient": "vertical"},
                "series": [
                    {
                        "name": "Placement",
                        "type": "pie",
                        "radius": ["40%", "70%"],
                        "avoidLabelOverlap": False,
                        "label": {"formatter": "{b}: {d}%"},
                        "data": [
                            {"value": p, "name": c}
                            for c, p in zip(categories_p, percentages)
                        ],
                    }
                ],

            }

            with stats_container:
                with ui.row().classes('w-full gap-4'):
                    with ui.column().classes('flex-1'):
                        ui.label('Ranked Game Stats').classes('text-lg')
                        ui.table(columns=columns, rows=ranked_rows).classes('w-full')
                    with ui.column().classes('flex-1'):
                        ui.label('Non-Ranked Game Stats').classes('text-lg')
                        ui.table(columns=columns, rows=unranked_rows).classes('w-full')
                with ui.row().classes('w-full mt-4'):
                    with ui.column().classes('w-1/3'):
                        ui.label('Placement Averages').classes('text-lg')
                        ui.echart(options=chart_options).classes('w-full h-64')
        
    with ui.row().classes('flex w-full gap-4'):

        with ui.column().classes('w-[400px] shrink-0'):
            with ui.row().classes('w-full gap-4'):
                
                class PlayerValue:
                    @property
                    def value(self):
                        return user
                    @value.setter
                    def value(self, v):
                        pass

                player = PlayerValue()
            
            
            with ui.row().classes('items-center gap-0'):
                ranked = ui.checkbox()
                ui.label('Ranked').bind_visibility_from(ranked, 'visible', lambda _: True)

            hero = ui.radio(HERO_OPTIONS, value=None).classes('w-full').props('inline')

            wins = ui.slider(min=0, max=10, step=1, value=0).classes('w-full')
            wins_label = ui.label(f"Wins: {wins.value}")
            wins_label.bind_text_from(wins, "value", lambda v: f"Wins: {v}")

            finished = ui.slider(min=0, max=20, step=1, value=wins.value).classes('w-full')

            finished_label = ui.label(f"Day Finished: {finished.value}")
            finished_label.bind_text_from(finished, "value", lambda v: f"Day Finished: {v}")

            def enforce_win_limit(e=None):
                if wins.value > finished.value:
                    wins.value = finished.value
                if finished.value < wins.value:
                    finished.value = wins.value

            def sync_finished_with_wins(e=None):
                if finished.value < wins.value:
                    finished.value = wins.value

            wins.on('change', sync_finished_with_wins)
            wins.on('change', enforce_win_limit)
            finished.on('change', enforce_win_limit)
            def is_valid_url(url: str) -> bool:
                pattern = re.compile(
                    r'^(https?://)'                  
                    r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'  
                    r'(:\d+)?'                       
                    r'(/.*)?$'                       
                )
                return bool(pattern.match(url.strip()))

            with ui.element('div').classes('border border-gray-800 rounded-lg p-2 w-full pt-0'):
                media = ui.input(label='Media URL').classes('w-full')

            def validate_media_url():
                url = media.value or ''
                if url and not is_valid_url(url):
                    media.props('error error-message="Invalid Media URL"')
                else:
                    media.props(remove='error error-message')

            media.on('change', validate_media_url)
            upload_component = ui.upload(label='Upload Screenshot or Video', on_upload=handle_upload).classes('w-full')
            MAX_NOTES_LENGTH = 75
            notes = ui.textarea(label=f'Notes (max {MAX_NOTES_LENGTH} chars)').classes('w-full rounded-lg border border-gray-800 p-2 pt-0')
            char_count_label = ui.label('0/75').classes('text-xs text-gray-500 mb-2')

            def update_char_count():
                value = notes.value or ''
                if len(value) > MAX_NOTES_LENGTH:
                    value = value[:MAX_NOTES_LENGTH]
                    notes.value = value
                char_count_label.text = f'{len(value)}/{MAX_NOTES_LENGTH}'

            ui.timer(0.25, update_char_count)
            add_run_btn = ui.button('Add Run', on_click=create).classes('w-full').props('color=primary')

        with ui.column().classes('flex-1'):
            games_container = ui.column().classes('w-full')
            pagination_row = ui.row().classes('w-full justify-end mt-4')
            stats_container = ui.column().classes('w-full')
            await list_of_games()
            await stats_tables()

    # automatically refresh the user's data when any run is created or deleted
    session_version = game_data_version.get(user.id, 0)

    def refresh_if_needed():
        nonlocal session_version
        current_version = game_data_version.get(user.id, 0)
        if session_version != current_version:
            session_version = current_version
            ui.run_async(load_page(current_page))
            ui.run_async(stats_tables.refresh())

    ui.timer(1.0, refresh_if_needed)


 
        

ui.run(dark="true")
